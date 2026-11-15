# 记忆档案注入插件（astrbot_plugin_memory_inject）

把 `memory/` 目录中的 `.md` 档案以**独立标签**注入到每次 LLM 请求。默认注入到 **system prompt 末尾**（约束力强，内容静态不破坏缓存）；可切换为尾部 `extra_user_content_parts` 注入。与其它注入插件叠加共存、互不覆盖。

## 一、安装
1. AstrBot WebUI → 插件市场 → 上传本 zip；
2. 插件管理 → 记忆档案注入 → 配置：
   - `memory_dir`：填你的档案目录（见下）；
   - `inject_target`：`system`（默认，头部追加，约束力强）/ `tail`（尾部注入，缓存绝对稳）；
   - `enable_inject`：默认开；
   - `custom_rules`：可选附加规则（多行文本，每行一条规则）。

## 二、目录与分区（改文件名即改权限）
```
memory/
├── 00_index.md            # 无前缀 → 默认只读
├── 01_user_preference.md  # 只读
├── rw_10_ai_notes.md      # rw_ 前缀 → 可写（AI 自主更新）
└── off_99_old.md          # off_ 前缀 → 不注入
```

| 前缀 | 含义 |
|---|---|
| `ro_` 或无前缀 | **只读**：AI 只能读，禁止修改 |
| `rw_` | **可写**：AI 可更新（新偏好/环境变化追加到这里） |
| `off_` | 不注入（跳过该文件） |

## 三、/memory 指令（自动扫描 + 批量改权限，不用手动改名）

给机器人发消息即可操作（默认仅管理员）：

```
/memory                       查看目录与当前每个文件的权限
/memory ro <文件名...>         设为只读（自动加 ro_ 前缀，可一次多个）
/memory rw <文件名...>         设为可写（自动加 rw_ 前缀）
/memory off <文件名...>        设为不注入（自动加 off_ 前缀）
/memory clear <文件名...>      移除前缀（恢复无前缀=默认只读）
/memory all ro                 一键把所有文件设为只读
/memory all rw                 一键把所有文件设为可写
/memory all clear              一键去掉全部前缀
```

例：
```
/memory all rw     →  00_index.md、01_user_preference.md 全部变可写（不推荐，演示用）
/memory rw 10_ai_notes.md  →  只把该文件设为可写
```

文件名支持「核心名」模糊匹配：不带前缀和后缀也能找到唯一目标，如
`/memory rw 10_ai_notes`（自动匹配 rw_10_ai_notes.md 等，去前缀后核心名必须完全相等）。
若多个文件同核心名（如 ro_ 与 rw_ 同名共存），会列出候选让你用完整文件名明确指定，绝不乱改。

改名即时生效：下次 LLM 请求的注入块会按新权限重新生成，无需重启。

## 四、每次注入的效果
```
<memory_archives>
记忆档案目录：/AstrBot/data/workspaces/.../memory
[只读·响应前先读] 00_index.md、01_user_preference.md
[可写] rw_10_ai_notes.md —— 新偏好/环境/工作方法变化时追加要点，追加前先读原文去重
（自定义规则）
</memory_archives>
```

## 五、为什么与其它注入插件（如表情包插件）不冲突
1. **只 append，不替换**：`req.extra_user_content_parts.append()` 只追加自己的块，不触碰、不覆盖其它插件注入的内容；
2. **独立标签**：`<memory_archives>` 与其它插件的块语义隔离；
3. **零成本兜底**：未配置 `memory_dir` 或目录不存在时，直接跳过，不产生任何注入。

## 五、建议配合
- 给 AI 开启 shell 权限时：全局关、只开该会话/人格；`require_admin` 保持 true；
- `rw_` 档案由 AI 追加式更新，你定期审阅后把要点合并进只读档案；
- 定期审计 `docker logs` 中 AI 执行过的 shell 命令。


---

## 致谢

本插件由 hdhyhjfhjd 主导设计与维护，开发过程中使用 [Doubao Work](https://www.doubao.com)（豆包 AI 助手）进行代码协作与调试。
