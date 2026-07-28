from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from .router import AgentRoute, classify_question

# Define a type for the RAG retriever function
RagRetriever = Callable[[str], List[Dict[str, Any]]]


@dataclass
class AgentContext:
    route: AgentRoute
    tool_result: Optional[Any] = None
    rag_contexts: List[Dict[str, Any]] = field(default_factory=list)


def build_agent_context(
    question: str,
    tools: Mapping[str, Any],
    rag_retriever: RagRetriever,
) -> AgentContext:
    route = classify_question(question)
    tool_result = None
    rag_contexts: List[Dict[str, Any]] = []

    if route.tool_name:
        tool = tools.get(route.tool_name)
        if tool is None:
            raise KeyError(f"Tool not found: {route.tool_name}")
        tool_result = tool.invoke({"project_keyword": route.project_keyword})

    if route.route in {"rag", "hybrid"}:
        rag_contexts = rag_retriever(question)

    return AgentContext(route=route, tool_result=tool_result, rag_contexts=rag_contexts)


def build_agent_prompt(question: str, context: AgentContext, max_context_chars: int = 2400) -> str:
    """构建 Agent 输入 prompt。

    结构顺序（从上到下）：
    1. 规则与角色设定
    2. 回答风格
    3. 结构化数据（如有）
    4. RAG 知识库资料（如有）
    5. 用户问题

    关键：知识库资料必须放在 "请基于资料回答" 之后、用户问题之前，
    否则模型读到 "以上资料" 时上面还没有资料，会误判为无资料可用。
    """
    is_hybrid = context.route.route == "hybrid"

    # 资料部分先收集
    data_sections = []
    if is_hybrid:
        data_sections.append("【回答顺序】\n先回答项目当前事实，再说明流程依据，最后给出结合建议。")

    if context.tool_result is not None:
        tool_section = "项目事实" if is_hybrid else "结构化项目数据"
        data_sections.append(f"【{tool_section}】\n{_format_tool_result(context.tool_result)}")

    if context.rag_contexts:
        rag_section = "流程依据" if is_hybrid else "知识库资料"
        data_sections.append(f"【{rag_section}】\n{_format_rag_contexts(context.rag_contexts, max_context_chars)}")

    sections = [
        "【最高优先级强制执行规则，必须严格遵守】",
    ]

    # 纯 RAG（无项目ID）场景：弱化数据库查询要求，避免模型过度谨慎
    if context.route.route == "rag":
        sections.extend([
            "你是企业内部 APQP 和项目质量管理助手。",
            "当用户询问 APQP 流程、阶段、方法论、规范、FMEA、控制计划等通用质量管理知识时，直接基于知识库资料和你的专业知识回答，**不需要查询项目数据库**。",
            "只有当用户明确提到项目编号（如P001、P002）并询问具体项目信息时，才需要调用数据库查询工具。",
            "不要输出原始 JSON，不要输出字段名，不要提及工具名，不要提及路由信息。",
        ])
    else:
        sections.extend([
            "1. 用户提问中带有项目编号（如P001、P002），询问项目负责人、项目进度、风险、交付物、任务等结构化项目信息时，**必须先调用数据库查询工具获取结构化数据，禁止直接只用RAG文档作答**。",
            "2. 仅当数据库查询工具返回空、无匹配结构化记录时，才可以使用RAG检索到的文档资料作为补充说明。",
            "3. 禁止跳过数据库查询工具，仅依靠操作手册文档回复项目结构化相关问题。",
            "你是企业内部 APQP 和项目质量管理助手。",
            "只回答当前用户问题对应项目，只回答结构化数据中列出的记录；不要补充其他项目，不要补充未列出的风险、问题或交付物。",
            "不要输出原始 JSON，不要输出字段名，不要提及工具名，不要提及路由信息。",
        ])

    sections.extend([
        (
            "【回答风格】\n"
            "请用自然、专业、简洁的业务语言回答，像一位熟悉 APQP 的项目质量同事。\n"
            "不要机械套用固定标题，也不要写成客服话术；优先说清结论、依据和下一步建议。\n"
            "不要逐表复述数据来源，不要连续使用 '根据… 表'；先综合判断项目状态，再合并说明关键关注点。\n"
            "建议尽量落到责任人、部门、日期、风险、问题或交付物等具体信息上。\n"
            "资料不足时只说明缺少的业务信息；资料足够时不要额外强调信息不足。"
        ),
        "不要追加 AI 免责声明。",
    ])

    # 追加资料（在规则之后、用户问题之前）
    sections.extend(data_sections)

    # 用户问题放最后，紧跟 "请基于以下资料回答"
    # 用 "以下" 代替 "以上"，避免资料出现在这句话之后时产生歧义
    has_data = bool(data_sections)
    if has_data:
        sections.append("请基于以上提供的资料回答；如果资料不足，请明确说明缺少哪些依据，不要编造。")
    else:
        sections.append("未检索到相关结构化数据或知识库资料，请基于你的专业知识回答；如果不确定，请明确说明缺少依据，不要编造。")

    sections.append(f"【用户问题】\n{question}")

    return "\n\n".join(sections)

