"""验证8D编号提取和文档查找逻辑"""
import sys, os
sys.path.insert(0, '.')
os.environ['EMBEDDING_MODEL_PATH'] = r'D:/liworkplace/lora finetuning/apqp-deepseek-lora-finetuning/models/bge-small-zh-v1.5'

from back.agent.router import extract_eightd_id
from back.rag.sqlite_vector_store import SqliteVectorStore

print('测试8D编号提取：')
tests = [
    '8D202604007的问题描述是什么',
    '请查看8D202604007',
    '关于8D202604007的信息',
    'APQP是什么',
    'PROJ2026001的进度',
]
for q in tests:
    eid = extract_eightd_id(q)
    print(f'  "{q}" -> "{eid}"')

print()
print('测试文档查找：')
store = SqliteVectorStore('knowledge_base/vector_store.sqlite').load()
source = store.find_source_by_text_keyword('8D202604007')
print(f'  8D202604007 -> source: {source}')

if source:
    chunks = store.get_source_chunks(source)
    print(f'  该文档有 {len(chunks)} 个分片')
    for i, c in enumerate(chunks[:3], 1):
        print(f'    chunk {i}: {c.text[:50]}...')
