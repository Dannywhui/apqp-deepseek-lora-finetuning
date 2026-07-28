import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.main import Message, enrich_messages_with_agent


class FakeTool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return self.result


class MainAgentIntegrationTests(unittest.TestCase):
    def test_project_question_injects_tool_context(self):
        tool = FakeTool(
            [
                {
                    "project_id": "APQP-2026-001",
                    "current_status": "Delayed",
                    "source_file": "project_progress_samples.xlsx",
                    "source_sheet": "项目进度",
                }
            ]
        )

        with patch("back.main.get_structured_query_tools", return_value=[tool]):
            tool.name = "apqp_project_status"
            messages, sources = enrich_messages_with_agent(
                [Message(role="user", content="APQP-2026-001 当前进度怎么样？")]
            )

        self.assertEqual(tool.calls, [{"project_keyword": "APQP-2026-001"}])
        self.assertEqual(sources[0]["source"], "project_progress_samples.xlsx")
        self.assertEqual(sources[0]["label"], "project_progress_samples.xlsx，项目进度")
        self.assertIn("【结构化项目数据】", messages[0].content)
        self.assertIn("Delayed", messages[0].content)

    def test_rag_question_keeps_rag_sources(self):
        with patch(
            "back.main.retrieve_rag_contexts",
            return_value=[
                {
                    "text": "APQP has five phases.",
                    "metadata": {"source": "apqp.md", "chunk_index": 1},
                    "score": 0.9,
                }
            ],
        ):
            messages, sources = enrich_messages_with_agent(
                [Message(role="user", content="APQP 流程有哪些阶段？")]
            )

        self.assertIn("【知识库资料】", messages[0].content)
        self.assertIn("APQP has five phases.", messages[0].content)
        self.assertEqual(sources[0]["source"], "apqp.md")


if __name__ == "__main__":
    unittest.main()
