from typing import Any, Dict, Iterable


NO_EVIDENCE_TEXT = "当前知识库没有找到明确依据"
NO_EVIDENCE_RULE = (
    f"只有在未检索到相关资料时，才说明“{NO_EVIDENCE_TEXT}”，不要编造。"
)


def build_rag_prompt(
    user_question: str,
    contexts: Iterable[Dict[str, Any]],
    max_context_chars: int = 1600,
) -> str:
    context_blocks = []
    used_chars = 0

    for index, context in enumerate(contexts, start=1):
        metadata = context.get("metadata") or {}
        source = metadata.get("source", "unknown")
        chunk_index = metadata.get("chunk_index", "?")
        score = context.get("score", 0.0)
        text = str(context.get("text", ""))

        remaining = max_context_chars - used_chars
        if remaining <= 0:
            break

        was_truncated = len(text) > remaining
        text = text[:remaining].rstrip()
        used_chars += len(text)
        if was_truncated:
            text = f"{text}\n[truncated]"

        context_blocks.append(
            f"[SOURCE {index}] file={source}, chunk={chunk_index}, score={score:.4f}\n{text}"
        )

    context_text = "\n\n".join(context_blocks) if context_blocks else "未检索到相关资料。"
    return (
        "你是企业内部 APQP 与项目质量管理助手。\n"
        "请优先依据下方知识库资料回答，不要大段复制原文。\n"
        f"{NO_EVIDENCE_RULE}\n\n"
        "【输出格式 - 必须严格按以下结构输出】\n"
        "【主题】一句话概括问题主题\n"
        "【结论】直接给出核心结论（1-2句）\n"
        "【要点】用 2-5 条分点说明关键内容，每条要具体、可核对\n"
        "【风险】如有相关风险写清影响；没有则写「暂无明显风险」\n"
        "【建议】给出 1-3 条可执行建议（动作 + 责任角色/时机）\n\n"
        "【内容质量要求】\n"
        "1. 先结论后细节；禁止空话、口号式表述。\n"
        "2. 尽量引用资料中的具体概念、阶段、要求或指标。\n"
        "3. 建议必须可执行；总长度控制在 400 字以内。\n"
        "4. 关键词可用 **加粗**；不要追加 AI 免责声明。\n\n"
        f"【知识库资料】\n{context_text}\n\n"
        "请仅基于以上资料回答；资料不足时明确说明缺少哪些依据，不要编造。\n\n"
        f"【用户问题】\n{user_question}"
    )
