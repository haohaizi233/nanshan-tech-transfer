-- ============================================================
-- 014: lrm 分支合并遗留数据修复 —— 机构管理员双模型归一
--
-- 背景：lrm 分支的 backend_identity 以 user_role='org_admin'
--       + user_profile.org_id（institution.registration_status='approved'）
--       判定机构管理员；合并后的 master 采用 organization_membership
--       实时查库模型。两套模型切换期间产生的存量数据只有
--       user_role.org_admin（无 membership 行），导致这类账号
--       能通过 Vue 后台登录门禁（_get_roles 读 user_role），
--       但所有 /admin/* 内容接口被 backend_identity 判 403
--       （TT_ADMIN_40301 非管理员）。
--
-- 修复：
--   1. 按 lrm 语义（org_admin 角色 + profile.org_id 指向活跃且
--      已审批机构）回填 organization_membership(role='admin', active)；
--   2. 回填成功后删除 user_role 中冗余的 org_admin 行
--      （机构权限统一由 membership 实时判定，不再落 user_role；
--      仅在 membership 已存在时删除，避免误撤无 membership 用户的权限）。
--
-- 幂等：可重复执行。
-- ============================================================

BEGIN;

-- ── 1. 回填 membership ──────────────────────────────────────
INSERT INTO organization_membership
    (org_id, user_id, role, status, verified_by_user_id, verified_at)
SELECT p.org_id, ur.user_id, 'admin', 'active', NULL, CURRENT_TIMESTAMP
FROM user_role ur
JOIN user_profile p ON p.user_id = ur.user_id
JOIN institution i ON i.id = p.org_id
WHERE ur.role_code = 'org_admin'
  AND i.status = 'active'
  AND i.registration_status = 'approved'
  AND NOT EXISTS (
      SELECT 1 FROM organization_membership m
      WHERE m.user_id = ur.user_id
        AND m.org_id = p.org_id
        AND m.role = 'admin'
        AND m.status = 'active'
  );

-- ── 2. 清理 user_role 冗余 org_admin（保留无 membership 兜底）──
DELETE FROM user_role ur
WHERE ur.role_code = 'org_admin'
  AND EXISTS (
      SELECT 1 FROM organization_membership m
      WHERE m.user_id = ur.user_id
        AND m.role = 'admin'
        AND m.status = 'active'
  );

COMMIT;
