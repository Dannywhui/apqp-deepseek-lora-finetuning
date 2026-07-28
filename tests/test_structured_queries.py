import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.structured.queries import (
    query_high_risks,
    query_missing_deliverables,
    query_open_issues,
    query_project_status,
    summarize_project,
)


# 轻量模拟 mysql-connector 的 cursor，用来记录 SQL 和参数。
# 这样测试不需要真实 MySQL，也能验证查询是否安全、参数是否正确。
class FakeQueryCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeQueryConnection:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.cursors = []

    def cursor(self, **kwargs):
        # 每次查询消耗一组预设结果，模拟真实连接每次返回新 cursor 的行为。
        rows = self.result_sets.pop(0)
        cursor = FakeQueryCursor(rows)
        cursor.kwargs = kwargs
        self.cursors.append(cursor)
        return cursor


class StructuredQueryTests(unittest.TestCase):
    def test_query_project_status_filters_by_project_keyword(self):
        conn = FakeQueryConnection(
            [
                [
                    {
                        "project_id": "APQP-2026-002",
                        "project_name": "Industrial Control Display Reliability Improvement",
                        "current_status": "Delayed",
                        "planned_finish_date": date(2026, 6, 10),
                    }
                ]
            ]
        )

        rows = query_project_status(conn, "APQP-2026-002")

        self.assertEqual(rows[0]["planned_finish_date"], "2026-06-10")
        sql, params = conn.cursors[0].calls[0]
        self.assertIn("FROM project_progress", sql)
        self.assertIn("LIKE %(keyword)s", sql)
        self.assertEqual(params["keyword"], "%APQP-2026-002%")
        self.assertEqual(conn.cursors[0].kwargs, {"dictionary": True})

    def test_query_functions_use_bounded_safe_queries(self):
        conn = FakeQueryConnection([[], [], []])

        query_high_risks(conn, "LCM", limit=3)
        query_open_issues(conn, "LCM", limit=4)
        query_missing_deliverables(conn, "LCM", limit=5)

        risk_sql, risk_params = conn.cursors[0].calls[0]
        issue_sql, issue_params = conn.cursors[1].calls[0]
        deliverable_sql, deliverable_params = conn.cursors[2].calls[0]

        self.assertIn("FROM project_risks", risk_sql)
        self.assertIn("ORDER BY rpn DESC", risk_sql)
        self.assertEqual(risk_params["limit"], 3)
        self.assertIn("FROM project_issues", issue_sql)
        self.assertEqual(issue_params["keyword"], "%LCM%")
        self.assertIn("FROM apqp_deliverables", deliverable_sql)
        self.assertEqual(deliverable_params["limit"], 5)

    def test_summarize_project_combines_status_risks_issues_and_deliverables(self):
        conn = FakeQueryConnection(
            [
                [{"project_id": "APQP-2026-001", "current_status": "In Progress"}],
                [{"risk_id": "R-001", "risk_level": "High"}],
                [{"issue_id": "I-001", "current_status": "In Progress"}],
                [{"deliverable_id": "D-002", "review_status": "Pending Submission"}],
            ]
        )

        summary = summarize_project(conn, "APQP-2026-001")

        self.assertEqual(summary["project"], "APQP-2026-001")
        self.assertEqual(len(summary["status"]), 1)
        self.assertEqual(len(summary["high_risks"]), 1)
        self.assertEqual(len(summary["open_issues"]), 1)
        self.assertEqual(len(summary["missing_deliverables"]), 1)


if __name__ == "__main__":
    unittest.main()
