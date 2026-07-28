"""这个文件读取我们数据库里的表结构，把它转换为纯文本，然后调用大模型生成查询sql  """

import re
from typing import Any, Dict, List, Tuple

try:
    from .excel_ingest import connect_mysql_from_env
except ImportError:
    from excel_ingest import connect_mysql_from_env

try:
    from .sql_rules import simple_sql_generator
except ImportError:
    from sql_rules import simple_sql_generator


TABLE_WHITELIST = {
    "project_progress",
    "project_risks",
    "project_issues",
    "apqp_deliverables",
}

DANGEROUS_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
    "CREATE", "RENAME", "GRANT", "REVOKE", "SHUTDOWN", "FLUSH",
    "EXEC", "EXECUTE", "XP_"
}


def get_table_schema(connection: Any, table_name: str) -> Dict[str, Any]:
    sql = """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_COMMENT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %(table)s
        ORDER BY ORDINAL_POSITION
    """
    with connection.cursor(dictionary=True) as cursor:
        cursor.execute(sql, {"table": table_name})
        columns = cursor.fetchall()
    return {
        "table_name": table_name,
        "columns": columns,
        "column_names": [col["COLUMN_NAME"] for col in columns]
    }


def get_all_table_schemas(connection: Any, tables: List[str] = None) -> List[Dict[str, Any]]:
    if tables is None:
        tables = list(TABLE_WHITELIST)
    schemas = []
    for table in tables:
        if table in TABLE_WHITELIST:
            schemas.append(get_table_schema(connection, table))
    return schemas


def format_schema_for_prompt(schemas: List[Dict[str, Any]]) -> str:
    parts = []
    for schema in schemas:
        columns_str = "\n".join(
            f"  - {col['COLUMN_NAME']} ({col['DATA_TYPE']}, nullable={col['IS_NULLABLE']})"
            for col in schema["columns"]
        )
        parts.append(f"表名: {schema['table_name']}\n字段:\n{columns_str}")
    return "\n\n".join(parts)


def validate_sql(sql: str) -> Tuple[bool, str]:
    sql_upper = sql.strip().upper()
    
    if not sql_upper.startswith("SELECT"):
        return False, "SQL必须以SELECT开头"
    
    for keyword in DANGEROUS_KEYWORDS:
        # 使用单词边界匹配，避免子串误伤（如 FLUSH 误伤 INFLUSH）
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, sql_upper):
            return False, f"SQL包含危险关键词: {keyword}"
    
    # 单独检测注释符号（先移除字符串字面量，避免字符串内误伤）
    sql_no_strings = re.sub(r"'[^']*'", "''", sql_upper)
    sql_no_strings = re.sub(r'"[^"]*"', '""', sql_no_strings)
    if re.search(r'(^|\s|;)--', sql_no_strings) or '/*' in sql_no_strings:
        return False, "SQL包含注释符号"
    
    for table in TABLE_WHITELIST:
        if table.upper() in sql_upper:
            return True, ""
    
    return False, "SQL中没有找到允许的表"


def extract_sql_from_response(response: str) -> str:
    match = re.search(r"```sql\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    match = re.search(r"```\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    return response.strip()


def build_sql_generation_prompt(question: str, schemas: List[Dict[str, Any]]) -> str:
    schema_text = format_schema_for_prompt(schemas)
    return f"""根据表结构和用户问题生成SQL。必须提取用户问题中的具体值（如项目ID、名称）放到SQL里。

表结构:
{schema_text}

示例:
问题: 查询项目PROJ001的风险
SQL: SELECT * FROM project_risks WHERE project_id = 'PROJ001';

问题: 查询项目ABC123的所有问题
SQL: SELECT * FROM project_issues WHERE project_id = 'ABC123';

问题: 查询PROJ2026001的进度
SQL: SELECT * FROM project_progress WHERE project_id = 'PROJ2026001';

问题: {question}
SQL:"""


def generate_and_execute_sql(
    question: str,
    generate_func,
    tables: List[str] = None
) -> Tuple[List[Dict[str, Any]], str]:
    
    connection = connect_mysql_from_env()
    try:
        schemas = get_all_table_schemas(connection, tables)
        if not schemas:
            return [], "未找到可用的表结构"
        
        # 优先尝试规则生成SQL（更快、更可靠）
        result, success, err_msg = simple_sql_generator(question, schemas)
        
        # 如果规则生成失败，且是格式/识别错误，直接返回
        if not success and err_msg:
            return [], err_msg
        
        # 如果规则生成失败（没有匹配到规则），再用大模型尝试
        if not success:
            prompt = build_sql_generation_prompt(question, schemas)
            response = generate_func(prompt, temperature=0.1, max_new_tokens=512, top_p=0.9)
            sql = extract_sql_from_response(response)
            params = []
        else:
            # 规则生成成功，解包 (sql, params)
            sql, params = result
        
        is_valid, err_msg = validate_sql(sql)
        if not is_valid:
            return [], f"SQL校验失败: {err_msg}。生成的SQL: {sql}"
        
        with connection.cursor(dictionary=True) as cursor:
            # 使用参数化查询，防止SQL注入
            cursor.execute(sql, params)
            results = cursor.fetchall()
            return results, sql
    
    finally:
        connection.close()
