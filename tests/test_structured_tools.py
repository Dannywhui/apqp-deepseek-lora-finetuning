import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.structured.tools import get_structured_query_tools


class StructuredToolsTests(unittest.TestCase):
    def test_registers_expected_langchain_tools(self):
        tools = get_structured_query_tools()

        tool_names = {tool.name for tool in tools}

        self.assertEqual(
            tool_names,
            {
                "apqp_project_status",
                "apqp_high_risks",
                "apqp_open_issues",
                "apqp_missing_deliverables",
                "apqp_project_summary",
            },
        )
        self.assertTrue(all(tool.description for tool in tools))

    def test_project_summary_tool_wraps_controlled_query_function(self):
        tools = {tool.name: tool for tool in get_structured_query_tools()}

        class FakeConnection:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        fake_summary = {
            "project": "APQP-2026-001",
            "status": [{"project_id": "APQP-2026-001"}],
            "high_risks": [],
            "open_issues": [],
            "missing_deliverables": [],
        }

        with patch("back.structured.tools.connect_mysql_from_env", return_value=fake_connection) as connect:
            with patch("back.structured.tools.summarize_project", return_value=fake_summary) as summarize:
                result = tools["apqp_project_summary"].invoke({"project_keyword": "APQP-2026-001"})

        connect.assert_called_once_with()
        summarize.assert_called_once_with(fake_connection, "APQP-2026-001")
        self.assertEqual(result, fake_summary)
        self.assertTrue(fake_connection.closed)


if __name__ == "__main__":
    unittest.main()
