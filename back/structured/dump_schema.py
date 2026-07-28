"""导出数据库现有表结构"""
import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "apqp"),
    charset="utf8mb4",
)

cursor = conn.cursor(dictionary=True)

tables = ["project_progress", "project_risks", "project_issues", "apqp_deliverables"]

for table in tables:
    print(f"\n{'='*60}")
    print(f"表: {table}")
    print(f"{'='*60}")
    
    cursor.execute(f"SHOW CREATE TABLE {table}")
    result = cursor.fetchone()
    print(result["Create Table"])
    
    cursor.execute(f"SELECT * FROM {table}")
    rows = cursor.fetchall()
    if rows:
        print(f"\n数据 ({len(rows)} 条):")
        for row in rows:
            print(f"  {row}")

cursor.close()
conn.close()
