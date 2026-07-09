#!/usr/bin/env python3
"""
通用 Hook 管理器

负责：
1. 加载 hook 配置（启用状态、导出路径、格式等）
2. 注册/注销 hook
3. 在对话结束时按顺序触发 hook
4. 隔离 hook 异常，确保不影响主流程
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HookContext:
    """传递给每个 hook 的上下文对象。"""

    conversation_id: Optional[str] = None
    work_dir: Optional[str] = None
    session_file: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "HookContext":
        """从环境变量中解析上下文（agent 调用时可能传入）。"""
        return cls(
            conversation_id=os.environ.get("AGENT_CONVERSATION_ID"),
            work_dir=os.environ.get("AGENT_WORK_DIR"),
            session_file=os.environ.get("AGENT_SESSION_FILE"),
        )


HookCallable = Callable[[HookContext, Dict[str, Any]], Any]


class HookManager:
    """Hook 注册与触发中枢。"""

    DEFAULT_CONFIG_PATH = Path(__file__).with_name("hook-config.json")
    LOCAL_CONFIG_PATH = Path(__file__).with_name("hook-config.local.json")

    def __init__(self, config_path: Optional[str] = None):
        # 优先使用 local 配置（用户自定义），其次默认配置
        if config_path:
            self.config_path = Path(config_path)
        elif self.LOCAL_CONFIG_PATH.exists():
            self.config_path = self.LOCAL_CONFIG_PATH
        else:
            self.config_path = self.DEFAULT_CONFIG_PATH
        self._hooks: Dict[str, HookCallable] = {}
        self.config: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """加载 JSON 配置文件；不存在或损坏时使用默认配置。"""
        defaults = {
            "enabled": True,
            "exportPath": "~/Documents/agent对话导出/{date}_{conversationId}",
            "format": "markdown",
            "includeToolResults": False,
            "onError": "log",
            "logPath": "~/.agent/logs/conversation-export-hook.log",
        }

        if not self.config_path.exists():
            logger.warning("配置文件不存在，使用默认配置: %s", self.config_path)
            return defaults

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            defaults.update(user_config)
        except json.JSONDecodeError as exc:
            logger.error("配置文件 JSON 解析失败: %s", exc)
        except Exception as exc:
            logger.error("读取配置文件失败: %s", exc)

        return defaults

    def register(self, name: str, hook: HookCallable) -> None:
        """注册一个 hook。"""
        self._hooks[name] = hook
        logger.debug("已注册 hook: %s", name)

    def unregister(self, name: str) -> None:
        """注销一个 hook。"""
        self._hooks.pop(name, None)

    def setup_logging(self) -> None:
        """根据配置初始化日志；若文件写入失败则降级为仅控制台。"""
        handlers: List[logging.Handler] = [logging.StreamHandler()]
        log_path_str = self.config.get("logPath") or "~/.agent/logs/conversation-export-hook.log"
        log_path = Path(log_path_str).expanduser()

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.insert(0, logging.FileHandler(log_path, encoding="utf-8"))
        except Exception as exc:
            logger.warning("无法创建日志文件 %s: %s，降级为控制台日志", log_path, exc)

        # 清除已有的 root handlers，避免重复
        for h in logging.root.handlers[:]:
            logging.root.removeHandler(h)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=handlers,
        )

    def trigger(self, context: Optional[HookContext] = None) -> Dict[str, Any]:
        """
        触发所有已注册的 hook。

        每个 hook 独立执行；任意 hook 抛异常都会被捕获，不会中断后续 hook 或主流程。
        返回每个 hook 的执行结果摘要。
        """
        if not self.config.get("enabled", True):
            logger.info("Hook 机制已禁用，跳过触发")
            return {"status": "skipped", "reason": "disabled"}

        self.setup_logging()
        context = context or HookContext.from_env()
        results: Dict[str, Any] = {}

        for name, hook in self._hooks.items():
            try:
                logger.info("触发 hook: %s", name)
                result = hook(context, self.config)
                results[name] = {"status": "success", "result": result}
            except Exception as exc:
                error_msg = str(exc)
                tb = traceback.format_exc()
                logger.error("Hook '%s' 执行失败: %s\n%s", name, error_msg, tb)
                results[name] = {"status": "failed", "error": error_msg}

                if self.config.get("onError") == "raise":
                    logger.warning("onError=raise，但主流程不应被阻断；仅记录异常")

        return {"status": "completed", "results": results}
