import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.agent.router import AgentRoute, classify_question, extract_project_keyword


class AgentRouterTests(unittest.TestCase):
    def test_routes_project_progress_question_to_project_status(self):
        route = classify_question("APQP-2026-001 当前进度怎么样，是否延期？")

        self.assertEqual(route.route, "project_status")
        self.assertEqual(route.tool_name, "apqp_project_status")
        self.assertEqual(route.project_keyword, "APQP-2026-001")

    def test_routes_high_risk_question_to_risk_tool(self):
        route = classify_question("APQP-2026-002 有哪些高风险和 RPN 项？")

        self.assertEqual(route.route, "high_risks")
        self.assertEqual(route.tool_name, "apqp_high_risks")

    def test_routes_open_issue_question_to_issue_tool(self):
        route = classify_question("APQP-2026-003 还有哪些未关闭问题？")

        self.assertEqual(route.route, "open_issues")
        self.assertEqual(route.tool_name, "apqp_open_issues")

    def test_routes_missing_deliverable_question_to_deliverable_tool(self):
        route = classify_question("APQP-2026-001 缺少哪些交付物？")

        self.assertEqual(route.route, "missing_deliverables")
        self.assertEqual(route.tool_name, "apqp_missing_deliverables")

    def test_routes_apqp_knowledge_question_to_rag(self):
        route = classify_question("APQP 流程有哪些阶段？")

        self.assertEqual(route.route, "rag")
        self.assertIsNone(route.tool_name)

    def test_routes_project_plus_knowledge_question_to_hybrid(self):
        route = classify_question("APQP-2026-001 为什么延期，APQP 阶段评审要求是什么？")

        self.assertEqual(route.route, "hybrid")
        self.assertEqual(route.tool_name, "apqp_project_summary")

    def test_extract_project_keyword_supports_project_id(self):
        self.assertEqual(extract_project_keyword("请看 APQP-2026-006 的状态"), "APQP-2026-006")

    def test_unknown_question_defaults_to_rag(self):
        route = classify_question("控制计划应该包含哪些内容？")

        self.assertEqual(route, AgentRoute(route="rag"))


if __name__ == "__main__":
    unittest.main()
