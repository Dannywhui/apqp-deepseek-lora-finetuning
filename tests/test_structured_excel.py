import tempfile
import unittest
from datetime import date
from pathlib import Path
import sys

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from back.structured.excel_ingest import extract_excel_batches, import_excel_directory


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.executemany_calls = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1


def write_workbook(path: Path, sheet_name: str, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


class StructuredExcelIngestTests(unittest.TestCase):
    def test_extracts_project_progress_rows_from_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "project_progress_samples.xlsx"
            write_workbook(
                path,
                "ProjectProgress",
                [
                    "project_id",
                    "project_name",
                    "customer",
                    "product_type",
                    "apqp_phase",
                    "current_status",
                    "planned_start_date",
                    "planned_finish_date",
                    "actual_finish_date",
                    "owner",
                    "delay_days",
                    "progress_note",
                ],
                [
                    [
                        "APQP-2026-001",
                        "Vehicle Center LCM Module Development",
                        "Desay SV",
                        "LCM module",
                        "Phase 3",
                        "In Progress",
                        date(2026, 1, 8),
                        date(2026, 7, 15),
                        "",
                        "Li Ming",
                        0,
                        "PFMEA draft is complete.",
                    ]
                ],
            )

            batches = extract_excel_batches(tmp_dir)

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].table_name, "project_progress")
        self.assertEqual(batches[0].rows[0]["project_id"], "APQP-2026-001")
        self.assertEqual(batches[0].rows[0]["actual_finish_date"], None)
        self.assertEqual(batches[0].rows[0]["source_file"], "project_progress_samples.xlsx")

    def test_import_excel_directory_writes_only_xlsx_to_mysql_tables(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "manual.pdf").write_text("ignored", encoding="utf-8")
            write_workbook(
                root / "project_risk_samples.xlsx",
                "ProjectRisks",
                [
                    "risk_id",
                    "project_id",
                    "project_name",
                    "risk_category",
                    "risk_description",
                    "severity_s",
                    "occurrence_o",
                    "detection_d",
                    "rpn",
                    "risk_level",
                    "mitigation_action",
                    "owner",
                    "planned_close_date",
                    "closure_status",
                ],
                [
                    [
                        "R-001",
                        "APQP-2026-001",
                        "Vehicle Center LCM Module Development",
                        "Process Risk",
                        "Air bubble defects in bonding.",
                        8,
                        5,
                        4,
                        160,
                        "High",
                        "Optimize bonding parameters.",
                        "Li Ming",
                        date(2026, 6, 30),
                        "In Progress",
                    ]
                ],
            )
            conn = FakeConnection()

            summary = import_excel_directory(root, conn)

        self.assertEqual(summary["files"], 1)
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(conn.commits, 1)
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS project_risks" in sql for sql, _ in conn.cursor_obj.statements))
        self.assertTrue(any("TRUNCATE TABLE project_risks" in sql for sql, _ in conn.cursor_obj.statements))
        insert_sql, insert_rows = conn.cursor_obj.executemany_calls[0]
        self.assertIn("INSERT INTO project_risks", insert_sql)
        self.assertEqual(insert_rows[0]["source_file"], "project_risk_samples.xlsx")

    def test_extracts_mixed_chinese_and_english_headers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "project_progress_samples.xlsx"
            write_workbook(
                path,
                "项目进度",
                [
                    "项目 ID",
                    "项目名称",
                    "顾客",
                    "产品类型",
                    "apqp_phase",
                    "当前状态",
                    "计划开始日期",
                    "计划完成日期",
                    "实际完成日期",
                    "所有者",
                    "延迟天数",
                    "进度说明",
                ],
                [
                    [
                        "APQP-2026-002",
                        "Industrial Control Display Reliability Improvement",
                        "Industrial Control BU",
                        "Industrial display",
                        "Phase 4",
                        "Delayed",
                        date(2026, 2, 1),
                        date(2026, 6, 10),
                        "",
                        "Wang Qian",
                        8,
                        "Pilot run issue requires validation.",
                    ]
                ],
            )

            batches = extract_excel_batches(tmp_dir)

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].table_name, "project_progress")
        self.assertEqual(batches[0].rows[0]["project_id"], "APQP-2026-002")
        self.assertEqual(batches[0].rows[0]["owner"], "Wang Qian")


if __name__ == "__main__":
    unittest.main()
