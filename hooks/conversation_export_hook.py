#!/usr/bin/env python3
"""
对话结束导出 Hook

在对话结束时捕获当前对话的 JSONL 记录，并按配置导出为：
- json: 保留原始 JSONL 结构（全量）
- markdown: 人类可读的对话文本（默认仅消息，可选完整记录）
- text: 纯文本对话记录（默认仅消息，可选完整记录）

与 ~/.codex/export-session.sh 共享同一套 Obsidian 目录，文件名采用 YYYYMMDD_HHMMSS_id 格式。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from hook_manager import HookContext

logger = logging.getLogger(__name__)

HKT = timezone(timedelta(hours=8))
DEFAULT_AGENT_DIR = Path(os.environ.get("AGENT_DATA_DIR", Path.home() / ".agent"))


class ConversationExportHook:
    """对话导出 hook 实现。"""

    SUPPORTED_FORMATS = {"json", "markdown", "text"}

    def __init__(self, agent_dir: Optional[Path] = None):
        self.agent_dir = agent_dir or DEFAULT_AGENT_DIR
        self.projects_dir = self.agent_dir / "projects"
        self.sessions_file = self.agent_dir / "app" / "sessions.json"

    def __call__(self, context: HookContext, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行导出。"""
        fmt = (config.get("format") or "markdown").lower()
        if fmt not in self.SUPPORTED_FORMATS:
            raise ValueError(f"不支持的导出格式: {fmt}，可选: {self.SUPPORTED_FORMATS}")

        conversation_id, work_dir = self._resolve_conversation(context)
        if not conversation_id:
            raise RuntimeError("无法确定当前对话 ID")

        jsonl_path = self._find_jsonl(conversation_id, work_dir)
        if not jsonl_path or not jsonl_path.exists():
            raise FileNotFoundError(f"找不到对话记录文件: {conversation_id}")

        raw_lines = self._read_jsonl(jsonl_path)
        title = self._extract_title(raw_lines) or "agent对话"
        output_path = self._build_output_path(config, conversation_id, title)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 增量写入：目标文件已存在且比源文件新，直接跳过
        if self._should_skip(jsonl_path, output_path):
            logger.info("目标文件已存在且最新，跳过导出: %s", output_path)
            return {
                "conversationId": conversation_id,
                "source": str(jsonl_path),
                "output": str(output_path),
                "format": fmt,
                "records": len(raw_lines),
                "bytes": output_path.stat().st_size,
                "title": title,
                "skipped": True,
            }

        include_full = config.get("includeToolResults", False)

        if fmt == "json":
            written = self._write_json(raw_lines, output_path)
        elif fmt == "markdown":
            written = self._write_markdown(raw_lines, output_path, conversation_id, title, include_full)
        else:
            written = self._write_text(raw_lines, output_path, conversation_id, include_full)

        return {
            "conversationId": conversation_id,
            "source": str(jsonl_path),
            "output": str(output_path),
            "format": fmt,
            "records": len(raw_lines),
            "bytes": written,
            "title": title,
            "skipped": False,
        }

    def _resolve_conversation(self, context: HookContext) -> tuple[Optional[str], Optional[str]]:
        """解析当前对话 ID 和工作目录。"""
        conversation_id = context.conversation_id or os.environ.get("AGENT_CONVERSATION_ID")
        work_dir = context.work_dir or os.environ.get("AGENT_WORK_DIR")

        if conversation_id:
            return conversation_id, work_dir

        if context.session_file:
            try:
                with open(context.session_file, "r", encoding="utf-8") as f:
                    session = json.load(f)
                return session.get("conversationId"), session.get("workDir")
            except Exception as exc:
                logger.warning("读取 session 文件失败: %s", exc)

        if self.sessions_file.exists():
            try:
                with open(self.sessions_file, "r", encoding="utf-8") as f:
                    sessions_meta = json.load(f)
                sessions = sessions_meta.get("sessions", [])
                if sessions:
                    sessions_sorted = sorted(
                        sessions,
                        key=lambda s: s.get("resumedAt") or s.get("startedAt") or "",
                        reverse=True,
                    )
                    latest = sessions_sorted[0]
                    return latest.get("conversationId"), latest.get("workDir")
            except Exception as exc:
                logger.warning("读取 sessions.json 失败: %s", exc)

        return None, None

    def _find_jsonl(self, conversation_id: str, work_dir: Optional[str]) -> Optional[Path]:
        """查找对话对应的 JSONL 文件。"""
        candidates: List[Path] = []

        if work_dir:
            project_name = work_dir.strip("/").replace("/", "-")
            candidates.append(self.projects_dir / project_name / f"{conversation_id}.jsonl")

        if self.projects_dir.exists():
            for project_dir in self.projects_dir.iterdir():
                candidate = project_dir / f"{conversation_id}.jsonl"
                if candidate.exists():
                    return candidate

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0] if candidates else None

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        """读取 JSONL 文件，过滤损坏行。"""
        records = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("跳过损坏的 JSONL 行")
        except Exception as exc:
            raise RuntimeError(f"读取对话记录失败: {path}") from exc
        return records

    @staticmethod
    def _should_skip(source: Path, target: Path) -> bool:
        """若目标文件已存在且比源文件新，则跳过写入。"""
        try:
            if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
                return True
        except Exception:
            pass
        return False

    def _build_output_path(
        self, config: Dict[str, Any], conversation_id: str, title: str
    ) -> Path:
        """根据配置生成输出路径（支持占位符）。"""
        raw_path = config.get("exportPath") or (
            "~/Documents/agent对话导出/{date8}_{conversationId}_{title}"
        )
        expanded = os.path.expanduser(raw_path)

        now = datetime.now(HKT)
        title_safe = self._sanitize_filename(title)
        placeholders = {
            "{date}": now.strftime("%Y-%m-%d"),
            "{date8}": now.strftime("%Y%m%d"),
            "{datetime}": now.strftime("%Y%m%d_%H%M%S"),
            "{conversationId}": conversation_id,
            "{conversation_id}": conversation_id,
            "{title}": title_safe,
        }
        for key, value in placeholders.items():
            expanded = expanded.replace(key, value)

        fmt = (config.get("format") or "markdown").lower()
        extension_map = {"json": ".json", "markdown": ".md", "text": ".txt"}
        extension = extension_map.get(fmt, ".md")

        if not expanded.lower().endswith((".json", ".md", ".txt")):
            expanded += extension

        return Path(expanded)

    @staticmethod
    def _sanitize_filename(text: str, max_len: int = 40) -> str:
        """将任意文本转换为安全的文件名片段。"""
        text = text.strip()
        text = re.sub(r"[^\w\u4e00-\u9fff\s\-]", "", text)
        text = re.sub(r"\s+", "_", text)
        if len(text) > max_len:
            text = text[:max_len]
        return text or "untitled"

    def _extract_title(self, records: List[Dict[str, Any]]) -> Optional[str]:
        """从记录中提取对话标题。"""
        # 优先使用 AI 生成的标题
        for record in records:
            if record.get("type") == "ai-title":
                title = record.get("aiTitle") or record.get("title")
                if title and self._is_valid_title(title):
                    return title
        # Fallback：取第一条 user 消息作为标题
        for record in records:
            if record.get("type") == "message" and record.get("role") == "user":
                text = self._extract_text(record.get("content"), role="user").strip()
                if not text:
                    continue
                cleaned = re.sub(r"[\s\n]+", " ", text).strip()
                if cleaned and self._is_valid_title(cleaned):
                    return cleaned
        return None

    @staticmethod
    def _is_valid_title(text: str) -> bool:
        """判断文本是否适合作为标题（过滤系统指令、过短、非自然语言等）。"""
        text = text.strip()
        if len(text) < 2:
            return False
        # 以 . 开头通常是系统指令残留（如 ". You MUST follow..."）
        if text.startswith("."):
            return False
        # 以 < 开头通常是 XML/HTML 标签
        if text.startswith("<"):
            return False
        # 全是标点/符号
        if not re.search(r"[\w\u4e00-\u9fff]", text):
            return False
        return True

    def _extract_text(self, content: Any, role: str = "") -> str:
        """从 content 字段提取文本。如果是 user 消息，提取 <user_query> 标签内的内容。"""
        raw = ""
        if isinstance(content, str):
            raw = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") in ("input_text", "output_text", "text", "reasoning_text"):
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result" and block.get("output"):
                        parts.append(f"[ToolResult] {block.get('output')}")
            raw = "\n".join(p for p in parts if p)

        if role == "user" and raw:
            # 提取 <user_query>...</user_query> 标签内的真正用户输入
            match = re.search(r'<user_query>(.*?)</user_query>', raw, re.DOTALL)
            if match:
                return match.group(1).strip()
            # 提取失败：如果原文以 < 开头，说明是系统注入的 prompt，返回空字符串过滤掉
            if raw.lstrip().startswith("<"):
                return ""
        return raw

    def _format_timestamp(self, ts: Any) -> str:
        """把时间戳格式化为 HKT 时间字符串。"""
        if isinstance(ts, (int, float)):
            try:
                return datetime.fromtimestamp(ts / 1000, tz=HKT).strftime("%H:%M:%S")
            except Exception:
                pass
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(HKT).strftime("%H:%M:%S")
            except Exception:
                pass
        return ""

    def _render_record(
        self, record: Dict[str, Any], index: int, include_full: bool
    ) -> Optional[str]:
        """将单条记录渲染为 Markdown 片段。"""
        rec_type = record.get("type")
        ts = self._format_timestamp(record.get("timestamp"))
        ts_str = f" *{ts}*" if ts else ""

        if rec_type == "ai-title":
            title = record.get("aiTitle") or record.get("title") or "未命名对话"
            return f"### 🤖 AI 标题{ts_str}\n\n**{title}**\n\n---"

        if rec_type == "message":
            role = record.get("role")
            if role not in ("user", "assistant"):
                return None
            text = self._extract_text(record.get("content"), role=role).strip()
            if not text:
                return None

            label = "**你**" if role == "user" else "**AI**"
            return f"## {label}{ts_str}\n\n{text}\n\n---"

        if not include_full:
            return None

        if rec_type == "reasoning":
            content = record.get("rawContent") or record.get("content") or []
            text = self._extract_text(content).strip()
            if not text:
                return None
            return f"## 💭 Reasoning{ts_str}\n\n{text}\n\n---"

        if rec_type == "function_call":
            name = record.get("name") or "unknown"
            arguments = record.get("arguments") or "{}"
            try:
                if isinstance(arguments, str):
                    arg_text = json.dumps(json.loads(arguments), ensure_ascii=False, indent=2)
                else:
                    arg_text = json.dumps(arguments, ensure_ascii=False, indent=2)
            except Exception:
                arg_text = str(arguments)
            return f"## 🔧 工具调用: `{name}`{ts_str}\n\n```json\n{arg_text}\n```\n\n---"

        if rec_type == "function_call_result":
            name = record.get("name") or "unknown"
            status = record.get("status") or "completed"
            output = record.get("output", {})
            if isinstance(output, dict):
                output_text = output.get("text") or output.get("content") or json.dumps(output, ensure_ascii=False, indent=2)
            else:
                output_text = str(output)
            return f"## ✅ 工具结果: `{name}` ({status}){ts_str}\n\n{output_text}\n\n---"

        if rec_type == "file-history-snapshot":
            cwd = record.get("cwd") or ""
            snapshot = record.get("snapshot", {})
            backups = snapshot.get("trackedFileBackups") or {}
            files = list(backups.keys()) if backups else []
            files_text = "\n".join(f"- `{f}`" for f in files) or "*(无 tracked 文件)*"
            return f"## 📸 文件快照{ts_str}\n\n- cwd: `{cwd}`\n- tracked files:\n{files_text}\n\n---"

        return None

    def _write_json(self, records: List[Dict[str, Any]], path: Path) -> int:
        """导出为完整 JSON 数组。"""
        payload = {
            "exportedAt": datetime.now(HKT).isoformat(),
            "totalRecords": len(records),
            "records": records,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")
        return len(text.encode("utf-8"))

    def _write_markdown(
        self, records: List[Dict[str, Any]], path: Path, conversation_id: str, title: str, include_full: bool
    ) -> int:
        """导出为 Markdown 对话记录（含 Obsidian frontmatter）。"""
        now = datetime.now(HKT)
        date_str = now.strftime("%Y-%m-%d")

        # YAML frontmatter（Obsidian / Dataview 可识别）
        frontmatter = [
            "---",
            f"type: agent-conversation",
            f"date: {date_str}",
            f"conversationId: {conversation_id}",
            f'title: "{title}"',
            f"tags: [agent, 对话导出]",
            "---",
            "",
        ]

        lines = frontmatter + [
            f"# {title}",
            "",
            f"> **会话 ID**: `{conversation_id}`",
            f"> **导出时间**: {now.strftime('%Y-%m-%d %H:%M:%S')} (HKT)",
            f"> **原始记录数**: {len(records)} 条",
            "",
            "---",
            "",
        ]

        rendered_count = 0
        for idx, record in enumerate(records, start=1):
            rendered = self._render_record(record, idx, include_full)
            if rendered:
                lines.append(rendered)
                lines.append("")
                rendered_count += 1

        lines.append(
            f"\n*共渲染 {rendered_count} 条记录 · 由 agent 对话导出 Hook 生成*"
        )
        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")

        # 导出后更新月度索引
        try:
            self._update_monthly_index(path.parent, now)
        except Exception as exc:
            logger.warning("更新月度索引失败: %s", exc)

        return len(content.encode("utf-8"))

    def _update_monthly_index(self, export_dir: Path, now: datetime) -> None:
        """扫描导出目录，生成/更新当月索引文件。"""
        year_month = now.strftime("%Y-%m")
        month_prefix = now.strftime("%Y%m")
        index_path = export_dir / f"{year_month}-索引.md"

        # 收集当月所有对话导出文件（YYYYMMDD_开头的 .md，排除索引和摘要文件）
        entries = []
        for f in sorted(export_dir.glob(f"{month_prefix}*.md")):
            if "索引" in f.name or "摘要" in f.name:
                continue
            stem = f.stem
            # 从 frontmatter 提取标题，失败则用文件名
            title = stem
            try:
                content = f.read_text(encoding="utf-8")
                match = re.search(r'^title:\s*"?(.+?)"?\s*$', content, re.MULTILINE)
                if match:
                    title = match.group(1)
            except Exception:
                pass
            # 从文件名提取日期
            date_part = stem[:8]  # YYYYMMDD
            try:
                date_fmt = datetime.strptime(date_part, "%Y%m%d").strftime("%m-%d")
            except ValueError:
                date_fmt = date_part
            entries.append({
                "date": date_fmt,
                "title": title,
                "filename": f.name,
            })

        # 生成索引内容
        lines = [
            "---",
            f"type: agent-index",
            f"month: {year_month}",
            f"tags: [agent, 索引]",
            "---",
            "",
            f"# {year_month} agent 对话索引",
            "",
            f"> 自动生成 · 最后更新: {now.strftime('%Y-%m-%d %H:%M')} (HKT)",
            f"> 共 {len(entries)} 个对话",
            "",
            "| 日期 | 标题 | 文件 |",
            "|------|------|------|",
        ]
        for entry in entries:
            lines.append(f"| {entry['date']} | {entry['title']} | `[[{entry['filename']}]]` |")

        lines.append("")
        lines.append(f"*由 agent 对话导出 Hook 自动生成*")

        index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("月度索引已更新: %s（%d 个对话）", index_path.name, len(entries))

    def _write_text(self, records: List[Dict[str, Any]], path: Path, conversation_id: str, include_full: bool) -> int:
        """导出为纯文本。"""
        lines = [
            f"agent 对话记录",
            f"会话 ID: {conversation_id}",
            f"导出时间: {datetime.now(HKT).strftime('%Y-%m-%d %H:%M:%S')} (HKT)",
            f"记录数: {len(records)}",
            "=" * 40,
            "",
        ]

        for record in records:
            rec_type = record.get("type")
            if rec_type == "message":
                role = record.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = self._extract_text(record.get("content"), role=role).strip()
                if not text:
                    continue
                label = "你" if role == "user" else "AI"
                lines.append(f"[{label}]\n{text}\n")
            elif include_full and rec_type == "function_call":
                name = record.get("name") or "unknown"
                lines.append(f"[工具调用] {name}\n")
            elif include_full and rec_type == "function_call_result":
                name = record.get("name") or "unknown"
                lines.append(f"[工具结果] {name}\n")
            elif include_full and rec_type == "reasoning":
                text = self._extract_text(record.get("rawContent") or []).strip()
                if text:
                    lines.append(f"[Reasoning]\n{text}\n")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return len(content.encode("utf-8"))
