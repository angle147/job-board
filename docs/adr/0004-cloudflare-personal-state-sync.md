# 使用 Cloudflare 承载班级成员个人状态同步

状态：已被 ADR-0005 取代。Cloudflare Worker 与 D1 保留，但未接入公开看板。

公开岗位看板继续托管于 GitHub Pages，账号认证、个人状态同步和管理员人数统计由 Cloudflare Workers 与 D1 承担，第一版直接使用 Cloudflare 提供的 `workers.dev` 服务地址。相比让本机提供服务或把成员状态提交到 GitHub，这一方案不要求维护者电脑持续开机，不暴露个人状态到公开仓库，并能以较低运维负担支持班级规模的多账号隔离与跨设备同步；未来绑定自定义域名时无需迁移账号数据库。

2026-09-03 部署验证发现当前网络访问 `workers.dev` 时出现 TLS 握手错误，Edge 实测为 `ERR_SSL_VERSION_OR_CIPHER_MISMATCH`。Worker 与 D1 已创建，但在取得可稳定访问的自定义域名或迁移至可达后端前，不将该地址接入公开看板。
