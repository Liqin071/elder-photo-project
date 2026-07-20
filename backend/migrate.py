"""数据库迁移脚本"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import init_db, Base

def migrate():
    print("开始数据库迁移...")
    try:
        init_db()
        print("迁移完成！")
        print("已创建的表：")
        for table in Base.metadata.tables.keys():
            print(f"  - {table}")
    except Exception as e:
        print(f"迁移失败: {e}")
        raise

if __name__ == "__main__":
    migrate()
