#!/usr/bin/env python3
"""
飞书输出适配器
统一通过中转API (http://localhost:8000/api/send_message) 发送消息到飞书
"""

import sys
import json
from pathlib import Path


class FeishuOutput:
    """飞书输出适配器

    所有飞书消息发送统一走中转API，不再直接调用飞书API或lark-cli。
    """

    RELAY_API_URL = "http://localhost:8000/api/send_message"

    def __init__(self, chat_id=None):
        self.chat_id = chat_id
        # 从配置加载
        self._load_config()

    def _load_config(self):
        """加载飞书配置中的 chat_id"""
        if self.chat_id:
            return
        config_file = Path(__file__).parent.parent.parent / 'feishu_config.json'
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.chat_id = cfg.get("chat_id", self.chat_id or "oc_599b2776ddd142e49fa2b22aac449c3b")
            except Exception:
                pass
        if not self.chat_id:
            self.chat_id = "oc_599b2776ddd142e49fa2b22aac449c3b"

    def send_message(self, message_text):
        """发送 Markdown 消息到飞书

        Args:
            message_text: Markdown 格式的消息内容

        Returns:
            bool: 是否发送成功
        """
        import requests
        try:
            payload = {"msg_type": "markdown", "content": message_text}
            resp = requests.post(self.RELAY_API_URL, json=payload, timeout=15)
            if resp.status_code == 200:
                print("✅ 飞书消息发送成功 (via relay API)")
                return True
            else:
                print(f"⚠️ 中转API失败 (status={resp.status_code}): {resp.text[:200]}")
                return False
        except ImportError:
            print("⚠️ requests 未安装，无法发送飞书消息")
            return False
        except Exception as e:
            print(f"⚠️ 中转API异常: {e}")
            return False

    def send_report(self, report, message_key='message'):
        """发送已生成的报告（message 字段）到飞书

        Args:
            report: dict — 包含 message 字段的报告
            message_key: 消息内容的字段名，默认 'message'
        """
        if not report:
            print("❌ 报告为空，无法发送")
            return False
        message_text = report.get(message_key, report) if isinstance(report, dict) else report
        return self.send_message(message_text)
