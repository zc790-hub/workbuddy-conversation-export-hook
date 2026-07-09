#!/usr/bin/env python3
"""
对话结束 Hook 触发入口

用法：
    python3 run_hook.py                              # 使用默认配置导出当前对话
    python3 run_hook.py --conversation-id <id>       # 导出指定对话
    python3 run_hook.py --format json                # 指定导出格式
    python3 run_hook.py --output /path/to/file.md    # 指定输出路径
    python3 run_hook.py --config /path/to/config.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from hook_manager import HookContext, HookManager
from conversation_export_hook import ConversationExportHook


def interactive_init(config_path: str) -> int:
    """交互式生成配置文件。"""
    print("=" * 50)
    print("  agent 对话导出配置向导")
    print("=" * 50)
    print()

    # 导出路径
    default_path = "~/Documents/agent对话导出/{date8}_{conversationId}_{title}"
    print(f"导出路径（支持占位符 {{date8}} {{conversationId}} {{title}}）")
    path_input = input(f"  [{default_path}]: ").strip()
    export_path = path_input or default_path

    # 格式
    print("导出格式: 1) markdown (推荐)  2) json  3) text")
    fmt_input = input("  [1]: ").strip()
    fmt_map = {"1": "markdown", "2": "json", "3": "text"}
    fmt = fmt_map.get(fmt_input, "markdown")

    # 是否包含工具调用
    print("包含工具调用和推理过程？ 1) 否（推荐，仅消息）  2) 是")
    full_input = input("  [1]: ").strip()
    include_full = full_input == "2"

    # 日志路径
    default_log = "~/.agent/logs/conversation-export-hook.log"
    log_input = input(f"日志路径 [{default_log}]: ").strip()
    log_path = log_input or default_log

    config = {
        "enabled": True,
        "exportPath": export_path,
        "format": fmt,
        "includeToolResults": include_full,
        "onError": "log",
        "logPath": log_path,
    }

    config_file = Path(config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"✅ 配置已保存到: {config_file}")
    print(f"   导出路径: {export_path}")
    print(f"   格式: {fmt}")
    print(f"   包含工具调用: {'是' if include_full else '否'}")
    print()
    print("提示: 将 Obsidian 知识库路径填入导出路径，即可自动归档到 Obsidian。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="agent 对话导出 Skill")
    parser.add_argument("--config", "-c", help="Hook 配置文件路径")
    parser.add_argument("--conversation-id", "-i", help="指定对话 ID")
    parser.add_argument("--work-dir", "-w", help="指定工作目录")
    parser.add_argument("--session-file", "-s", help="指定 session 文件")
    parser.add_argument("--format", "-f", choices=["json", "markdown", "text"], help="导出格式")
    parser.add_argument("--output", "-o", help="输出文件路径（覆盖配置文件中的 exportPath）")
    parser.add_argument("--dry-run", action="store_true", help="只打印配置和上下文，不执行导出")
    parser.add_argument("--init", action="store_true", help="交互式生成配置文件")
    args = parser.parse_args()

    # 确定配置文件路径
    config_path = args.config or str(Path(__file__).with_name("hook-config.json"))

    # 交互式初始化
    if args.init:
        return interactive_init(config_path)

    manager = HookManager(config_path=config_path)

    # 命令行参数覆盖配置文件
    if args.format:
        manager.config["format"] = args.format
    if args.output:
        manager.config["exportPath"] = args.output

    manager.setup_logging()
    logging.getLogger().setLevel(logging.DEBUG if args.dry_run else logging.INFO)

    context = HookContext(
        conversation_id=args.conversation_id,
        work_dir=args.work_dir,
        session_file=args.session_file,
    )

    if args.dry_run:
        print("=== Hook 干运行模式 ===")
        print(f"配置: {json.dumps(manager.config, ensure_ascii=False, indent=2)}")
        print(f"上下文: conversation_id={context.conversation_id}, work_dir={context.work_dir}")
        return 0

    manager.register("conversation_export", ConversationExportHook())
    result = manager.trigger(context)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 返回非零码仅用于脚本判断，不会阻断主流程
    failed = any(r.get("status") == "failed" for r in result.get("results", {}).values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
