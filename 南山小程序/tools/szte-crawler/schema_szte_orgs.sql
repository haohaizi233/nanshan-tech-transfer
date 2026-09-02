CREATE DATABASE IF NOT EXISTS `nanshan_capital`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `nanshan_capital`;

-- 银行融资模块：知识产权融资信息服务 → 专业服务机构
CREATE TABLE IF NOT EXISTS `ip_service_org` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `account` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '源站账号标识',
  `org_name` VARCHAR(255) NOT NULL COMMENT '机构/公司名称',
  `intro` TEXT COMMENT '公司简介（列表/悬停）',
  `detail_info` MEDIUMTEXT COMMENT '详细信息（点击公司后详情页）',
  `label` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '标签（如专业服务机构）',
  `user_type` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '源站 userType',
  `logo_file_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '源站 logo 文件 id',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '排序',
  `source_site` VARCHAR(128) NOT NULL DEFAULT 'szte.com' COMMENT '数据来源站点',
  `source_api` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '来源接口',
  `fetched_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '抓取时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_account` (`account`),
  KEY `idx_org_name` (`org_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='知识产权融资信息服务-专业服务机构（银行融资）';

-- 投资机构模块：特色投资机构一览
CREATE TABLE IF NOT EXISTS `featured_invest_org` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `org_name` VARCHAR(255) NOT NULL COMMENT '机构/公司名称',
  `intro` TEXT COMMENT '公司简介（列表/悬停卡片）',
  `detail_info` MEDIUMTEXT COMMENT '详细信息（点击公司后详情页正文）',
  `logo_file_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '源站 logo/配图文件 id',
  `detail_activity_id` INT NULL COMMENT '源站详情活动页 id（如有）',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '排序（页面展示顺序）',
  `source_site` VARCHAR(128) NOT NULL DEFAULT 'szte.com' COMMENT '数据来源站点',
  `source_page` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '来源页面',
  `fetched_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '抓取时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_org_name` (`org_name`),
  KEY `idx_sort_order` (`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='特色投资机构一览（投资机构）';
