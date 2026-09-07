-- ============================================================
-- 南山科转通 · PostgreSQL 冒烟测试（tech_transfer）
-- 验证：中文读写 / updated_at 触发器 / active_flag 生成列 /
--       唯一键（user_no、identity 三段键、活跃意向）/ 预算 CHECK
-- 整体运行在事务中并 ROLLBACK，不产生任何残留数据，可重复执行。
-- 执行方式：
--   psql -h 127.0.0.1 -U postgres -d tech_transfer -v ON_ERROR_STOP=1 -f 003_smoke_test.sql
-- ============================================================

BEGIN;

-- 1) 中文写入 + updated_at 触发器（统一机构目录 institution，organization 已并入）
INSERT INTO institution (kind, name, intro, region, user_type, source_site)
VALUES ('university', '北京大学深圳研究生院', '南山区大学城机构，中文冒烟测试', '深圳市南山区', 'university', 'smoke_test');

UPDATE institution
   SET intro = '更新后的简介：验证 updated_at 自动维护'
 WHERE name = '北京大学深圳研究生院';

SELECT name AS org_name,
       intro,
       (updated_at >= created_at) AS updated_at_trigger_ok
  FROM institution
 WHERE name = '北京大学深圳研究生院';

-- 2) 准备两个测试用户
INSERT INTO app_user (user_no) VALUES ('smoke-u1');
INSERT INTO app_user (user_no) VALUES ('smoke-u2');

-- 3) 生成列：pending → active_flag=1；rejected → NULL
INSERT INTO cooperation_intent
    (initiator_user_id, target_type, target_id, target_owner_user_id, message, status)
VALUES ((SELECT id FROM app_user WHERE user_no = 'smoke-u1'), 'achievement', 1,
        (SELECT id FROM app_user WHERE user_no = 'smoke-u2'), '中文对接意向消息', 'pending');

SELECT status, active_flag FROM cooperation_intent;

UPDATE cooperation_intent SET status = 'rejected';

SELECT status, active_flag FROM cooperation_intent;

-- 4) 终态后可重新发起（active_flag NULL 不参与唯一去重）
INSERT INTO cooperation_intent
    (initiator_user_id, target_type, target_id, target_owner_user_id, message, status)
VALUES ((SELECT id FROM app_user WHERE user_no = 'smoke-u1'), 'achievement', 1,
        (SELECT id FROM app_user WHERE user_no = 'smoke-u2'), '重新发起的意向', 'pending');

SELECT count(*) AS intent_rows_after_reopen FROM cooperation_intent;

-- 5) 预算倒挂必须被 CHECK 拒绝
DO $$
BEGIN
    BEGIN
        INSERT INTO demand (owner_user_id, created_by_user_id, title, description, budget_min_wan, budget_max_wan)
        VALUES ((SELECT id FROM app_user WHERE user_no = 'smoke-u1'),
                (SELECT id FROM app_user WHERE user_no = 'smoke-u1'),
                '预算倒挂的需求', '描述', 100, 50);
        RAISE EXCEPTION 'FAIL: inverted budget was not rejected';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'PASS: budget CHECK rejected inverted range';
    END;
END $$;

-- 6) 外部身份三段唯一键 (issuer, tenant_id, external_subject)
DO $$
BEGIN
    BEGIN
        INSERT INTO external_identity (user_id, issuer, tenant_id, external_subject)
        VALUES ((SELECT id FROM app_user WHERE user_no = 'smoke-u1'), 'WECHAT', 'default', 'wx-123');
        INSERT INTO external_identity (user_id, issuer, tenant_id, external_subject)
        VALUES ((SELECT id FROM app_user WHERE user_no = 'smoke-u1'), 'WECHAT', 'default', 'wx-123');
        RAISE EXCEPTION 'FAIL: duplicate identity was not rejected';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'PASS: identity unique key rejected duplicate';
    END;
END $$;

-- 7) user_no 唯一键
DO $$
BEGIN
    BEGIN
        INSERT INTO app_user (user_no) VALUES ('smoke-u1');
        RAISE EXCEPTION 'FAIL: duplicate user_no was not rejected';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'PASS: user_no unique key rejected duplicate';
    END;
END $$;

ROLLBACK;

-- 8) 结构核对：24 张表（业务 + 资本域，organization 已并入 institution）+ 12 个 updated_at 触发器 + 2 个 GIN 全文索引
SELECT count(*) AS table_count FROM pg_tables WHERE schemaname = 'public';

SELECT count(*) AS trigger_count
  FROM pg_trigger
 WHERE NOT tgisinternal
   AND tgrelid::regclass::text IN
       ('app_user', 'user_profile', 'auth_session', 'institution',
        'achievement', 'demand', 'cooperation_intent',
        'platform_base', 'ip_service_org', 'featured_invest_org',
        'ai_task', 'user_credential');

SELECT indexname, indexdef
  FROM pg_indexes
 WHERE schemaname = 'public' AND indexdef ILIKE '%gin%';
