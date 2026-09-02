-- 身份域建库 + 建表
-- 执行方式：mysql -u root -p < 001_identity_domain.sql
-- 或在 Python 中逐条执行

CREATE DATABASE IF NOT EXISTS `tech_transfer`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `tech_transfer`;

-- 1. app_user —— 科转通本地用户
CREATE TABLE IF NOT EXISTS `app_user` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_no`    VARCHAR(32)     NOT NULL,
  `status`     VARCHAR(16)     NOT NULL DEFAULT 'active',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` DATETIME        DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_no` (`user_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. external_identity —— 外部身份映射
CREATE TABLE IF NOT EXISTS `external_identity` (
  `id`                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`               BIGINT UNSIGNED NOT NULL,
  `issuer`                VARCHAR(32)     NOT NULL,
  `tenant_id`             VARCHAR(32)     NOT NULL DEFAULT 'default',
  `external_subject`      VARCHAR(128)    NOT NULL,
  `display_name_snapshot` VARCHAR(64)     DEFAULT NULL,
  `linked_at`             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `unlinked_at`           DATETIME        DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_identity` (`issuer`, `tenant_id`, `external_subject`),
  KEY `idx_identity_user` (`user_id`),
  CONSTRAINT `fk_ext_identity_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. user_profile —— 用户业务资料（一对一）
CREATE TABLE IF NOT EXISTS `user_profile` (
  `user_id`     BIGINT UNSIGNED NOT NULL,
  `display_name` VARCHAR(64)    DEFAULT NULL,
  `user_type`   VARCHAR(32)     DEFAULT NULL,
  `phone`       VARCHAR(32)     DEFAULT NULL,
  `email`       VARCHAR(128)    DEFAULT NULL,
  `org_id`      BIGINT UNSIGNED DEFAULT NULL,
  `org_title`   VARCHAR(64)     DEFAULT NULL,
  `version`     INT             NOT NULL DEFAULT 1,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  KEY `idx_profile_org` (`org_id`),
  CONSTRAINT `fk_profile_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. user_role —— 用户角色
CREATE TABLE IF NOT EXISTS `user_role` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `role_code`  VARCHAR(32)     NOT NULL DEFAULT 'user',
  `granted_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_role` (`user_id`, `role_code`),
  CONSTRAINT `fk_role_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. auth_session —— 会话吊销登记
CREATE TABLE IF NOT EXISTS `auth_session` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     BIGINT UNSIGNED NOT NULL,
  `refresh_jti` VARCHAR(64)     NOT NULL,
  `status`      VARCHAR(16)     NOT NULL DEFAULT 'active',
  `issued_at`   DATETIME        NOT NULL,
  `expires_at`  DATETIME        NOT NULL,
  `revoked_at`  DATETIME        DEFAULT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_auth_session_jti` (`refresh_jti`),
  KEY `idx_auth_session_user` (`user_id`, `status`),
  CONSTRAINT `fk_session_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
