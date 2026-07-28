"""基于规则的SQL生成器 - 作为大模型SQL生成的备选方案"""
import re
from typing import List, Dict, Any, Tuple


# 白名单：允许查询的表名
ALLOWED_TABLES = {
    'project_risks',
    'project_issues',
    'project_progress',
    'apqp_deliverables',
}

# 白名单：允许查询的字段名
ALLOWED_FIELDS = {
    'project_id',
    'risk_name',
    'risk_level',
    'risk_status',
    'issue_name',
    'issue_status',
    'project_name',
    'apqp_phase',
    'deliverable_name',
    'is_completed',
}

SUPPORTED_QUERY_TYPES = {
    '风险': 'project_risks',
    '问题': 'project_issues',
    '进度': 'project_progress',
    '状态': 'project_progress',
    '交付物': 'apqp_deliverables',
}


def extract_project_id(question: str) -> str:
    """从问题中提取项目ID，必须是PROJ开头+数字的格式"""
    match = re.search(r'PROJ\d+', question, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    return None


def validate_project_id_format(project_id: str) -> bool:
    """验证项目ID格式是否正确"""
    return bool(re.match(r'^PROJ\d+$', project_id.upper()))


def detect_query_type(question: str) -> str:
    """检测查询类型"""
    for keyword in SUPPORTED_QUERY_TYPES:
        if keyword in question:
            return keyword
    return None


def contains_project_mention(question: str) -> bool:
    """检测问题中是否提到了'项目'"""
    return '项目' in question


def validate_table_name(table_name: str) -> bool:
    """验证表名是否在白名单中"""
    return table_name in ALLOWED_TABLES


def simple_sql_generator(question: str, schemas: List[Dict[str, Any]]) -> Tuple[str, bool, str]:
    """
    简单的基于规则的SQL生成器
    返回: (sql, success, error_message)
    
    安全措施：
    1. 表名和字段名使用白名单校验
    2. 参数使用占位符，返回参数列表
    3. 项目ID格式严格校验
    
    注意：调用方需使用参数化查询执行SQL，例如：
        sql, params = simple_sql_generator(...)
        cursor.execute(sql, params)
    """
    question_lower = question.lower()
    project_id = extract_project_id(question)
    query_type = detect_query_type(question)
    has_project = contains_project_mention(question)
    
    table_names = [s['table_name'] for s in schemas]
    
    # 构造安全SQL的辅助函数
    def build_safe_query(table: str, where_field: str = None, where_value: str = None, limit: int = None) -> Tuple[str, List]:
        """
        构造安全的SQL查询
        返回: (sql, params)
        """
        # 表名白名单校验
        if not validate_table_name(table):
            return None, []
        
        # 基础查询
        sql = f"SELECT * FROM {table}"
        params = []
        
        # WHERE 条件（参数化）
        if where_field and where_value:
            if where_field not in ALLOWED_FIELDS:
                return None, []
            sql += f" WHERE {where_field} = ?"
            params.append(where_value)
        
        # LIMIT（整型，安全）
        if limit:
            sql += f" LIMIT {int(limit)}"
        
        return sql, params
    
    if has_project:
        if not project_id:
            return None, False, "未识别到有效的项目ID。项目ID格式应为PROJ开头+数字（如PROJ2026001）"
        if not validate_project_id_format(project_id):
            return None, False, f"项目ID格式不正确，请使用PROJ开头+数字的格式（如PROJ2026001）"
        
        if query_type:
            table_name = SUPPORTED_QUERY_TYPES[query_type]
            if table_name not in table_names:
                return None, False, f"不支持查询'{query_type}'类型的数据，数据库中缺少相关表"
            
            sql, params = build_safe_query(table_name, 'project_id', project_id)
            if sql is None:
                return None, False, "非法的查询表或字段"
        else:
            return None, False, "未识别到查询类型。当前支持查询：风险、问题、进度、交付物"
    elif query_type:
        table_name = SUPPORTED_QUERY_TYPES[query_type]
        if table_name not in table_names:
            return None, False, f"不支持查询'{query_type}'类型的数据，数据库中缺少相关表"
        sql, params = build_safe_query(table_name, limit=100)
        if sql is None:
            return None, False, "非法的查询表或字段"
    elif project_id:
        if not validate_project_id_format(project_id):
            return None, False, f"项目ID格式不正确，请使用PROJ开头+数字的格式（如PROJ2026001）"
        sql, params = build_safe_query('project_progress', 'project_id', project_id)
        if sql is None:
            return None, False, "非法的查询表或字段"
    else:
        return None, False, "无法识别查询需求。请提供项目ID（如PROJ2026001）和查询类型（如风险、问题、进度、交付物）"
    
    # 返回元组：(sql, params, success, error_message)
    # 兼容旧接口：返回 (sql, success, error_message)，但实际调用方应该用参数化查询
    # 这里为了兼容性，仍然返回字符串sql，但调用方需要改为参数化查询
    return (sql, params), True, ""