"""基于规则的自然语言回复生成器 - 替代大模型"""
import re
from typing import List, Dict, Any


def extract_project_id_from_sql(sql: str) -> str:
    """从SQL语句中提取项目ID"""
    match = re.search(r"project_id\s*=\s*['\"](PROJ\d+)['\"]", sql, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _check_project_exists(results: List[Dict[str, Any]], sql: str, query_type: str) -> str:
    """检查项目是否存在，如果不存在返回错误提示"""
    project_id = extract_project_id_from_sql(sql)
    if project_id and not results:
        return f"未查询到项目【{project_id}】的{query_type}数据。可能该项目不存在，或尚未录入相关{query_type}信息。"
    return None


def generate_natural_reply(question: str, results: List[Dict[str, Any]], sql: str) -> str:
    """根据查询结果生成自然语言回复"""
    
    question_lower = question.lower()
    
    # 判断查询类型
    if '风险' in question_lower:
        not_found_msg = _check_project_exists(results, sql, "风险")
        if not_found_msg:
            return not_found_msg
        return _format_risk_reply(results)
    elif '问题' in question_lower:
        not_found_msg = _check_project_exists(results, sql, "问题")
        if not_found_msg:
            return not_found_msg
        return _format_issue_reply(results)
    elif '进度' in question_lower or '状态' in question_lower:
        not_found_msg = _check_project_exists(results, sql, "进度")
        if not_found_msg:
            return not_found_msg
        return _format_progress_reply(results)
    elif '交付物' in question_lower:
        not_found_msg = _check_project_exists(results, sql, "交付物")
        if not_found_msg:
            return not_found_msg
        return _format_deliverable_reply(results)
    else:
        not_found_msg = _check_project_exists(results, sql, "")
        if not_found_msg:
            return not_found_msg
        return _format_generic_reply(results)


def _format_risk_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "该项目当前没有风险记录。"
    
    lines = [f"项目共存在 {len(results)} 个风险："]
    for i, row in enumerate(results, 1):
        category = row.get('risk_category', '未知风险')
        level = row.get('risk_level', '未知等级')
        status = row.get('closure_status', '未知状态')
        desc = row.get('risk_description', '')
        action = row.get('mitigation_action', '')
        owner = row.get('owner', '')
        
        lines.append(f"\n{i}. 【{category}】")
        lines.append(f"   风险等级：{level}")
        lines.append(f"   当前状态：{status}")
        if desc:
            lines.append(f"   风险描述：{desc}")
        if action:
            lines.append(f"   应对措施：{action}")
        if owner:
            lines.append(f"   负责人：{owner}")
    
    return "\n".join(lines)


def _format_issue_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "该项目当前没有问题记录。"
    
    lines = [f"项目共存在 {len(results)} 个问题："]
    for i, row in enumerate(results, 1):
        title = row.get('issue_title', '未知问题')
        status = row.get('issue_status', '未知状态')
        desc = row.get('issue_description', '')
        owner = row.get('owner', '')
        
        lines.append(f"\n{i}. 【{title}】")
        lines.append(f"   状态：{status}")
        if desc:
            lines.append(f"   描述：{desc}")
        if owner:
            lines.append(f"   负责人：{owner}")
    
    return "\n".join(lines)


def _format_progress_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "未查询到项目进度信息。"
    
    row = results[0]
    project_name = row.get('project_name', '未知项目')
    status = row.get('current_status', '未知状态')
    phase = row.get('apqp_phase', '未知阶段')
    planned_start = row.get('planned_start_date', '')
    planned_finish = row.get('planned_finish_date', '')
    actual_start = row.get('actual_start_date', '')
    actual_finish = row.get('actual_finish_date', '')
    progress_note = row.get('progress_note', '')
    
    lines = [f"【{project_name}】项目进度信息："]
    lines.append(f"\n当前阶段：{phase}")
    lines.append(f"项目状态：{status}")
    if planned_start:
        lines.append(f"计划开始：{planned_start}")
    if planned_finish:
        lines.append(f"计划完成：{planned_finish}")
    if actual_start:
        lines.append(f"实际开始：{actual_start}")
    if actual_finish:
        lines.append(f"实际完成：{actual_finish}")
    if progress_note:
        lines.append(f"\n进度说明：{progress_note}")
    
    return "\n".join(lines)


def _format_deliverable_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "该项目当前没有交付物记录。"
    
    lines = [f"项目共有 {len(results)} 个交付物："]
    for i, row in enumerate(results, 1):
        name = row.get('deliverable_name', '未知交付物')
        deliverable_type = row.get('deliverable_type', '')
        status = row.get('is_completed', '未知')
        review = row.get('review_status', '')
        planned = row.get('planned_submit_date', '')
        actual = row.get('actual_submit_date', '')
        
        status_str = "已完成" if str(status).lower() in ['1', 'true', 'yes', '已完成'] else "未完成"
        
        lines.append(f"\n{i}. 【{name}】")
        if deliverable_type:
            lines.append(f"   类型：{deliverable_type}")
        lines.append(f"   完成状态：{status_str}")
        if review:
            lines.append(f"   评审状态：{review}")
        if planned:
            lines.append(f"   计划提交：{planned}")
        if actual:
            lines.append(f"   实际提交：{actual}")
    
    return "\n".join(lines)


def _format_generic_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "未查询到相关数据。"
    
    lines = [f"查询到 {len(results)} 条记录："]
    for i, row in enumerate(results, 1):
        items = []
        for k, v in row.items():
            if v is not None and str(v).strip():
                items.append(f"{k}: {v}")
        lines.append(f"\n{i}. " + " | ".join(items[:5]))  # 只显示前5个字段
    
    return "\n".join(lines)
