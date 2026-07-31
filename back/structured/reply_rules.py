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
        return "【结论】该项目当前没有风险记录。\n【项目情况】暂无风险条目。\n【关注点】暂无额外关注点\n【建议】保持现有风险监控节奏即可。"

    lines = [
        f"【结论】项目共存在 **{len(results)}** 个风险。",
        "【项目情况】",
    ]
    for i, row in enumerate(results, 1):
        category = row.get('risk_category', '未知风险')
        level = row.get('risk_level', '未知等级')
        status = row.get('closure_status', '未知状态')
        desc = row.get('risk_description', '')
        action = row.get('mitigation_action', '')
        owner = row.get('owner', '')

        lines.append(f"{i}. **{category}**｜等级：{level}｜状态：{status}")
        if desc:
            lines.append(f"   描述：{desc}")
        if action:
            lines.append(f"   应对：{action}")
        if owner:
            lines.append(f"   负责人：{owner}")

    open_count = sum(
        1 for r in results
        if str(r.get('closure_status', '')).strip() not in {'已关闭', '关闭', 'Closed', 'closed'}
    )
    lines.append("【关注点】")
    if open_count:
        lines.append(f"仍有 **{open_count}** 项未关闭，需优先跟进高等级风险。")
    else:
        lines.append("暂无额外关注点")
    lines.append("【建议】")
    lines.append("1. 按风险等级排期关闭，明确责任人与计划关闭日期。")
    lines.append("2. 对高等级风险复核应对措施是否已落地。")

    return "\n".join(lines)


def _format_issue_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "【结论】该项目当前没有问题记录。\n【项目情况】暂无问题条目。\n【关注点】暂无额外关注点\n【建议】保持问题闭环监控即可。"

    lines = [
        f"【结论】项目共存在 **{len(results)}** 个问题。",
        "【项目情况】",
    ]
    for i, row in enumerate(results, 1):
        title = row.get('issue_title', '未知问题')
        status = row.get('issue_status', '未知状态')
        desc = row.get('issue_description', '')
        owner = row.get('owner', '')

        lines.append(f"{i}. **{title}**｜状态：{status}")
        if desc:
            lines.append(f"   描述：{desc}")
        if owner:
            lines.append(f"   负责人：{owner}")

    lines.append("【关注点】优先关闭逾期或高影响问题。")
    lines.append("【建议】")
    lines.append("1. 明确责任人与目标关闭日期，逐项闭环。")
    lines.append("2. 对重复问题回溯流程或控制计划缺口。")

    return "\n".join(lines)


def _format_progress_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "【结论】未查询到项目进度信息。\n【项目情况】暂无进度数据。\n【关注点】缺少项目进度依据\n【建议】确认项目编号是否正确，或补充进度录入。"

    row = results[0]
    project_name = row.get('project_name', '未知项目')
    status = row.get('current_status', '未知状态')
    phase = row.get('apqp_phase', '未知阶段')
    planned_start = row.get('planned_start_date', '')
    planned_finish = row.get('planned_finish_date', '')
    actual_start = row.get('actual_start_date', '')
    actual_finish = row.get('actual_finish_date', '')
    progress_note = row.get('progress_note', '')

    lines = [
        f"【结论】**{project_name}** 当前处于 **{phase}**，状态为 **{status}**。",
        "【项目情况】",
        f"- 当前阶段：{phase}",
        f"- 项目状态：{status}",
    ]
    if planned_start:
        lines.append(f"- 计划开始：{planned_start}")
    if planned_finish:
        lines.append(f"- 计划完成：{planned_finish}")
    if actual_start:
        lines.append(f"- 实际开始：{actual_start}")
    if actual_finish:
        lines.append(f"- 实际完成：{actual_finish}")
    if progress_note:
        lines.append(f"- 进度说明：{progress_note}")

    lines.append("【关注点】")
    if "延" in str(status) or "delay" in str(status).lower():
        lines.append("项目存在延期迹象，需核对关键路径与未完成交付物。")
    else:
        lines.append("暂无额外关注点")
    lines.append("【建议】")
    lines.append("1. 对照计划完成日期核对关键里程碑是否按期。")
    lines.append("2. 对未完成交付物明确责任人与提交时间。")

    return "\n".join(lines)


def _format_deliverable_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "【结论】该项目当前没有交付物记录。\n【项目情况】暂无交付物条目。\n【关注点】缺少交付物依据\n【建议】确认项目编号或补充交付物台账。"

    lines = [
        f"【结论】项目共有 **{len(results)}** 个交付物。",
        "【项目情况】",
    ]
    incomplete = 0
    for i, row in enumerate(results, 1):
        name = row.get('deliverable_name', '未知交付物')
        deliverable_type = row.get('deliverable_type', '')
        status = row.get('is_completed', '未知')
        review = row.get('review_status', '')
        planned = row.get('planned_submit_date', '')
        actual = row.get('actual_submit_date', '')

        status_str = "已完成" if str(status).lower() in ['1', 'true', 'yes', '已完成'] else "未完成"
        if status_str == "未完成":
            incomplete += 1

        lines.append(f"{i}. **{name}**｜{status_str}")
        if deliverable_type:
            lines.append(f"   类型：{deliverable_type}")
        if review:
            lines.append(f"   评审：{review}")
        if planned:
            lines.append(f"   计划提交：{planned}")
        if actual:
            lines.append(f"   实际提交：{actual}")

    lines.append("【关注点】")
    if incomplete:
        lines.append(f"仍有 **{incomplete}** 项未完成，需优先补齐。")
    else:
        lines.append("暂无额外关注点")
    lines.append("【建议】")
    lines.append("1. 按计划提交日期催办未完成交付物。")
    lines.append("2. 对退回项补齐缺口后重新评审。")

    return "\n".join(lines)


def _format_generic_reply(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "【结论】未查询到相关数据。\n【项目情况】暂无匹配记录。\n【关注点】缺少查询依据\n【建议】请确认项目编号与查询类型后重试。"

    lines = [
        f"【结论】查询到 **{len(results)}** 条记录。",
        "【项目情况】",
    ]
    for i, row in enumerate(results, 1):
        items = []
        for k, v in row.items():
            if v is not None and str(v).strip():
                items.append(f"{k}: {v}")
        lines.append(f"{i}. " + " | ".join(items[:5]))

    lines.append("【关注点】暂无额外关注点")
    lines.append("【建议】如需更详细解读，请补充具体关注点（进度/风险/问题/交付物）。")

    return "\n".join(lines)
