"""测试 LLM 服务模块。"""
import unittest
from services.llm_service import _clean_response


class TestCleanResponse(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(_clean_response(""), "")

    def test_no_think_tag(self):
        text = "这是正常的回复内容。"
        self.assertEqual(_clean_response(text), text)

    def test_think_tag_removal(self):
        result = _clean_response("")
        self.assertEqual(_clean_response("实际内容"), "实际内容")

    def test_think_tag_with_attributes(self):
        result = _clean_response("正文")
        self.assertEqual(result, "正文")

    def test_thinking_prefix(self):
        result = _clean_response("Thinking Process:\n\n这是第一段\n\n这是实际内容有足够长度的正文")
        self.assertIn("实际内容", result)
        self.assertNotIn("Thinking", result)

    def test_thinking_newline_prefix(self):
        result = _clean_response("Thinking\n\n这里是实际内容有足够长度的回复正文")
        self.assertIn("实际内容", result)

    def test_chinese_thinking_prefix(self):
        result = _clean_response("思考过程:\n\n这是实际内容有足够长度")
        self.assertIn("实际内容", result)

    def test_only_think_tag(self):
        result = _clean_response("<think>只思考了</think>")
        self.assertEqual(result, "")

    def test_nested_think_tags(self):
        input_text = "<think>深层思考</think>最终输出内容"
        result = _clean_response(input_text)
        self.assertEqual(result, "最终输出内容")

    def test_think_tag_and_aftermath(self):
        input_text = "<think deepseek='yes'>一些思考</think>回复正文"
        result = _clean_response(input_text)
        self.assertNotIn("思考", result)
        self.assertIn("回复正文", result)

    def test_multiple_think_tags(self):
        input_text = "<think>第一次思考</think>中间文本最终文本"
        result = _clean_response(input_text)
        self.assertIn("最终文本", result)


if __name__ == "__main__":
    unittest.main()
