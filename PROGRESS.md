# 乡影相伴·情暖夕阳 — 后端开发文档

> 最后更新：2026-07-25

---

## 一、架构

```
客户端（浏览器/微信小程序/Postman）
         │
         ▼
     Nginx :80（反向代理 + 静态文件 /uploads/）
         │
         ▼
  FastAPI :8000（app.py）
         │
         ▼
  MariaDB（elder_photo_db）
```

- 公网入口：`http://60.205.13.93`
- Swagger 文档：`http://60.205.13.93/docs`
- GitHub：`https://github.com/Liqin071/elder-photo-project`

---

## 二、服务器连接信息

| 项目 | 值 |
|------|-----|
| 公网 IP | 60.205.13.93 |
| SSH 登录 | root@60.205.13.93 |
| Git SSH Key | ~/.ssh/id_ed25519（本地） |
| GitHub SSH | git@github.com:Liqin071/elder-photo-project.git |
| 工作目录 | /home/elder_photo_project/backend |
| Python 版本 | 3.11 |
| 数据库 | MariaDB |
| 数据库名 | elder_photo_db |
| 数据库用户 | root / 0109A80b |
| 宝塔面板 | https://60.205.122.68:38221/76b47d2f |
| 宝塔账号 | onwbk0nv / 7727f4b3 |

---

## 三、服务管理

```bash
# 重启后端
pkill -f uvicorn
cd /home/elder_photo_project/backend
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > /tmp/app.log 2>&1 &

# 重启 Nginx
systemctl reload nginx

# 清除 Python 缓存
find /home/elder_photo_project/backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# 查看日志
tail -20 /tmp/app.log

# 代码更新
cd /home/elder_photo_project && git pull

# 生成测试 token
TOKEN=$(python3 -c "import sys; sys.path.insert(0,'/home/elder_photo_project/backend'); from utils.auth import create_access_token; print(create_access_token(11,'volunteer'))")
```

---

## 四、API 清单（28 接口）

### 认证（6 个，其中 wx-login、users/me 系列为 API.md 外新增）
| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 1 | POST | /api/auth/register | 注册 |
| 2 | POST | /api/auth/login | 密码登录 |
| 3 | POST | /api/auth/wx-login | 微信登录（等 AppID/Secret） |
| 4 | GET | /api/users/me | 个人信息 |
| 5 | PUT | /api/users/me | 修改信息 |
| 6 | DELETE | /api/users/me | 删除账号 |

### 老人管理（5 个）
| 7 | GET | /api/elders | 列表（分页+搜索） |
| 8 | GET | /api/elders/:id | 详情 |
| 9 | POST | /api/elders | 新增 |
| 10 | PUT | /api/elders/:id | 修改 |
| 11 | DELETE | /api/elders/:id | 删除（有照片时阻止） |

### 照片（4 个）
| 12 | POST | /api/upload | 上传（multipart） |
| 13 | GET | /api/images | 列表（按老人/年月筛选） |
| 14 | PUT | /api/images/:id | 修改备注 |
| 15 | DELETE | /api/images/:id | 删除（文件一并删除） |

### 志愿者/家属（2 个）
| 16 | GET | /api/volunteer/elders | 我的老人列表 |
| 17 | GET | /api/family/parents | 家属视图（含统计） |

### 时间线（3 个）
| 18 | GET | /api/timeline | 分页列表（cursor 翻页） |
| 19 | GET | /api/timeline/years | 年份列表 |
| 20 | GET | /api/timeline/aggregation | 月份聚合统计 |

### 评论（4 个）
| 21 | GET | /api/comments | 列表 |
| 22 | POST | /api/comments | 文字评论 |
| 23 | POST | /api/comments/voice | 语音评论（multipart） |
| 24 | DELETE | /api/comments/:id | 删除（仅作者） |

### 通知（4 个，API.md 外新增 read-all）
| 25 | GET | /api/notifications | 列表 |
| 26 | GET | /api/notifications/unread-count | 未读数 |
| 27 | PUT | /api/notifications/:id/read | 标记已读 |
| 28 | PUT | /api/notifications/read-all | 全部已读 |

---

### API.md 外新增接口

| 接口 | 说明 |
|------|------|
| POST /api/auth/wx-login | 微信小程序登录，code 换 openid + JWT |
| GET /api/users/me | 查看个人信息 |
| PUT /api/users/me | 修改个人信息（name/avatar/phone） |
| DELETE /api/users/me | 注销账号 |
| PUT /api/notifications/read-all | 一键全部已读 |

