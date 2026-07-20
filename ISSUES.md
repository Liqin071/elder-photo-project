# 待修复问题清单

## 问题 1：错误码不一致（高优先级）

| 场景 | API.md 规定 | 当前实际 | 涉及文件 |
|------|------------|---------|---------|
| 用户名或密码错误 | 1001 | 1004 | `app.py` + `api/auth.py` |
| 账号被禁用 | 1002 | 未实现 | `api/auth.py` |
| 邀请码无效 | 1011 | 未实现 | `api/auth.py` |
| 有影像数据不能删 | 2002 | 1010 | `app.py` + `api/elders.py` |
| 无权限操作 | 2003 | 1005 | `app.py` |
| 文件类型不支持 | 3001 | 1003 | `app.py` + `api/photos.py` |
| 超过 20MB | 3002 | 5000 | `app.py` + `api/photos.py` |
| 上传失败 | 3003 | 5000 | `app.py` |
| 老人不存在 | 3004 | 2001 | `app.py` + `api/photos.py` |

修复方案：重构 `app.py` 的错误映射机制，从简单的 HTTP→业务码映射改为支持各接口自定义业务码。

## 问题 2：老人详情缺少 childrenIds / childrenNames 字段

API: `GET /api/elders/:id`
缺失字段：`childrenIds`（数组）、`childrenNames`（数组）

修复方案：建立老人与子女用户的双向关联。需要新建关联表 `elderly_children`，并修改老人详情接口。

## 问题 3：图片列表缺少 fileSize / width / height

API: `GET /api/images`
缺失字段：`fileSize`、`width`、`height`（当前返回 null）

修复方案：上传时用 Pillow 读取图片宽高，存入数据库。需要新增数据库字段并在模型中添加。

## 问题 4：微信小程序适配（待办）

- [ ] 申请 SSL 证书 + 配置 Nginx HTTPS
- [ ] 域名备案 + 绑定
- [ ] 新增微信登录接口 `POST /api/auth/wx-login`
- [ ] 上传时自动生成缩略图
- [ ] Nginx 直接 serve `/uploads/`（替换 FastAPI StaticFiles）
- [ ] 内容安全审核接入
- [ ] 接口限流
