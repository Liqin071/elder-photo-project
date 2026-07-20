---
name: "server-deployment-guide"
description: "Guide for deploying and fixing backend services on remote servers. Invoke when deploying code, fixing server errors, or updating server files. Includes printf usage, case consistency, and common pitfalls."
---

# 服务器部署指南 - 经验总结

基于实际项目部署过程中反复遇到的问题总结出的最佳实践。

## 核心原则

### 1. 文件写入：使用 printf 而非 cat

**❌ 错误做法**
```bash
# cat heredoc 容易出错，特别是包含特殊字符时
cat > file.py << 'EOF'
code with 'quotes' and (parentheses)
EOF
```

**✅ 正确做法**
```bash
# 使用 printf，每行一个参数
printf '%s\n' 'line1' 'line2' 'line3' > file.py

# 或者创建 Python 脚本文件
printf '%s\n' 'import sys' 'sys.path.insert(0, "/path")' 'print("test")' > /tmp/test.py
python3 /tmp/test.py
```

**原因**：
- cat heredoc 对特殊字符（括号、引号）敏感，容易语法错误
- printf 更可靠，每行作为独立参数，避免转义问题
- Python 脚本适合复杂内容

---

### 2. 大小写统一：数据库、枚举、代码必须一致

**❌ 错误案例**
```python
# Python 枚举
class UserRole(str, enum.Enum):
    VOLUNTEER = "volunteer"  # 成员名大写，值小写

# 数据库
role ENUM('volunteer', 'admin')  # 小写值

# 代码使用
role: str = "volunteer"  # 小写
```

**问题**：SQLAlchemy 使用**枚举成员名**（VOLUNTEER）匹配数据库值，导致不匹配。

**✅ 正确做法**
```python
# Python 枚举 - 统一大写
class UserRole(str, enum.Enum):
    VOLUNTEER = "VOLUNTEER"
    ADMIN = "ADMIN"

# 数据库 - 统一大写
role ENUM('VOLUNTEER', 'ADMIN')

# 代码使用 - 统一大写
role: str = "VOLUNTEER"
```

**修改命令**：
```bash
# 修改数据库
mysql -u root -p -e "USE db; ALTER TABLE users MODIFY role ENUM('VOLUNTEER', 'ADMIN');"

# 修改 Python 文件
sed -i 's/VOLUNTEER = "volunteer"/VOLUNTEER = "VOLUNTEER"/g' models/user.py
sed -i 's/role: str = "volunteer"/role: str = "VOLUNTEER"/g' api/auth.py
```

---

### 3. 导入路径：确保文件结构与导入语句匹配

**❌ 错误**
```python
# 文件实际在：auth/utils.py
from auth.utils import get_password_hash  # 但代码导入路径错误
```

**✅ 正确**
```python
# 确认文件结构
ls -la /path/backend/auth/utils.py

# 使用正确路径
from utils.auth import get_password_hash  # 或根据实际结构调整
```

**检查步骤**：
```bash
# 1. 查看文件结构
find /path/backend -name "*.py" | head -20

# 2. 检查导入语句
grep "from.*import" api/auth.py

# 3. 测试导入
cd /path/backend && python3 -c "from utils.auth import get_password_hash; print('OK')"
```

---

### 4. 错误排查流程

**步骤 1：清除缓存**
```bash
find /path/backend -name "*.pyc" -delete
find /path/backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
```

**步骤 2：测试模块导入**
```bash
cd /path/backend && python3 -c "
import sys, os
sys.path.insert(0, '/path/backend')
from utils.auth import get_password_hash
hashed = get_password_hash('test')
print('Hash:', hashed)
"
```

**步骤 3：前台启动看实时错误**
```bash
pkill -f uvicorn
cd /path/backend && python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
```

**步骤 4：查看日志（最新错误在底部）**
```bash
tail -50 /path/backend/nohup.out
grep -A 10 "Error\|Exception" /path/backend/nohup.out | tail -20
```

---

### 5. 数据库连接验证

**检查数据库配置**
```bash
# 查看.env 文件
cat /path/backend/.env

# 测试数据库连接
mysql -u root -p -e "SHOW DATABASES;"

# 检查表结构
mysql -u root -p -e "USE db; DESCRIBE users;"
```

**常见问题**：
- 数据库未创建
- 表结构不匹配（字段名、类型、枚举值）
- 连接字符串错误

---

### 6. 服务启动与测试

**后台启动**
```bash
# 停止旧服务
pkill -f uvicorn

# 后台启动
cd /path/backend && nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &

# 等待启动
sleep 2

# 测试
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"123456","email":"test@test.com"}'
```

