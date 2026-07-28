"""验证多个8D文档的精确匹配"""
import sys, os
sys.path.insert(0, '.')
os.environ['EMBEDDING_MODEL_PATH'] = r'D:/liworkplace/lora finetuning/apqp-deepseek-lora-finetuning/models/bge-small-zh-v1.5'

from back.agent.router import extract_eightd_id
from back.rag.sqlite_vector_store import SqliteVectorStore

store = SqliteVectorStore('knowledge_base/vector_store.sqlite').load()

print('测试多个8D编号精确匹配：')
print()

tests = [
    ('8D202604007', '84559_8D202604007_8D报告总表_陈琴-001 (1).xlsx'),
    ('8D20240416001', '8D20240416001.xlsx'),
]

for eightd_id, expected_source in tests:
    source = store.find_source_by_text_keyword(eightd_id)
    chunks = store.get_source_chunks(source) if source else []
    status = '✓' if source == expected_source else '✗'
    print(f'{status} 编号 {eightd_id}')
    print(f'  期望文档: {expected_source}')
    print(f'  实际命中: {source}')
    print(f'  分片数量: {len(chunks)}')
    if chunks:
        print(f'  首片预览: {chunks[0].text[:60]}...')
    print()