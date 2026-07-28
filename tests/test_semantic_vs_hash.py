"""对比哈希 vs 语义的检索质量（不需要清库，临时对比）"""
import sys
sys.path.insert(0, '.')

import os
os.environ['EMBEDDING_MODEL_PATH'] = r'D:/liworkplace/lora finetuning/apqp-deepseek-lora-finetuning/models/bge-small-zh-v1.5'

from back.rag import HashingEmbeddingModel, SemanticEmbeddingModel, SqliteVectorStore

# 加载两个嵌入器
hash_model = HashingEmbeddingModel(dimension=384)
sem_model = SemanticEmbeddingModel()
print(f"hash dim={hash_model.dimension}, sem dim={sem_model.dimension}")

# 测试问题对：相关 vs 不相关
test_pairs = [
    ("APQP是什么", "APQP产品质量先期策划，用于新产品开发的质量管理框架"),
    ("APQP是什么", "汽车电子的车载导航系统采用Android操作系统，支持蓝牙和WiFi连接"),
    ("什么是FMEA", "FMEA失效模式分析是识别潜在失效并评估风险的方法"),
    ("什么是FMEA", "公司年会将于下周五在酒店举行，请各部门提前报名"),
    ("送样评估的流程", "送样评估需要填写送样通知单，经过质量部初步审核后送至客户"),
    ("送样评估的流程", "财务部正在制定2025年度的预算编制计划"),
]

def cos(a, b):
    import math
    dot = sum(x*y for x,y in zip(a,b))
    n1 = math.sqrt(sum(x*x for x in a))
    n2 = math.sqrt(sum(x*x for x in b))
    if n1*n2 == 0: return 0
    return dot / (n1*n2)

print("\n问题\t\t\t相关分数\t无关分数\t差值")
print("-" * 80)
for q, relevant in test_pairs[:2]:  # 只测前两组做对比
    for label, model in [("hash", hash_model), ("sem ", sem_model)]:
        qv = model.embed(q)
        rv = model.embed(relevant)
        irv = model.embed(test_pairs[1][1] if 'APQP' in q else test_pairs[3][1])
        s_rel = cos(qv, rv)
        s_irr = cos(qv, irv)
        print(f"{label} '{q[:15]}'\t{s_rel:.3f}\t\t{s_irr:.3f}\t\t{s_rel-s_irr:+.3f}")
    print()
