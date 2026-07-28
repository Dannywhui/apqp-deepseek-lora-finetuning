import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List

try:
    from .excel_ingest import connect_mysql_from_env
except ImportError:
    from excel_ingest import connect_mysql_from_env


# 查询层先保持为普通 Python 函数，后续 LangChain Tool 可以直接包装这些函数。
# 这样模型只能调用受控查询能力，不会直接接触任意 SQL。
def query_project_status(connection: Any, project_keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            project_id,
            project_name,
            customer,
            product_type,
            apqp_phase,
            current_status,
            planned_start_date,
            planned_finish_date,
            actual_finish_date,
            owner,
            delay_days,
            progress_note,
            source_file,
            source_sheet
        FROM project_progress
        WHERE project_id LIKE %(keyword)s OR project_name LIKE %(keyword)s
        ORDER BY planned_finish_date ASC, project_id ASC
        LIMIT %(limit)s
    """
    return _fetch_all(connection, sql, _keyword_params(project_keyword, limit))


def query_high_risks(connection: Any, project_keyword: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            risk_id,
            project_id,
            project_name,
            risk_category,
            risk_description,
            severity_s,
            occurrence_o,
            detection_d,
            rpn,
            risk_level,
            mitigation_action,
            owner,
            planned_close_date,
            closure_status,
            source_file,
            source_sheet
        FROM project_risks
        WHERE (%(keyword)s = '%%' OR project_id LIKE %(keyword)s OR project_name LIKE %(keyword)s)
          AND (closure_status IS NULL OR closure_status NOT IN ('Closed', '已关闭'))
        ORDER BY rpn DESC, planned_close_date ASC
        LIMIT %(limit)s
    """
    return _fetch_all(connection, sql, _keyword_params(project_keyword, limit)) 


def query_open_issues(connection: Any, project_keyword: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            issue_id,
            project_id,
            project_name,
            issue_source,
            issue_description,
            found_date,
            responsible_department,
            owner,
            planned_close_date,
            actual_close_date,
            current_status,
            resolution_note,
            source_file,
            source_sheet
        FROM project_issues
        WHERE (%(keyword)s = '%%' OR project_id LIKE %(keyword)s OR project_name LIKE %(keyword)s)
          AND (current_status IS NULL OR current_status NOT IN ('Closed', '已关闭'))
        ORDER BY planned_close_date ASC, issue_id ASC
        LIMIT %(limit)s
    """
    return _fetch_all(connection, sql, _keyword_params(project_keyword, limit))


def query_missing_deliverables(connection: Any, project_keyword: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            deliverable_id,
            project_id,
            project_name,
            apqp_phase,
            deliverable_name,
            is_completed,
            review_status,
            owner,
            planned_submit_date,
            actual_submit_date,
            missing_or_reject_reason,
            source_file,
            source_sheet
        FROM apqp_deliverables
        WHERE (%(keyword)s = '%%' OR project_id LIKE %(keyword)s OR project_name LIKE %(keyword)s)
          AND (
            is_completed IS NULL
            OR is_completed NOT IN ('Yes', '是', '已完成')
            OR review_status IN ('Pending Submission', 'Returned for Revision', '待提交', '退回修改')
          )
        ORDER BY planned_submit_date ASC, deliverable_id ASC
        LIMIT %(limit)s
    """
    return _fetch_all(connection, sql, _keyword_params(project_keyword, limit))


def summarize_project(connection: Any, project_keyword: str) -> Dict[str, Any]:
    # 为后续“项目汇总”工具准备一个紧凑的统一返回结构。
    return {
        "project": project_keyword,
        "status": query_project_status(connection, project_keyword, limit=5),
        "high_risks": query_high_risks(connection, project_keyword, limit=5),
        "open_issues": query_open_issues(connection, project_keyword, limit=5),
        "missing_deliverables": query_missing_deliverables(connection, project_keyword, limit=5),
    }


def _fetch_all(connection: Any, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # dictionary=True 会让 mysql-connector 返回字典列表，方便 API 和 Tool 直接消费。
    with connection.cursor(dictionary=True) as cursor:
        cursor.execute(sql, params)
        return [_json_ready(row) for row in cursor.fetchall()]


def _keyword_params(project_keyword: str, limit: int) -> Dict[str, Any]:
    # 使用参数化查询并限制 limit，避免工具调用触发过大的查询。
    keyword = project_keyword.strip()
    return {
        "keyword": f"%{keyword}%" if keyword else "%",
        "limit": max(1, min(int(limit), 100)),
    }


def _json_ready(row: Dict[str, Any]) -> Dict[str, Any]:
    # 将数据库原生类型转成 JSON 友好的值，便于前端展示和工具返回。
    return {key: _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query structured APQP data from MySQL.")
    parser.add_argument("project", help="Project id or project name keyword.")
    args = parser.parse_args(argv)

    connection = connect_mysql_from_env()
    try:
        summary = summarize_project(connection, args.project)
    finally:
        connection.close()

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
