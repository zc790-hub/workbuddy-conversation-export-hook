# Agent 对话导出 Skill (conversation-export-skill)

**中文** | [English](#english)

用 AI agent 干活久了，你会发现一个痛点：对话记录散落在各个 JSONL 文件里，想回顾"上次那个对话聊了什么"很难找，想归档到知识库更是手动一条条复制。大多数 agent 没有原生的对话导出功能，JSONL 格式也不适合直接阅读。

这个 skill 就是来解决这个问题的：一个轻量的 hook 机制，在对话结束（shell 退出）时自动把当前对话导出为人类可读的 Markdown，归档到 Obsidian 或任意目录。支持增量写入（不重复导出）、月度索引自动生成、Obsidian frontmatter（Dataview 可查询），以及 JSON / Text 等多种格式。

## ✨ 功能

- 🔄 **自动导出**：对话结束时自动捕获 JSONL 记录并导出
- 📝 **三种格式**：Markdown（默认，含 Obsidian frontmatter）、JSON（全量）、Text（纯文本）
- 🔒 **增量写入**：已导出且最新的对话自动跳过，避免重复 I/O
- 📋 **月度索引**：自动生成 `YYYY-MM-索引.md`，含表格和 Obsidian 双链
- 🏷️ **Frontmatter**：Markdown 导出包含 YAML 元数据，支持 Dataview 查询
- ⚙️ **可配置**：JSON 配置文件控制路径、格式、启用状态
- 🛡️ **异常隔离**：Hook 失败不影响主流程
- 🧹 **简洁输出**：默认仅导出用户/AI 消息，可选包含工具调用和推理过程
- 🔧 **交互式配置**：`--init` 向导引导首次配置

## 📦 安装

```bash
git clone https://github.com/zc790-hub/conversation-export-skill.git
cd conversation-export-skill
./install.sh
```

安装后运行交互式配置向导：

```bash
~/.agent/hooks/run-conversation-export.sh --init
```

向导会引导你设置导出路径、格式和是否包含工具调用。

## 🚀 使用

### 手动导出

```bash
# 导出最近活跃的对话
~/.agent/hooks/run-conversation-export.sh

# 导出指定对话
~/.agent/hooks/run-conversation-export.sh --conversation-id <uuid>

# 指定格式
~/.agent/hooks/run-conversation-export.sh --format json

# 干运行（只看配置，不执行）
~/.agent/hooks/run-conversation-export.sh --dry-run
```

### 自动触发（Shell EXIT Trap）

在 `~/.zshrc` 或 `~/.bashrc` 末尾添加：

```bash
# 对话结束自动导出
agent_export_on_exit() {
  if [[ "$PWD" == */agent/* ]]; then
    ~/.agent/hooks/run-conversation-export.sh >>~/.agent/logs/export.log 2>&1
  fi
}
trap agent_export_on_exit EXIT
```

每次关闭终端时，如果在工作目录下，会自动导出最近活跃的对话。

### 定时补漏（cron / 自动化）

Shell EXIT trap 解决的是"实时导出"，但如果某天 shell 一直没退出，当天的对话就会漏掉。可以配合定时任务做补漏：

```bash
#!/bin/bash
# 遍历最近 1 天内修改过的 JSONL，逐个导出
for jsonl in ~/.agent/projects/*/*.jsonl; do
  mtime=$(stat -f "%m" "$jsonl" 2>/dev/null)
  now=$(date +%s)
  diff=$(( (now - mtime) / 86400 ))
  if [ "$diff" -le 1 ]; then
    conv_id=$(basename "$jsonl" .jsonl)
    ~/.agent/hooks/run-conversation-export.sh --conversation-id "$conv_id" 2>/dev/null
  fi
done
```

增量机制会自动跳过已导出的对话，只补缺失的。

## ⚙️ 配置

配置文件位于 `~/.agent/hooks/conversation-export/hook-config.json`：

```json
{
  "enabled": true,
  "exportPath": "~/Documents/agent对话导出/{date8}_{conversationId}_{title}",
  "format": "markdown",
  "includeToolResults": false,
  "onError": "log",
  "logPath": "~/.agent/logs/conversation-export-hook.log"
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `true` | 是否启用 hook |
| `exportPath` | string | `~/Documents/...` | 输出路径，支持占位符 |
| `format` | string | `markdown` | `json` / `markdown` / `text` |
| `includeToolResults` | bool | `false` | 是否包含工具调用和推理过程 |
| `onError` | string | `log` | 错误策略（异常不会抛出） |
| `logPath` | string | `~/.agent/logs/...` | 日志文件路径 |

### 路径占位符

| 占位符 | 示例 | 说明 |
|--------|------|------|
| `{date}` | `2026-07-09` | 日期（带连字符） |
| `{date8}` | `20260709` | 日期（紧凑格式） |
| `{datetime}` | `20260709_143000` | 日期+时间 |
| `{conversationId}` | `9d535323-...` | 对话 ID |
| `{title}` | `实现对话导出` | 对话标题（已清理为安全文件名） |

### 归档到 Obsidian

将 `exportPath` 改为你的 Obsidian 知识库路径即可：

```json
{
  "exportPath": "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/我的知识库/agent对话导出/{date8}_{conversationId}_{title}"
}
```

## 📁 文件结构

```
.
├── hooks/
│   ├── hook_manager.py              # 通用 hook 管理器
│   ├── conversation_export_hook.py   # 对话导出实现
│   ├── run_hook.py                   # CLI 入口（含 --init 向导）
│   └── hook-config.json              # 默认配置
├── tests/
│   └── test_hook.py                  # 单元测试
├── install.sh                        # 安装脚本
├── LICENSE
└── README.md
```

## 📋 导出效果

### Markdown（默认）

```markdown
---
type: agent-conversation
date: 2026-07-09
conversationId: 9d535323-...
title: "实现对话导出"
tags: [agent, 对话导出]
---

# 实现对话导出

> **会话 ID**: `9d535323-...`
> **导出时间**: 2026-07-09 15:41 (HKT)

---

## **你** *14:01:04*

帮我导出对话记录

---

## **AI** *14:01:05*

好的，我来帮你导出...
```

### 月度索引

每次导出后自动更新 `YYYY-MM-索引.md`：

```markdown
| 日期 | 标题 | 文件 |
|------|------|------|
| 07-09 | 实现对话导出 | `[[20260709_9d535323-..._实现对话导出.md]]` |
| 07-09 | 撰写专访稿 | `[[20260709_bafa5e05-..._撰写专访稿.md]]` |
```

## 🧪 测试

```bash
python3 tests/test_hook.py -v
```

## 📝 技术细节

- 对话源文件：`~/.agent/projects/<project-name>/<conversation-id>.jsonl`
- `project-name` 由工作目录绝对路径将 `/` 替换为 `-` 得到
- User 消息从 `<user_query>` 标签中提取真正用户输入，过滤系统注入的 context
- 标题优先取 AI 生成的 `ai-title`，fallback 到第一条 user 消息，过滤非自然语言标题
- 增量写入：目标文件 mtime ≥ 源 JSONL mtime 时跳过
- 配置优先级：`hook-config.local.json` > `hook-config.json`（local 不被 install.sh 覆盖）
- 适配其他 agent：修改 `conversation_export_hook.py` 中的路径和 JSONL 字段映射即可

## License

[MIT](./LICENSE) · Copyright (c) 2026 zc790-hub

---

## English

[↑ 中文](#agent-对话导出-skill-conversation-export-skill)

After using AI agents for a while, you'll hit a pain point: conversation records are scattered across JSONL files, hard to search when you want to recall "what did we discuss last time," and even harder to archive into your knowledge base. Most agents have no native conversation export, and raw JSONL isn't meant for human reading.

This skill solves that: a lightweight hook that auto-exports the current conversation to readable Markdown when your session ends (shell exit), archiving it to Obsidian or any directory. Supports incremental writes (no duplicate exports), auto-generated monthly index, Obsidian frontmatter (Dataview-queryable), plus JSON / Text formats.

## ✨ Features

- 🔄 **Auto-export**: captures JSONL records and exports on session end
- 📝 **Three formats**: Markdown (default, with Obsidian frontmatter), JSON (full), Text (plain)
- 🔒 **Incremental write**: skips already-exported conversations that are up-to-date
- 📋 **Monthly index**: auto-generates `YYYY-MM-index.md` with table and Obsidian wikilinks
- 🏷️ **Frontmatter**: Markdown exports include YAML metadata for Dataview queries
- ⚙️ **Configurable**: JSON config controls path, format, enable/disable
- 🛡️ **Exception isolation**: hook failures don't affect the main process
- 🧹 **Clean output**: defaults to user/AI messages only; optionally includes tool calls and reasoning
- 🔧 **Interactive setup**: `--init` wizard for first-time configuration

## 📦 Installation

```bash
git clone https://github.com/zc790-hub/conversation-export-skill.git
cd conversation-export-skill
./install.sh
```

After installation, run the interactive config wizard:

```bash
~/.agent/hooks/run-conversation-export.sh --init
```

## 🚀 Usage

### Manual export

```bash
# Export the most recent active conversation
~/.agent/hooks/run-conversation-export.sh

# Export a specific conversation
~/.agent/hooks/run-conversation-export.sh --conversation-id <uuid>

# Specify format
~/.agent/hooks/run-conversation-export.sh --format json

# Dry run (print config, don't export)
~/.agent/hooks/run-conversation-export.sh --dry-run
```

### Auto-trigger (Shell EXIT Trap)

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
agent_export_on_exit() {
  if [[ "$PWD" == */agent/* ]]; then
    ~/.agent/hooks/run-conversation-export.sh >>~/.agent/logs/export.log 2>&1
  fi
}
trap agent_export_on_exit EXIT
```

Every time you close your terminal, if you're in a work directory, it auto-exports the most recent active conversation.

### Scheduled catch-up (cron / automation)

The EXIT trap handles "real-time export," but if your shell stays open overnight, that day's conversations might be missed. A scheduled task can fill the gap:

```bash
#!/bin/bash
for jsonl in ~/.agent/projects/*/*.jsonl; do
  mtime=$(stat -f "%m" "$jsonl" 2>/dev/null)
  now=$(date +%s)
  diff=$(( (now - mtime) / 86400 ))
  if [ "$diff" -le 1 ]; then
    conv_id=$(basename "$jsonl" .jsonl)
    ~/.agent/hooks/run-conversation-export.sh --conversation-id "$conv_id" 2>/dev/null
  fi
done
```

The incremental mechanism skips already-exported conversations automatically.

## ⚙️ Configuration

Config file: `~/.agent/hooks/conversation-export/hook-config.json`

```json
{
  "enabled": true,
  "exportPath": "~/Documents/agent-exports/{date8}_{conversationId}_{title}",
  "format": "markdown",
  "includeToolResults": false,
  "onError": "log",
  "logPath": "~/.agent/logs/conversation-export-hook.log"
}
```

### Path placeholders

| Placeholder | Example | Description |
|-------------|---------|-------------|
| `{date}` | `2026-07-09` | Date with hyphens |
| `{date8}` | `20260709` | Compact date |
| `{datetime}` | `20260709_143000` | Date + time |
| `{conversationId}` | `9d535323-...` | Conversation ID |
| `{title}` | `Export conversations` | Conversation title (sanitized) |

### Archive to Obsidian

Point `exportPath` to your Obsidian vault:

```json
{
  "exportPath": "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault/agent-exports/{date8}_{conversationId}_{title}"
}
```

## 📁 File structure

```
.
├── hooks/
│   ├── hook_manager.py              # Generic hook manager
│   ├── conversation_export_hook.py   # Export implementation
│   ├── run_hook.py                   # CLI entry (with --init wizard)
│   └── hook-config.json              # Default config
├── tests/
│   └── test_hook.py                  # Unit tests
├── install.sh                        # Install script
├── LICENSE
└── README.md
```

## 📋 Export preview

### Markdown (default)

```markdown
---
type: agent-conversation
date: 2026-07-09
conversationId: 9d535323-...
title: "Export conversations"
tags: [agent, conversation-export]
---

# Export conversations

> **Session ID**: `9d535323-...`
> **Exported at**: 2026-07-09 15:41 (HKT)

---

## **You** *14:01:04*

Help me export the conversation

---

## **AI** *14:01:05*

Sure, let me help you with that...
```

### Monthly index

Auto-updated after each export:

```markdown
| Date | Title | File |
|------|-------|------|
| 07-09 | Export conversations | `[[20260709_9d535323-..._Export_conversations.md]]` |
| 07-09 | Write article | `[[20260709_bafa5e05-..._Write_article.md]]` |
```

## 🧪 Tests

```bash
python3 tests/test_hook.py -v
```

## 📝 Technical details

- Source: `~/.agent/projects/<project-name>/<conversation-id>.jsonl`
- `project-name` is derived from the working directory by replacing `/` with `-`
- User messages are extracted from `<user_query>` tags, filtering out system-injected context
- Title priority: AI-generated `ai-title` → first user message → default; non-natural-language titles are filtered
- Incremental: skips if target file mtime ≥ source JSONL mtime
- Config priority: `hook-config.local.json` > `hook-config.json` (local is preserved across installs)
- Adapting to other agents: modify path and JSONL field mappings in `conversation_export_hook.py`

## License

[MIT](./LICENSE) · Copyright (c) 2026 zc790-hub