**前台启动（查看实时错误）**
```bash
pkill -f uvicorn
cd /path/backend && python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
```

---

### 7. 常见错误及解决方案

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `ValueError: password cannot be longer than 72 bytes` | bcrypt 长度限制 | 使用 SHA256 预哈希 + bcrypt |
| `LookupError: 'volunteer' is not among enum values` | 枚举值大小写不匹配 | 统一数据库和代码的枚举值为大写 |
| `ModuleNotFoundError: No module named 'utils'` | 导入路径错误 | 检查文件结构，修正导入路径 |
| `Internal Server Error` | 多种原因 | 前台启动看实时错误日志 |
| `Address already in use` | 端口被占用 | `pkill -f uvicorn` 停止占用进程 |
| `syntax error near unexpected token` | 命令格式错误 | 使用 printf 代替 cat，避免特殊字符 |
| `(pymysql.err.DataError) (1406, "Data too long for column")` | 字段长度不足 | `ALTER TABLE users MODIFY column_name VARCHAR(500)` |
| `(pymysql.err.OperationalError) (1292, "Truncated incorrect DOUBLE value")` | `func.now() + timedelta()` 在 MySQL 中不工作 | 使用 `datetime.utcnow() + timedelta()` |
| `FastAPI response_model 过滤字段` | Pydantic 模型未定义返回字段 | 在 response_model 中添加 Optional 字段 |
| `NameError: name 'Optional' is not defined` | 缺少 typing 导入 | `from typing import Optional` |

---

### 8. 完整修改流程示例

**场景**：修复密码加密和枚举值问题

```bash
# 1. 停止服务
pkill -f uvicorn

# 2. 修改 utils/auth.py（使用 printf）
printf '%s\n' \
  'import hashlib' \
  'import bcrypt' \
  'from datetime import datetime, timedelta' \
  'from typing import Optional' \
  'from jose import JWTError, jwt' \
  'import os' \
  'from dotenv import load_dotenv' \
  '' \
  'load_dotenv()' \
  '' \
  'SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")' \
  'ALGORITHM = os.getenv("ALGORITHM", "HS256")' \
  'ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))' \
  '' \
  'def _prehash_password(password: str) -> str:' \
  '    return hashlib.sha256(password.encode("utf-8")).hexdigest()' \
  '' \
  'def get_password_hash(password: str) -> str:' \
  '    prehashed = _prehash_password(password)' \
  '    return bcrypt.hashpw(prehashed.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")' \
  '' \
  'def verify_password(plain, hashed):' \
  '    prehashed = _prehash_password(plain)' \
  '    return bcrypt.checkpw(prehashed.encode("utf-8"), hashed.encode("utf-8"))' \
  '' \
  'def create_access_token(data, expires_delta=None):' \
  '    to_encode = data.copy()' \
  '    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))' \
  '    to_encode.update({"exp": expire, "type": "access", "iat": datetime.utcnow()})' \
  '    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)' \
  '' \
  'def verify_token(token):' \
  '    try:' \
  '        return int(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("sub"))' \
  '    except:' \
  '        return None' \
  > /path/backend/utils/auth.py

# 3. 修改数据库枚举值
mysql -u root -p -e "USE db; ALTER TABLE users MODIFY role ENUM('VOLUNTEER', 'ADMIN');"

# 4. 修改 models/user.py
sed -i 's/VOLUNTEER = "volunteer"/VOLUNTEER = "VOLUNTEER"/g' /path/backend/models/user.py
sed -i 's/ADMIN = "admin"/ADMIN = "ADMIN"/g' /path/backend/models/user.py

# 5. 修改 api/auth.py
sed -i 's/role: str = "volunteer"/role: str = "VOLUNTEER"/g' /path/backend/api/auth.py

# 6. 清除缓存
find /path/backend -name "*.pyc" -delete
find /path/backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# 7. 测试导入
cd /path/backend && python3 -c "
import sys; sys.path.insert(0, '/path/backend')
from utils.auth import get_password_hash
print('OK:', get_password_hash('test'))
"

# 8. 启动服务
cd /path/backend && nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
sleep 2

# 9. 测试接口
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"123456","email":"test@test.com"}'
```

---

### 9. SQLAlchemy 时间字段处理

**❌ 错误做法 1：使用 func.now() + timedelta()**
```python
from sqlalchemy import func
# 这在 MySQL 中会报错！
user.reset_token_expires = func.now() + timedelta(minutes=60)
```

**问题**：`func.now() + timedelta()` 在 MySQL 中不工作，会导致：
```
(pymysql.err.OperationalError) (1292, "Truncated incorrect DOUBLE value: '1970-01-01 01:00:00'")
```

