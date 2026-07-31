"""验证 build_agent_prompt 的资料顺序修复"""
import sys; sys.path.insert(0, '.')

from back.agent.context import build_agent_prompt, AgentContext
from back.agent.router import AgentRoute

# 模拟 RAG 有资料的情况
ctx = AgentContext(
    route=AgentRoute("rag"),
    rag_contexts=[{
        "text": "APQP 是 Advanced Product Quality Planning 的缩写...",
        "metadata": {"source": "apqp_overview.md", "chunk_index": 1},
        "score": 0.768,
    }]
)

prompt = build_agent_prompt("apqp是什么", ctx, max_context_chars=1600)
print("=" * 60)
print("修复后的 prompt 结构：")
print("=" * 60)

lines = prompt.split("\n")
for i, line in enumerate(lines, 1):
    print(f"{i:3d} | {line[:100]}")

# 验证顺序：知识库资料应该在 "请基于资料回答" 之前
rag_idx = prompt.find("【知识库资料】")
answer_idx = prompt.find("请仅基于以上资料回答")
question_idx = prompt.find("【用户问题】")

print("\n" + "=" * 60)
print(f"【知识库资料】位置: {rag_idx}")
print(f"'请仅基于以上资料回答'位置: {answer_idx}")
print(f"【用户问题】位置: {question_idx}")

if rag_idx < answer_idx < question_idx:
    print("\n✅ 顺序正确: 资料 → 指令 → 问题")
else:
    print("\n❌ 顺序错误!")
