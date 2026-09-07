-- ============================================================
-- 008: 管理员代发布 + 平台协助对接（Assisted Cooperation）
--   1) achievement / demand 新增 created_by_user_id（录入人，≠ 业务归属人 owner_user_id）
--      —— 历史数据 backfill：created_by = owner（全覆盖 → SET NOT NULL）
--   2) achievement / demand 的 owner_user_id 改为可空
--      —— NULL = 真实机构尚无平台绑定账号（管理员代录入）
--      —— owner FK 由 ON DELETE CASCADE 改为 ON DELETE SET NULL：
--         平台用户删除不应级联删除公开需求/成果（项目以软删为主，FK 语义仍需正确）
--   3) cooperation_intent 改造：
--      —— target_owner_user_id 改为可空（NULL = 目标机构未绑定平台账号）
--      —— 新增 handling_mode（direct/assisted，服务端按目标 owner 自动计算）
--      —— 新增 assist_status（平台运营处理阶段，与主状态 status 分离）
--      —— 新增 accept_mode（self / platform_assisted，解释 accepted 由谁确认）
--      —— 新增 handled_by_user_id（负责该协助意向的运营人员）
--      —— 新增 target_org_id（目标机构，协助流程的联系对象）
--      —— 新增 initiator_contact_snapshot（申请方联系方式快照，服务端生成）
--      —— 新增 assist_note（运营内部记录，不对普通用户返回）
--      —— 新增 contact_share_consent_at（联系方式共享同意时间）
--   4) 主状态机（pending/accepted/rejected/confirmed/cancelled/completed）不变
--      uk_coop_active 唯一约束不变
-- 幂等：可重复执行
-- 数据保护：迁移前后 achievement=225 / demand=39 / cooperation_intent=7 行数一致，不 DELETE 任何数据
-- ============================================================

-- ── 1. achievement.created_by_user_id ────────────────────────
ALTER TABLE public.achievement
    ADD COLUMN IF NOT EXISTS created_by_user_id BIGINT;
UPDATE public.achievement SET created_by_user_id = owner_user_id WHERE created_by_user_id IS NULL;
ALTER TABLE public.achievement ALTER COLUMN created_by_user_id SET NOT NULL;
COMMENT ON COLUMN public.achievement.created_by_user_id IS
    '录入人（实际执行录入操作的平台用户）；管理员代录入时=admin，与业务归属人 owner_user_id 区分';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ach_created_by' AND conrelid = 'public.achievement'::regclass
    ) THEN
        ALTER TABLE public.achievement
            ADD CONSTRAINT fk_ach_created_by FOREIGN KEY (created_by_user_id)
            REFERENCES public.app_user(id) ON UPDATE CASCADE;
        -- 审计保护：录入人被硬删时拒绝（项目以软删为主）
    END IF;
END $$;

-- ── 2. demand.created_by_user_id ─────────────────────────────
ALTER TABLE public.demand
    ADD COLUMN IF NOT EXISTS created_by_user_id BIGINT;
UPDATE public.demand SET created_by_user_id = owner_user_id WHERE created_by_user_id IS NULL;
ALTER TABLE public.demand ALTER COLUMN created_by_user_id SET NOT NULL;
COMMENT ON COLUMN public.demand.created_by_user_id IS
    '录入人（实际执行录入操作的平台用户）；管理员代录入时=admin，与业务归属人 owner_user_id 区分';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_dmd_created_by' AND conrelid = 'public.demand'::regclass
    ) THEN
        ALTER TABLE public.demand
            ADD CONSTRAINT fk_dmd_created_by FOREIGN KEY (created_by_user_id)
            REFERENCES public.app_user(id) ON UPDATE CASCADE;
    END IF;
END $$;

