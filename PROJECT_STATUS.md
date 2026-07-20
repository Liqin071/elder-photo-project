# 老年拍照助手项目 - 状态文档

## 项目概述
- **项目名称**: 老年拍照助手
- **服务器IP**: 36.112.162.239
- **宝塔面板**: https://60.205.122.68:38221/76b47d2f
- **宝塔账号**: onwbk0nv / 7727f4b3
- **工作目录**: /home/elder_photo_project/

---

## 已完成的功能 ✅

### 1. 项目结构搭建
```
/home/elder_photo_project/
├── backend/
│   ├── api/
│   │   ├── __init__.py
│   │   └── auth.py          # 用户认证API
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py      # 数据库连接池
│   │   ├── user.py          # 用户模型
│   │   └── schema.sql       # 数据库表结构
│   ├── utils/
│   │   ├── __init__.py
│   │   └── auth.py          # JWT认证工具
│   ├── config.py            # 配置文件
│   ├── app.py               # FastAPI主应用
│   ├── migrate.py           # 数据库迁移脚本
│   └── .env                 # 环境变量
├── logs/
├── static/
├── uploads/
└── requirements.txt
```

### 2. 数据库配置
- **数据库类型**: MariaDB (MySQL兼容)
- **数据库名**: elder_photo_db
- **root密码**: 0109A80b
- **数据表**:
  - users (用户表) ✅
  - elderly (老人信息表) ✅
  - photos (照片表) ✅
  - activities (活动记录表) ✅
- **默认管理员**: admin / admin123

### 3. API接口 (已实现但需修复)
- `POST /api/register` - 用户注册
- `POST /api/login` - 用户登录
- `GET /api/users/me` - 获取当前用户信息

### 4. 配置文件
- `.env` 文件已配置数据库连接信息
- `config.py` 包含应用配置
- 防火墙已开放 8000 端口

---

## 待解决的问题 ❌

### 问题1: 用户注册API报错 - bcrypt密码长度限制
**现象**: 调用注册接口返回 "Internal Server Error"
**错误信息**: `ValueError: password cannot be longer than 72 bytes`
**位置**: `/home/elder_photo_project/backend/utils/auth.py`
**分析**:
- bcrypt算法限制密码不能超过72字节
- 当前代码已添加 `password[:72]` 截取，但仍然报错
- 可能是passlib/bcrypt版本问题

**建议解决方案**:
1. 方案A: 更换密码加密方式（如SHA256）
2. 方案B: 降级bcrypt版本
3. 方案C: 检查并修复passlib配置

### 问题2: 浏览器无法访问API文档
**现象**: 无法打开 `http://36.112.162.239:8000/docs`
**可能原因**:
- 阿里云安全组未正确开放8000端口
- 服务未正常运行
- 网络问题

**验证方法**:
```bash
# 在服务器上测试
ps aux | grep uvicorn          # 检查服务是否运行
curl http://localhost:8000/     # 本地测试
```

### 问题3: 需要测试所有API接口
- 注册接口
- 登录接口
- 获取用户信息接口

---

## 关键配置信息

### 数据库连接
```
DB_HOST=localhost
DB_PORT=3306
DB_NAME=elder_photo_db
DB_USER=root
DB_PASSWORD=0109A80b
```

### 服务启动命令
```bash
cd /home/elder_photo_project/backend
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000

# 后台运行
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 &
```

### 依赖包
requirements.txt 已包含:
- fastapi
- uvicorn
- sqlalchemy
- pymysql
- python-jose
- passlib
- python-dotenv
- pydantic
- email-validator

---

## 下一步建议

1. **修复密码加密问题** - 优先解决注册接口报错
2. **测试API接口** - 使用curl或Postman测试所有接口
3. **创建前端页面** - 开发用户界面
4. **添加更多功能**:
   - 老人信息管理API
   - 照片上传API
   - AI处理接口

---

## 注意事项

1. **生产环境安全**: 当前使用root用户连接数据库，生产环境应创建专用数据库用户
2. **密码安全**: admin默认密码为admin123，请及时修改
3. **JWT密钥**: 当前使用默认密钥，生产环境应更换
4. **文件权限**: 确保uploads和static目录有写入权限

---

## 常用命令

```bash
# 进入项目目录
cd /home/elder_photo_project/backend

# 启动服务
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000

# 检查服务状态
ps aux | grep uvicorn

# 查看日志
cat nohup.out

# 数据库操作
mysql -u root -p
curl http://localhost:8000/api/register
```

---

**文档生成时间**: 2026-03-23
**最后更新**: 待修复密码加密问题后更新
