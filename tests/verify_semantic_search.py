"""验证重建后的语义检索质量"""
import sys, os
sys.path.insert(0, '.')
os.environ['EMBEDDING_MODEL_PATH'] = r'D:/liworkplace/lora finetuning/apqp-deepseek-lora-finetuning/models/bge-small-zh-v1.5'

from back.rag import get_embedding_model, SqliteVectorStore

embedder = get_embedding_model(prefer='semantic')
store = SqliteVectorStore('knowledge_base/vector_store.sqlite').load()
print(f'库内文档: {len(store.list_documents())} 个, 分片: {len(store.records)} 个, 嵌入维度: {len(store.records[0].embedding)}')

# 真实场景测试
tests = [
    'APQP是什么',
    '什么是FMEA',
    '送样评估的流程是什么',
    '康强冲压的操作手册讲什么',
    '公司年会在哪开',  # 不相关
    '8D报告怎么写',
    'LCD LCM有什么区别',
]
for q in tests:
    qv = embedder.embed(q)
    results = store.search(qv, top_k=3, min_score=0.0)
    print(f'\n问题: {q}')
    for r in results:
        src = r.record.metadata.get('source', '?')
        idx = r.record.metadata.get('chunk_index', '?')
        text = r.record.text[:80].replace('\n', ' ')
        print(f'  {r.score:.3f} | {src}#{idx} | {text}...')
