-- ============================================================
-- 009: organization → institution 机构目录统一
--   背景：2026-09-07 开发库手工完成合并（organization 26 行按名称并入
--   institution，org_type→kind 映射，registration_status='approved'，
--   原表移至 tech_transfer_backup.organization_original_20260907，
--   demand/achievement/user_profile 的 org FK 重指 institution）。
--   本迁移把该手术固化为幂等迁移：
--     1) 内容表 org FK 若仍指向旧表 → 先 DROP（重挂前数据可自由重映射）
--     2) public.organization 若仍存在 → 移入 tech_transfer_backup 归档
--     3) 按名称把旧组织行 get-or-create 进 institution，
--        并把 demand/achievement/user_profile 的 org_id 重定向到新 id
--     4) 重建内容表 org FK → institution（ON DELETE SET NULL）
--   开发库已处于目标态，重跑本迁移为 no-op。
--   新库从 001→009 顺序执行可复现相同结构。
-- 幂等：可重复执行；不 DELETE 任何数据
-- ============================================================

-- ── 1. 先 DROP 未指向 institution 的内容表 org FK ────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_dmd_org' AND conrelid = 'public.demand'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%institution%'
    ) THEN
        ALTER TABLE public.demand DROP CONSTRAINT fk_dmd_org;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ach_org' AND conrelid = 'public.achievement'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%institution%'
    ) THEN
        ALTER TABLE public.achievement DROP CONSTRAINT fk_ach_org;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_profile_org' AND conrelid = 'public.user_profile'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%institution%'
    ) THEN
        ALTER TABLE public.user_profile DROP CONSTRAINT fk_profile_org;
    END IF;
END $$;

-- ── 2. public.organization 移入备份 schema ────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'organization'
    ) THEN
        CREATE SCHEMA IF NOT EXISTS tech_transfer_backup;
        ALTER TABLE public.organization SET SCHEMA tech_transfer_backup;
        ALTER TABLE tech_transfer_backup.organization RENAME TO organization_original_20260907;
    END IF;
END $$;

-- ── 3. 旧组织行按名称 get-or-create 进 institution，重定向内容引用 ──
--    org_type: university/institute 原样保留，空值映射 enterprise（与手工合并一致）
DO $$
DECLARE
    r RECORD;
    new_id BIGINT;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'tech_transfer_backup'
          AND table_name  = 'organization_original_20260907'
    ) THEN
        FOR r IN
            SELECT id, org_name, intro, region, status,
                   COALESCE(NULLIF(org_type, ''), 'enterprise') AS kind
            FROM tech_transfer_backup.organization_original_20260907
        LOOP
            SELECT i.id INTO new_id
            FROM public.institution i WHERE i.name = r.org_name LIMIT 1;
            IF new_id IS NULL THEN
                INSERT INTO public.institution
                    (kind, name, intro, region, user_type, source_site, source_pk,
                     sort_order, status, registration_status, registration_applied_at)
                VALUES (r.kind, r.org_name, r.intro, r.region, r.kind, 'organization', r.id,
                        r.id, COALESCE(r.status, 'active'), 'approved', NOW())
                RETURNING id INTO new_id;
            END IF;
            UPDATE public.demand       SET org_id = new_id WHERE org_id = r.id;
            UPDATE public.achievement  SET org_id = new_id WHERE org_id = r.id;
            UPDATE public.user_profile SET org_id = new_id WHERE org_id = r.id;
        END LOOP;
    END IF;
END $$;

-- ── 4. 重建内容表 org FK → institution ────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_dmd_org' AND conrelid = 'public.demand'::regclass
    ) THEN
        ALTER TABLE public.demand
            ADD CONSTRAINT fk_dmd_org FOREIGN KEY (org_id)
            REFERENCES public.institution(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ach_org' AND conrelid = 'public.achievement'::regclass
    ) THEN
        ALTER TABLE public.achievement
            ADD CONSTRAINT fk_ach_org FOREIGN KEY (org_id)
            REFERENCES public.institution(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_profile_org' AND conrelid = 'public.user_profile'::regclass
    ) THEN
        ALTER TABLE public.user_profile
            ADD CONSTRAINT fk_profile_org FOREIGN KEY (org_id)
            REFERENCES public.institution(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;