-- ── 3. achievement.owner_user_id 可空 + FK 改 SET NULL ────────
ALTER TABLE public.achievement ALTER COLUMN owner_user_id DROP NOT NULL;
COMMENT ON COLUMN public.achievement.owner_user_id IS
    '业务归属人平台账号；NULL = 真实机构尚无平台绑定账号（管理员代录入，进入平台协助对接）';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ach_owner' AND conrelid = 'public.achievement'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%ON DELETE SET NULL%'
    ) THEN
        ALTER TABLE public.achievement DROP CONSTRAINT fk_ach_owner;
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ach_owner' AND conrelid = 'public.achievement'::regclass
    ) THEN
        ALTER TABLE public.achievement
            ADD CONSTRAINT fk_ach_owner FOREIGN KEY (owner_user_id)
            REFERENCES public.app_user(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;

-- ── 4. demand.owner_user_id 可空 + FK 改 SET NULL ─────────────
ALTER TABLE public.demand ALTER COLUMN owner_user_id DROP NOT NULL;
COMMENT ON COLUMN public.demand.owner_user_id IS
    '业务归属人平台账号；NULL = 真实机构尚无平台绑定账号（管理员代录入，进入平台协助对接）';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_dmd_owner' AND conrelid = 'public.demand'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%ON DELETE SET NULL%'
    ) THEN
        ALTER TABLE public.demand DROP CONSTRAINT fk_dmd_owner;
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_dmd_owner' AND conrelid = 'public.demand'::regclass
    ) THEN
        ALTER TABLE public.demand
            ADD CONSTRAINT fk_dmd_owner FOREIGN KEY (owner_user_id)
            REFERENCES public.app_user(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;

-- ── 5. cooperation_intent：target_owner 可空 + FK 改 SET NULL ─
ALTER TABLE public.cooperation_intent ALTER COLUMN target_owner_user_id DROP NOT NULL;
COMMENT ON COLUMN public.cooperation_intent.target_owner_user_id IS
    '被发起方（冗余自目标表）；NULL = 目标机构尚未绑定平台账号（assisted，由平台运营线下联系）';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_coop_owner' AND conrelid = 'public.cooperation_intent'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%ON DELETE SET NULL%'
    ) THEN
        ALTER TABLE public.cooperation_intent DROP CONSTRAINT fk_coop_owner;
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_coop_owner' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT fk_coop_owner FOREIGN KEY (target_owner_user_id)
            REFERENCES public.app_user(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;

-- ── 6. cooperation_intent：assisted 域新列 ────────────────────
ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS handling_mode VARCHAR(16) NOT NULL DEFAULT 'direct';
COMMENT ON COLUMN public.cooperation_intent.handling_mode IS
    '处理模式：direct=目标方已有平台账号（原流程）；assisted=目标机构未绑定账号，平台协助对接；创建时服务端按目标 owner 自动计算，不信任前端传值';

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS assist_status VARCHAR(32) DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.assist_status IS
    '平台运营处理阶段（仅 assisted）：queued/contacting/waiting_reply/target_agreed/target_rejected/unreachable；与主状态 status 分离，unreachable 仍属 status=pending';

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS accept_mode VARCHAR(32) DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.accept_mode IS
    '接受方式：self=目标方自己点击接受；platform_assisted=Admin 根据线下机构确认代操作；NULL=尚未 accepted';

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS handled_by_user_id BIGINT DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.handled_by_user_id IS '负责该 Assisted Cooperation 的运营人员';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_coop_handled_by' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT fk_coop_handled_by FOREIGN KEY (handled_by_user_id)
            REFERENCES public.app_user(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS target_org_id BIGINT DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.target_org_id IS
    '目标机构（协助流程的联系对象，冗余自目标表 org_id；目标方无账号时后台据此知道联系谁）';

DO $$
BEGIN
    -- 自愈：2026-09-07 organization 并入 institution 后，历史约束可能仍指向
    -- 旧表（被移动为 tech_transfer_backup.organization_original_20260907），删除重建
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_coop_target_org' AND conrelid = 'public.cooperation_intent'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%institution%'
    ) THEN
        ALTER TABLE public.cooperation_intent DROP CONSTRAINT fk_coop_target_org;
    END IF;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_coop_target_org' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT fk_coop_target_org FOREIGN KEY (target_org_id)
            REFERENCES public.institution(id) ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS initiator_contact_snapshot JSONB DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.initiator_contact_snapshot IS
    '申请方联系方式快照（创建时服务端按当时 profile 生成，防止事后改资料导致历史申请联系人漂移）';

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS assist_note TEXT DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.assist_note IS
    '运营内部记录（仅 Admin 可见，普通用户 API 不返回）';

ALTER TABLE public.cooperation_intent
    ADD COLUMN IF NOT EXISTS contact_share_consent_at TIMESTAMPTZ DEFAULT NULL;
COMMENT ON COLUMN public.cooperation_intent.contact_share_consent_at IS
    '申请方同意平台将联系方式提供给目标机构的时间（提交申请即同意）';

-- ── 7. CHECK 约束（枚举 + direct/assisted 一致性） ────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_coop_handling_mode' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT chk_coop_handling_mode CHECK (handling_mode IN ('direct', 'assisted'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_coop_handling_owner' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT chk_coop_handling_owner CHECK (
                (handling_mode = 'direct' AND target_owner_user_id IS NOT NULL)
                OR (handling_mode = 'assisted' AND target_owner_user_id IS NULL)
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_coop_assist_status' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT chk_coop_assist_status CHECK (
                assist_status IS NULL
                OR assist_status IN ('queued', 'contacting', 'waiting_reply', 'target_agreed', 'target_rejected', 'unreachable')
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_coop_assist_pair' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT chk_coop_assist_pair CHECK (
                (handling_mode = 'assisted' AND assist_status IS NOT NULL)
                OR (handling_mode = 'direct' AND assist_status IS NULL)
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_coop_accept_mode' AND conrelid = 'public.cooperation_intent'::regclass
    ) THEN
        ALTER TABLE public.cooperation_intent
            ADD CONSTRAINT chk_coop_accept_mode CHECK (
                accept_mode IS NULL OR accept_mode IN ('self', 'platform_assisted')
            );
    END IF;
END $$;

-- ── 8. backfill：历史 accepted 均为目标方自行接受 ────────────
UPDATE public.cooperation_intent
SET accept_mode = 'self'
WHERE accept_mode IS NULL
  AND status IN ('accepted', 'confirmed', 'completed');

-- ── 9. 协助队列筛选索引（Admin 列表 handlingMode/assistStatus） ─
CREATE INDEX IF NOT EXISTS idx_coop_assist
    ON public.cooperation_intent (handling_mode, assist_status);
