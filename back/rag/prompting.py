from typing import Any, Dict, Iterable


NO_EVIDENCE_TEXT = "\u5f53\u524d\u77e5\u8bc6\u5e93\u6ca1\u6709\u627e\u5230\u660e\u786e\u4f9d\u636e"
NO_EVIDENCE_RULE = (
    "\u53ea\u6709\u5728\u672a\u68c0\u7d22\u5230\u76f8\u5173\u8d44\u6599\u65f6\uff0c"
    f"\u624d\u8bf4\u660e\u201c{NO_EVIDENCE_TEXT}\u201d\uff0c\u4e0d\u8981\u7f16\u9020\u3002"
)


def build_rag_prompt(
    user_question: str,
    contexts: Iterable[Dict[str, Any]],
    max_context_chars: int = 1600, # 限制prompt的长度 也就是减少上下文的长度
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

    context_text = "\n\n".join(context_blocks) if context_blocks else "\u672a\u68c0\u7d22\u5230\u76f8\u5173\u8d44\u6599\u3002"
    return (
        "\u4f60\u662f\u4f01\u4e1a\u5185\u90e8 APQP \u548c\u9879\u76ee\u8d28\u91cf\u7ba1\u7406\u52a9\u624b\u3002\n"
        "\u8bf7\u4f18\u5148\u4f9d\u636e\u4e0b\u65b9\u8d44\u6599\u56de\u7b54\uff0c\u4e0d\u8981\u590d\u5236\u5927\u6bb5\u539f\u6587\u3002\n"
        "\u56de\u7b54\u8981\u5148\u7ed9\u7ed3\u8bba\uff0c\u518d\u7ed9\u5173\u952e\u6b65\u9aa4\uff0c\u5c3d\u91cf\u63a7\u5236\u5728 500 \u5b57\u4ee5\u5185\u3002\n"
        f"{NO_EVIDENCE_RULE}\n\n"
        f"\u3010\u77e5\u8bc6\u5e93\u8d44\u6599\u3011\n{context_text}\n\n"
        f"\u3010\u7528\u6237\u95ee\u9898\u3011\n{user_question}"
    )
