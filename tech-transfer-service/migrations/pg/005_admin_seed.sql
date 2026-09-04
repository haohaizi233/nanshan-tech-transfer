-- ========================================================
-- 005_admin_seed —— admin 角色种子（P0-3）
--
-- 设计约定（docs/architecture/04-backend-domain-design.md §5.4）：
--   admin 模块无自有表，角色判定唯一入口是 user_role（06 §授权 RBAC）。
--   一期 admin 由种子数据授予；本地预置 dev-user-001（user_id=1）为 admin 便于联调。
-- 幂等可重跑。
-- ========================================================

INSERT INTO public.user_role (user_id, role_code)
VALUES (1, 'admin')
ON CONFLICT (user_id, role_code) DO NOTHING;
