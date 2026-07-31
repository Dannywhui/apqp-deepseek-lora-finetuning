import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.agent.context import AgentContext, build_agent_context, build_agent_prompt
from back.agent.router import AgentRoute


class FakeTool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return self.result


class AgentContextTests(unittest.TestCase):
    def test_project_question_calls_matching_tool_without_rag(self):
        summary_tool = FakeTool([{"project_id": "APQP-2026-001", "current_status": "In Progress"}])
        rag_calls = []

        context = build_agent_context(
            "APQP-2026-001 当前进度怎么样？",
            tools={"apqp_project_status": summary_tool},
            rag_retriever=lambda question: rag_calls.append(question) or [],
        )

        self.assertEqual(context.route.route, "project_status")
        self.assertEqual(summary_tool.calls, [{"project_keyword": "APQP-2026-001"}])
        self.assertEqual(rag_calls, [])
        self.assertEqual(context.tool_result[0]["current_status"], "In Progress")

    def test_rag_question_calls_only_rag(self):
        context = build_agent_context(
            "APQP 流程有哪些阶段？",
            tools={},
            rag_retriever=lambda question: [{"text": "APQP has five phases.", "metadata": {"source": "apqp.md"}}],
        )

        self.assertEqual(context.route.route, "rag")
        self.assertEqual(context.tool_result, None)
        self.assertEqual(context.rag_contexts[0]["metadata"]["source"], "apqp.md")

    def test_hybrid_question_calls_tool_and_rag(self):
        summary_tool = FakeTool({"status": [{"project_id": "APQP-2026-001"}]})

        context = build_agent_context(
            "APQP-2026-001 为什么延期，APQP 阶段评审要求是什么？",
            tools={"apqp_project_summary": summary_tool},
            rag_retriever=lambda question: [{"text": "Phase gate review requires evidence.", "metadata": {"source": "manual.md"}}],
        )

        self.assertEqual(context.route.route, "hybrid")
        self.assertEqual(summary_tool.calls, [{"project_keyword": "APQP-2026-001"}])
        self.assertEqual(len(context.rag_contexts), 1)

    def test_build_agent_prompt_includes_tool_and_rag_context(self):
        context = AgentContext(
            route=AgentRoute("hybrid", "apqp_project_summary", "PROJ2026001"),
            tool_result={"status": [{"project_id": "PROJ2026001", "current_status": "Delayed"}]},
            rag_contexts=[
                {
                    "text": "阶段评审需要确认风险和交付物。",
                    "metadata": {"source": "manual.md"},
                }
            ],
        )

        prompt = build_agent_prompt("PROJ2026001 为什么延期，APQP 阶段评审要求是什么？", context)

        self.assertIn("【项目事实】", prompt)
        self.assertIn("PROJ2026001", prompt)
        self.assertIn("【流程依据】", prompt)
        self.assertIn("阶段评审需要确认风险和交付物。", prompt)
        self.assertIn("请仅基于以上资料回答", prompt)

    def test_build_agent_prompt_formats_tool_result_as_business_summary(self):
        context = AgentContext(
            route=AgentRoute("project_summary", "apqp_project_summary", "APQP-2026-001"),
            tool_result={
                "status": [
                    {
                        "project_id": "APQP-2026-001",
                        "current_phase": "第三阶段 - 工艺设计与开发",
                        "current_status": "进行中",
                        "progress_note": "PFMEA 草案已完成，控制计划等待确认。",
                        "source_file": "project_progress_samples.xlsx",
                        "source_sheet": "项目进度",
                    }
                ],
                "missing_deliverables": [
                    {
                        "delivery_id": "D-002",
                        "deliverable_name": "控制计划",
                        "owner": "王磊",
                        "missing_or_reject_reason": "关键焊接工序反应计划缺失",
                    }
                ],
            },
        )

        prompt = build_agent_prompt("APQP-2026-001 当前进度怎么样？", context)

        self.assertIn("项目进度", prompt)
        self.assertIn("项目编号：APQP-2026-001", prompt)
        self.assertIn("当前状态：进行中", prompt)
        self.assertIn("未完成交付物", prompt)
        self.assertIn("交付物名称：控制计划", prompt)
        self.assertNotIn('"status"', prompt)
        self.assertNotIn("{", prompt)
        self.assertNotIn("来源文件", prompt)
        self.assertNotIn("来源表", prompt)
        self.assertNotIn("project_progress_samples.xlsx", prompt)

    def test_build_agent_prompt_does_not_expose_internal_route_info(self):
        context = AgentContext(
            route=AgentRoute("high_risks", "apqp_high_risks", "APQP-2026-003"),
            tool_result={"high_risks": [{"project_id": "APQP-2026-003", "rpn": 210}]},
        )

        prompt = build_agent_prompt("APQP-2026-003 当前 RPN 最高的风险是什么？", context)

        self.assertNotIn("【路由信息】", prompt)
        self.assertNotIn("route=", prompt)
        self.assertNotIn("tool=", prompt)
        self.assertNotIn("apqp_high_risks", prompt)

    def test_build_agent_prompt_forbids_cross_project_or_unlisted_records(self):
        context = AgentContext(
            route=AgentRoute("high_risks", "apqp_high_risks", "APQP-2026-001"),
            tool_result=[
                {
                    "project_id": "APQP-2026-001",
                    "risk_id": "R-001",
                    "risk_description": "粘合过程中的气泡缺陷可能导致显示异常",
                }
            ],
        )

        prompt = build_agent_prompt("APQP-2026-001 有哪些高风险？", context)

        self.assertIn("只回答当前用户问题对应项目", prompt)
        self.assertIn("只回答结构化数据中列出的记录", prompt)
        self.assertIn("不要补充其他项目", prompt)
        self.assertIn("不要补充未列出的风险", prompt)

    def test_build_agent_prompt_explicitly_forbids_json_fields_and_tool_info(self):
        context = AgentContext(
            route=AgentRoute("missing_deliverables", "apqp_missing_deliverables", "APQP-2026-006"),
            tool_result={"missing_deliverables": [{"project_id": "APQP-2026-006"}]},
        )

        prompt = build_agent_prompt("APQP-2026-006 有哪些交付物没有完成？", context)

        self.assertIn("不要输出原始 JSON", prompt)
        self.assertIn("不要输出字段名", prompt)
        self.assertIn("不要提及工具名", prompt)
        self.assertIn("不要提及路由信息", prompt)

    def test_build_agent_prompt_separates_project_facts_and_process_basis_for_hybrid_questions(self):
        context = AgentContext(
            route=AgentRoute("hybrid", "apqp_project_summary", "APQP-2026-003"),
            tool_result={
                "high_risks": [
                    {
                        "project_id": "APQP-2026-003",
                        "risk_description": "偏光片供应商验证周期过长",
                        "rpn": 210,
                        "mitigation_action": "双供应商验证，增加安全库存",
                    }
                ]
            },
            rag_contexts=[
                {
                    "text": "APQP 风险评审应形成可执行的预防措施，并明确责任人和完成时间。",
                    "metadata": {"source": "manual.md", "chunk_index": 2},
                }
            ],
        )

        prompt = build_agent_prompt("APQP-2026-003 当前风险是什么，按照 APQP 流程应该如何处理？", context)

        self.assertIn("【项目事实】", prompt)
        self.assertIn("【流程依据】", prompt)
        self.assertIn("先回答项目当前事实", prompt)
        self.assertIn("再说明流程依据", prompt)
        self.assertIn("最后给出结合建议", prompt)
        self.assertIn("偏光片供应商验证周期过长", prompt)
        self.assertIn("APQP 风险评审应形成可执行的预防措施", prompt)

    def test_build_agent_prompt_guides_structured_professional_answer_style(self):
        context = AgentContext(
            route=AgentRoute("project_summary", "apqp_project_summary", "APQP-2026-001"),
            tool_result={"status": [{"project_id": "APQP-2026-001", "current_status": "进行中"}]},
        )

        prompt = build_agent_prompt("APQP-2026-001 当前进度怎么样？", context)

        self.assertIn("【输出格式", prompt)
        self.assertIn("【结论】", prompt)
        self.assertIn("【项目情况】", prompt)
        self.assertIn("【关注点】", prompt)
        self.assertIn("【建议】", prompt)
        self.assertIn("【内容质量要求】", prompt)
        self.assertIn("先结论后细节", prompt)
        self.assertIn("建议必须可执行", prompt)
        self.assertIn("不要逐表复述「根据…表」", prompt)
        self.assertIn("不要追加 AI 免责声明", prompt)


if __name__ == "__main__":
    unittest.main()
