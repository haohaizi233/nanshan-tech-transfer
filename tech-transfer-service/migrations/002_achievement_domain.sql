-- 成果域建表
-- 执行方式同 001_identity_domain.sql

USE `tech_transfer`;

-- 1. organization —— 来源机构（最小化建表，后续扩展）
CREATE TABLE IF NOT EXISTS `organization` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `org_name`   VARCHAR(128)    NOT NULL,
  `org_type`   VARCHAR(32)     DEFAULT NULL,
  `intro`      TEXT            DEFAULT NULL,
  `region`     VARCHAR(64)     DEFAULT NULL,
  `status`     VARCHAR(16)     NOT NULL DEFAULT 'active',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` DATETIME        DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_org_name_active` (`org_name`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. achievement_category —— 成果分类（字典表）
CREATE TABLE IF NOT EXISTS `achievement_category` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code`       VARCHAR(32)     NOT NULL,
  `name`       VARCHAR(64)     NOT NULL,
  `sort_order` INT             NOT NULL DEFAULT 0,
  `enabled`    TINYINT(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_cat_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. achievement —— 成果主表
CREATE TABLE IF NOT EXISTS `achievement` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `owner_user_id`     BIGINT UNSIGNED NOT NULL,
  `org_id`            BIGINT UNSIGNED DEFAULT NULL,
  `source_org_name`   VARCHAR(128)    DEFAULT NULL,
  `title`             VARCHAR(200)    NOT NULL,
  `category_id`       BIGINT UNSIGNED DEFAULT NULL,
  `tech_intro`        TEXT            DEFAULT NULL,
  `tech_route`        TEXT            DEFAULT NULL,
  `maturity_level`    VARCHAR(16)     NOT NULL DEFAULT '02_lab',
  `maturity_desc`     VARCHAR(255)    DEFAULT NULL,
  `application_fields` JSON          DEFAULT NULL,
  `innovation_points`  JSON          DEFAULT NULL,
  `pricing_mode`      VARCHAR(32)    NOT NULL DEFAULT 'negotiable',
  `price_min_wan`     DECIMAL(14,2)  DEFAULT NULL,
  `price_max_wan`     DECIMAL(14,2)  DEFAULT NULL,
  `contact_name`      VARCHAR(64)    DEFAULT NULL,
  `contact_title`     VARCHAR(64)    DEFAULT NULL,
  `contact_phone`     VARCHAR(32)    DEFAULT NULL,
  `contact_email`     VARCHAR(128)   DEFAULT NULL,
  `contact_wechat`    VARCHAR(64)    DEFAULT NULL,
  `status`            VARCHAR(16)    NOT NULL DEFAULT 'published',
  `reject_reason`     VARCHAR(500)   DEFAULT NULL,
  `version`           INT            NOT NULL DEFAULT 1,
  `view_count`        INT UNSIGNED  NOT NULL DEFAULT 0,
  `published_at`      DATETIME       DEFAULT NULL,
  `created_at`        DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at`        DATETIME       DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_ach_status_pub` (`status`, `published_at`),
  KEY `idx_ach_owner` (`owner_user_id`, `status`),
  KEY `idx_ach_org` (`org_id`),
  KEY `idx_ach_title` (`title`),
  KEY `idx_ach_category` (`category_id`),
  FULLTEXT KEY `ft_ach_text` (`title`, `tech_intro`),
  CONSTRAINT `fk_ach_owner` FOREIGN KEY (`owner_user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ach_org` FOREIGN KEY (`org_id`)
    REFERENCES `organization`(`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_ach_cat` FOREIGN KEY (`category_id`)
    REFERENCES `achievement_category`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. inventor —— 成果完成人
CREATE TABLE IF NOT EXISTS `inventor` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`       VARCHAR(64)     NOT NULL,
  `org_name`   VARCHAR(128)    DEFAULT NULL,
  `person_type` VARCHAR(16)   DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_inventor` (`name`, `org_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. achievement_inventor —— 成果-完成人关联
CREATE TABLE IF NOT EXISTS `achievement_inventor` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `achievement_id`   BIGINT UNSIGNED NOT NULL,
  `inventor_id`      BIGINT UNSIGNED NOT NULL,
  `sort_order`       INT             NOT NULL DEFAULT 0,
  `contribution`     VARCHAR(255)    DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ach_inv` (`achievement_id`, `inventor_id`),
  KEY `idx_inv` (`inventor_id`),
  CONSTRAINT `fk_ai_achievement` FOREIGN KEY (`achievement_id`)
    REFERENCES `achievement`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ai_inventor` FOREIGN KEY (`inventor_id`)
    REFERENCES `inventor`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
