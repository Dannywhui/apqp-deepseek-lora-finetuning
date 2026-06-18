import re
from typing import Any, Dict, Iterable, List


PAGE_PATTERN = re.compile(r"\[Page\s+(\d+)\]")


def build_source_summaries(contexts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}

    for context in contexts:
        metadata = context.get("metadata") or {}
        source = str(metadata.get("source") or "unknown")
        entry = grouped.setdefault(
            source,
            {
                "source": source,
                "pages": set(),
                "chunks": set(),
                "score": 0.0,
            },
        )
        entry["score"] = max(float(context.get("score") or 0.0), entry["score"])

        chunk_index = metadata.get("chunk_index")
        if chunk_index is not None:
            entry["chunks"].add(int(chunk_index))

        for match in PAGE_PATTERN.findall(str(context.get("text") or "")):
            entry["pages"].add(int(match))

    summaries: List[Dict[str, Any]] = []
    for entry in grouped.values():
        pages = sorted(entry["pages"])
        chunks = sorted(entry["chunks"])
        summaries.append(
            {
                "source": entry["source"],
                "pages": pages,
                "chunks": chunks,
                "score": round(entry["score"], 4),
                "label": _format_source_label(entry["source"], pages),
            }
        )

    return sorted(summaries, key=lambda item: item["score"], reverse=True)


def _format_source_label(source: str, pages: List[int]) -> str:
    if not pages:
        return source

    if len(pages) == 1:
        page_text = f"\u7b2c {pages[0]} \u9875"
    elif pages == list(range(pages[0], pages[-1] + 1)):
        page_text = f"\u7b2c {pages[0]}-{pages[-1]} \u9875"
    else:
        page_text = "\u7b2c " + "\u3001".join(str(page) for page in pages) + " \u9875"

    return f"{source}\uff0c{page_text}"
