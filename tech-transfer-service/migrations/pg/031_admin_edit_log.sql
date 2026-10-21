-- 031: 管理员修改内容的字段级变更日志（发布者可见变更对比）
-- 业务背景：后台管理员修改了发布者的需求/成果后，发布者打开详情页应能看到
--          「哪些字段被修改了、修改前后各是什么」。
-- 写入约定：管理端 PATCH 需求/成果时与业务写同事务落库，一行一个字段；
--          同一次保存的行共享 batch_id（发布端按批次分组展示）。
-- 已读约定：发布者在详情页展开变更对比后标记 read_at；read_at IS NULL = 未读。

CREATE SEQUENCE IF NOT EXISTS admin_edit_log_batch_seq;

CREATE TABLE IF NOT EXISTS admin_edit_log (
    id                BIGSERIAL PRIMARY KEY,
    batch_id          BIGINT NOT NULL,
    target_type       VARCHAR(16) NOT NULL,
    target_id         BIGINT NOT NULL,
    field_name        VARCHAR(64) NOT NULL,
    field_label       VARCHAR(64) NOT NULL,
    change_kind       VARCHAR(16) NOT NULL DEFAULT 'updated',
    old_value         TEXT,
    new_value         TEXT,
    operator_user_id  BIGINT,
    operator_user_no  VARCHAR(32),
    operator_name     VARCHAR(64),
    read_at           TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_admin_edit_log_target_type CHECK (target_type IN ('demand', 'achievement')),
    CONSTRAINT ck_admin_edit_log_change_kind CHECK (change_kind IN ('created', 'updated'))
);

-- 发布者详情页按目标拉取变更（最新在前）
CREATE INDEX IF NOT EXISTS idx_admin_edit_log_target
    ON admin_edit_log (target_type, target_id, id DESC);

-- 未读变更计数（详情页顶部提示条）
CREATE INDEX IF NOT EXISTS idx_admin_edit_log_unread
    ON admin_edit_log (target_type, target_id)
    WHERE read_at IS NULL;
