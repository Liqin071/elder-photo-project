"""
小程序适配 —— 幂等增量数据库迁移(不触碰现有数据)

用法(服务器上,在 backend 目录下):
    python3 migrate_miniprogram.py

说明:
- 只做"新增列 / 改列类型",不改动任何既有行,可重复执行。
- 缺失的表(comments / notifications / elderly_children 等)由 create_all 直接创建。
- 服务器为 MariaDB(支持 ADD COLUMN IF NOT EXISTS);若实际是 MySQL,
  请把失败项手动改成不带 IF NOT EXISTS 的 ALTER 执行一次。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from models.database import engine, Base
import models  # noqa: F401  确保所有模型注册到 Base.metadata

# (表名, ALTER 语句) —— 全部纯增量
ADDITIVE_ALTERS = [
    # users:小程序登录/绑定需要的列(旧表只有 username/password_hash/email/role/created_at/last_login)
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(100) NULL"),
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar VARCHAR(500) NULL"),
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20) NULL"),
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS openid VARCHAR(100) NULL"),
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login DATETIME NULL"),
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR(500) NULL"),
    ("users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires DATETIME NULL"),
    # 旧表 role 是 ENUM('volunteer','admin'),插 'elder'/'children' 会直接报错 → 改 VARCHAR(数据不丢)
    ("users", "ALTER TABLE users MODIFY COLUMN role VARCHAR(20) NOT NULL DEFAULT 'volunteer'"),
    # elderly:头像 + 照护志愿者分配
    ("elderly", "ALTER TABLE elderly ADD COLUMN IF NOT EXISTS volunteer_id INT NULL"),
    ("elderly", "ALTER TABLE elderly ADD COLUMN IF NOT EXISTS avatar VARCHAR(500) NULL"),
    # photos:小程序契约字段(备注/尺寸/缩略图等;旧表缺失时 INSERT 会失败)
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS processed_path VARCHAR(500) NULL"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS thumbnail_path VARCHAR(500) NULL"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS photo_type VARCHAR(20) DEFAULT 'normal'"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'original'"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS ai_enhancement_type VARCHAR(30) DEFAULT 'none'"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS note TEXT NULL"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS file_size INT NULL"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS width INT NULL"),
    ("photos", "ALTER TABLE photos ADD COLUMN IF NOT EXISTS height INT NULL"),
    # elderly_children:绑定关系显示名(母亲/父亲),缺失时 create_all 已建,此处补列
    ("elderly_children", "ALTER TABLE elderly_children ADD COLUMN IF NOT EXISTS relationship VARCHAR(20) NULL"),
]


def migrate():
    print("==> 1/2 补齐缺失的表(comments/notifications/elderly_children 等)")
    Base.metadata.create_all(bind=engine)

    print("==> 2/2 增量补充列(纯新增,不触碰现有数据)")
    with engine.begin() as conn:
        for table, sql in ADDITIVE_ALTERS:
            try:
                conn.execute(text(sql))
                print(f"  OK   [{table}] {sql}")
            except Exception as e:
                # 重复执行/已存在等场景直接跳过,不中断
                print(f"  SKIP [{table}] {sql}\n       -> {e}")

    print("迁移完成。若存在 SKIP,请人工核对是否为真正的问题(如 MySQL 不支持 IF NOT EXISTS)。")


if __name__ == "__main__":
    migrate()
