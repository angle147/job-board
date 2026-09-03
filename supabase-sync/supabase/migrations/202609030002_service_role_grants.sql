-- 新项目关闭“自动暴露新表”后，需要显式授权后端专用角色。
-- anon/authenticated 仍无任何直连权限，网页只能经过 Edge Function。
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
