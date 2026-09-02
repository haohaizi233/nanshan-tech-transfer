CREATE DATABASE IF NOT EXISTS `nanshan_capital`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `nanshan_capital`;

CREATE TABLE IF NOT EXISTS `platform_base` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `serial_no` INT NOT NULL COMMENT '序号',
  `platform_name` VARCHAR(255) NOT NULL COMMENT '平台名称',
  `platform_type` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '平台类型（概念验证中心/中小试基地）',
  `support_unit` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '依托单位',
  `platform_fun` TEXT COMMENT '平台功能',
  `contact_person` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '联系人',
  `contact_mobile` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '联系方式',
  `source_status` INT NULL COMMENT '源站 status',
  `order_num` INT NULL COMMENT '源站 orderNum',
  `source_site` VARCHAR(128) NOT NULL DEFAULT 'first-net.cn' COMMENT '数据来源站点',
  `fetched_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '抓取时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_serial_no` (`serial_no`),
  KEY `idx_platform_type` (`platform_type`),
  KEY `idx_platform_name` (`platform_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='概念验证中心/中小试基地库';