**✅ 正确做法**
```python
# 方法 1：直接使用 datetime.utcnow()（推荐）
from datetime import datetime, timedelta
user.reset_token_expires = datetime.utcnow() + timedelta(minutes=60)

# 方法 2：在模型中使用 server_default
from sqlalchemy import func, text
reset_token_expires = Column(DateTime, server_default=func.now() + text('INTERVAL 60 MINUTE'))
```

**最佳实践**：
- Python 代码中设置时间：使用 `datetime.utcnow() + timedelta()`
- 数据库默认值：使用 `server_default` + `func.now()`
- 避免使用 `func.now() + timedelta()` 这种混合写法

---

### 10. 远程终端交互问题（2026-07-20 调试新增）

**问题 1：长命令被终端自动折行打断**

用户的 SSH 终端软件会在固定宽度处自动折行，导致长命令中的引号、括号被截断。heredoc（`<< 'EOF'`）在多行输入时也会触发 `>` 等待模式，用户无法正确退出。

**解决方法**：
- 每条命令控制在 80 字符以内
- 使用逐行 `echo '...' >> file.py` 追加写文件（最可靠）
- 使用单行 `python3 -c "..."` 测试（无缩进语句）
- base64 编码也需切成小块（每条约 60 字符），不能整段粘贴
- **禁止**使用 heredoc 和多行 python 字符串

**问题 2：复制命令时第一行丢失或变异**

用户复制粘贴时，第一行命令有时候会变成只有文件路径（丢失了 `cat` / `head` 等命令名）。

**解决方法**：
- 关键命令前面加一句注释性质的短命令（如 `echo "start"`）
- 让用户先执行一条无意义的短命令确认粘贴正常

---

### 11. SQLAlchemy Enum 与数据库 ENUM 的致命坑（2026-07-20 调试新增）

**问题**：
```python
# Python 枚举
class UserRole(str, enum.Enum):
    VOLUNTEER = "volunteer"  # 成员名大写，值小写
```

但 SQLAlchemy 的 `Enum` 类型在读写数据库时使用的是**枚举成员名称**（`VOLUNTEER`），不是值（`volunteer`）。导致：
- 数据库存的是 `'volunteer'`（小写）
- SQLAlchemy 一读就报 `LookupError: 'volunteer' is not among the defined enum values`

**错误信息示例**：
```
LookupError: 'volunteer' is not among the defined enum values.
Enum name: userrole. Possible values: ADMIN, ELDER, VOLUNTEER, CHILDREN
```

**必须采用的解决方案**：
```python
# 不要用 Enum 类型！
# role = Column(Enum(UserRole), default=UserRole.VOLUNTEER)  ❌

# 改用 String 类型
role = Column(String(20), default="volunteer")  # ✅
```

同时修改数据库：
```bash
mysql -u root -p -e "ALTER TABLE db.users MODIFY role VARCHAR(20) NOT NULL DEFAULT 'volunteer';"
```

**连带影响**：改用 String 后，所有 `user.role.value` 调用都要改为 `user.role`：
```bash
sed -i 's/.role.value/.role/g' api/auth.py
```

**查错方法**：
```bash
python3 -c "import sys; sys.path.insert(0,'/path/backend'); from models.user import UserRole; print(UserRole('volunteer'))"
```

---

### 12. relationship 引用缺失模型导致启动失败（2026-07-20 调试新增）

**问题**：`models/user.py` 中定义了 `relationship("Elderly")`、`relationship("Photo")` 等，但服务器上 `models/photo.py` 和 `models/activity.py` 文件不存在，导致 SQLAlchemy 映射时报错：
```
InvalidRequestError: When initializing mapper Mapper[User(users)], expression 'Elderly' failed to locate a name
```

**解决方法**：
- 临时方案：注释掉缺失的 relationship 行
```bash
sed -i '/elderly_records\|photos\|activities/s/^/## /' models/user.py
```
- 永久方案：确保所有被引用的模型文件都存在于服务器

---

### 13. 排查 500 Internal Server Error 的标准流程（2026-07-20 调试新增）

当接口返回 `Internal Server Error` 且 `nohup.out` 没有最新日志时：

1. **前台启动，实时看错误**：
```bash
pkill -f uvicorn
cd /path/backend && python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
```
另开终端发请求，看前台打印的完整 traceback。

