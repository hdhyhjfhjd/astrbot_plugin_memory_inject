# -*- coding: utf-8 -*-
"""
astrbot_plugin_memory_inject —— 记忆档案注入插件

把 memory 目录中的 .md 档案按「文件名前缀」分区，以独立标签 <memory_archives>
注入到每次 LLM 请求。默认追加到 system prompt 末尾（约束力强，内容静态不破坏
前缀缓存）；可配置 inject_target=tail 改为追加到 extra_user_content_parts
（尾部注入，缓存绝对稳但约束力弱）。只追加、不替换任何已有内容，与其它注入类
插件（如表情包插件）叠加共存，互不覆盖。

分区约定（改文件名即可改权限，无需编辑配置）：
  ro_ 前缀     → 只读（AI 只能读，禁止修改）
  rw_ 前缀     → 可写（AI 可更新：新偏好/环境变化追加到这里）
  off_ 前缀    → 不注入（跳过该文件）
  无前缀       → 默认按只读处理（兼容既有命名，如 00_index.md）
"""

import logging
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import TextPart

logger = logging.getLogger(__name__)

PREFIX_RO = "ro_"
PREFIX_RW = "rw_"
PREFIX_OFF = "off_"


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.context = context
        self.config = config or {}

    def _scan_archives(self, d: Path) -> tuple[list[str], list[str]]:
        """扫描目录，返回 (只读文件列表, 可写文件列表)。"""
        ro, rw = [], []
        for f in sorted(d.glob("*.md")):
            name = f.name
            if name.startswith(PREFIX_OFF):
                continue
            if name.startswith(PREFIX_RW):
                rw.append(name)
            else:  # ro_ 前缀或无前缀默认只读
                ro.append(name)
        return ro, rw

    @filter.on_llm_request()
    async def inject_memory_rules(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        if not bool(self.config.get("enable_inject", True)):
            return
        try:
            memory_dir = str(self.config.get("memory_dir", "") or "").strip()
            if not memory_dir:
                return
            d = Path(memory_dir)
            if not d.is_dir():
                logger.debug("memory_inject: 目录不存在，跳过: %s", memory_dir)
                return

            ro_files, rw_files = self._scan_archives(d)
            if not ro_files and not rw_files:
                return

            lines = ["<memory_archives>", f"记忆档案目录：{memory_dir}"]
            if ro_files:
                lines.append(
                    "[只读·响应前先读] " + "、".join(ro_files)
                    + " —— 只读档案，禁止修改"
                )
            if rw_files:
                lines.append(
                    "[可写] " + "、".join(rw_files)
                    + " —— 可更新：新偏好/环境/工作方法变化时追加要点，追加前先读原文去重"
                )
            custom = str(self.config.get("custom_rules", "") or "").strip()
            if custom:
                lines.append(custom)
            lines.append("</memory_archives>")
            block_text = "\n".join(lines)

            # 注入位置：system=头部（约束力强，内容静态不破坏缓存，默认）；
            # tail=尾部 extra_user_content_parts（缓存绝对稳，约束力弱）
            inject_target = str(
                self.config.get("inject_target", "system") or "system"
            ).strip().lower()
            if inject_target == "tail":
                req.extra_user_content_parts.append(TextPart(text=block_text))
            else:
                req.system_prompt = (req.system_prompt or "") + "\n" + block_text
        except Exception as exc:  # noqa: BLE001 - 注入失败不影响主流程
            logger.warning("memory_inject 注入失败（不影响功能）: %s", exc)

    # ------------------------------------------------------------------
    # /memory 管理指令：自动扫描目录 + 批量改前缀（无需手动 mv 改名）
    # ------------------------------------------------------------------
    def _memory_dir(self) -> Path | None:
        raw = str(self.config.get("memory_dir", "") or "").strip()
        if not raw:
            return None
        return Path(raw)

    def _fmt_archive_list(self, d: Path) -> str:
        lines = [f"memory 目录：{d}", ""]
        for f in sorted(d.glob("*.md")):
            name = f.name
            if name.startswith(PREFIX_OFF):
                tag = "不注入 (off_)"
            elif name.startswith(PREFIX_RW):
                tag = "可写 (rw_)"
            elif name.startswith(PREFIX_RO):
                tag = "只读 (ro_)"
            else:
                tag = "只读 (无前缀默认)"
            lines.append(f"- {name}  [{tag}]")
        return "\n".join(lines)

    def _strip_prefix(self, name: str) -> str:
        for p in (PREFIX_RO, PREFIX_RW, PREFIX_OFF):
            if name.startswith(p):
                return name[len(p):]
        return name

    def _resolve_name(self, d: Path, name: str) -> tuple[str | None, list[str]]:
        """把用户输入解析为真实文件名。

        返回 (目标文件名, 候选列表)：
          - 精确命中：直接返回该文件名；
          - 模糊命中唯一：返回唯一候选；
          - 模糊命中多个：返回 (None, 候选列表)，由调用方让用户明确指定；
          - 完全无匹配：返回 (原输入, [])，由调用方报不存在。
        匹配规则：先按完整文件名精确找；否则去掉 .md 后缀和权限前缀后，
        按「核心名完全相等」匹配，避免相近名字（如 10_ai_notes 与
        10_ai_notes_old）互相误配。
        """
        if d.joinpath(name).is_file():
            return name, []
        core = name[:-3] if name.endswith(".md") else name
        core = self._strip_prefix(core)
        candidates = []
        for f in sorted(d.glob("*.md")):
            f_core = self._strip_prefix(f.name[:-3])
            if f_core == core:
                candidates.append(f.name)
        if not candidates:
            return name, []
        if len(candidates) == 1:
            return candidates[0], []
        return None, candidates

    def _apply_prefix(self, d: Path, name: str, prefix: str) -> str:
        target, candidates = self._resolve_name(d, name)
        if target is None:
            return (
                f"「{name}」匹配到多个文件，请用完整文件名明确指定："
                + "、".join(candidates)
            )
        src = d / target
        if not src.is_file():
            return f"跳过：{target} 不存在"
        base = self._strip_prefix(target)
        new_name = prefix + base
        if new_name == target:
            return f"{target}：已是目标权限，无需改动"
        dst = d / new_name
        if dst.exists():
            return f"跳过：{new_name} 已存在"
        try:
            src.rename(dst)
        except OSError as exc:
            return f"失败：{target} → {new_name}（{exc}）"
        return f"{target} → {new_name}"

    @filter.command("memory")
    async def memory_cmd(
        self, event: AstrMessageEvent, arg1: str = "", arg2: str = ""
    ):
        """管理 memory 档案分区权限。

        用法：
          /memory                       查看目录与当前权限
          /memory ro|rw|off <文件名...>  设置权限（自动改名加前缀，可一次多个）
          /memory clear <文件名...>      移除前缀（恢复默认只读）
          /memory all ro|rw|off|clear    一键批量设置全部文件
        """
        if bool(self.config.get("memory_admin_only", True)) and not event.is_admin():
            yield event.plain_result("❌ /memory 仅管理员可用。")
            return
        d = self._memory_dir()
        if d is None:
            yield event.plain_result(
                "未配置 memory_dir，请先在插件配置面板填写档案目录。"
            )
            return
        if not d.is_dir():
            yield event.plain_result(f"目录不存在：{d}")
            return

        action = (arg1 or "").strip().lower()
        if not action or action == "list":
            yield event.plain_result(self._fmt_archive_list(d))
            return

        if action == "all":
            target = (arg2 or "").strip().lower()
            valid = {
                "ro": PREFIX_RO,
                "rw": PREFIX_RW,
                "off": PREFIX_OFF,
                "clear": "",
            }
            if target not in valid:
                yield event.plain_result("用法：/memory all ro|rw|off|clear")
                return
            changed = skipped = 0
            msgs = []
            for f in sorted(d.glob("*.md")):
                msg = self._apply_prefix(d, f.name, valid[target])
                msgs.append(msg)
                if msg.startswith(("失败", "跳过")):
                    skipped += 1
                else:
                    changed += 1
            if not msgs:
                yield event.plain_result("目录中没有 .md 文件。")
                return
            summary = (
                f"批量设置 {target or '无前缀(默认只读)'} 完成："
                f"{changed} 个变更，{skipped} 个跳过。"
            )
            yield event.plain_result(summary + "\n" + "\n".join(msgs))
            return

        prefix_map = {
            "ro": PREFIX_RO,
            "rw": PREFIX_RW,
            "off": PREFIX_OFF,
            "clear": "",
        }
        if action not in prefix_map:
            yield event.plain_result(
                "用法：/memory [list] | "
                "/memory ro|rw|off|clear <文件名...> | "
                "/memory all ro|rw|off|clear"
            )
            return
        names = [n.strip() for n in (arg2 or "").split() if n.strip()]
        if not names:
            yield event.plain_result("请指定至少一个文件名。")
            return
        for name in names:
            yield event.plain_result(self._apply_prefix(d, name, prefix_map[action]))
