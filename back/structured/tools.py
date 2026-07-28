from typing import Any, Dict, List

from langchain.tools import tool

try:
    from .excel_ingest import connect_mysql_from_env
except ImportError:
    from excel_ingest import connect_mysql_from_env
from .queries import (
    query_high_risks,
    query_missing_deliverables,
    query_open_issues,
    query_project_status,
    summarize_project,
)
from .agent_dynamic import run_dynamic_query


def _with_connection(query_fn: Any, *args: Any, **kwargs: Any) -> Any:
    connection = connect_mysql_from_env()
    try:
        return query_fn(connection, *args, **kwargs)
    finally:
        connection.close()


@tool
def apqp_project_status(project_keyword: str, limit: int = 5) -> list[dict[str, Any]]:
    """查询 APQP 项目的当前阶段、状态、负责人、计划完成时间和进度说明。"""
    return _with_connection(query_project_status, project_keyword, limit=limit)


@tool
def apqp_high_risks(project_keyword: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """查询 APQP 项目的未关闭高风险项，并按 RPN 从高到低排序。"""
    return _with_connection(query_high_risks, project_keyword, limit=limit)

@tool
def apqp_open_issues(project_keyword: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """查询 APQP 项目的未关闭问题项，包括责任部门、责任人和计划关闭日期。"""
    return _with_connection(query_open_issues, project_keyword, limit=limit)

@tool
def apqp_missing_deliverables(project_keyword: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """查询 APQP 项目缺失、待提交或退回修改的交付物。"""
    return _with_connection(query_missing_deliverables, project_keyword, limit=limit)


@tool
def apqp_project_summary(project_keyword: str) -> dict[str, Any]:
    """汇总一个 APQP 项目的进度、风险、问题和缺失交付物。"""
    return _with_connection(summarize_project, project_keyword)


@tool
def apqp_dynamic_query(question: str) -> str:
    """根据用户自然语言问题，动态生成SQL查询数据库并返回结果。
    
    适用场景：
    - 用户问"查询项目PROJ2026001的风险"
    - 用户问"项目ABC123有哪些问题"
    - 用户问"查看PROJ2026002的进度"
    - 任何包含项目ID的查询类问题
    
    传入用户原始问题文本即可。
    """
    result = run_dynamic_query(question)
    if "error" in result:
        return f"查询失败: {result['error']}"
    return f"【查询SQL】{result['sql']}\n\n【查询结果】\n{result['answer']}"


def get_structured_query_tools() -> List[Any]:
    """返回可交给 LangChain/LangGraph agent 使用的受控 MySQL 查询工具。"""
    return [
        apqp_project_status,
        apqp_high_risks,
        apqp_open_issues,
        apqp_missing_deliverables,
        apqp_project_summary,
        apqp_dynamic_query,
    ]
