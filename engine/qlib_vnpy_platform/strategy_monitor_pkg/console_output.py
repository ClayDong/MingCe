#!/usr/bin/env python3
"""
控制台输出适配器
直接将报告内容打印到控制台
"""


class ConsoleOutput:
    """控制台输出适配器"""

    @staticmethod
    def send_message(message_text):
        """直接打印到控制台"""
        print(message_text)
        return True

    @staticmethod
    def send_report(report, message_key='message'):
        """发送报告到控制台"""
        if not report:
            print("❌ 报告为空")
            return False
        message_text = report.get(message_key, report) if isinstance(report, dict) else report
        print(message_text)
        return True
