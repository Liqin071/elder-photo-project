from models.database import SessionLocal
from models.user import User, UserRole
from utils.auth import get_password_hash

db = SessionLocal()
try:
    existing = db.query(User).filter(User.username == "test").first()
    if existing:
        print("用户已存在")
    else:
        new_user = User(
            username="test",
            password_hash=get_password_hash("123456"),
            email="test@test.com",
            role=UserRole.VOLUNTEER
        )
        db.add(new_user)
        db.commit()
        print("注册成功")
except Exception as e:
    print("错误:", e)
    db.rollback()
finally:
    db.close()