2. **用 Python 直接测试数据库操作**，绕过 API 层：
```bash
python3 -c "import sys; sys.path.insert(0,'/path/backend'); from models.database import SessionLocal; from models.user import User, UserRole; from utils.auth import get_password_hash; db=SessionLocal(); u=User(username='t1', password_hash=get_password_hash('123456'), role='volunteer'); db.add(u); db.commit(); print('OK id:', u.id); db.close()"
```

3. **逐层定位**：枚举值 → 数据库写入 → API 路由 → 中间件，从底层往上排查

---

### 10. FastAPI 响应模型字段过滤问题

**❌ 错误案例**
```python
# Pydantic 模型定义
class TokenResponse(BaseModel):
    access_token: str
    token_type: str

# 路由返回
return {
    "access_token": token,
    "token_type": "bearer",
    "refresh_token": refresh_token  # 这个字段会被过滤掉！
}

# 结果：客户端收不到 refresh_token
```

**问题**：当设置了 `response_model=TokenResponse` 时，FastAPI 会自动过滤掉 Pydantic 模型中未定义的字段。

**✅ 正确做法**
```python
# 方法 1：在 Pydantic 模型中添加可选字段
from typing import Optional

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None  # 添加可选字段

# 方法 2：移除 response_model（不推荐，会失去自动验证）
@router.post("/login")  # 不加 response_model
def login(...):
    return {"access_token": token, "refresh_token": refresh_token}
```

**最佳实践**：
- 使用 `response_model` 可以获得自动验证和文档生成
- 需要返回额外字段时，在 Pydantic 模型中添加 `Optional` 字段
- 忘记导入 `Optional` 会导致 `NameError`

---

## 总结

### 远程终端交互
1. **命令要短**：控制在 80 字符以内，避免终端折行打断引号/括号
2. **逐行 echo 追加**：最可靠的文件写入方式，每行一条 `echo '...' >> file`
3. **禁止 heredoc**：`<< 'EOF'` 在这个终端上会触发 `>` 等待模式
4. **单行 python3 -c**：测试代码用单行，避免缩进问题

### 代码与数据库一致性
5. **不要用 SQLAlchemy Enum**：用 `String` 类型代替，枚举匹配机制是坑
6. **数据库 ENUM 改 VARCHAR**：用 `ALTER TABLE MODIFY role VARCHAR(20)` 迁移
7. **`.value` 调用**：用 String 后检查所有 `.role.value`，改为 `.role`
8. **relationship**：确保所有被引用的模型文件都存在于服务器
9. **`__init__.py`**：完成后检查 `models/__init__.py` 是否导出了所有模型
10. **模型字段必须匹配数据库**：先 `DESCRIBE table` 看实际列名，再写模型
11. **API 字段名映射**：用 `_to_dict()` 函数在 API 层做字段映射，隔离 DB 列名和接口字段名

### 错误排查流程
12. **前台启动看实时错误**：`python3 -m uvicorn app:app --host 0.0.0.0 --port 8000`
13. **Python 直测绕过 API**：用 `python3 -c` 测试枚举值 → 数据库写入 → 逐层排查
14. **日志记到文件**：`> /tmp/app.log 2>&1`，然后用 `tail` 查看

### curl 调用注意事项（2026-07-20 新增）
15. **token 不要直接粘贴**：JWT 含 `.` 和 JWT 看起来没问题，但直接粘贴在 curl 里，bash 可能解析特殊字符。用环境变量：`TOKEN=$(...)` 然后 `-H "Authorization: Bearer $TOKEN"`
16. **URL 中 `?` 要加引号**：`curl "http://host/api/elders?page=1"` 否则 bash 当成通配符

### git 工作流（2026-07-20 新增）
17. **git pull 冲突**：如果服务器有未跟踪文件与远程同名，先 `rm` 再 pull
18. **每个里程碑打 tag**：`git tag v1.0-xxx -m "描述"` → `git push origin v1.0-xxx`
19. **不要在生产服务器上编辑代码**：本地编辑 → git push → 服务器 git pull

### 数据库迁移（2026-07-20 新增）
20. **添加字段前先 DESCRIBE**：服务器可能和本地模型不同，先看实际表结构
21. **ALTER TABLE 分条执行**：多条 ALTER 逐条执行比合并更安全
22. **ENUM→VARCHAR 是安全的**：不会丢数据，只是放宽约束

### 文件上传测试（2026-07-20 新增）
23. **base64 生成测试图片**：`python3 -c "import base64; open('/tmp/test.jpg','wb').write(base64.b64decode('...'))"`
24. **multipart/form-data**：用 `-F "file=@/tmp/test.jpg"` 而非 `-d`，注意字段名要和 API 的 `alias` 匹配

遵循这些原则可以避免 90% 的部署问题！