# 提供给 Agent 的上下文构建和提示语生成函数，结合路由分类、工具调用结果和 RAG 检索结果，形成完整的 Agent 输入。
SECTION_LABELS = {
    "status": "项目进度",
    "high_risks": "高风险项",
    "open_issues": "未关闭问题",
    "missing_deliverables": "未完成交付物",
}

FIELD_LABELS = {
    "project": "项目关键词",
    "project_id": "项目编号",
    "project_name": "项目名称",
    "customer": "客户",
    "product_type": "产品类型",
    "apqp_phase": "APQP 阶段",
    "current_phase": "当前阶段",
    "current_status": "当前状态",
    "planned_start_date": "计划开始日期",
    "planned_finish_date": "计划完成日期",
    "actual_finish_date": "实际完成日期",
    "owner": "责任人",
    "delay_days": "延期天数",
    "progress_note": "进展说明",
    "risk_id": "风险编号",
    "risk_category": "风险类别",
    "risk_description": "风险描述",
    "severity_s": "严重度",
    "occurrence_o": "发生度",
    "detection_d": "探测度",
    "rpn": "RPN",
    "risk_level": "风险等级",
    "mitigation_action": "应对措施",
    "planned_close_date": "计划关闭日期",
    "closure_status": "关闭状态",
    "issue_id": "问题编号",
    "issue_source": "问题来源",
    "issue_description": "问题描述",
    "found_date": "发现日期",
    "responsible_department": "责任部门",
    "actual_close_date": "实际关闭日期",
    "resolution_note": "处理说明",
    "deliverable_id": "交付物编号",
    "delivery_id": "交付物编号",
    "deliverable_name": "交付物名称",
    "is_completed": "是否完成",
    "review_status": "评审状态",
    "planned_submit_date": "计划提交日期",
    "actual_submit_date": "实际提交日期",
    "missing_or_reject_reason": "未完成或退回原因",
    "source_file": "来源文件",
    "source_sheet": "来源表",
}

MODEL_HIDDEN_FIELDS = {"source_file", "source_sheet"}


def _format_tool_result(value: Any) -> str:
    if isinstance(value, Mapping):
        blocks = []
        for key, item in value.items():
            if _is_empty_value(item):
                continue
            label = SECTION_LABELS.get(str(key), FIELD_LABELS.get(str(key), str(key)))
            blocks.append(_format_named_value(label, item))
        return "\n\n".join(blocks) if blocks else "未查询到相关结构化项目数据。"

    if isinstance(value, list):
        return _format_list(value)

    return str(value)


def _format_named_value(label: str, value: Any) -> str:
    if isinstance(value, list):
        return f"{label}：\n{_format_list(value)}"
    if isinstance(value, Mapping):
        details = _format_mapping(value)
        return f"{label}：\n{details}" if details else f"{label}：未填写"
    return f"{label}：{_format_scalar(value)}"


def _format_list(values: List[Any]) -> str:
    if not values:
        return "未查询到相关记录。"

    lines = []
    for index, item in enumerate(values, start=1):
        if isinstance(item, Mapping):
            details = _format_mapping(item)
            lines.append(f"{index}. {details}" if details else f"{index}. 未填写")
        else:
            lines.append(f"{index}. {_format_scalar(item)}")
    return "\n".join(lines)


def _format_mapping(value: Mapping[str, Any]) -> str:
    parts = []
    for key, item in value.items():
        if key in MODEL_HIDDEN_FIELDS:
            continue
        if _is_empty_value(item):
            continue
        label = FIELD_LABELS.get(str(key), str(key))
        parts.append(f"{label}：{_format_scalar(item)}")
    return "；".join(parts)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "未填写"
    return str(value)


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == []


def _format_rag_contexts(contexts: List[Dict[str, Any]], max_context_chars: int) -> str:
    blocks = []
    used_chars = 0
    for index, context in enumerate(contexts, start=1):
        metadata = context.get("metadata") or {}
        source = metadata.get("source", "unknown")
        chunk_index = metadata.get("chunk_index", "?")
        text = str(context.get("text", ""))

        remaining = max_context_chars - used_chars
        if remaining <= 0:
            break

        was_truncated = len(text) > remaining
        text = text[:remaining].rstrip()
        used_chars += len(text)
        if was_truncated:
            text = f"{text}\n[truncated]"

        blocks.append(f"[SOURCE {index}] file={source}, chunk={chunk_index}\n{text}")

    return "\n\n".join(blocks) if blocks else "未检索到相关资料。"
