# 待修复问题清单

## ~~问题 1：错误码不一致~~ ✅ 已修复 (2026-07-20)

引入 `utils/exceptions.py` 定义 `AppException`，每个接口使用精确业务错误码。验证通过。

## ~~问题 2：老人详情缺少 childrenIds / childrenNames~~ ✅ 已修复 (2026-07-20)

新建 `elderly_children` 关联表，Elderly 模型添加 `children` relationship。验证通过。

## ~~问题 3：图片列表缺少 fileSize / width / height~~ ✅ 已修复 (2026-07-20)

Photo 模型新增 `file_size`/`width`/`height` 字段，上传时用 Pillow 读取宽高。验证通过（100x80）。

## 问题 4：微信小程序适配（待办）

- [ ] 申请 SSL 证书 + 配置 Nginx HTTPS
- [ ] 域名备案 + 绑定
- [ ] 新增微信登录接口 `POST /api/auth/wx-login`
- [ ] 上传时自动生成缩略图
- [ ] Nginx 直接 serve `/uploads/`（替换 FastAPI StaticFiles）
- [ ] 内容安全审核接入
- [ ] 接口限流
