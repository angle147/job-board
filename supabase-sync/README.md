# Supabase 同步后端

该目录承载招聘看板的 Supabase Edge Function 与数据库迁移。公开网页只连接 Edge Function，不能直接读写数据库。

- `supabase/migrations/202609030001_initial.sql`：私有表、索引与 RLS。
- `supabase/functions/job-board-sync/index.ts`：兼容现有 `sync-client.js` 的 `/api/*` 接口。
- `supabase/config.toml`：关闭 Supabase JWT 校验，因为应用使用自己的 30 天会话令牌。

部署秘密（只在 Supabase 项目中配置，不进入 Git）：`ADMIN_USERNAME`、`ADMIN_PASSWORD`、`INITIAL_INVITE_CODE`、`RATE_LIMIT_SECRET`、`ALLOWED_ORIGINS`。
