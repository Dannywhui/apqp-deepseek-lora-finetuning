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


# 统一输出格式（与微调数据【主题/分析/风险/建议】对齐，并按场景细化）
_OUTPUT_FORMAT_RAG = """【输出格式 - 必须严格按以下结构输出】
【主题】一句话概括问题主题
【结论】直接给出核心结论（1-2句）
【要点】用 2-5 条分点说明关键内容，每条要具体、可核对
【风险】如有相关风险写清影响；没有则写「暂无明显风险」
【建议】给出 1-3 条可执行建议（动作 + 责任角色/时机）"""

_OUTPUT_FORMAT_PROJECT = """【输出格式 - 必须严格按以下结构输出】
【结论】先用 1-2 句话概括项目当前状态或查询结果
【项目情况】分点列出资料中的关键事实（阶段、状态、责任人、日期、数值等）
【关注点】列出需要跟进的风险、问题或缺口；没有则写「暂无额外关注点」
【建议】给出 1-3 条可执行下一步（动作 + 责任人/部门 + 时机，能落到资料中就写出来）"""

_OUTPUT_FORMAT_HYBRID = """【输出格式 - 必须严格按以下结构输出】
【结论】综合项目事实与流程要求，给出总体判断
【项目事实】先说明项目当前进度、风险、问题或交付物等事实
【流程依据】再说明相关 APQP/质量流程要求
【建议】给出结合事实与流程的可执行建议（动作 + 责任角色 + 时机）"""

_CONTENT_QUALITY_RULES = """【内容质量要求】
1. 先结论后细节；禁止客服套话、空话、口号式表述（如仅写「完善流程」「加强管理」）。
2. 尽量引用资料中的具体信息：项目编号、责任人、部门、日期、RPN、阶段、交付物名称等。
3. 建议必须可执行，避免抽象原则；资料里有责任人/日期时必须写进建议。
4. 只回答用户当前问题，不要跑题扩写；总长度控制在 400 字以内。
5. 关键词可用 **加粗** 强调；不要输出原始 JSON、英文字段名、工具名、路由信息。
6. 不要追加 AI 免责声明；资料足够时不要强调「信息不足」。
7. 不要逐表复述「根据…表」，先综合判断，再合并说明关键关注点。"""


def build_agent_prompt(question: str, context: AgentContext, max_context_chars: int = 2400) -> str:
    """构建 Agent 输入 prompt。

    结构顺序（从上到下）：
    1. 规则与角色设定
    2. 输出格式 + 内容质量
    3. 结构化数据（如有）
    4. RAG 知识库资料（如有）
    5. 回答指令
    6. 用户问题

    注意：知识库资料必须放在回答指令之前、用户问题之前，
    否则模型读到「以上资料」时上面还没有资料，会误判为无资料可用。
    """
    route_name = context.route.route
    is_hybrid = route_name == "hybrid"
    is_rag = route_name == "rag"

    data_sections = []
    if is_hybrid:
        data_sections.append(
            "【回答顺序】\n先回答项目当前事实，再说明流程依据，最后给出结合建议。"
        )

    if context.tool_result is not None:
        tool_section = "项目事实" if is_hybrid else "结构化项目数据"
        data_sections.append(f"【{tool_section}】\n{_format_tool_result(context.tool_result)}")

    if context.rag_contexts:
        rag_section = "流程依据" if is_hybrid else "知识库资料"
        data_sections.append(
            f"【{rag_section}】\n{_format_rag_contexts(context.rag_contexts, max_context_chars)}"
        )

    sections = [
        "【角色】你是企业内部 APQP 与项目质量管理助手，用专业、简洁的业务语言回答。"
    ]

    if is_rag:
        sections.extend([
            "【规则】",
            "1. 询问 APQP 流程、阶段、方法论、规范、FMEA、控制计划等通用知识时，直接基于知识库资料与专业知识回答，不需要查询项目数据库。",
            "2. 只有用户明确提到项目编号（如 PROJ001）并询问具体项目信息时，才需要依赖结构化项目数据。",
            "3. 只回答当前用户问题；不要编造资料中不存在的事实。",
            "4. 不要输出原始 JSON，不要输出字段名，不要提及工具名，不要提及路由信息。",
            _OUTPUT_FORMAT_RAG,
        ])
    elif is_hybrid:
        sections.extend([
            "【规则】",
            "1. 必须优先使用下方【项目事实】作答；【流程依据】仅用于补充规范要求。",
            "2. 只回答当前用户问题对应项目，只使用资料中列出的记录；不要补充其他项目或未列出的风险/问题/交付物。",
            "3. 不要输出原始 JSON，不要输出字段名，不要提及工具名，不要提及路由信息。",
            _OUTPUT_FORMAT_HYBRID,
        ])
    else:
        sections.extend([
            "【规则】",
            "1. 用户提问含项目编号并询问进度、风险、问题、交付物等结构化信息时，必须优先使用下方结构化数据作答，禁止只靠知识库文档编造项目事实。",
            "2. 仅当结构化数据为空或无匹配记录时，才可说明缺少项目数据；不要编造。",
            "3. 只回答当前用户问题对应项目，只回答结构化数据中列出的记录；不要补充其他项目，不要补充未列出的风险、问题或交付物。",
            "4. 不要输出原始 JSON，不要输出字段名，不要提及工具名，不要提及路由信息。",
            _OUTPUT_FORMAT_PROJECT,
        ])

    sections.append(_CONTENT_QUALITY_RULES)
    sections.extend(data_sections)

    if data_sections:
        sections.append(
            "请仅基于以上资料回答；如果资料不足，请明确说明缺少哪些业务依据，不要编造。"
        )
    else:
        sections.append(
            "未检索到相关结构化数据或知识库资料，请基于专业知识谨慎回答；"
            "如果不确定，请明确说明缺少依据，不要编造。"
        )

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
