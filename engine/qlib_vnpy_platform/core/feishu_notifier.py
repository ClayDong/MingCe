"""
飞书通知模块
提供统一的飞书消息发送接口
优先通过中转API发送，失败则fallback到lark-cli
"""

import os
import json
import time
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RELAY_API_URL = "http://localhost:8000/api/send_message"


class FeishuNotifier:
    """飞书通知管理器"""

    def __init__(self, config_path: str = None):
        """
        初始化飞书通知器

        Args:
            config_path: 配置文件路径，默认使用项目根目录下的 feishu_config.json
        """
        if config_path is None:
            config_path = str(PROJECT_ROOT / "feishu_config.json")

        self.config_path = config_path
        self.config = self._load_config()
        self.chat_id = self.config.get("chat_id", "")

        self.lark_cli_path = self._find_lark_cli()

        logger.info(f"FeishuNotifier initialized: chat_id={self.chat_id}")

    def _load_config(self) -> dict:
        """加载配置文件"""
        try:
            if not os.path.exists(self.config_path):
                logger.warning(f"Config file not found: {self.config_path}")
                return {}
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def _find_lark_cli(self) -> str:
        """查找 lark-cli 可执行文件"""
        lark_cli_path = shutil.which("lark-cli")
        if lark_cli_path:
            return lark_cli_path
        for p in [
            "/Users/dong/.nvm/versions/node/v24.14.0/bin/lark-cli",
            "/Users/dong/.nvm/versions/node/v22.22.3/bin/lark-cli",
            "/usr/local/bin/lark-cli",
        ]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return ""

    def send_markdown(self, markdown_text: str) -> bool:
        """
        发送 Markdown 消息

        Args:
            markdown_text: Markdown 格式的文本

        Returns:
            是否发送成功
        """
        # 优先使用中转API
        if self._send_with_relay_api(markdown_text):
            return True

        # fallback到 lark-cli
        if self.lark_cli_path:
            if self._send_with_lark_cli(markdown_text):
                return True

        logger.error("All feishu sending methods failed")
        return False

    def send_daily_report(self, report_content: str) -> bool:
        """
        发送日报

        Args:
            report_content: 日报内容

        Returns:
            是否发送成功
        """
        message_lines = [
            f"📊 **每日交易报告**",
            f"🕐 **{datetime.now().strftime('%Y-%m-%d %H:%M')}**",
            f"",
            f"---",
            f"",
        ]
        for line in report_content.split('\n'):
            if line.strip():
                message_lines.append(line)

        message = "\n".join(message_lines)
        return self.send_markdown(message)

    def send_alert(self, title: str, content: str, level: str = "warning") -> bool:
        """
        发送告警

        Args:
            title: 标题
            content: 内容
            level: 告警级别 (warning/error/info)

        Returns:
            是否发送成功
        """
        icon_map = {
            "warning": "⚠️",
            "error": "🚨",
            "info": "ℹ️",
        }
        icon = icon_map.get(level, "⚠️")

        message_lines = [
            f"{icon} **{title}**",
            f"🕐 **{datetime.now().strftime('%Y-%m-%d %H:%M')}**",
            f"",
            f"---",
            f"",
            content,
        ]
        message = "\n".join(message_lines)
        return self.send_markdown(message)

    def _send_with_relay_api(self, message: str) -> bool:
        """通过中转API发送消息"""
        if not self.chat_id:
            logger.warning("chat_id not configured, skipping relay API")
            return False
        try:
            import requests
            payload = {
                "msg_type": "markdown",
                "content": message,
            }
            resp = requests.post(RELAY_API_URL, json=payload, timeout=15)
            if resp.status_code == 200:
                logger.info("Feishu message sent successfully via relay API")
                return True
            else:
                logger.warning(f"Relay API returned status {resp.status_code}: {resp.text[:200]}")
                return False
        except ImportError:
            logger.warning("requests not installed, cannot use relay API")
            return False
        except Exception as e:
            logger.error(f"Failed to send via relay API: {e}")
            return False

    def _send_with_lark_cli(self, message: str) -> bool:
        """使用 lark-cli 发送消息"""
        try:
            node_bin = os.path.dirname(self.lark_cli_path)
            node_env = os.environ.copy()
            if node_bin:
                node_env['PATH'] = node_bin + ':' + node_env.get('PATH', '')

            cmd = [self.lark_cli_path, "im", "+messages-send",
                   "--chat-id", self.chat_id, "--markdown", message]

            result = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=30, env=node_env)

            if result.returncode == 0:
                logger.info("Feishu message sent successfully via lark-cli")
                return True
            else:
                logger.warning(f"lark-cli failed: {result.stderr[:200]}")
                return False
        except Exception as e:
            logger.error(f"Failed to send via lark-cli: {e}")
            return False


# 全局单例
_notifier_instance = None


def get_notifier() -> FeishuNotifier:
    """获取飞书通知器单例"""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = FeishuNotifier()
    return _notifier_instance


def send_markdown(message: str) -> bool:
    """便捷函数：发送 Markdown 消息"""
    try:
        return get_notifier().send_markdown(message)
    except Exception as e:
        logger.error(f"Failed to send: {e}")
        return False


def send_daily_report(report_content: str) -> bool:
    """便捷函数：发送日报"""
    try:
        return get_notifier().send_daily_report(report_content)
    except Exception as e:
        logger.error(f"Failed to send daily report: {e}")
        return False


def send_alert(title: str, content: str, level: str = "warning") -> bool:
    """便捷函数：发送告警"""
    try:
        return get_notifier().send_alert(title, content, level)
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")
        return False
