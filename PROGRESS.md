# 开发进度

> 最后更新：2026-07-20

## 服务器信息

- 公网 IP：36.112.162.239
- 工作目录：/home/elder_photo_project/backend
- 端口：8000
- 数据库：MariaDB / elder_photo_db / root / 0109A80b
- GitHub：Liqin071/elder-photo-project

## API 完成清单（27 接口 / 100%）

| # | 接口 | 路径 | 状态 |
|---|------|------|------|
| 1 | 注册 | POST /api/auth/register | ✅ |
| 2 | 登录 | POST /api/auth/login | ✅ |
| 3 | 微信登录 | POST /api/auth/wx-login | ✅ 等 AppID/Secret |
| 4 | 个人信息 | GET /api/users/me | ✅ |
| 5 | 修改信息 | PUT /api/users/me | ✅ |
| 6 | 删除账号 | DELETE /api/users/me | ✅ |
| 7 | 老人列表 | GET /api/elders | ✅ |
| 8 | 老人详情 | GET /api/elders/:id | ✅ |
| 9 | 新增老人 | POST /api/elders | ✅ |
| 10 | 更新老人 | PUT /api/elders/:id | ✅ |
| 11 | 删除老人 | DELETE /api/elders/:id | ✅ |
| 12 | 上传照片 | POST /api/upload | ✅ 自动缩略图 |
| 13 | 照片列表 | GET /api/images | ✅ |
| 14 | 修改照片 | PUT /api/images/:id | ✅ |
| 15 | 删除照片 | DELETE /api/images/:id | ✅ |
| 16 | 志愿者老人 | GET /api/volunteer/elders | ✅ |
| 17 | 家属老人 | GET /api/family/parents | ✅ |
| 18 | 时间线 | GET /api/timeline | ✅ |
| 19 | 时间线年份 | GET /api/timeline/years | ✅ |
| 20 | 时间线聚合 | GET /api/timeline/aggregation | ✅ |
| 21 | 评论列表 | GET /api/comments | ✅ |
| 22 | 创建评论 | POST /api/comments | ✅ |
| 23 | 语音评论 | POST /api/comments/voice | ✅ |
| 24 | 删除评论 | DELETE /api/comments/:id | ✅ |
| 25 | 通知列表 | GET /api/notifications | ✅ |
| 26 | 未读数量 | GET /api/notifications/unread-count | ✅ |
| 27 | 标记已读 | PUT /api/notifications/:id/read + /read-all | ✅ |

## 已修复的问题

- [x] 错误码统一（AppException + 精确业务码 1001/2002/3001 等）
- [x] 老人详情 childrenIds / childrenNames
- [x] 图片上传 fileSize / width / height
- [x] 缩略图生成（200x200）

## 待完成

- [ ] Nginx 反向代理 + HTTPS（进行中）
- [ ] 微信小程序 AppID / Secret 填入 .env
- [ ] 内容安全审核
- [ ] 接口限流

## 快速启动命令

```bash
# 服务管理
pkill -f uvicorn
cd /home/elder_photo_project/backend
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > /tmp/app.log 2>&1 &

# 清除缓存
find /home/elder_photo_project/backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# 查看日志
tail -20 /tmp/app.log

# 生成测试 token
TOKEN=$(python3 -c "import sys; sys.path.insert(0,'/home/elder_photo_project/backend'); from utils.auth import create_access_token; print(create_access_token(11,'volunteer'))")
```

## 标签历史

| Tag | 内容 |
|-----|------|
| v1.0-auth-elders-photos | 认证+老人+照片 |
| v1.1-photos-done | 照片完整 |
| v1.2-volunteer-family | 志愿者+家属 |
| v1.3-timeline | 时间线 |
| v1.4-comments-notifications | 评论+通知 |
| v1.5-all-fixes | 三问题修复 |