---

## 五、错误码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1001 | 用户名或密码错误 |
| 1002 | 账户已被禁用 |
| 1004 | 未登录或 token 已过期 |
| 1005 | 无权限 |
| 1010 | 用户名已存在 |
| 1011 | 邀请码无效 |
| 1012 | 密码长度不足 |
| 2001 | 资源不存在 |
| 2002 | 有影像数据不能删 |
| 2003 | 无权限操作 |
| 3001 | 文件类型不支持 |
| 3002 | 超过 20MB |
| 3003 | 上传失败 |
| 3004 | 老人不存在 |
| 5000 | 服务器错误 |

---

## 六、Nginx 配置

配置文件：`/etc/nginx/conf.d/elder-photo.conf`

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 25m;

    location /uploads/ {
        alias /home/elder_photo_project/backend/uploads/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 七、前端联调指南

### 立即可以开始
1. 打开 `http://60.205.13.93/docs` 查看 Swagger 文档
2. 所有接口走 HTTP + 公网 IP 即可联调
3. 认证方式：`Authorization: Bearer <token>`
4. 统一响应格式：`{"code": 0, "message": "success", "data": {...}}`

### 微信小程序联调
1. 前端用 `wx.login()` 获取 code
2. 调 `POST /api/auth/wx-login` 换取 token
3. token 存 `wx.setStorageSync('token', token)`
4. 后续请求 header 带 `Authorization: Bearer <token>`
5. 图片上传用 `wx.uploadFile`，字段名见 Swagger
6. 语音评论用 `wx.getRecorderManager()` 录音后上传

---

## 八、域名与 HTTPS（待办）

### 为什么需要
- 微信小程序只允许 `https://` 请求
- SSL 证书只能绑定域名，不能绑定 IP
- 阿里云要求域名备案后才能对外提供 HTTPS

### 操作步骤
1. **买域名**：阿里云万网，几十元/年
2. **ICP 备案**：阿里云免费代办，约 15-20 个工作日
3. **申请 SSL 证书**：备案通过后阿里云控制台免费 DV 证书
4. **DNS 解析**：域名 A 记录指向 `60.205.13.93`
5. **配 Nginx HTTPS**：证书拿到后执行（我来配）

### 联调阶段不受影响
用 `http://60.205.13.93` 调 API 完全正常。域名和 HTTPS 是上线前最后一步。

---

## 九、微信小程序 AppID / Secret

需联系前端获取：
1. 前端注册小程序后在微信公众平台获取 AppID 和 AppSecret
2. 填入服务器 `.env`：
```
WX_APPID=wxXXXXXXXXXXXX
WX_SECRET=XXXXXXXXXXXXXXXXXXXXXXXXXXXX
```
3. 同时在公众平台「开发管理」→「服务器域名」中加入后端域名

---

## 十、已修复的坑

| 问题 | 解决 |
|------|------|
| SQLAlchemy Enum 与数据库 ENUM 不匹配 | 全部改为 VARCHAR/String |
| bcrypt 72 字节限制 | SHA256 预哈希 + bcrypt |
| 服务器和本地文件结构不一致 | 统一以 GitHub 为准 |
| 远程终端折行打断命令 | 短命令 + 逐行 echo + base64 |
| role.value 报 AttributeError | 改 role 为 String 后同步调用 |
| Swagger 无法渲染 /docs | 中间件跳过 /docs,/openapi,/redoc 路径 |
| Swagger 不显示 Authorize 按钮 | 自定义 OpenAPI schema 添加 BearerAuth |
| Swagger Authorize 不发送 token | 添加全局 security 声明 |
| API 返回字段 snake_case 与 API.md 不一致 | 全部改为 camelCase |
| Form 参数 alias 在 Swagger 不生效 | 直接用 camelCase 参数名 |

---

## 十一、标签历史

| Tag | 内容 |
|-----|------|
| v1.0-auth-elders-photos | 认证+老人+照片 |
| v1.1-photos-done | 照片完整 |
| v1.2-volunteer-family | 志愿者+家属 |
| v1.3-timeline | 时间线 |
| v1.4-comments-notifications | 评论+通知 |
| v1.5-all-fixes | 错误码/儿童/尺寸修复 |
| v1.6-camelCase-swagger | 字段命名对齐 API.md + Swagger 修复 |
