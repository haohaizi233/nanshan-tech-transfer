-- 交互域建表：收藏 + 对接意向 + 对接事件
-- Architecture source: 05-data-model-design.md §6.1/§6.2/§6.3
-- 执行方式同 001_identity_domain.sql（独立脚本 run_migration.py）

USE `tech_transfer`;

-- 1. favorite —— 收藏（无软删：取消即物理 DELETE，审计走 audit_log）
CREATE TABLE IF NOT EXISTS `favorite` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     BIGINT UNSIGNED NOT NULL,
  `target_type` VARCHAR(16)     NOT NULL COMMENT 'achievement / demand',
  `target_id`   BIGINT UNSIGNED NOT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_fav` (`user_id`, `target_type`, `target_id`),
  KEY `idx_fav_target` (`target_type`, `target_id`),
  CONSTRAINT `fk_fav_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. cooperation_intent —— 对接意向
-- uk_coop_active 说明：05 文档原设计 (initiator, target_type, target_id, status)
-- 在"终态后重新发起、再次终态"场景会产生同键重复（MySQL 无条件唯一索引）。
-- 改用生成列 active_flag：活跃状态(pending/accepted/confirmed)=1，终态=NULL；
-- MySQL 唯一索引对 NULL 不去重 → 语义即文档真实意图"同一发起人对同一目标
-- 同时只能有一条活跃意向，终态记录可重复"。活跃重复发起另由服务端校验兜底。
CREATE TABLE IF NOT EXISTS `cooperation_intent` (
  `id`                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `initiator_user_id`    BIGINT UNSIGNED NOT NULL COMMENT '发起人（服务端注入）',
  `target_type`          VARCHAR(16)     NOT NULL COMMENT 'achievement / demand',
  `target_id`            BIGINT UNSIGNED NOT NULL,
  `target_owner_user_id` BIGINT UNSIGNED NOT NULL COMMENT '被发起方（冗余自目标表）',
  `message`              VARCHAR(1000)   DEFAULT NULL,
  `status`               VARCHAR(16)     NOT NULL DEFAULT 'pending'
                         COMMENT 'pending/accepted/rejected/confirmed/completed/cancelled',
  `active_flag`          TINYINT GENERATED ALWAYS AS
                         (IF(`status` IN ('pending','accepted','confirmed'), 1, NULL)) STORED,
  `version`              INT             NOT NULL DEFAULT 1,
  `accepted_at`          DATETIME        DEFAULT NULL,
  `confirmed_at`         DATETIME        DEFAULT NULL,
  `completed_at`         DATETIME        DEFAULT NULL,
  `closed_at`            DATETIME        DEFAULT NULL COMMENT '终态（rejected/cancelled）关闭时间',
  `created_at`           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coop_active` (`initiator_user_id`, `target_type`, `target_id`, `active_flag`),
  KEY `idx_coop_target_owner` (`target_owner_user_id`, `status`),
  KEY `idx_coop_initiator` (`initiator_user_id`, `status`),
  KEY `idx_coop_target` (`target_type`, `target_id`, `status`),
  CONSTRAINT `fk_coop_initiator` FOREIGN KEY (`initiator_user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_coop_owner` FOREIGN KEY (`target_owner_user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. cooperation_event —— 对接事件（状态事实源）
CREATE TABLE IF NOT EXISTS `cooperation_event` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `intent_id`         BIGINT UNSIGNED NOT NULL,
  `event_type`        VARCHAR(32)     NOT NULL
                      COMMENT 'created/accepted/rejected/confirmed/cancelled/completed/auto_rejected',
  `from_status`       VARCHAR(16)     DEFAULT NULL,
  `to_status`         VARCHAR(16)     NOT NULL,
  `operator_user_id`  BIGINT UNSIGNED NOT NULL COMMENT '取自服务端 IdentityContext',
  `operator_role`     VARCHAR(16)     NOT NULL COMMENT 'initiator/target_owner/admin/system',
  `remark`            VARCHAR(500)   DEFAULT NULL,
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_coop_event_intent` (`intent_id`, `id`),
  CONSTRAINT `fk_coop_event_intent` FOREIGN KEY (`intent_id`)
    REFERENCES `cooperation_intent`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
