"""
数据库初始化脚本
用于创建数据库和表结构
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Base, engine
from models.user import User, UserRole
from models.elderly import Elderly
from models.photo import Photo, PhotoType, PhotoStatus, AIEnhancementType
from models.activity import Activity


def init_database():
    print("开始初始化数据库...")
    
    try:
        Base.metadata.create_all(bind=engine)
        print("数据库表创建成功！")
        
        print("\n已创建的表：")
        for table in Base.metadata.tables.keys():
            print(f"  - {table}")
            
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        raise


def create_test_data():
    from models import SessionLocal
    from passlib.context import CryptContext
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()
    
    try:
        admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if not admin:
            print("\n创建默认管理员账号...")
            admin_user = User(
                username="admin",
                password_hash=pwd_context.hash("admin123"),
                email="admin@example.com",
                role=UserRole.ADMIN
            )
            db.add(admin_user)
            db.commit()
            print("默认管理员创建成功")
            print("   用户名: admin")
            print("   密码: admin123")
            print("   请及时修改默认密码！")
        else:
            print("\n管理员账号已存在，跳过创建")
            
    except Exception as e:
        print(f"创建测试数据失败: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("老年拍照助手 - 数据库初始化工具")
    print("=" * 50)
    
    init_database()
    
    print("\n" + "=" * 50)
    response = input("是否创建默认管理员账号？(y/n): ").strip().lower()
    if response in ["y", "yes", "是"]:
        create_test_data()
    
    print("\n" + "=" * 50)
    print("数据库初始化完成！")
    print("=" * 50)
