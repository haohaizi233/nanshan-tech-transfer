-- 003_audit_log.sql — 审计日志表
-- Architecture source: 05-data-model-design.md §audit_log
-- Phase A: additive migration, no existing data affected

CREATE TABLE IF NOT EXISTS `audit_log` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `actor_user_id` BIGINT UNSIGNED NULL COMMENT '操作者用户ID（系统操作为 NULL）',
    `actor_user_no` VARCHAR(32) NULL COMMENT '操作者用户编号（冗余，便于查询）',
    `action` VARCHAR(64) NOT NULL COMMENT '操作类型，如 create_achievement / approve_demand',
    `resource_type` VARCHAR(32) NOT NULL COMMENT '资源类型，如 achievement / demand / cooperation',
    `resource_id` VARCHAR(64) NULL COMMENT '资源ID',
    `details` JSON NULL COMMENT '操作详情快照',
    `ip_address` VARCHAR(45) NULL COMMENT '操作者 IP',
    `request_id` VARCHAR(64) NULL COMMENT '请求ID，关联 X-Request-Id',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_audit_actor` (`actor_user_id`),
    INDEX `idx_audit_resource` (`resource_type`, `resource_id`),
    INDEX `idx_audit_created` (`created_at`),
    CONSTRAINT `fk_audit_actor` FOREIGN KEY (`actor_user_id`) REFERENCES `app_user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志，只 INSERT 不 UPDATE/DELETE';
