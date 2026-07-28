"""
数据库表结构迁移脚本
备份现有数据 -> 删除旧表 -> 按代码期望字段重建 -> 迁移数据
"""
import os
import sys
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import Error

load_dotenv()

def get_conn():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "apqp"),
        charset="utf8mb4",
    )

def backup_and_drop_tables(cursor):
    """备份数据到临时表，然后删除旧表"""
    tables = ["project_progress", "project_risks", "project_issues", "apqp_deliverables"]
    
    for table in tables:
        # 检查表是否存在
        cursor.execute(f"""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = DATABASE() AND table_name = '{table}'
        """)
        if cursor.fetchone()[0] == 0:
            print(f"  ⚠️  表 {table} 不存在，跳过")
            continue
            
        # 备份到临时表
        backup_table = f"{table}_backup"
        cursor.execute(f"DROP TABLE IF EXISTS {backup_table}")
        cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
        print(f"  ✅ {table} 数据已备份到 {backup_table}")
        
        # 删除旧表
        cursor.execute(f"DROP TABLE {table}")
        print(f"  ✅ 旧表 {table} 已删除")

def create_new_tables(cursor):
    """按代码期望的字段创建新表"""
    
    # project_progress 表
    cursor.execute("""
        CREATE TABLE project_progress (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            project_id VARCHAR(255) NULL,
            project_name VARCHAR(255) NULL,
            customer VARCHAR(255) NULL,
            product_type VARCHAR(255) NULL,
            apqp_phase VARCHAR(255) NULL,
            current_status VARCHAR(255) NULL,
            planned_start_date DATE NULL,
            planned_finish_date DATE NULL,
            actual_finish_date DATE NULL,
            owner VARCHAR(255) NULL,
            delay_days INT NULL,
            progress_note TEXT NULL,
            source_file VARCHAR(255) NULL,
            source_sheet VARCHAR(255) NULL,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    print("  ✅ project_progress 表已创建")
    
    # project_risks 表
    cursor.execute("""
        CREATE TABLE project_risks (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            risk_id VARCHAR(255) NULL,
            project_id VARCHAR(255) NULL,
            project_name VARCHAR(255) NULL,
            risk_category VARCHAR(255) NULL,
            risk_description TEXT NULL,
            severity_s INT NULL,
            occurrence_o INT NULL,
            detection_d INT NULL,
            rpn INT NULL,
            risk_level VARCHAR(255) NULL,
            mitigation_action TEXT NULL,
            owner VARCHAR(255) NULL,
            planned_close_date DATE NULL,
            closure_status VARCHAR(255) NULL,
            source_file VARCHAR(255) NULL,
            source_sheet VARCHAR(255) NULL,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    print("  ✅ project_risks 表已创建")
    
    # project_issues 表
    cursor.execute("""
        CREATE TABLE project_issues (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            issue_id VARCHAR(255) NULL,
            project_id VARCHAR(255) NULL,
            project_name VARCHAR(255) NULL,
            issue_source VARCHAR(255) NULL,
            issue_description TEXT NULL,
            found_date DATE NULL,
            responsible_department VARCHAR(255) NULL,
            owner VARCHAR(255) NULL,
            planned_close_date DATE NULL,
            actual_close_date DATE NULL,
            current_status VARCHAR(255) NULL,
            resolution_note TEXT NULL,
            source_file VARCHAR(255) NULL,
            source_sheet VARCHAR(255) NULL,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    print("  ✅ project_issues 表已创建")
    
    # apqp_deliverables 表
    cursor.execute("""
        CREATE TABLE apqp_deliverables (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            deliverable_id VARCHAR(255) NULL,
            project_id VARCHAR(255) NULL,
            project_name VARCHAR(255) NULL,
            apqp_phase VARCHAR(255) NULL,
            deliverable_name VARCHAR(255) NULL,
            is_completed VARCHAR(255) NULL,
            review_status VARCHAR(255) NULL,
            owner VARCHAR(255) NULL,
            planned_submit_date DATE NULL,
            actual_submit_date DATE NULL,
            missing_or_reject_reason TEXT NULL,
            source_file VARCHAR(255) NULL,
            source_sheet VARCHAR(255) NULL,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    print("  ✅ apqp_deliverables 表已创建")

def migrate_data(cursor):
    """从备份表迁移数据到新表（字段映射）"""
    
    # project_progress 映射
    cursor.execute("""
        INSERT INTO project_progress (
            project_id, project_name, current_status,
            planned_start_date, planned_finish_date, actual_finish_date,
            owner, progress_note, source_file
        )
        SELECT 
            project_id, project_name, current_status,
            planned_start_date, planned_finish_date, actual_finish_date,
            manager, CONCAT('进度: ', progress_rate, '%'), '从旧表迁移'
        FROM project_progress_backup
    """)
    print(f"  ✅ project_progress 迁移了 {cursor.rowcount} 条数据")
    
    # project_risks 映射（简化：risk_title->risk_description, risk_level保留, handle_suggest->mitigation_action）
    cursor.execute("""
        INSERT INTO project_risks (
            project_id, risk_category, risk_description,
            risk_level, mitigation_action, owner, closure_status
        )
        SELECT 
            project_id, risk_title, risk_desc,
            risk_level, handle_suggest, responsible_person, risk_status
        FROM project_risks_backup
    """)
    print(f"  ✅ project_risks 迁移了 {cursor.rowcount} 条数据")
    
    # project_issues 映射
    cursor.execute("""
        INSERT INTO project_issues (
            project_id, issue_description, current_status,
            owner, resolution_note
        )
        SELECT 
            project_id, CONCAT(issue_title, ': ', issue_content), issue_status,
            solver, CONCAT('优先级: ', priority)
        FROM project_issues_backup
    """)
    print(f"  ✅ project_issues 迁移了 {cursor.rowcount} 条数据")
    
    # apqp_deliverables 映射
    cursor.execute("""
        INSERT INTO apqp_deliverables (
            project_id, deliverable_name, deliverable_id,
            is_completed, owner, missing_or_reject_reason
        )
        SELECT 
            project_id, deliverable_name, deliverable_type,
            finish_status, reviewer, remark
        FROM apqp_deliverables_backup
    """)
    print(f"  ✅ apqp_deliverables 迁移了 {cursor.rowcount} 条数据")

def main():
    print("=" * 60)
    print("数据库表结构迁移")
    print("=" * 60)
    print()
    print("⚠️  警告: 此操作会删除现有表并重建！")
    print("   数据会先备份到 *_backup 表")
    print()
    
    confirm = input("确认执行迁移? (输入 yes 继续): ")
    if confirm.strip().lower() != "yes":
        print("已取消")
        return 0
    
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        print("\n【1】备份并删除旧表...")
        backup_and_drop_tables(cursor)
        
        print("\n【2】创建新表...")
        create_new_tables(cursor)
        
        print("\n【3】迁移数据...")
        migrate_data(cursor)
        
        conn.commit()
        print("\n✅ 迁移完成！")
        print("\n说明:")
        print("  - 原数据已备份到 *_backup 表")
        print("  - 新表结构和代码期望的一致")
        print("  - 部分字段做了简化映射（如 FMEA 评分字段留空）")
        print("  - 如需完整 APQP 数据，建议重新导入 Excel")
        
    except Error as e:
        print(f"\n❌ 迁移失败: {e}")
        return 1
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
