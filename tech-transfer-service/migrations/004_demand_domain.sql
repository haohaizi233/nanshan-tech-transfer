-- 需求域建表
-- Architecture source: 05-data-model-design.md §5.1 §5.2
-- 执行方式同 001_identity_domain.sql（additive only，全部 IF NOT EXISTS，可重复执行）
-- demand_attachment 延后：依赖 file 模块 file_object 表（file 模块未实现前无法建 FK）

USE `tech_transfer`;

-- 1. demand_category —— 需求分类（字典表）
CREATE TABLE IF NOT EXISTS `demand_category` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code`       VARCHAR(32)     NOT NULL,
  `name`       VARCHAR(64)     NOT NULL,
  `sort_order` INT             NOT NULL DEFAULT 0,
  `enabled`    TINYINT(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dmdcat_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. demand_tag —— 需求标签（字典表）
CREATE TABLE IF NOT EXISTS `demand_tag` (
  `id`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code`    VARCHAR(64)     NOT NULL,
  `name`    VARCHAR(64)     NOT NULL,
  `enabled` TINYINT(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dmdtag_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. demand —— 需求主表
-- 状态机（06 §5.2）：draft → pending_review → published → matched → closed
--                  draft/rejected → pending_review（重新提交）
--                  published → cancelled / closed（未匹配直接关闭）
CREATE TABLE IF NOT EXISTS `demand` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `owner_user_id`      BIGINT UNSIGNED NOT NULL,
  `org_id`             BIGINT UNSIGNED DEFAULT NULL,
  `title`              VARCHAR(200)    NOT NULL,
  `category_id`        BIGINT UNSIGNED DEFAULT NULL,
  `description`        TEXT            NOT NULL,
  `region`             VARCHAR(64)     DEFAULT NULL,
  `coop_mode`          JSON            DEFAULT NULL,
  `budget_min_wan`     DECIMAL(14,2)  DEFAULT NULL,
  `budget_max_wan`     DECIMAL(14,2)  DEFAULT NULL,
  `budget_negotiable`  TINYINT(1)      NOT NULL DEFAULT 0,
  `expect_deadline`    DATE            DEFAULT NULL,
  `deadline_desc`      VARCHAR(128)    DEFAULT NULL,
  `contact_name`       VARCHAR(64)     DEFAULT NULL,
  `contact_title`      VARCHAR(64)     DEFAULT NULL,
  `contact_phone`      VARCHAR(32)     DEFAULT NULL,
  `contact_email`      VARCHAR(128)    DEFAULT NULL,
  `contact_wechat`     VARCHAR(64)     DEFAULT NULL,
  `status`             VARCHAR(16)     NOT NULL DEFAULT 'draft',
  `reject_reason`      VARCHAR(500)    DEFAULT NULL,
  `version`            INT             NOT NULL DEFAULT 1,
  `published_at`       DATETIME        DEFAULT NULL,
  `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at`         DATETIME        DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_dmd_status_published` (`status`, `published_at`),
  KEY `idx_dmd_owner` (`owner_user_id`, `status`),
  KEY `idx_dmd_org` (`org_id`),
  KEY `idx_dmd_title` (`title`),
  KEY `idx_dmd_category` (`category_id`),
  FULLTEXT KEY `ft_dmd_text` (`title`, `description`),
  CONSTRAINT `fk_dmd_owner` FOREIGN KEY (`owner_user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_dmd_org` FOREIGN KEY (`org_id`)
    REFERENCES `organization`(`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_dmd_cat` FOREIGN KEY (`category_id`)
    REFERENCES `demand_category`(`id`) ON DELETE SET NULL,
  CONSTRAINT `chk_dmd_budget` CHECK (`budget_min_wan` IS NULL OR `budget_max_wan` IS NULL OR `budget_min_wan` <= `budget_max_wan`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. demand_tag_relation —— 需求-标签关联
CREATE TABLE IF NOT EXISTS `demand_tag_relation` (
  `id`        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `demand_id` BIGINT UNSIGNED NOT NULL,
  `tag_id`    BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dmd_tag` (`demand_id`, `tag_id`),
  KEY `idx_dmdtr_tag` (`tag_id`),
  CONSTRAINT `fk_dmdtr_demand` FOREIGN KEY (`demand_id`)
    REFERENCES `demand`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_dmdtr_tag` FOREIGN KEY (`tag_id`)
    REFERENCES `demand_tag`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
