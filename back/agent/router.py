import re
from dataclasses import dataclass
from typing import Optional

PROJECT_ID_PATTERN = re.compile(r"\bPROJ\d+\b", re.IGNORECASE)
EIGHTD_ID_PATTERN = re.compile(r"8D\d{6,12}", re.IGNORECASE)

PROGRESS_KEYWORDS = ("进度", "当前阶段", "延期", "延迟", "状态", "负责人", "当前")
RISK_KEYWORDS = ("风险", "高风险", "rpn", "RPN")
ISSUE_KEYWORDS = ("问题", "未关闭", "逾期", "责任人", "责任部门")
DELIVERABLE_KEYWORDS = ("交付物", "缺少", "缺失", "待提交", "退回")
KNOWLEDGE_KEYWORDS = ("流程", "规范", "要求", "FMEA", "控制计划", "阶段评审", "阶段", "APQP", "apqp", "五大阶段", "五个阶段")


@dataclass(frozen=True)
class AgentRoute:
    route: str
    tool_name: Optional[str] = None
    project_keyword: str = ""

# 根据问题内容分类路由
def classify_question(question: str) -> AgentRoute:
    text = question.strip() #去除空格
    project_keyword = extract_project_keyword(text)
    has_project = bool(project_keyword) # 检查问题中是否包含项目ID，工程性问题
    has_knowledge = _contains_any(text, KNOWLEDGE_KEYWORDS) # 检查问题中是否包含知识相关的关键词

    # 优先级：混合 > 风险 > 问题 > 交付物 > 进度
    if has_project and has_knowledge and _contains_any(text, PROGRESS_KEYWORDS):
        return AgentRoute("hybrid", "apqp_project_summary", project_keyword)

    if has_project and _contains_any(text, RISK_KEYWORDS):
        return AgentRoute("high_risks", "apqp_high_risks", project_keyword)

    if has_project and _contains_any(text, ISSUE_KEYWORDS):
        return AgentRoute("open_issues", "apqp_open_issues", project_keyword)

    if has_project and _contains_any(text, DELIVERABLE_KEYWORDS):
        return AgentRoute("missing_deliverables", "apqp_missing_deliverables", project_keyword)

    if has_project and _contains_any(text, PROGRESS_KEYWORDS):
        return AgentRoute("project_status", "apqp_project_status", project_keyword)

    return AgentRoute("rag")

#判断问题中是否包含项目ID，有则提取，没有则返回空字符串
def extract_project_keyword(question: str) -> str:
    match = PROJECT_ID_PATTERN.search(question)
    return match.group(0).upper() if match else ""


def extract_eightd_id(question: str) -> str:
    """提取问题中的8D编号（格式：8D+8位数字，如8D202604007）。"""
    match = EIGHTD_ID_PATTERN.search(question)
    return match.group(0).upper() if match else ""


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)
