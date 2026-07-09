#!/usr/bin/env python3
"""
对话导出 Hook 单元测试
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 将 hooks 目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from hook_manager import HookContext, HookManager
from conversation_export_hook import ConversationExportHook


class TestConversationExportHook(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name) / "exports"
        self.config = {
            "enabled": True,
            "exportPath": str(self.output_dir / "{date}_{conversationId}"),
            "format": "markdown",
            "includeToolResults": False,
            "onError": "log",
            "logPath": str(Path(self.temp_dir.name) / "hook.log"),
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _project_dir(self, name: str) -> Path:
        """在临时目录中创建 agent 项目目录。"""
        return Path(self.temp_dir.name) / ".agent" / "projects" / name

    def _make_jsonl(self, conversation_id: str, project_dir: Path) -> Path:
        project_dir.mkdir(parents=True, exist_ok=True)
        jsonl = project_dir / f"{conversation_id}.jsonl"
        records = [
            {"type": "ai-title", "aiTitle": "测试对话", "sessionId": conversation_id},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "你好"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "你好！有什么可以帮你？"}]},
            {"type": "function_call", "name": "TaskCreate", "arguments": "{}"},
        ]
        with open(jsonl, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return jsonl

    def _work_dir_for(self, project_name: str) -> str:
        """根据项目目录名反推 workDir（模拟 agent 的命名规则）。"""
        # project_name 形如 Users-user-Agent-TestProject
        # workDir 形如 /Users/user/Agent/TestProject
        parts = project_name.split("-")
        if len(parts) > 3 and parts[:3] == ["Users", "user", "Agent"]:
            return "/" + "/".join(parts[3:])
        return "/" + project_name.replace("-", "/")

    def test_export_markdown(self):
        """默认仅导出消息，不含工具调用。"""
        conversation_id = "test-conv-123"
        project_name = "Users-user-Agent-TestProject"
        project_dir = self._project_dir(project_name)
        self._make_jsonl(conversation_id, project_dir)

        hook = ConversationExportHook(agent_dir=Path(self.temp_dir.name) / ".agent")
        context = HookContext(conversation_id=conversation_id, work_dir=self._work_dir_for(project_name))
        result = hook(context, self.config)

        self.assertEqual(result["format"], "markdown")
        self.assertTrue(Path(result["output"]).exists())
        content = Path(result["output"]).read_text(encoding="utf-8")
        self.assertIn("# 测试对话", content)
        self.assertIn("你好", content)
        self.assertIn("有什么可以帮你", content)
        self.assertNotIn("工具调用", content)

    def test_export_markdown_full(self):
        """includeToolResults=True 时包含工具调用。"""
        conversation_id = "test-conv-123-full"
        project_name = "Users-user-Agent-TestProject"
        project_dir = self._project_dir(project_name)
        self._make_jsonl(conversation_id, project_dir)

        self.config["includeToolResults"] = True
        self.config["exportPath"] = str(self.output_dir / "full_{date}_{conversationId}")
        hook = ConversationExportHook(agent_dir=Path(self.temp_dir.name) / ".agent")
        context = HookContext(conversation_id=conversation_id, work_dir=self._work_dir_for(project_name))
        result = hook(context, self.config)

        content = Path(result["output"]).read_text(encoding="utf-8")
        self.assertIn("工具调用", content)

    def test_skip_if_up_to_date(self):
        """目标文件已存在且最新时跳过。"""
        conversation_id = "test-conv-skip"
        project_name = "Users-user-Agent-TestProject"
        project_dir = self._project_dir(project_name)
        jsonl = self._make_jsonl(conversation_id, project_dir)

        hook = ConversationExportHook(agent_dir=Path(self.temp_dir.name) / ".agent")
        context = HookContext(conversation_id=conversation_id, work_dir=self._work_dir_for(project_name))
        result1 = hook(context, self.config)
        self.assertFalse(result1.get("skipped", False))

        result2 = hook(context, self.config)
        self.assertTrue(result2.get("skipped", True))

    def test_export_json(self):
        conversation_id = "test-conv-456"
        project_name = "Users-user-Agent-TestProject"
        project_dir = self._project_dir(project_name)
        self._make_jsonl(conversation_id, project_dir)

        self.config["format"] = "json"
        hook = ConversationExportHook(agent_dir=Path(self.temp_dir.name) / ".agent")
        context = HookContext(conversation_id=conversation_id, work_dir=self._work_dir_for(project_name))
        result = hook(context, self.config)

        self.assertEqual(result["format"], "json")
        with open(result["output"], "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.assertIn("records", payload)
        self.assertEqual(payload["totalRecords"], 4)

    def test_export_text(self):
        conversation_id = "test-conv-789"
        project_name = "Users-user-Agent-TestProject"
        project_dir = self._project_dir(project_name)
        self._make_jsonl(conversation_id, project_dir)

        self.config["format"] = "text"
        hook = ConversationExportHook(agent_dir=Path(self.temp_dir.name) / ".agent")
        context = HookContext(conversation_id=conversation_id, work_dir=self._work_dir_for(project_name))
        result = hook(context, self.config)

        self.assertTrue(result["output"].endswith(".txt"))
        content = Path(result["output"]).read_text(encoding="utf-8")
        self.assertIn("[你]", content)
        self.assertIn("[AI]", content)

    def test_hook_manager_exception_isolation(self):
        """Hook 异常不应影响主流程和其他 hook。"""

        def failing_hook(ctx, cfg):
            raise RuntimeError("故意失败")

        def success_hook(ctx, cfg):
            return "ok"

        manager = HookManager()
        manager.config = self.config
        manager.register("fail", failing_hook)
        manager.register("success", success_hook)

        result = manager.trigger(HookContext())

        self.assertEqual(result["results"]["fail"]["status"], "failed")
        self.assertEqual(result["results"]["success"]["status"], "success")

    def test_disabled_hook(self):
        self.config["enabled"] = False
        manager = HookManager()
        manager.config = self.config
        manager.register("export", ConversationExportHook())
        result = manager.trigger(HookContext())
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
