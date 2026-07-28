"""测试数据库查询的边界情况"""
import sys
sys.path.insert(0, '.')

from agent_dynamic import run_dynamic_query

test_cases = [
    "查询项目PROJ999999的风险",
    "查询项目PROJ2026001的交付物",
    "查询项目XYZ123的风险",
    "查询项目财务报表",
    "查询风险",
    "查询项目PROJ2026001的财务报表",
    "查询项目PROJ2026001",
    "查询项目ABC",
    "查询问题"
]

for question in test_cases:
    print(f"\n{'='*60}")
    print(f"用户提问: {question}")
    try:
        result = run_dynamic_query(question)
        if "error" in result:
            print(f"错误: {result['error']}")
        else:
            print(f"生成SQL: {result['sql']}")
            print(f"查询结果数量: {len(result['results'])}")
            print(f"AI回复: {result['answer']}")
    except Exception as e:
        print(f"执行异常: {e}")
