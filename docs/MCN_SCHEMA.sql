-- MCN MySQL Schema (DDL only)
-- Generated: 2026-04-20T06:36:04
-- Source: im.zhongxiangbao.com:3306/shortju
-- Tables: 50

-- ============================================================
-- Table: account_groups    Rows: 1593
-- ============================================================
DROP TABLE IF EXISTS `account_groups`;
CREATE TABLE `account_groups` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `group_name` varchar(100) NOT NULL,
  `description` varchar(500) DEFAULT '',
  `color` varchar(20) DEFAULT '#409EFF',
  `sort_order` int(11) DEFAULT '0',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `owner_id` int(11) DEFAULT NULL COMMENT '所属用户ID',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `group_name` (`group_name`) USING BTREE,
  KEY `idx_group_name` (`group_name`) USING BTREE,
  KEY `idx_sort_order` (`sort_order`) USING BTREE,
  KEY `idx_owner_id` (`owner_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1791 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC;

-- ============================================================
-- Table: account_summary    Rows: 1354
-- ============================================================
DROP TABLE IF EXISTS `account_summary`;
CREATE TABLE `account_summary` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `uid` varchar(50) NOT NULL COMMENT '快手账号UID',
  `total_tasks` int(11) DEFAULT '0' COMMENT '总任务数',
  `success_tasks` int(11) DEFAULT '0' COMMENT '成功任务数',
  `failed_tasks` int(11) DEFAULT '0' COMMENT '失败任务数',
  `last_task_time` datetime DEFAULT NULL COMMENT '最后任务时间',
  `success_rate` decimal(5,2) DEFAULT NULL COMMENT '成功率（%）',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uid` (`uid`) USING BTREE,
  KEY `idx_uid` (`uid`) USING BTREE,
  KEY `idx_success_rate` (`success_rate`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=72018 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='账号统计汇总表';

-- ============================================================
-- Table: admin_operation_logs    Rows: 27463
-- ============================================================
DROP TABLE IF EXISTS `admin_operation_logs`;
CREATE TABLE `admin_operation_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL COMMENT '操作用户ID',
  `username` varchar(50) NOT NULL COMMENT '操作用户名',
  `action` varchar(50) NOT NULL COMMENT '操作类型',
  `module` varchar(50) NOT NULL COMMENT '操作模块',
  `target` varchar(100) DEFAULT '' COMMENT '操作目标',
  `detail` text COMMENT '详细信息',
  `ip` varchar(50) DEFAULT '' COMMENT 'IP地址',
  `user_agent` varchar(500) DEFAULT '' COMMENT '浏览器信息',
  `status` varchar(20) DEFAULT 'success' COMMENT '操作状态',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_user_id` (`user_id`) USING BTREE,
  KEY `idx_action` (`action`) USING BTREE,
  KEY `idx_module` (`module`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=55799 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC;

-- ============================================================
-- Table: admin_users    Rows: 1419
-- ============================================================
DROP TABLE IF EXISTS `admin_users`;
CREATE TABLE `admin_users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  `password_hash` varchar(128) NOT NULL,
  `password_salt` varchar(64) NOT NULL,
  `nickname` varchar(100) DEFAULT '',
  `role` varchar(20) DEFAULT 'admin',
  `is_active` tinyint(4) DEFAULT '1',
  `last_login` datetime DEFAULT NULL,
  `login_count` int(11) DEFAULT '0',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `avatar` varchar(255) DEFAULT '',
  `email` varchar(100) DEFAULT '',
  `phone` varchar(20) DEFAULT '',
  `default_auth_code` varchar(255) DEFAULT '' COMMENT '默认授权码',
  `user_level` varchar(20) DEFAULT 'normal' COMMENT '用户等级: normal=普通, enterprise=企业',
  `quota` int(11) DEFAULT '10' COMMENT '配额数量: -1表示无限',
  `cooperation_type` varchar(20) DEFAULT 'cooperative' COMMENT '合作类型: cooperative=合作, non_cooperative=非合作',
  `is_oem` tinyint(4) DEFAULT '0' COMMENT '是否贴牌: 0=非贴牌, 1=贴牌',
  `oem_name` varchar(100) DEFAULT '' COMMENT '贴牌名称',
  `oem_config` text COMMENT '贴牌配置项(JSON格式)',
  `parent_user_id` int(11) DEFAULT NULL COMMENT '上级用户ID（团长创建的普通用户）',
  `commission_rate` decimal(5,2) DEFAULT '100.00' COMMENT '分成比例(%)，默认100%',
  `commission_rate_visible` tinyint(4) DEFAULT '0' COMMENT '分成比例可见: 0=不可见, 1=可见',
  `commission_amount_visible` tinyint(4) DEFAULT '0' COMMENT '分成金额可见: 0=不可见, 1=可见',
  `allow_member_query` tinyint(4) DEFAULT '1' COMMENT '是否允许成员数据公开查询: 0=否, 1=是',
  `total_income_visible` tinyint(4) DEFAULT '0' COMMENT '累计收入可见: 0=不可见, 1=可见',
  `organization_access` int(11) DEFAULT NULL COMMENT '所属机构ID(单个)',
  `alipay_info` text COMMENT '支付宝信息(JSON): {"name": "姓名", "account": "账号"}',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `username` (`username`) USING BTREE,
  KEY `idx_username` (`username`) USING BTREE,
  KEY `idx_is_oem` (`is_oem`) USING BTREE,
  KEY `idx_parent_user_id` (`parent_user_id`) USING BTREE,
  KEY `idx_organization_access` (`organization_access`),
  KEY `idx_role` (`role`),
  KEY `idx_parent_role` (`parent_user_id`,`role`),
  KEY `idx_is_active` (`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=1503 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC;

-- ============================================================
-- Table: auto_devices    Rows: 472
-- ============================================================
DROP TABLE IF EXISTS `auto_devices`;
CREATE TABLE `auto_devices` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `device_id` varchar(255) NOT NULL COMMENT '设备ID',
  `device_number` varchar(50) NOT NULL COMMENT '设备编号',
  `kuaishou_count` int(11) DEFAULT '1' COMMENT '快手号数量',
  `auth_code` varchar(100) NOT NULL COMMENT '授权码',
  `device_info` json DEFAULT NULL COMMENT '设备信息',
  `token` varchar(255) DEFAULT NULL COMMENT '设备令牌',
  `is_online` tinyint(1) DEFAULT '0' COMMENT '是否在线',
  `registered_at` bigint(20) DEFAULT NULL COMMENT '注册时间',
  `connected_at` bigint(20) DEFAULT NULL COMMENT '连接时间',
  `last_seen` bigint(20) DEFAULT NULL COMMENT '最后心跳时间',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `accessibility_enabled` tinyint(1) NOT NULL DEFAULT '0' COMMENT '无障碍服务是否开启: 0=未开启, 1=已开启',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `device_id` (`device_id`) USING BTREE,
  KEY `idx_device_id` (`device_id`) USING BTREE,
  KEY `idx_device_number` (`device_number`) USING BTREE,
  KEY `idx_auth_code` (`auth_code`) USING BTREE,
  KEY `idx_last_seen` (`last_seen`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=694 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='AutoJs设备表';

-- ============================================================
-- Table: auto_device_accounts    Rows: 641
-- ============================================================
DROP TABLE IF EXISTS `auto_device_accounts`;
CREATE TABLE `auto_device_accounts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `device_id` varchar(255) NOT NULL COMMENT '设备ID',
  `account_index` int(11) NOT NULL COMMENT '账号序号',
  `nickname` varchar(255) NOT NULL COMMENT '昵称',
  `kwai_id` varchar(50) NOT NULL COMMENT '快手号',
  `package_name` varchar(100) DEFAULT NULL COMMENT '快手应用包名',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_device_account` (`device_id`,`account_index`) USING BTREE,
  KEY `idx_device_id` (`device_id`) USING BTREE,
  KEY `idx_kwai_id` (`kwai_id`) USING BTREE,
  KEY `idx_device_account` (`device_id`,`account_index`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1581 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='AutoJs设备快手账号表';

-- ============================================================
-- Table: auto_task_history    Rows: 17745
-- ============================================================
DROP TABLE IF EXISTS `auto_task_history`;
CREATE TABLE `auto_task_history` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `task_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '任务ID',
  `device_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '设备ID',
  `device_number` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '设备编号',
  `task_type` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '任务类型',
  `plan_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '计划类型',
  `status` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '任务状态: PENDING, DISPATCHED, RECEIVED, RUNNING, COMPLETED, FAILED',
  `progress` int(11) DEFAULT '0' COMMENT '任务进度 0-100',
  `progress_message` text COLLATE utf8mb4_unicode_ci COMMENT '进度消息',
  `result` json DEFAULT NULL COMMENT '任务执行结果',
  `error` text COLLATE utf8mb4_unicode_ci COMMENT '错误信息',
  `created_at` datetime NOT NULL COMMENT '任务创建时间',
  `dispatched_at` datetime DEFAULT NULL COMMENT '任务下发时间',
  `received_at` datetime DEFAULT NULL COMMENT '任务接收时间',
  `started_at` datetime DEFAULT NULL COMMENT '任务开始时间',
  `completed_at` datetime DEFAULT NULL COMMENT '任务完成时间',
  `updated_at` datetime NOT NULL COMMENT '任务更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_task_id` (`task_id`) USING BTREE,
  KEY `idx_device_id` (`device_id`) USING BTREE,
  KEY `idx_device_number` (`device_number`) USING BTREE,
  KEY `idx_status` (`status`) USING BTREE,
  KEY `idx_task_type` (`task_type`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE,
  KEY `idx_completed_at` (`completed_at`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=20882 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='AutoJs任务执行历史记录表';

-- ============================================================
-- Table: card_keys    Rows: 8
-- ============================================================
DROP TABLE IF EXISTS `card_keys`;
CREATE TABLE `card_keys` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `card_code` varchar(16) NOT NULL COMMENT '卡密(16位小写英文+数字)',
  `card_type` enum('monthly','quarterly') NOT NULL COMMENT '卡类型: monthly=月卡, quarterly=季卡',
  `status` enum('unused','active','used','expired','disabled') DEFAULT 'unused' COMMENT '状态: unused=未使用, active=已激活(可重复使用), used=已使用(一次性), expired=已过期, disabled=已禁用',
  `created_by` int(11) NOT NULL COMMENT '创建者管理员ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `used_at` timestamp NULL DEFAULT NULL COMMENT '使用时间',
  `used_by_auth_code` varchar(255) DEFAULT NULL COMMENT '绑定的授权码',
  `expires_at` timestamp NULL DEFAULT NULL COMMENT '过期时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `card_code` (`card_code`),
  KEY `idx_card_code` (`card_code`),
  KEY `idx_status` (`status`),
  KEY `idx_created_by` (`created_by`),
  KEY `idx_used_by_auth_code` (`used_by_auth_code`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COMMENT='卡密管理表';

-- ============================================================
-- Table: card_usage_logs    Rows: 54
-- ============================================================
DROP TABLE IF EXISTS `card_usage_logs`;
CREATE TABLE `card_usage_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `card_code` varchar(16) NOT NULL COMMENT '卡密',
  `auth_code` varchar(255) DEFAULT NULL COMMENT '授权码',
  `action` enum('validated','activated','verified','expired','disabled') DEFAULT 'validated' COMMENT '操作类型',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录时间',
  PRIMARY KEY (`id`),
  KEY `idx_card_code` (`card_code`)
) ENGINE=InnoDB AUTO_INCREMENT=55 DEFAULT CHARSET=utf8mb4 COMMENT='卡密使用日志表';

-- ============================================================
-- Table: cloud_cookie_accounts    Rows: 876
-- ============================================================
DROP TABLE IF EXISTS `cloud_cookie_accounts`;
CREATE TABLE `cloud_cookie_accounts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `owner_code` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '所有者标识码',
  `device_serial` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '设备序列号',
  `account_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '账号ID',
  `account_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '账号名称',
  `kuaishou_uid` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '快手UID',
  `kuaishou_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '快手昵称',
  `cookies` longtext COLLATE utf8mb4_unicode_ci COMMENT 'Cookie数据(JSON)',
  `login_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'logged_in' COMMENT '登录状态',
  `login_time` datetime DEFAULT NULL COMMENT '登录时间',
  `browser_port` int(11) DEFAULT NULL COMMENT '浏览器端口',
  `success_count` int(11) DEFAULT '0' COMMENT '成功次数',
  `fail_count` int(11) DEFAULT '0' COMMENT '失败次数',
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '备注',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_owner_code` (`owner_code`) USING BTREE,
  KEY `idx_account_name` (`account_name`) USING BTREE,
  KEY `idx_kuaishou_uid` (`kuaishou_uid`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=880 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='云端Cookie账号表';

-- ============================================================
-- Table: collect_pool_auth_codes    Rows: 1423
-- ============================================================
DROP TABLE IF EXISTS `collect_pool_auth_codes`;
CREATE TABLE `collect_pool_auth_codes` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `auth_code` varchar(100) NOT NULL COMMENT '授权码',
  `name` varchar(100) DEFAULT '' COMMENT '授权码名称/备注',
  `is_active` tinyint(1) DEFAULT '1' COMMENT '是否启用: 1=启用, 0=禁用',
  `expire_at` datetime DEFAULT NULL COMMENT '过期时间，NULL表示永不过期',
  `created_by` int(11) DEFAULT NULL COMMENT '创建人ID',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `auth_code` (`auth_code`) USING BTREE,
  KEY `idx_auth_code` (`auth_code`) USING BTREE,
  KEY `idx_is_active` (`is_active`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1499 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='收藏池授权码表';

-- ============================================================
-- Table: cxt_author    Rows: 298
-- ============================================================
DROP TABLE IF EXISTS `cxt_author`;
CREATE TABLE `cxt_author` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '作者名称',
  `author_id` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '作者id',
  `platform` tinyint(4) unsigned NOT NULL DEFAULT '0' COMMENT '平台 0.抖音 1.快手',
  `type` tinyint(4) unsigned NOT NULL DEFAULT '0' COMMENT '类型 0.影视 1.短剧',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=348 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='橙心推影视对标达人';

-- ============================================================
-- Table: cxt_titles    Rows: 6096
-- ============================================================
DROP TABLE IF EXISTS `cxt_titles`;
CREATE TABLE `cxt_titles` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `title` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '剧名',
  `type` tinyint(4) unsigned NOT NULL DEFAULT '0' COMMENT '类型 0.电影 1.电视剧',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=6097 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='橙心推剧名表';

-- ============================================================
-- Table: cxt_user    Rows: 150
-- ============================================================
DROP TABLE IF EXISTS `cxt_user`;
CREATE TABLE `cxt_user` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `uid` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '橙星推uid',
  `note` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '备注',
  `auth_code` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '授权码',
  `status` tinyint(4) unsigned DEFAULT '0' COMMENT '状态 0.待审核 1.审核通过 2.禁用',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=169 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='橙星推验证表';

-- ============================================================
-- Table: cxt_videos    Rows: 1503
-- ============================================================
DROP TABLE IF EXISTS `cxt_videos`;
CREATE TABLE `cxt_videos` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `sec_user_id` varchar(200) DEFAULT NULL COMMENT '作者id',
  `title` varchar(500) DEFAULT NULL COMMENT '剧名',
  `author` varchar(100) DEFAULT NULL COMMENT '作者',
  `aweme_id` varchar(100) DEFAULT NULL COMMENT '作品id',
  `description` text COMMENT '作品描述',
  `video_url` text COMMENT '视频地址',
  `cover_url` text COMMENT '封面地址',
  `duration` int(11) DEFAULT NULL COMMENT '时长',
  `comment_count` int(11) DEFAULT NULL COMMENT '评论数',
  `collect_count` int(11) DEFAULT NULL COMMENT '收藏数',
  `recommend_count` int(11) DEFAULT NULL COMMENT '推荐数',
  `share_count` int(11) DEFAULT NULL COMMENT '分享数',
  `play_count` int(11) DEFAULT NULL COMMENT '播放数',
  `digg_count` int(11) DEFAULT NULL COMMENT '点赞数',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `platform` tinyint(4) unsigned NOT NULL DEFAULT '0' COMMENT '平台 0.抖音 1.快手 2.橙心推官方链接',
  PRIMARY KEY (`id`),
  KEY `idx_sec_user_id` (`sec_user_id`),
  KEY `idx_aweme_id` (`aweme_id`)
) ENGINE=InnoDB AUTO_INCREMENT=9960 DEFAULT CHARSET=utf8mb4 COMMENT='橙星推剧集表';

-- ============================================================
-- Table: drama_collections    Rows: 113257
-- ============================================================
DROP TABLE IF EXISTS `drama_collections`;
CREATE TABLE `drama_collections` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `kuaishou_uid` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '快手账号UID',
  `kuaishou_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '快手账号名称',
  `device_serial` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '设备序列号',
  `drama_name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '短剧名称',
  `drama_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '短剧链接',
  `plan_mode` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'spark' COMMENT '平台模式: spark=星火计划, firefly=萤火计划',
  `actual_drama_name` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '实际短剧名称',
  `collected_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_uid_drama_mode` (`kuaishou_uid`,`drama_name`,`plan_mode`),
  KEY `idx_kuaishou_uid` (`kuaishou_uid`) USING BTREE,
  KEY `idx_drama_name` (`drama_name`) USING BTREE,
  KEY `idx_plan_mode` (`plan_mode`) USING BTREE,
  KEY `idx_collected_at` (`collected_at`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=161819 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='短剧收藏记录表';

-- ============================================================
-- Table: drama_execution_logs    Rows: 0
-- ============================================================
DROP TABLE IF EXISTS `drama_execution_logs`;
CREATE TABLE `drama_execution_logs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '日志ID',
  `uid` varchar(50) NOT NULL COMMENT '账号UID',
  `device_serial` varchar(50) DEFAULT '' COMMENT '设备序列号',
  `drama_name` varchar(200) DEFAULT '' COMMENT '短剧名称',
  `episode_number` int(11) DEFAULT '0' COMMENT '集数',
  `status` varchar(20) NOT NULL COMMENT '状态：success/failed',
  `duration` int(11) DEFAULT '0' COMMENT '执行时长(秒)',
  `error_message` text COMMENT '错误信息',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `config_data` json DEFAULT NULL COMMENT '任务配置信息(JSON格式)',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_uid` (`uid`) USING BTREE,
  KEY `idx_device` (`device_serial`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE,
  KEY `idx_status` (`status`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='短剧执行日志表';

-- ============================================================
-- Table: firefly_income    Rows: 3558
-- ============================================================
DROP TABLE IF EXISTS `firefly_income`;
CREATE TABLE `firefly_income` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `income_date` date NOT NULL COMMENT '收益时间',
  `video_id` varchar(50) NOT NULL COMMENT '视频ID',
  `video_url` varchar(500) DEFAULT '' COMMENT '视频链接',
  `author_id` varchar(50) NOT NULL COMMENT '作者ID',
  `author_nickname` varchar(100) DEFAULT '' COMMENT '作者昵称',
  `task_name` varchar(200) DEFAULT '' COMMENT '任务名称',
  `monetize_type` varchar(50) DEFAULT '' COMMENT '变现类型',
  `upload_date` date DEFAULT NULL COMMENT '上传日期',
  `settlement_amount` decimal(10,2) DEFAULT '0.00' COMMENT '达人结算金额',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `commission_rate` decimal(5,2) DEFAULT '100.00' COMMENT '分成比例(%)，默认100%',
  `settlement_status` varchar(20) DEFAULT 'unsettled' COMMENT '结算状态: settled=已结清, unsettled=未结清',
  `commission_amount` decimal(10,2) GENERATED ALWAYS AS (((`settlement_amount` * `commission_rate`) / 100)) STORED COMMENT '扣除分成金额（自动计算）',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_date_video` (`income_date`,`video_id`) USING BTREE,
  KEY `idx_income_date` (`income_date`) USING BTREE,
  KEY `idx_author_id` (`author_id`) USING BTREE,
  KEY `idx_author_nickname` (`author_nickname`) USING BTREE,
  KEY `idx_task_name` (`task_name`) USING BTREE,
  KEY `idx_commission_rate` (`commission_rate`),
  KEY `idx_settlement_status` (`settlement_status`)
) ENGINE=InnoDB AUTO_INCREMENT=3605 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='萤光收益表';

-- ============================================================
-- Table: firefly_members    Rows: 218
-- ============================================================
DROP TABLE IF EXISTS `firefly_members`;
CREATE TABLE `firefly_members` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `author_id` varchar(100) NOT NULL,
  `author_name` varchar(255) DEFAULT NULL,
  `total_income` decimal(12,2) DEFAULT '0.00',
  `period_income` decimal(12,2) DEFAULT '0.00',
  `period_start` date DEFAULT NULL,
  `period_end` date DEFAULT NULL,
  `record_count` int(11) DEFAULT '0',
  `first_income_date` date DEFAULT NULL,
  `last_income_date` date DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `author_id` (`author_id`),
  KEY `idx_author_id` (`author_id`),
  KEY `idx_total_income` (`total_income`)
) ENGINE=InnoDB AUTO_INCREMENT=318 DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- Table: fluorescent_income    Rows: 29472
-- ============================================================
DROP TABLE IF EXISTS `fluorescent_income`;
CREATE TABLE `fluorescent_income` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '成员昵称',
  `task_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '任务ID',
  `task_name` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '任务名称',
  `task_start_time` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '任务开始时间(YYYYMMDD)',
  `income` decimal(10,2) DEFAULT '0.00' COMMENT '收益金额',
  `settlement_status` varchar(20) NOT NULL DEFAULT 'unsettled' COMMENT '结算状态: settled=已结清, unsettled=未结清',
  `org_id` int(11) unsigned DEFAULT '1' COMMENT '所属机构ID',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_unique` (`member_id`,`task_id`),
  KEY `idx_member_id` (`member_id`),
  KEY `idx_task_id` (`task_id`),
  KEY `idx_task_start_time` (`task_start_time`),
  KEY `idx_settlement_status` (`settlement_status`)
) ENGINE=InnoDB AUTO_INCREMENT=48763 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='荧光计划收益表';

-- ============================================================
-- Table: fluorescent_income_archive    Rows: 12489
-- ============================================================
DROP TABLE IF EXISTS `fluorescent_income_archive`;
CREATE TABLE `fluorescent_income_archive` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '成员昵称',
  `member_head` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像URL',
  `fans_count` int(11) DEFAULT '0' COMMENT '粉丝数',
  `in_limit` tinyint(1) DEFAULT '0' COMMENT '是否限额(0=否,1=是)',
  `broker_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT '未分配' COMMENT '经纪人名称',
  `org_task_num` int(11) DEFAULT '0' COMMENT '机构任务数',
  `total_amount` decimal(10,2) DEFAULT '0.00' COMMENT '总金额',
  `settlement_status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'unsettled' COMMENT '结算状态: settled=已结清, unsettled=未结清',
  `archive_month` int(11) NOT NULL COMMENT '收益所属月份(1-12)',
  `archive_year` int(11) NOT NULL COMMENT '收益所属年份',
  `start_time` bigint(20) DEFAULT NULL COMMENT '开始时间戳(毫秒)',
  `end_time` bigint(20) DEFAULT NULL COMMENT '结束时间戳(毫秒)',
  `archived_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '存档时间',
  `org_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  PRIMARY KEY (`id`),
  KEY `idx_member_id` (`member_id`),
  KEY `idx_broker_name` (`broker_name`),
  KEY `idx_fans_count` (`fans_count`),
  KEY `idx_archive_period` (`archive_year`,`archive_month`),
  KEY `idx_org_id` (`org_id`),
  KEY `idx_settlement_status` (`settlement_status`)
) ENGINE=InnoDB AUTO_INCREMENT=27827 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='荧光计划成员收益存档表';

-- ============================================================
-- Table: fluorescent_members    Rows: 18812
-- ============================================================
DROP TABLE IF EXISTS `fluorescent_members`;
CREATE TABLE `fluorescent_members` (
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) NOT NULL COMMENT '成员昵称',
  `member_head` varchar(500) DEFAULT NULL COMMENT '头像URL',
  `fans_count` int(11) DEFAULT '0' COMMENT '粉丝数',
  `in_limit` tinyint(1) DEFAULT '0' COMMENT '是否限额(0=否,1=是)',
  `broker_name` varchar(50) DEFAULT '未分配' COMMENT '经纪人名称',
  `org_task_num` int(11) DEFAULT '0' COMMENT '机构任务数',
  `total_amount` decimal(10,2) DEFAULT '0.00' COMMENT '总金额',
  `org_id` int(11) unsigned DEFAULT '1' COMMENT '所属机构ID',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`member_id`) USING BTREE,
  KEY `idx_member_id` (`member_id`),
  KEY `idx_org_id` (`org_id`),
  KEY `idx_total_amount` (`total_amount`),
  KEY `idx_member_org` (`member_id`,`org_id`),
  KEY `idx_org_member_cover` (`org_id`,`member_id`),
  KEY `idx_member_name_search` (`member_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='荧光计划成员表';

-- ============================================================
-- Table: iqiyi_videos    Rows: 7313
-- ============================================================
DROP TABLE IF EXISTS `iqiyi_videos`;
CREATE TABLE `iqiyi_videos` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `block_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT 'Block唯一ID',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '片名',
  `subtitle` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '副标题/宣传语',
  `category` tinyint(1) unsigned NOT NULL DEFAULT '0' COMMENT '类型:1=电影,2=电视剧,4=动漫,6=综艺',
  `score` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '评分或集数状态',
  `cover_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '封面图URL',
  `status_mark` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '播放状态标识',
  `album_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '专辑ID',
  `tv_id` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '视频ID',
  `s_target` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '搜索文档ID',
  `share_url` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '分享链接',
  `raw_data` text COLLATE utf8mb4_unicode_ci COMMENT '原始JSON数据',
  `createtime` int(11) unsigned DEFAULT NULL,
  `updatetime` int(11) unsigned DEFAULT NULL,
  `platform` tinyint(4) unsigned NOT NULL DEFAULT '0' COMMENT '平台: 0=爱奇艺,1=优酷',
  PRIMARY KEY (`id`),
  UNIQUE KEY `title_category_platform` (`title`,`category`,`platform`) USING BTREE,
  KEY `block_id` (`block_id`),
  KEY `album_id` (`album_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7903 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爱奇艺影视数据表';

-- ============================================================
-- Table: ks_account    Rows: 23251
-- ============================================================
DROP TABLE IF EXISTS `ks_account`;
CREATE TABLE `ks_account` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '账号名称',
  `uid` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '快手号',
  `device_num` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '设备码',
  `uid_real` varchar(50) CHARACTER SET utf8mb4 DEFAULT NULL COMMENT '快手真实UID',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_device_uid` (`device_num`,`uid`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=57978 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC;

-- ============================================================
-- Table: ks_episodes    Rows: 1043
-- ============================================================
DROP TABLE IF EXISTS `ks_episodes`;
CREATE TABLE `ks_episodes` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `photo_id` varchar(64) NOT NULL COMMENT '视频ID',
  `serial_id` varchar(64) DEFAULT NULL COMMENT '剧集ID',
  `episode_number` int(11) DEFAULT NULL COMMENT '集数',
  `episode_name` varchar(100) DEFAULT NULL COMMENT '集名',
  `caption` text COMMENT '标题/描述',
  `duration_ms` int(11) DEFAULT NULL COMMENT '时长(毫秒)',
  `like_count` int(11) DEFAULT '0' COMMENT '点赞数',
  `view_count` int(11) DEFAULT '0' COMMENT '播放量',
  `comment_count` int(11) DEFAULT '0' COMMENT '评论数',
  `forward_count` int(11) DEFAULT '0' COMMENT '转发数',
  `serial_title` varchar(255) DEFAULT NULL COMMENT '剧集名称',
  `episode_count` int(11) DEFAULT NULL COMMENT '总集数',
  `author_user_id` bigint(20) DEFAULT NULL COMMENT '作者用户ID',
  `author_user_name` varchar(100) DEFAULT NULL COMMENT '作者用户名',
  `video_url` text COMMENT '视频URL',
  `cover_url` text COMMENT '封面URL',
  `share_user_id` varchar(255) DEFAULT '' COMMENT '分享用户id',
  `share_photo_id` varchar(255) DEFAULT '' COMMENT '分享作品id',
  `raw_json` json DEFAULT NULL COMMENT '原始JSON数据',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_photo_id` (`photo_id`),
  KEY `idx_serial_id` (`serial_id`),
  KEY `idx_episode_number` (`episode_number`),
  KEY `idx_author_user_id` (`author_user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=1109 DEFAULT CHARSET=utf8mb4 COMMENT='快手短剧集数表';

-- ============================================================
-- Table: kuaishou_accounts    Rows: 23075
-- ============================================================
DROP TABLE IF EXISTS `kuaishou_accounts`;
CREATE TABLE `kuaishou_accounts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `uid` varchar(50) NOT NULL COMMENT '快手账号UID',
  `device_serial` varchar(50) DEFAULT NULL COMMENT '设备序列号',
  `nickname` varchar(100) DEFAULT NULL COMMENT '账号昵称',
  `is_mcm_member` tinyint(1) DEFAULT '0' COMMENT '是否加入MCM机构',
  `mcm_join_date` datetime DEFAULT NULL COMMENT 'MCM加入日期',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  `group_id` int(11) DEFAULT NULL,
  `owner_id` int(11) DEFAULT NULL COMMENT '所属用户ID',
  `is_blacklisted` tinyint(1) DEFAULT '0' COMMENT '是否被拉黑',
  `blacklist_reason` varchar(255) DEFAULT NULL COMMENT '拉黑原因',
  `blacklisted_at` datetime DEFAULT NULL COMMENT '拉黑时间',
  `blacklisted_by` int(11) DEFAULT NULL COMMENT '拉黑操作人ID',
  `account_status` varchar(50) DEFAULT 'normal' COMMENT '账号状态: normal/marked/suspended',
  `status_note` varchar(255) DEFAULT NULL COMMENT '状态备注',
  `platform` tinyint(4) DEFAULT '1' COMMENT '账号所属平台 1.短剧精灵 2.快手小精灵',
  `contract_status` varchar(50) DEFAULT NULL COMMENT '签约状态: 邀约发送等待接受/已签约/邀约已拒绝/邀约已过期',
  `org_note` text COMMENT '机构备注（实名-团长格式）',
  `phone_number` varchar(20) DEFAULT NULL COMMENT '手机号码',
  `invite_time` datetime DEFAULT NULL COMMENT '邀约时间',
  `invitation_success_count` int(11) DEFAULT '0' COMMENT '邀约成功次数',
  `uid_real` varchar(50) DEFAULT NULL COMMENT '快手真实UID',
  `real_name` varchar(50) DEFAULT NULL COMMENT '实名（从备注或开通星火时填写）',
  `organization_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  `commission_rate` decimal(5,2) DEFAULT NULL COMMENT '账号分成比例(%),NULL时使用所属用户的分成比例',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uid` (`uid`) USING BTREE,
  KEY `idx_uid` (`uid`) USING BTREE,
  KEY `idx_device` (`device_serial`) USING BTREE,
  KEY `idx_mcm_member` (`is_mcm_member`) USING BTREE,
  KEY `idx_group_id` (`group_id`) USING BTREE,
  KEY `idx_uid_real` (`uid_real`) USING BTREE,
  KEY `idx_organization_id` (`organization_id`),
  KEY `idx_owner_id` (`owner_id`),
  KEY `idx_owner_group` (`owner_id`,`group_id`),
  KEY `idx_uid_real_owner` (`uid_real`,`owner_id`),
  KEY `idx_owner_uid_real_cover` (`owner_id`,`uid_real`,`uid`),
  KEY `idx_uid_uid_real` (`uid`,`uid_real`)
) ENGINE=InnoDB AUTO_INCREMENT=49190 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='快手账号信息表';

-- ============================================================
-- Table: kuaishou_account_bindings    Rows: 2
-- ============================================================
DROP TABLE IF EXISTS `kuaishou_account_bindings`;
CREATE TABLE `kuaishou_account_bindings` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `kuaishou_id` varchar(50) NOT NULL COMMENT '快手号',
  `machine_id` varchar(100) NOT NULL COMMENT '机器码',
  `operator_account` varchar(100) NOT NULL COMMENT '操作员登录账号',
  `bind_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
  `last_used_time` datetime DEFAULT NULL COMMENT '最后使用时间',
  `status` enum('active','disabled') DEFAULT 'active' COMMENT '状态',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_kuaishou_machine_operator` (`kuaishou_id`,`machine_id`,`operator_account`) USING BTREE,
  KEY `idx_operator` (`operator_account`) USING BTREE,
  KEY `idx_machine` (`machine_id`) USING BTREE,
  KEY `idx_kuaishou` (`kuaishou_id`) USING BTREE,
  KEY `idx_status` (`status`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='快手账号绑定表';

-- ============================================================
-- Table: kuaishou_urls    Rows: 1734694
-- ============================================================
DROP TABLE IF EXISTS `kuaishou_urls`;
CREATE TABLE `kuaishou_urls` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '短剧链接',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '短剧名称',
  `uid` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户id',
  `nickname` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户名',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1745057 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='短剧成功链接库';

-- ============================================================
-- Table: mcm_organizations    Rows: 17
-- ============================================================
DROP TABLE IF EXISTS `mcm_organizations`;
CREATE TABLE `mcm_organizations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `org_name` varchar(100) NOT NULL COMMENT '机构名称',
  `org_code` mediumtext COMMENT '机构代码/Cookie',
  `description` text COMMENT '机构描述',
  `is_active` tinyint(1) DEFAULT '1' COMMENT '是否启用',
  `include_video_collaboration` tinyint(1) DEFAULT '1' COMMENT '是否需要发送视频邀约: 1=需要, 0=不需要',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_org_name` (`org_name`)
) ENGINE=InnoDB AUTO_INCREMENT=20 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='MCM机构表';

-- ============================================================
-- Table: mcn_verification_logs    Rows: 493549
-- ============================================================
DROP TABLE IF EXISTS `mcn_verification_logs`;
CREATE TABLE `mcn_verification_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `uid` varchar(50) DEFAULT NULL COMMENT '账号UID',
  `client_ip` varchar(50) DEFAULT NULL COMMENT '客户端IP',
  `status` varchar(20) DEFAULT NULL COMMENT '验证状态: SUCCESS, FAILED',
  `is_mcn_member` tinyint(1) DEFAULT NULL COMMENT '是否为MCN成员',
  `error_message` text COMMENT '错误信息',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_uid` (`uid`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE,
  KEY `idx_status` (`status`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=494445 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='MCN验证审计日志';

-- ============================================================
-- Table: operator_quota    Rows: 0
-- ============================================================
DROP TABLE IF EXISTS `operator_quota`;
CREATE TABLE `operator_quota` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `operator_account` varchar(100) NOT NULL COMMENT '操作员账号',
  `max_accounts` int(11) DEFAULT '10' COMMENT '最大可绑定账号数',
  `created_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_time` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `operator_account` (`operator_account`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='操作员配额表';

-- ============================================================
-- Table: page_permissions    Rows: 21578
-- ============================================================
DROP TABLE IF EXISTS `page_permissions`;
CREATE TABLE `page_permissions` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `page_key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '页面标识',
  `is_allowed` tinyint(1) DEFAULT '1' COMMENT '是否允许访问: 1=允许, 0=禁止',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_user_page` (`user_id`,`page_key`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_page_key` (`page_key`),
  CONSTRAINT `page_permissions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `admin_users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=39377 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- Table: role_default_permissions    Rows: 246
-- ============================================================
DROP TABLE IF EXISTS `role_default_permissions`;
CREATE TABLE `role_default_permissions` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `role` varchar(50) NOT NULL COMMENT '角色: operator/captain/normal_user',
  `perm_type` varchar(50) NOT NULL COMMENT '权限类型: account_button/user_mgmt_button/web_page',
  `perm_key` varchar(100) NOT NULL COMMENT '权限标识',
  `is_allowed` tinyint(1) DEFAULT '1' COMMENT '是否默认开启',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_role_type_key` (`role`,`perm_type`,`perm_key`)
) ENGINE=InnoDB AUTO_INCREMENT=9985 DEFAULT CHARSET=utf8mb4 COMMENT='角色默认权限配置表';

-- ============================================================
-- Table: spark_drama_info    Rows: 126296
-- ============================================================
DROP TABLE IF EXISTS `spark_drama_info`;
CREATE TABLE `spark_drama_info` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `biz_id` bigint(20) NOT NULL COMMENT '业务ID',
  `business_type` int(11) DEFAULT NULL COMMENT '业务类型',
  `ref_business_id` bigint(20) DEFAULT NULL COMMENT '关联业务ID',
  `title` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '短剧标题',
  `icon` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '封面图URL',
  `start_time` bigint(20) DEFAULT NULL COMMENT '开始时间戳',
  `end_time` bigint(20) DEFAULT NULL COMMENT '结束时间戳',
  `promotion_type` int(11) DEFAULT NULL COMMENT '推广类型',
  `promotion_type_desc` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '推广类型描述',
  `redirect_url` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '跳转URL',
  `tags` json DEFAULT NULL COMMENT '标签(JSON格式)',
  `classifications` json DEFAULT NULL COMMENT '分类(JSON格式)',
  `label` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '标签',
  `description` text COLLATE utf8mb4_unicode_ci COMMENT '描述',
  `income_desc` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '收入描述',
  `joined` tinyint(4) DEFAULT '0' COMMENT '是否已加入: 1-是, 0-否',
  `view_status` int(11) DEFAULT NULL COMMENT '查看状态',
  `commission_rate` decimal(5,2) DEFAULT '0.00' COMMENT '佣金比例',
  `raw_data` json DEFAULT NULL COMMENT '原始数据(JSON格式)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `platform` tinyint(3) unsigned NOT NULL DEFAULT '1' COMMENT '平台 1-星火计划 2-荧光计划',
  `jump_url` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '试看url',
  `serial_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT '',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_biz_id` (`biz_id`) USING BTREE,
  KEY `idx_business_type` (`business_type`) USING BTREE,
  KEY `idx_joined` (`joined`) USING BTREE,
  KEY `idx_promotion_type` (`promotion_type`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE,
  KEY `idx_title` (`title`(255))
) ENGINE=InnoDB AUTO_INCREMENT=427456 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='快手短剧信息表';

-- ============================================================
-- Table: spark_highincome_dramas    Rows: 432
-- ============================================================
DROP TABLE IF EXISTS `spark_highincome_dramas`;
CREATE TABLE `spark_highincome_dramas` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `title` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '短剧标题',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_title_unique` (`title`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=1173 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- Table: spark_income    Rows: 80
-- ============================================================
DROP TABLE IF EXISTS `spark_income`;
CREATE TABLE `spark_income` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '成员昵称',
  `task_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '任务ID',
  `task_name` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '任务名称',
  `task_period` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '任务周期(如: 2025.11.25 ~ 2026.11.30)',
  `income` decimal(10,2) DEFAULT '0.00' COMMENT '收益金额',
  `start_date` date DEFAULT NULL COMMENT '任务开始日期',
  `end_date` date DEFAULT NULL COMMENT '任务结束日期',
  `org_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `idx_member_task` (`member_id`,`task_id`) USING BTREE,
  KEY `idx_member_id` (`member_id`) USING BTREE,
  KEY `idx_task_id` (`task_id`) USING BTREE,
  KEY `idx_income` (`income`) USING BTREE,
  KEY `idx_spark_income_org_id` (`org_id`),
  CONSTRAINT `spark_income_ibfk_1` FOREIGN KEY (`member_id`) REFERENCES `spark_members` (`member_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=114634 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='星火计划收益记录表';

-- ============================================================
-- Table: spark_income_archive    Rows: 3315
-- ============================================================
DROP TABLE IF EXISTS `spark_income_archive`;
CREATE TABLE `spark_income_archive` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '成员昵称',
  `member_head` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像URL',
  `fans_count` int(11) DEFAULT '0' COMMENT '粉丝数',
  `in_limit` tinyint(1) DEFAULT '0' COMMENT '是否限额(0=否,1=是)',
  `broker_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT '未分配' COMMENT '经纪人名称',
  `org_task_num` int(11) DEFAULT '0' COMMENT '机构任务数',
  `total_amount` decimal(10,2) DEFAULT '0.00' COMMENT '总金额',
  `archive_month` int(11) NOT NULL COMMENT '收益所属月份(1-12)',
  `archive_year` int(11) NOT NULL COMMENT '收益所属年份',
  `start_time` bigint(20) DEFAULT NULL COMMENT '开始时间戳(毫秒)',
  `end_time` bigint(20) DEFAULT NULL COMMENT '结束时间戳(毫秒)',
  `archived_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '存档时间',
  `settlement_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'unsettled' COMMENT '结算状态: settled=已结清, unsettled=未结清',
  `commission_rate` decimal(5,2) DEFAULT '100.00' COMMENT '分成比例(%)，默认100%',
  `commission_amount` decimal(10,2) GENERATED ALWAYS AS (((`total_amount` * `commission_rate`) / 100)) STORED COMMENT '扣除分成金额（自动计算）',
  `org_id` int(10) unsigned NOT NULL DEFAULT '1' COMMENT '机构id',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_member_id` (`member_id`) USING BTREE,
  KEY `idx_broker_name` (`broker_name`) USING BTREE,
  KEY `idx_fans_count` (`fans_count`) USING BTREE,
  KEY `idx_archive_period` (`archive_year`,`archive_month`) USING BTREE,
  KEY `idx_commission_rate` (`commission_rate`)
) ENGINE=InnoDB AUTO_INCREMENT=4789 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='星火计划成员收益存档表';

-- ============================================================
-- Table: spark_members    Rows: 1198
-- ============================================================
DROP TABLE IF EXISTS `spark_members`;
CREATE TABLE `spark_members` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '成员昵称',
  `member_head` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像URL',
  `fans_count` int(11) DEFAULT '0' COMMENT '粉丝数',
  `in_limit` tinyint(1) DEFAULT '0' COMMENT '是否限额(0=否,1=是)',
  `broker_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT '未分配' COMMENT '经纪人名称',
  `org_task_num` int(11) DEFAULT '0' COMMENT '机构任务数',
  `total_amount` decimal(10,2) DEFAULT '0.00' COMMENT '总金额',
  `org_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  `best_publish_times` text COLLATE utf8mb4_unicode_ci COMMENT 'AI分析的最佳发布时间(JSON格式)',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `member_id` (`member_id`) USING BTREE,
  KEY `idx_member_id` (`member_id`) USING BTREE,
  KEY `idx_broker_name` (`broker_name`) USING BTREE,
  KEY `idx_fans_count` (`fans_count`) USING BTREE,
  KEY `idx_spark_members_org_id` (`org_id`)
) ENGINE=InnoDB AUTO_INCREMENT=179323 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='星火计划成员表';

-- ============================================================
-- Table: spark_org_members    Rows: 6029
-- ============================================================
DROP TABLE IF EXISTS `spark_org_members`;
CREATE TABLE `spark_org_members` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `user_id` bigint(20) DEFAULT NULL COMMENT '用户ID',
  `member_name` varchar(255) DEFAULT NULL COMMENT '成员昵称',
  `member_head` varchar(512) DEFAULT NULL COMMENT '成员头像URL',
  `fans_count` int(11) DEFAULT '0' COMMENT '粉丝数',
  `broker_id` bigint(20) DEFAULT '0' COMMENT '经纪人ID',
  `broker_name` varchar(255) DEFAULT NULL COMMENT '经纪人姓名',
  `agreement_types` varchar(255) DEFAULT NULL COMMENT '合作类型列表(逗号分隔): 4视频合作MCN, 13星火计划, 14原生短剧推广计划',
  `broker_type` int(11) DEFAULT '-1' COMMENT '经纪人类型',
  `last_photo_time` bigint(20) DEFAULT NULL COMMENT '最后发作品时间戳(毫秒)',
  `last_photo_date` datetime DEFAULT NULL COMMENT '最后发作品时间',
  `last_live_time` bigint(20) DEFAULT NULL COMMENT '最后直播时间戳(毫秒)',
  `last_live_date` datetime DEFAULT NULL COMMENT '最后直播时间',
  `content_category` varchar(50) DEFAULT '-' COMMENT '内容分类',
  `contract_renew_status` int(11) DEFAULT '-1' COMMENT '续约状态: 8已开启自动续约',
  `contract_expire_time` bigint(20) DEFAULT NULL COMMENT '合同过期时间戳(毫秒)',
  `contract_expire_date` datetime DEFAULT NULL COMMENT '合同过期时间',
  `comment` text COMMENT '备注',
  `join_time` bigint(20) DEFAULT NULL COMMENT '加入机构时间戳(毫秒)',
  `join_date` datetime DEFAULT NULL COMMENT '加入机构时间',
  `mcn_grade` varchar(50) DEFAULT NULL COMMENT 'MCN等级',
  `org_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_member_id` (`member_id`) USING BTREE,
  KEY `idx_broker_id` (`broker_id`) USING BTREE,
  KEY `idx_contract_renew_status` (`contract_renew_status`) USING BTREE,
  KEY `idx_join_date` (`join_date`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE,
  KEY `idx_spark_org_members_org_id` (`org_id`)
) ENGINE=InnoDB AUTO_INCREMENT=55182 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='机构成员管理表';

-- ============================================================
-- Table: spark_photos    Rows: 0
-- ============================================================
DROP TABLE IF EXISTS `spark_photos`;
CREATE TABLE `spark_photos` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `photo_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '作品ID',
  `member_id` bigint(20) NOT NULL COMMENT '成员ID',
  `member_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '成员昵称',
  `title` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '作品标题',
  `view_count` int(11) DEFAULT '0' COMMENT '播放量',
  `like_count` int(11) DEFAULT '0' COMMENT '点赞数',
  `comment_count` int(11) DEFAULT '0' COMMENT '评论数',
  `duration` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '时长(如: 08:31)',
  `publish_time` bigint(20) DEFAULT NULL COMMENT '发布时间戳(毫秒)',
  `publish_date` datetime DEFAULT NULL COMMENT '发布时间',
  `cover_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '封面URL',
  `play_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '播放URL',
  `avatar_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '作者头像URL',
  `org_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `photo_id` (`photo_id`) USING BTREE,
  KEY `idx_member_id` (`member_id`) USING BTREE,
  KEY `idx_publish_time` (`publish_time`) USING BTREE,
  KEY `idx_view_count` (`view_count`) USING BTREE,
  KEY `idx_spark_photos_org_id` (`org_id`),
  CONSTRAINT `spark_photos_ibfk_1` FOREIGN KEY (`member_id`) REFERENCES `spark_members` (`member_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='星火计划作品表';

-- ============================================================
-- Table: spark_violation_dramas    Rows: 2434
-- ============================================================
DROP TABLE IF EXISTS `spark_violation_dramas`;
CREATE TABLE `spark_violation_dramas` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `drama_title` varchar(200) NOT NULL COMMENT '短剧标题（从作品标题中提取 #快来看短剧 前面的内容）',
  `source_photo_id` varchar(50) DEFAULT NULL COMMENT '来源作品ID',
  `source_caption` text COMMENT '原始作品标题',
  `user_id` bigint(20) DEFAULT NULL COMMENT '用户ID',
  `username` varchar(100) DEFAULT NULL COMMENT '用户昵称',
  `violation_count` int(11) DEFAULT '1' COMMENT '违规次数',
  `last_violation_time` bigint(20) DEFAULT NULL COMMENT '最近一次违规时间戳',
  `last_violation_date` datetime DEFAULT NULL COMMENT '最近一次违规时间',
  `sub_biz` varchar(50) DEFAULT NULL COMMENT '最新违规类型',
  `status_desc` varchar(50) DEFAULT NULL COMMENT '最新状态描述',
  `reason` text COMMENT '最新违规原因',
  `media_url` text COMMENT '作品视频URL',
  `thumb_url` text COMMENT '作品封面URL',
  `broker_name` varchar(100) DEFAULT NULL COMMENT '经纪人姓名',
  `is_blacklisted` tinyint(4) DEFAULT '0' COMMENT '是否已拉黑: 0-未拉黑, 1-已拉黑',
  `blacklisted_at` timestamp NULL DEFAULT NULL COMMENT '拉黑时间',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `org_id` int(10) unsigned NOT NULL DEFAULT '1' COMMENT '机构id',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_drama_title` (`drama_title`) USING BTREE,
  KEY `idx_user_id` (`user_id`) USING BTREE,
  KEY `idx_violation_count` (`violation_count`) USING BTREE,
  KEY `idx_last_violation_time` (`last_violation_time`) USING BTREE,
  KEY `idx_is_blacklisted` (`is_blacklisted`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=24341 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='星火计划违规短剧表';

-- ============================================================
-- Table: spark_violation_photos    Rows: 32497
-- ============================================================
DROP TABLE IF EXISTS `spark_violation_photos`;
CREATE TABLE `spark_violation_photos` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `photo_id` varchar(50) NOT NULL COMMENT '作品ID',
  `user_id` bigint(20) DEFAULT NULL COMMENT '用户ID',
  `username` varchar(100) DEFAULT NULL COMMENT '用户昵称',
  `caption` text COMMENT '作品标题',
  `like_count` int(11) DEFAULT '0' COMMENT '点赞数',
  `view_count` int(11) DEFAULT '0' COMMENT '播放量',
  `forward_count` int(11) DEFAULT '0' COMMENT '转发数',
  `comment_count` int(11) DEFAULT '0' COMMENT '评论数',
  `media_url` text COMMENT '视频URL',
  `thumb_url` text COMMENT '封面URL',
  `avatar_url` text COMMENT '头像URL',
  `publish_time` bigint(20) DEFAULT NULL COMMENT '发布时间戳(毫秒)',
  `publish_date` datetime DEFAULT NULL COMMENT '发布时间',
  `fans_count` int(11) DEFAULT '0' COMMENT '粉丝数',
  `broker_id` bigint(20) DEFAULT NULL COMMENT '经纪人ID',
  `broker_name` varchar(100) DEFAULT NULL COMMENT '经纪人姓名',
  `sub_biz_id` int(11) DEFAULT NULL COMMENT '违规类型ID',
  `sub_biz` varchar(50) DEFAULT NULL COMMENT '违规类型名称',
  `status` int(11) DEFAULT NULL COMMENT '状态: 1-可申诉, 2-申诉中, 3-不可申诉',
  `status_desc` varchar(50) DEFAULT NULL COMMENT '状态描述',
  `negative_audit_time` bigint(20) DEFAULT NULL COMMENT '违规审核时间戳',
  `reason` text COMMENT '违规原因',
  `suggestion` text COMMENT '改进建议',
  `appeal_status` int(11) DEFAULT NULL COMMENT '申诉状态',
  `appeal_status_desc` varchar(50) DEFAULT NULL COMMENT '申诉状态描述',
  `appeal_detail` text COMMENT '申诉详情',
  `punish_time` bigint(20) DEFAULT NULL COMMENT '处罚时间戳',
  `org_id` int(11) DEFAULT '1' COMMENT '所属机构ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_photo_id` (`photo_id`) USING BTREE,
  KEY `idx_user_id` (`user_id`) USING BTREE,
  KEY `idx_sub_biz` (`sub_biz`) USING BTREE,
  KEY `idx_publish_time` (`publish_time`) USING BTREE,
  KEY `idx_punish_time` (`punish_time`) USING BTREE,
  KEY `idx_spark_violation_photos_org_id` (`org_id`)
) ENGINE=InnoDB AUTO_INCREMENT=40105 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='违规作品表';

-- ============================================================
-- Table: system_announcements    Rows: 4
-- ============================================================
DROP TABLE IF EXISTS `system_announcements`;
CREATE TABLE `system_announcements` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '公告ID',
  `title` varchar(200) NOT NULL COMMENT '公告标题',
  `content` text NOT NULL COMMENT '公告内容',
  `link_url` varchar(500) DEFAULT NULL COMMENT '链接地址(可选)',
  `link_text` varchar(100) DEFAULT NULL COMMENT '链接文字(可选)',
  `is_enabled` tinyint(1) DEFAULT '1' COMMENT '是否启用: 1=启用, 0=禁用',
  `priority` int(11) DEFAULT '0' COMMENT '优先级(数字越大越优先)',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `target_roles` text COMMENT '目标角色(JSON数组)',
  `target_users` text COMMENT '目标用户ID(JSON数组)',
  `attachments` text COMMENT '附件列表(JSON数组)',
  `platform` varchar(20) DEFAULT 'web' COMMENT '平台类型: web=网页版, client=客户端',
  PRIMARY KEY (`id`),
  KEY `idx_enabled` (`is_enabled`),
  KEY `idx_priority` (`priority`),
  KEY `idx_platform` (`platform`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COMMENT='系统公告表';

-- ============================================================
-- Table: task_statistics    Rows: 84212
-- ============================================================
DROP TABLE IF EXISTS `task_statistics`;
CREATE TABLE `task_statistics` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `uid` varchar(50) NOT NULL COMMENT '快手账号UID',
  `device_serial` varchar(50) DEFAULT NULL COMMENT '设备序列号',
  `drama_link` varchar(500) DEFAULT NULL COMMENT '短剧链接',
  `drama_name` varchar(200) DEFAULT NULL COMMENT '短剧名称',
  `task_type` varchar(50) DEFAULT NULL COMMENT '任务类型（短剧/商品/合集）',
  `task_config` json DEFAULT NULL COMMENT '任务配置（JSON格式）',
  `status` varchar(20) NOT NULL COMMENT '任务状态（success/failed/pending）',
  `error_message` text COMMENT '错误信息',
  `start_time` datetime DEFAULT NULL COMMENT '开始时间',
  `end_time` datetime DEFAULT NULL COMMENT '结束时间',
  `duration` int(11) DEFAULT NULL COMMENT '执行时长（秒）',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_uid` (`uid`) USING BTREE,
  KEY `idx_device` (`device_serial`) USING BTREE,
  KEY `idx_status` (`status`) USING BTREE,
  KEY `idx_task_type` (`task_type`) USING BTREE,
  KEY `idx_created_at` (`created_at`) USING BTREE,
  KEY `idx_task_uid` (`uid`),
  KEY `idx_task_created_at` (`created_at`),
  KEY `idx_task_status` (`status`),
  KEY `idx_task_uid_created` (`uid`,`created_at`),
  KEY `idx_task_created_status` (`created_at`,`status`),
  KEY `idx_task_drama_name` (`drama_name`)
) ENGINE=InnoDB AUTO_INCREMENT=90128 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='任务执行统计表';

-- ============================================================
-- Table: tv_dramas    Rows: 391
-- ============================================================
DROP TABLE IF EXISTS `tv_dramas`;
CREATE TABLE `tv_dramas` (
  `id` int(11) NOT NULL,
  `platform` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `drama_name` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `category` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `hashtag` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- Table: tv_episodes    Rows: 7496
-- ============================================================
DROP TABLE IF EXISTS `tv_episodes`;
CREATE TABLE `tv_episodes` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `photo_id` varchar(64) NOT NULL COMMENT '视频ID',
  `collection_id` varchar(64) NOT NULL COMMENT '合集ID',
  `collection_name` varchar(255) DEFAULT NULL COMMENT '合集名称',
  `collection_like_count` bigint(20) DEFAULT '0' COMMENT '合集点赞数',
  `collection_view_count` bigint(20) DEFAULT '0' COMMENT '合集播放量',
  `episode_number` int(11) DEFAULT NULL COMMENT '集数',
  `episode_name` varchar(100) DEFAULT NULL COMMENT '集名',
  `caption` text COMMENT '标题/描述',
  `duration_ms` int(11) DEFAULT NULL COMMENT '时长(毫秒)',
  `like_count` int(11) DEFAULT '0' COMMENT '点赞数',
  `view_count` int(11) DEFAULT '0' COMMENT '播放量',
  `comment_count` int(11) DEFAULT '0' COMMENT '评论数',
  `forward_count` int(11) DEFAULT '0' COMMENT '转发数',
  `collect_count` int(11) DEFAULT '0' COMMENT '收藏数',
  `share_count` int(11) DEFAULT '0' COMMENT '分享数',
  `author_user_id` bigint(20) DEFAULT NULL COMMENT '作者用户ID',
  `author_user_name` varchar(100) DEFAULT NULL COMMENT '作者用户名',
  `timestamp` bigint(20) DEFAULT NULL COMMENT '发布时间戳',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `share_user_id` varchar(255) DEFAULT '' COMMENT '分享用户id',
  `share_photo_id` varchar(255) DEFAULT '' COMMENT '分享作品id',
  `drama_id` int(11) DEFAULT NULL COMMENT '剧集id',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_photo_id` (`photo_id`),
  KEY `idx_collection_id` (`collection_id`),
  KEY `idx_episode_number` (`episode_number`),
  KEY `idx_author_user_id` (`author_user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7846 DEFAULT CHARSET=utf8mb4 COMMENT='视频集数表';

-- ============================================================
-- Table: tv_publish_record    Rows: 6
-- ============================================================
DROP TABLE IF EXISTS `tv_publish_record`;
CREATE TABLE `tv_publish_record` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `drama_id` int(11) DEFAULT NULL COMMENT '剧集id',
  `uid` int(11) DEFAULT NULL COMMENT '快手号',
  `collection_id` varchar(64) CHARACTER SET utf8mb4 NOT NULL COMMENT '合集ID',
  `episode_number` int(11) DEFAULT NULL COMMENT '集数',
  `photo_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT '作品id',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='发布记录表';

-- ============================================================
-- Table: user_button_permissions    Rows: 57042
-- ============================================================
DROP TABLE IF EXISTS `user_button_permissions`;
CREATE TABLE `user_button_permissions` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL COMMENT '用户ID',
  `button_key` varchar(100) NOT NULL COMMENT '按钮标识',
  `is_allowed` tinyint(1) DEFAULT '1' COMMENT '是否允许: 1=允许, 0=禁止',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_user_button` (`user_id`,`button_key`) USING BTREE,
  KEY `idx_user_id` (`user_id`) USING BTREE,
  KEY `idx_button_key` (`button_key`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=64044 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='用户按钮权限表';

-- ============================================================
-- Table: user_page_permissions    Rows: 33564
-- ============================================================
DROP TABLE IF EXISTS `user_page_permissions`;
CREATE TABLE `user_page_permissions` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL COMMENT '用户ID',
  `page_key` varchar(100) NOT NULL COMMENT '页面标识',
  `is_allowed` tinyint(1) DEFAULT '1' COMMENT '是否允许: 1=允许, 0=禁止',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_user_page` (`user_id`,`page_key`) USING BTREE,
  KEY `idx_user_id` (`user_id`) USING BTREE,
  KEY `idx_page_key` (`page_key`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=39434 DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COMMENT='用户页面权限表';

-- ============================================================
-- Table: wait_collect_videos    Rows: 21170
-- ============================================================
DROP TABLE IF EXISTS `wait_collect_videos`;
CREATE TABLE `wait_collect_videos` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '短剧名称',
  `username` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所属用户',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '创建时间',
  `url` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '短剧链接',
  `platform` tinyint(1) NOT NULL DEFAULT '1' COMMENT '平台类型: 1=快手, 2=抖音',
  `cover_url` text COLLATE utf8mb4_unicode_ci COMMENT '封面链接',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_user_created` (`username`,`created_at`) USING BTREE,
  KEY `idx_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=127701 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='待收藏短剧';
