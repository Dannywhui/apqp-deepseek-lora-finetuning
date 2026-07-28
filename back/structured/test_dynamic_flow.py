"""测试动态SQL查询完整链路"""
from dotenv import load_dotenv
load_dotenv()

from agent_dynamic import run_dynamic_query
import json
from datetime import date, datetime
from decimal import Decimal

def default_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)

print("=" * 60)
print("【链路测试】用户问：查询项目PROJ2026001的风险")
print("=" * 60)

result = run_dynamic_query('查询项目PROJ2026001的风险')

if 'error' in result:
    print('\n❌ 错误:', result['error'])
else:
    print('\n【1】规则引擎生成 SQL：')
    print(result['sql'])

    print('\n【2】MySQL 查询结果：')
    print(json.dumps(result['results'], ensure_ascii=False, indent=2, default=default_serializer))

    print('\n【3】规则引擎生成自然语言回复：')
    print(result['answer'])

    print('\n' + '=' * 60)
    print(f"✅ 链路完成：SQL生成 → 数据库查询 → 自然语言回复")
    print('=' * 60)
