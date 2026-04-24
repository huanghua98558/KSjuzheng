# MCN MySQL Schema Dump

- **DB**: `shortju` @ `im.zhongxiangbao.com:3306`
- **Tables**: 50
- **Generated**: 2026-04-20T06:36:04

## 总览

| # | Table | Rows | Columns | PK | Comment |
|---|---|---|---|---|---|
| 1 | `account_groups` | 1,593 | 8 | id |  |
| 2 | `account_summary` | 1,354 | 8 | id | 账号统计汇总表 |
| 3 | `admin_operation_logs` | 27,463 | 11 | id |  |
| 4 | `admin_users` | 1,419 | 29 | id |  |
| 5 | `auto_devices` | 472 | 14 | id | AutoJs设备表 |
| 6 | `auto_device_accounts` | 641 | 8 | id | AutoJs设备快手账号表 |
| 7 | `auto_task_history` | 17,745 | 17 | id | AutoJs任务执行历史记录表 |
| 8 | `card_keys` | 8 | 9 | id | 卡密管理表 |
| 9 | `card_usage_logs` | 54 | 5 | id | 卡密使用日志表 |
| 10 | `cloud_cookie_accounts` | 876 | 16 | id | 云端Cookie账号表 |
| 11 | `collect_pool_auth_codes` | 1,423 | 8 | id | 收藏池授权码表 |
| 12 | `cxt_author` | 298 | 5 | id | 橙心推影视对标达人 |
| 13 | `cxt_titles` | 6,096 | 3 | id | 橙心推剧名表 |
| 14 | `cxt_user` | 150 | 5 | id | 橙星推验证表 |
| 15 | `cxt_videos` | 1,503 | 17 | id | 橙星推剧集表 |
| 16 | `drama_collections` | 113,257 | 10 | id | 短剧收藏记录表 |
| 17 | `drama_execution_logs` | 0 | 10 | id | 短剧执行日志表 |
| 18 | `firefly_income` | 3,558 | 15 | id | 萤光收益表 |
| 19 | `firefly_members` | 218 | 12 | id |  |
| 20 | `fluorescent_income` | 29,472 | 11 | id | 荧光计划收益表 |
| 21 | `fluorescent_income_archive` | 12,489 | 16 | id | 荧光计划成员收益存档表 |
| 22 | `fluorescent_members` | 18,812 | 11 | member_id | 荧光计划成员表 |
| 23 | `iqiyi_videos` | 7,313 | 16 | id | 爱奇艺影视数据表 |
| 24 | `ks_account` | 23,251 | 5 | id |  |
| 25 | `ks_episodes` | 1,043 | 22 | id | 快手短剧集数表 |
| 26 | `kuaishou_accounts` | 23,075 | 26 | id | 快手账号信息表 |
| 27 | `kuaishou_account_bindings` | 2 | 8 | id | 快手账号绑定表 |
| 28 | `kuaishou_urls` | 1,734,694 | 5 | id | 短剧成功链接库 |
| 29 | `mcm_organizations` | 17 | 8 | id | MCM机构表 |
| 30 | `mcn_verification_logs` | 493,549 | 7 | id | MCN验证审计日志 |
| 31 | `operator_quota` | 0 | 5 | id | 操作员配额表 |
| 32 | `page_permissions` | 21,578 | 6 | id |  |
| 33 | `role_default_permissions` | 246 | 7 | id | 角色默认权限配置表 |
| 34 | `spark_drama_info` | 126,296 | 25 | id | 快手短剧信息表 |
| 35 | `spark_highincome_dramas` | 432 | 3 | id |  |
| 36 | `spark_income` | 80 | 12 | id | 星火计划收益记录表 |
| 37 | `spark_income_archive` | 3,315 | 18 | id | 星火计划成员收益存档表 |
| 38 | `spark_members` | 1,198 | 13 | id | 星火计划成员表 |
| 39 | `spark_org_members` | 6,029 | 25 | id | 机构成员管理表 |
| 40 | `spark_photos` | 0 | 17 | id | 星火计划作品表 |
| 41 | `spark_violation_dramas` | 2,434 | 20 | id | 星火计划违规短剧表 |
| 42 | `spark_violation_photos` | 32,497 | 31 | id | 违规作品表 |
| 43 | `system_announcements` | 4 | 13 | id | 系统公告表 |
| 44 | `task_statistics` | 84,212 | 13 | id | 任务执行统计表 |
| 45 | `tv_dramas` | 391 | 5 | id |  |
| 46 | `tv_episodes` | 7,496 | 24 | id | 视频集数表 |
| 47 | `tv_publish_record` | 6 | 6 | id | 发布记录表 |
| 48 | `user_button_permissions` | 57,042 | 6 | id | 用户按钮权限表 |
| 49 | `user_page_permissions` | 33,564 | 6 | id | 用户页面权限表 |
| 50 | `wait_collect_videos` | 21,170 | 7 | id | 待收藏短剧 |

---

## 详情

### `account_groups`

**Rows**: 1,593  
**Columns**: 8  
**Indexes**: 5

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `group_name` | `varchar(100)` | N | UNI |  |  |  |
| `description` | `varchar(500)` | Y |  | `` |  |  |
| `color` | `varchar(20)` | Y |  | `#409EFF` |  |  |
| `sort_order` | `int(11)` | Y | MUL | `0` |  |  |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |
| `owner_id` | `int(11)` | Y | MUL |  |  | 所属用户ID |

**Indexes**:
  - `group_name` (UNIQUE `group_name`)
  - `idx_group_name` (`group_name`)
  - `idx_owner_id` (`owner_id`)
  - `idx_sort_order` (`sort_order`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1790,
    "group_name": "晓",
    "description": "晓的账号分组",
    "color": "#409EFF",
    "sort_order": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14",
    "owner_id": 873
  },
  {
    "id": 1789,
    "group_name": "自己的",
    "description": "",
    "color": "#409EFF",
    "sort_order": 0,
    "created_at": "2026-04-19T22:22:49",
    "updated_at": "2026-04-19T22:22:56",
    "owner_id": 982
  },
  {
    "id": 1787,
    "group_name": "梁",
    "description": "",
    "color": "#409EFF",
    "sort_order": 0,
    "created_at": "2026-04-19T22:14:39",
    "updated_at": "2026-04-19T22:14:39",
    "owner_id": 657
  }
]
```

### `account_summary`

**Rows**: 1,354  
**Columns**: 8  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `uid` | `varchar(50)` | N | UNI |  |  | 快手账号UID |
| `total_tasks` | `int(11)` | Y |  | `0` |  | 总任务数 |
| `success_tasks` | `int(11)` | Y |  | `0` |  | 成功任务数 |
| `failed_tasks` | `int(11)` | Y |  | `0` |  | 失败任务数 |
| `last_task_time` | `datetime` | Y |  |  |  | 最后任务时间 |
| `success_rate` | `decimal(5,2)` | Y | MUL |  |  | 成功率（%） |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_success_rate` (`success_rate`)
  - `idx_uid` (`uid`)
  - `PRIMARY` (UNIQUE `id`)
  - `uid` (UNIQUE `uid`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 72015,
    "uid": "API:大小姐她心动了",
    "total_tasks": 1,
    "success_tasks": 1,
    "failed_tasks": 0,
    "last_task_time": "2026-04-20T01:04:43",
    "success_rate": 100.0,
    "updated_at": "2026-04-20T01:04:50"
  },
  {
    "id": 72012,
    "uid": "API:错把保姆当亲妈",
    "total_tasks": 2,
    "success_tasks": 0,
    "failed_tasks": 2,
    "last_task_time": "2026-04-20T01:02:42",
    "success_rate": 0.0,
    "updated_at": "2026-04-20T01:02:43"
  },
  {
    "id": 72004,
    "uid": "API:哎呀你怎么又哭了",
    "total_tasks": 1,
    "success_tasks": 1,
    "failed_tasks": 0,
    "last_task_time": "2026-04-20T00:50:59",
    "success_rate": 100.0,
    "updated_at": "2026-04-20T00:51:02"
  }
]
```

### `admin_operation_logs`

**Rows**: 27,463  
**Columns**: 11  
**Indexes**: 5

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `user_id` | `int(11)` | N | MUL |  |  | 操作用户ID |
| `username` | `varchar(50)` | N |  |  |  | 操作用户名 |
| `action` | `varchar(50)` | N | MUL |  |  | 操作类型 |
| `module` | `varchar(50)` | N | MUL |  |  | 操作模块 |
| `target` | `varchar(100)` | Y |  | `` |  | 操作目标 |
| `detail` | `text` | Y |  |  |  | 详细信息 |
| `ip` | `varchar(50)` | Y |  | `` |  | IP地址 |
| `user_agent` | `varchar(500)` | Y |  | `` |  | 浏览器信息 |
| `status` | `varchar(20)` | Y |  | `success` |  | 操作状态 |
| `created_at` | `datetime` | Y | MUL | `CURRENT_TIMESTAMP` |  |  |

**Indexes**:
  - `idx_action` (`action`)
  - `idx_created_at` (`created_at`)
  - `idx_module` (`module`)
  - `idx_user_id` (`user_id`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 55798,
    "user_id": 1216,
    "username": "15645518552",
    "action": "login",
    "module": "auth",
    "target": "15645518552",
    "detail": "管理员登录",
    "ip": "221.209.132.108",
    "user_agent": "Python-urllib/3.12",
    "status": "success",
    "created_at": "2026-04-20T06:32:38"
  },
  {
    "id": 55797,
    "user_id": 1257,
    "username": "xiaobaobei",
    "action": "login",
    "module": "auth",
    "target": "xiaobaobei",
    "detail": "管理员登录",
    "ip": "127.0.0.1",
    "user_agent": "Mozilla/5.0 (Linux; Android 16; V2528A Build/BP2A.250605.031.A3_V000L1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 XWEB/1460043 MMWEBSDK/20260202 MMWEBID/2589 REV/009df8df2977fdbf29f25db1f9f4439aab34be2f MicroMessenger/8.0.70.3060(0x2800463F) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    "status": "success",
    "created_at": "2026-04-20T06:16:08"
  },
  {
    "id": 55796,
    "user_id": 12,
    "username": "liuchu888",
    "action": "login",
    "module": "auth",
    "target": "liuchu888",
    "detail": "管理员登录",
    "ip": "171.114.179.165",
    "user_agent": "Python-urllib/3.12",
    "status": "success",
    "created_at": "2026-04-20T06:08:33"
  }
]
```

### `admin_users`

**Rows**: 1,419  
**Columns**: 29  
**Indexes**: 9

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `username` | `varchar(50)` | N | UNI |  |  |  |
| `password_hash` | `varchar(128)` | N |  |  |  |  |
| `password_salt` | `varchar(64)` | N |  |  |  |  |
| `nickname` | `varchar(100)` | Y |  | `` |  |  |
| `role` | `varchar(20)` | Y | MUL | `admin` |  |  |
| `is_active` | `tinyint(4)` | Y | MUL | `1` |  |  |
| `last_login` | `datetime` | Y |  |  |  |  |
| `login_count` | `int(11)` | Y |  | `0` |  |  |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |
| `avatar` | `varchar(255)` | Y |  | `` |  |  |
| `email` | `varchar(100)` | Y |  | `` |  |  |
| `phone` | `varchar(20)` | Y |  | `` |  |  |
| `default_auth_code` | `varchar(255)` | Y |  | `` |  | 默认授权码 |
| `user_level` | `varchar(20)` | Y |  | `normal` |  | 用户等级: normal=普通, enterprise=企业 |
| `quota` | `int(11)` | Y |  | `10` |  | 配额数量: -1表示无限 |
| `cooperation_type` | `varchar(20)` | Y |  | `cooperative` |  | 合作类型: cooperative=合作, non_cooperative=非合作 |
| `is_oem` | `tinyint(4)` | Y | MUL | `0` |  | 是否贴牌: 0=非贴牌, 1=贴牌 |
| `oem_name` | `varchar(100)` | Y |  | `` |  | 贴牌名称 |
| `oem_config` | `text` | Y |  |  |  | 贴牌配置项(JSON格式) |
| `parent_user_id` | `int(11)` | Y | MUL |  |  | 上级用户ID（团长创建的普通用户） |
| `commission_rate` | `decimal(5,2)` | Y |  | `100.00` |  | 分成比例(%)，默认100% |
| `commission_rate_visible` | `tinyint(4)` | Y |  | `0` |  | 分成比例可见: 0=不可见, 1=可见 |
| `commission_amount_visible` | `tinyint(4)` | Y |  | `0` |  | 分成金额可见: 0=不可见, 1=可见 |
| `allow_member_query` | `tinyint(4)` | Y |  | `1` |  | 是否允许成员数据公开查询: 0=否, 1=是 |
| `total_income_visible` | `tinyint(4)` | Y |  | `0` |  | 累计收入可见: 0=不可见, 1=可见 |
| `organization_access` | `int(11)` | Y | MUL |  |  | 所属机构ID(单个) |
| `alipay_info` | `text` | Y |  |  |  | 支付宝信息(JSON): {"name": "姓名", "account": "账号"} |

**Indexes**:
  - `idx_is_active` (`is_active`)
  - `idx_is_oem` (`is_oem`)
  - `idx_organization_access` (`organization_access`)
  - `idx_parent_role` (`parent_user_id, role`)
  - `idx_parent_user_id` (`parent_user_id`)
  - `idx_role` (`role`)
  - `idx_username` (`username`)
  - `PRIMARY` (UNIQUE `id`)
  - `username` (UNIQUE `username`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1502,
    "username": "xiao666666",
    "password_hash": "<redacted len=64>",
    "password_salt": "<redacted len=32>",
    "nickname": "晓",
    "role": "normal_user",
    "is_active": 1,
    "last_login": "2026-04-19T23:11:32",
    "login_count": 1,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T23:11:32",
    "avatar": "",
    "email": "",
    "phone": "<redacted>",
    "default_auth_code": "",
    "user_level": "enterprise",
    "quota": -1,
    "cooperation_type": "cooperative",
    "is_oem": 0,
    "oem_name": null,
    "oem_config": null,
    "parent_user_id": 873,
    "commission_rate": 70.0,
    "commission_rate_visible": 0,
    "commission_amount_visible": 1,
    "allow_member_query": 1,
    "total_income_visible": 0,
    "organization_access": 5,
    "alipay_info": null
  },
  {
    "id": 1501,
    "username": "liuhongyuan",
    "password_hash": "<redacted len=64>",
    "password_salt": "<redacted len=32>",
    "nickname": "刘宏源",
    "role": "normal_user",
    "is_active": 1,
    "last_login": "2026-04-19T22:07:08",
    "login_count": 1,
    "created_at": "2026-04-19T21:59:32",
    "updated_at": "2026-04-19T22:07:08",
    "avatar": "",
    "email": "",
    "phone": "<redacted>",
    "default_auth_code": "",
    "user_level": "enterprise",
    "quota": -1,
    "cooperation_type": "cooperative",
    "is_oem": 0,
    "oem_name": null,
    "oem_config": null,
    "parent_user_id": 622,
    "commission_rate": 70.0,
    "commission_rate_visible": 0,
    "commission_amount_visible": 1,
    "allow_member_query": 1,
    "total_income_visible": 0,
    "organization_access": 1,
    "alipay_info": null
  },
  {
    "id": 1500,
    "username": "18170966644",
    "password_hash": "<redacted len=64>",
    "password_salt": "<redacted len=32>",
    "nickname": "胡佳文",
    "role": "normal_user",
    "is_active": 1,
    "last_login": "2026-04-19T22:20:06",
    "login_count": 2,
    "created_at": "2026-04-19T21:21:23",
    "updated_at": "2026-04-19T22:20:06",
    "avatar": "",
    "email": "",
    "phone": "<redacted>",
    "default_auth_code": "",
    "user_level": "enterprise",
    "quota": -1,
    "cooperation_type": "cooperative",
    "is_oem": 0,
    "oem_name": null,
    "oem_config": null,
    "parent_user_id": 859,
    "commission_rate": 60.0,
    "commission_rate_visible": 0,
    "commission_amount_visible": 1,
    "allow_member_query": 1,
    "total_income_visible": 0,
    "organization_access": 5,
    "alipay_info": "{\"name\":\"胡佳文\",\"account\":\"18170966644\"}"
  }
]
```

### `auto_devices`

**Rows**: 472  
**Columns**: 14  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `device_id` | `varchar(255)` | N | UNI |  |  | 设备ID |
| `device_number` | `varchar(50)` | N | MUL |  |  | 设备编号 |
| `kuaishou_count` | `int(11)` | Y |  | `1` |  | 快手号数量 |
| `auth_code` | `varchar(100)` | N | MUL |  |  | 授权码 |
| `device_info` | `json` | Y |  |  |  | 设备信息 |
| `token` | `varchar(255)` | Y |  |  |  | 设备令牌 |
| `is_online` | `tinyint(1)` | Y |  | `0` |  | 是否在线 |
| `registered_at` | `bigint(20)` | Y |  |  |  | 注册时间 |
| `connected_at` | `bigint(20)` | Y |  |  |  | 连接时间 |
| `last_seen` | `bigint(20)` | Y | MUL |  |  | 最后心跳时间 |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |
| `accessibility_enabled` | `tinyint(1)` | N |  | `0` |  | 无障碍服务是否开启: 0=未开启, 1=已开启 |

**Indexes**:
  - `device_id` (UNIQUE `device_id`)
  - `idx_auth_code` (`auth_code`)
  - `idx_device_id` (`device_id`)
  - `idx_device_number` (`device_number`)
  - `idx_last_seen` (`last_seen`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 693,
    "device_id": "874c2430b500d2a2",
    "device_number": "测试机器",
    "kuaishou_count": 2,
    "auth_code": "liwenfeng888",
    "device_info": "{\"brand\": \"HUAWEI\", \"model\": \"CDY-AN00\", \"sdkInt\": 29, \"product\": \"CDY-AN00\", \"release\": \"10\"}",
    "token": "<redacted len=29>",
    "is_online": 0,
    "registered_at": null,
    "connected_at": 1775649769794,
    "last_seen": 1775649769794,
    "created_at": "2026-04-07T14:23:32",
    "updated_at": "2026-04-16T16:06:45",
    "accessibility_enabled": 1
  },
  {
    "id": 692,
    "device_id": "4da3352019fe94eb",
    "device_number": "晨光",
    "kuaishou_count": 1,
    "auth_code": "liangbaichuan",
    "device_info": "{\"brand\": \"HUAWEI\", \"model\": \"JEF-AN20\", \"sdkInt\": 31, \"product\": \"JEF-AN20\", \"release\": \"12\"}",
    "token": "<redacted len=29>",
    "is_online": 0,
    "registered_at": null,
    "connected_at": 1775951188691,
    "last_seen": 1775957531860,
    "created_at": "2026-03-16T11:39:13",
    "updated_at": "2026-04-12T09:32:19",
    "accessibility_enabled": 0
  },
  {
    "id": 691,
    "device_id": "b45a94d06db7be6f",
    "device_number": "3",
    "kuaishou_count": 1,
    "auth_code": "17832611609",
    "device_info": "{\"brand\": \"HONOR\", \"model\": \"KOZ-AL00\", \"sdkInt\": 29, \"product\": \"KOZ-AL00\", \"release\": \"10\"}",
    "token": "<redacted len=29>",
    "is_online": 0,
    "registered_at": null,
    "connected_at": 1773388239307,
    "last_seen": 1773401960231,
    "created_at": "2026-03-13T13:22:40",
    "updated_at": "2026-03-13T19:39:21",
    "accessibility_enabled": 1
  }
]
```

### `auto_device_accounts`

**Rows**: 641  
**Columns**: 8  
**Indexes**: 5

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `device_id` | `varchar(255)` | N | MUL |  |  | 设备ID |
| `account_index` | `int(11)` | N |  |  |  | 账号序号 |
| `nickname` | `varchar(255)` | N |  |  |  | 昵称 |
| `kwai_id` | `varchar(50)` | N | MUL |  |  | 快手号 |
| `package_name` | `varchar(100)` | Y |  |  |  | 快手应用包名 |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |

**Indexes**:
  - `idx_device_account` (`device_id, account_index`)
  - `idx_device_id` (`device_id`)
  - `idx_kwai_id` (`kwai_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_device_account` (UNIQUE `device_id, account_index`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1580,
    "device_id": "874c2430b500d2a2",
    "account_index": 2,
    "nickname": "琦小姐剧场",
    "kwai_id": "5277889929",
    "package_name": "com.smile.gifmaker",
    "created_at": "2026-04-07T14:24:35",
    "updated_at": "2026-04-07T14:24:35"
  },
  {
    "id": 1579,
    "device_id": "874c2430b500d2a2",
    "account_index": 1,
    "nickname": "小熙吧！",
    "kwai_id": "5277882855",
    "package_name": "com.smile.gifmaker",
    "created_at": "2026-04-07T14:24:35",
    "updated_at": "2026-04-07T14:24:35"
  },
  {
    "id": 1578,
    "device_id": "4c9e9788b2c3e58e",
    "account_index": 1,
    "nickname": "锦程影视",
    "kwai_id": "4775905589",
    "package_name": "com.smile.gifmaker",
    "created_at": "2026-04-06T00:00:52",
    "updated_at": "2026-04-06T00:00:52"
  }
]
```

### `auto_task_history`

**Rows**: 17,745  
**Columns**: 17  
**Indexes**: 8

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20) unsigned` | N | PRI |  | auto_increment |  |
| `task_id` | `varchar(255)` | N | UNI |  |  | 任务ID |
| `device_id` | `varchar(255)` | N | MUL |  |  | 设备ID |
| `device_number` | `varchar(100)` | Y | MUL |  |  | 设备编号 |
| `task_type` | `varchar(100)` | Y | MUL |  |  | 任务类型 |
| `plan_type` | `varchar(50)` | Y |  |  |  | 计划类型 |
| `status` | `varchar(50)` | N | MUL |  |  | 任务状态: PENDING, DISPATCHED, RECEIVED, RUNNING, C... |
| `progress` | `int(11)` | Y |  | `0` |  | 任务进度 0-100 |
| `progress_message` | `text` | Y |  |  |  | 进度消息 |
| `result` | `json` | Y |  |  |  | 任务执行结果 |
| `error` | `text` | Y |  |  |  | 错误信息 |
| `created_at` | `datetime` | N | MUL |  |  | 任务创建时间 |
| `dispatched_at` | `datetime` | Y |  |  |  | 任务下发时间 |
| `received_at` | `datetime` | Y |  |  |  | 任务接收时间 |
| `started_at` | `datetime` | Y |  |  |  | 任务开始时间 |
| `completed_at` | `datetime` | Y | MUL |  |  | 任务完成时间 |
| `updated_at` | `datetime` | N |  |  |  | 任务更新时间 |

**Indexes**:
  - `idx_completed_at` (`completed_at`)
  - `idx_created_at` (`created_at`)
  - `idx_device_id` (`device_id`)
  - `idx_device_number` (`device_number`)
  - `idx_status` (`status`)
  - `idx_task_type` (`task_type`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_task_id` (UNIQUE `task_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 20881,
    "task_id": "task_batch_1776125956210_84wzgccj0",
    "device_id": "c8deed74a0d2e42f",
    "device_number": "测试机器",
    "task_type": "KUAISHOU_COLLECT_BATCH",
    "plan_type": null,
    "status": "PENDING",
    "progress": 0,
    "progress_message": null,
    "result": null,
    "error": null,
    "created_at": "2026-04-14T08:19:16",
    "dispatched_at": null,
    "received_at": null,
    "started_at": null,
    "completed_at": null,
    "updated_at": "2026-04-14T08:19:16"
  },
  {
    "id": 20880,
    "task_id": "task_batch_1775910300381_mu7j64vau",
    "device_id": "69fc1ea10ad6ca7a",
    "device_number": "测试机器",
    "task_type": "KUAISHOU_COLLECT_BATCH",
    "plan_type": null,
    "status": "PENDING",
    "progress": 0,
    "progress_message": null,
    "result": null,
    "error": null,
    "created_at": "2026-04-11T20:25:00",
    "dispatched_at": null,
    "received_at": null,
    "started_at": null,
    "completed_at": null,
    "updated_at": "2026-04-11T20:25:00"
  },
  {
    "id": 20879,
    "task_id": "task_account_get_1775910287237_rpfsjadsb",
    "device_id": "69fc1ea10ad6ca7a",
    "device_number": "测试机器",
    "task_type": "KUAISHOU_GET_ACCOUNTS",
    "plan_type": null,
    "status": "COMPLETED",
    "progress": 0,
    "progress_message": null,
    "result": "{\"message\": \"任务执行成功\", \"accounts\": [{\"index\": 1, \"kwaiId\": \"5127137424\", \"nickname\": \"雅终点\", \"timestamp\": 1775910292888, \"packageName\": \"com.smile.gifmaker\", \"kuaishouMode\": \"official\"}], \"totalAccounts\": 1}",
    "error": null,
    "created_at": "2026-04-11T20:24:47",
    "dispatched_at": "2026-04-11T20:24:47",
    "received_at": null,
    "started_at": null,
    "completed_at": "2026-04-11T20:25:00",
    "updated_at": "2026-04-11T20:25:00"
  }
]
```

### `card_keys`

**Rows**: 8  
**Columns**: 9  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `card_code` | `varchar(16)` | N | UNI |  |  | 卡密(16位小写英文+数字) |
| `card_type` | `enum('monthly','quarterly')` | N |  |  |  | 卡类型: monthly=月卡, quarterly=季卡 |
| `status` | `enum('unused','active','used','expire...` | Y | MUL | `unused` |  | 状态: unused=未使用, active=已激活(可重复使用), used=已使用(一次性... |
| `created_by` | `int(11)` | N | MUL |  |  | 创建者管理员ID |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `used_at` | `timestamp` | Y |  |  |  | 使用时间 |
| `used_by_auth_code` | `varchar(255)` | Y | MUL |  |  | 绑定的授权码 |
| `expires_at` | `timestamp` | Y |  |  |  | 过期时间 |

**Indexes**:
  - `card_code` (UNIQUE `card_code`)
  - `idx_card_code` (`card_code`)
  - `idx_created_by` (`created_by`)
  - `idx_status` (`status`)
  - `idx_used_by_auth_code` (`used_by_auth_code`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 20,
    "card_code": "i86jmmvzre6t0vl6",
    "card_type": "quarterly",
    "status": "active",
    "created_by": 1,
    "created_at": "2026-02-12T22:06:39",
    "used_at": "2026-02-12T22:09:36",
    "used_by_auth_code": "cpkj888",
    "expires_at": "2026-05-12T22:09:37"
  },
  {
    "id": 19,
    "card_code": "rgs0v3ngj4oshjtp",
    "card_type": "monthly",
    "status": "unused",
    "created_by": 1,
    "created_at": "2026-02-12T21:00:41",
    "used_at": null,
    "used_by_auth_code": null,
    "expires_at": null
  },
  {
    "id": 18,
    "card_code": "tkdt1kvt7swne6e8",
    "card_type": "monthly",
    "status": "unused",
    "created_by": 1,
    "created_at": "2026-02-12T21:00:41",
    "used_at": null,
    "used_by_auth_code": null,
    "expires_at": null
  }
]
```

### `card_usage_logs`

**Rows**: 54  
**Columns**: 5  
**Indexes**: 2

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `card_code` | `varchar(16)` | N | MUL |  |  | 卡密 |
| `auth_code` | `varchar(255)` | Y |  |  |  | 授权码 |
| `action` | `enum('validated','activated','verifie...` | Y |  | `validated` |  | 操作类型 |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 记录时间 |

**Indexes**:
  - `idx_card_code` (`card_code`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 54,
    "card_code": "i86jmmvzre6t0vl6",
    "auth_code": "cpkj888",
    "action": "verified",
    "created_at": "2026-04-11T14:23:23"
  },
  {
    "id": 53,
    "card_code": "i86jmmvzre6t0vl6",
    "auth_code": "cpkj888",
    "action": "verified",
    "created_at": "2026-03-24T10:35:11"
  },
  {
    "id": 52,
    "card_code": "i86jmmvzre6t0vl6",
    "auth_code": "cpkj888",
    "action": "verified",
    "created_at": "2026-03-02T20:18:35"
  }
]
```

### `cloud_cookie_accounts`

**Rows**: 876  
**Columns**: 16  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `owner_code` | `varchar(50)` | N | MUL |  |  | 所有者标识码 |
| `device_serial` | `varchar(100)` | Y |  |  |  | 设备序列号 |
| `account_id` | `varchar(50)` | Y |  |  |  | 账号ID |
| `account_name` | `varchar(100)` | Y | MUL |  |  | 账号名称 |
| `kuaishou_uid` | `varchar(50)` | Y | MUL |  |  | 快手UID |
| `kuaishou_name` | `varchar(100)` | Y |  |  |  | 快手昵称 |
| `cookies` | `longtext` | Y |  |  |  | Cookie数据(JSON) |
| `login_status` | `varchar(20)` | Y |  | `logged_in` |  | 登录状态 |
| `login_time` | `datetime` | Y |  |  |  | 登录时间 |
| `browser_port` | `int(11)` | Y |  |  |  | 浏览器端口 |
| `success_count` | `int(11)` | Y |  | `0` |  | 成功次数 |
| `fail_count` | `int(11)` | Y |  | `0` |  | 失败次数 |
| `remark` | `varchar(255)` | Y |  |  |  | 备注 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_account_name` (`account_name`)
  - `idx_kuaishou_uid` (`kuaishou_uid`)
  - `idx_owner_code` (`owner_code`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 879,
    "owner_code": "潘总",
    "device_serial": "no_device",
    "account_id": "acc_ba41f11f",
    "account_name": "梦屿追剧人",
    "kuaishou_uid": "4685622854",
    "kuaishou_name": "",
    "cookies": "<redacted len=1299>",
    "login_status": "logged_in",
    "login_time": "2026-04-18T16:11:47",
    "browser_port": 9639,
    "success_count": 0,
    "fail_count": 0,
    "remark": null,
    "created_at": "2026-04-19T00:13:40",
    "updated_at": "2026-04-19T00:14:18"
  },
  {
    "id": 878,
    "owner_code": "潘总",
    "device_serial": "no_device",
    "account_id": "acc_464a15d2",
    "account_name": "帆沉默",
    "kuaishou_uid": "5081529934",
    "kuaishou_name": "",
    "cookies": "<redacted len=1299>",
    "login_status": "logged_in",
    "login_time": "2026-04-18T19:32:59",
    "browser_port": 9575,
    "success_count": 0,
    "fail_count": 0,
    "remark": null,
    "created_at": "2026-04-19T00:13:37",
    "updated_at": "2026-04-19T00:14:13"
  },
  {
    "id": 877,
    "owner_code": "潘总",
    "device_serial": "no_device",
    "account_id": "acc_34cbf646",
    "account_name": "我的剧本我做主",
    "kuaishou_uid": "5440744716",
    "kuaishou_name": "",
    "cookies": "<redacted len=1299>",
    "login_status": "logged_in",
    "login_time": "2026-04-18T15:11:05",
    "browser_port": 9615,
    "success_count": 0,
    "fail_count": 0,
    "remark": null,
    "created_at": "2026-04-19T00:13:36",
    "updated_at": "2026-04-19T00:14:13"
  }
]
```

### `collect_pool_auth_codes`

**Rows**: 1,423  
**Columns**: 8  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `auth_code` | `varchar(100)` | N | UNI |  |  | 授权码 |
| `name` | `varchar(100)` | Y |  | `` |  | 授权码名称/备注 |
| `is_active` | `tinyint(1)` | Y | MUL | `1` |  | 是否启用: 1=启用, 0=禁用 |
| `expire_at` | `datetime` | Y |  |  |  | 过期时间，NULL表示永不过期 |
| `created_by` | `int(11)` | Y |  |  |  | 创建人ID |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `auth_code` (UNIQUE `auth_code`)
  - `idx_auth_code` (`auth_code`)
  - `idx_is_active` (`is_active`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1498,
    "auth_code": "xiao666666",
    "name": "晓",
    "is_active": 1,
    "expire_at": null,
    "created_by": 873,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 1497,
    "auth_code": "liuhongyuan",
    "name": "刘宏源",
    "is_active": 1,
    "expire_at": null,
    "created_by": 622,
    "created_at": "2026-04-19T21:59:32",
    "updated_at": "2026-04-19T21:59:32"
  },
  {
    "id": 1496,
    "auth_code": "18170966644",
    "name": "胡佳文",
    "is_active": 1,
    "expire_at": null,
    "created_by": 859,
    "created_at": "2026-04-19T21:21:23",
    "updated_at": "2026-04-19T21:21:23"
  }
]
```

### `cxt_author`

**Rows**: 298  
**Columns**: 5  
**Indexes**: 1

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(10) unsigned` | N | PRI |  | auto_increment |  |
| `name` | `varchar(50)` | Y |  |  |  | 作者名称 |
| `author_id` | `varchar(100)` | Y |  |  |  | 作者id |
| `platform` | `tinyint(4) unsigned` | N |  | `0` |  | 平台 0.抖音 1.快手 |
| `type` | `tinyint(4) unsigned` | N |  | `0` |  | 类型 0.影视 1.短剧 |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 347,
    "name": "肖肖爱追剧",
    "author_id": "3xswc7wb5shgj2k",
    "platform": 1,
    "type": 1
  },
  {
    "id": 346,
    "name": "天意短剧",
    "author_id": "3xarbstgv9ta7j9",
    "platform": 1,
    "type": 1
  },
  {
    "id": 345,
    "name": "无敌的追剧大佬",
    "author_id": "3xvr3prqjqyguki",
    "platform": 1,
    "type": 1
  }
]
```

### `cxt_titles`

**Rows**: 6,096  
**Columns**: 3  
**Indexes**: 1

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(10) unsigned` | N | PRI |  | auto_increment |  |
| `title` | `varchar(50)` | N |  | `` |  | 剧名 |
| `type` | `tinyint(4) unsigned` | N |  | `0` |  | 类型 0.电影 1.电视剧 |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 6096,
    "title": "104号房间 第三季",
    "type": 1
  },
  {
    "id": 6095,
    "title": "星期五晚餐 第二季",
    "type": 1
  },
  {
    "id": 6094,
    "title": "极地恶灵 第二季",
    "type": 1
  }
]
```

### `cxt_user`

**Rows**: 150  
**Columns**: 5  
**Indexes**: 1

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(10) unsigned` | N | PRI |  | auto_increment |  |
| `uid` | `varchar(10)` | N |  |  |  | 橙星推uid |
| `note` | `varchar(50)` | Y |  |  |  | 备注 |
| `auth_code` | `varchar(50)` | Y |  |  |  | 授权码 |
| `status` | `tinyint(4) unsigned` | Y |  | `0` |  | 状态 0.待审核 1.审核通过 2.禁用 |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 168,
    "uid": "661569744",
    "note": "TT",
    "auth_code": "wanglei999",
    "status": 1
  },
  {
    "id": 167,
    "uid": "661569736",
    "note": "阿伟",
    "auth_code": "xtc677899",
    "status": 1
  },
  {
    "id": 166,
    "uid": "661567610",
    "note": "星辰辰光",
    "auth_code": "zhj1989",
    "status": 1
  }
]
```

### `cxt_videos`

**Rows**: 1,503  
**Columns**: 17  
**Indexes**: 3

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `sec_user_id` | `varchar(200)` | Y | MUL |  |  | 作者id |
| `title` | `varchar(500)` | Y |  |  |  | 剧名 |
| `author` | `varchar(100)` | Y |  |  |  | 作者 |
| `aweme_id` | `varchar(100)` | Y | MUL |  |  | 作品id |
| `description` | `text` | Y |  |  |  | 作品描述 |
| `video_url` | `text` | Y |  |  |  | 视频地址 |
| `cover_url` | `text` | Y |  |  |  | 封面地址 |
| `duration` | `int(11)` | Y |  |  |  | 时长 |
| `comment_count` | `int(11)` | Y |  |  |  | 评论数 |
| `collect_count` | `int(11)` | Y |  |  |  | 收藏数 |
| `recommend_count` | `int(11)` | Y |  |  |  | 推荐数 |
| `share_count` | `int(11)` | Y |  |  |  | 分享数 |
| `play_count` | `int(11)` | Y |  |  |  | 播放数 |
| `digg_count` | `int(11)` | Y |  |  |  | 点赞数 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `platform` | `tinyint(4) unsigned` | N |  | `0` |  | 平台 0.抖音 1.快手 2.橙心推官方链接 |

**Indexes**:
  - `idx_aweme_id` (`aweme_id`)
  - `idx_sec_user_id` (`sec_user_id`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 9959,
    "sec_user_id": "MS4wLjABAAAA7aU4P3-zqA7lmO6e4YoLM7RdCiNTwJ6S3hIAmrpCJ_s",
    "title": "皇家女将",
    "author": "莫涵影视",
    "aweme_id": "7624843345596290981",
    "description": "",
    "video_url": "https://www.douyin.com/aweme/v1/play/?video_id=v1e00fgi0000d78e4tvog65irigrat20&line=0&file_id=53f0fa01fa6041d0ae9a7af9a8891b01&sign=7e43a1d356baf2624de05396590a0870&is_play_url=1&source=PackSourceEnum_PUBLISH",
    "cover_url": "https://p9-pc-sign.douyinpic.com/tos-cn-p-0015c000-ce/oQ0hvcTIYo7bDgeQACLTAxeGgQ8A6JUTecoBVL~tplv-dy-cropcenter:323:430.jpeg?lk3s=138a59ce&x-expires=2091866400&x-signature=3fzwE4ewqtrH0Bl%2FQn4nefARj6M%3D&from=327834062&s=PackSourceEnum_PUBLISH&se=true&sh=323_430&sc=cover&biz_tag=pcweb_cover&l=20260418185731AEA2E1D20850CB87D25C",
    "duration": 39,
    "comment_count": null,
    "collect_count": null,
    "recommend_count": null,
    "share_count": null,
    "play_count": null,
    "digg_count": null,
    "created_at": "2026-04-18T18:58:47",
    "platform": 0
  },
  {
    "id": 9957,
    "sec_user_id": "MS4wLjABAAAAwYbU8FqkHaFKyRS55vuVBIvFSN_rnIvTF0pyb5AMk3A",
    "title": "勇者行动",
    "author": "毒说影视",
    "aweme_id": "7593738000962571529",
    "description": "",
    "video_url": "https://www.douyin.com/aweme/v1/play/?video_id=v0d00fg10000d5h5u7vog65j2ucia6pg&line=0&file_id=a25905456e464e7dab3402730430aa67&sign=537f372bce786bce5203bde5792b36e1&is_play_url=1&source=PackSourceEnum_PUBLISH",
    "cover_url": "https://p3-pc-sign.douyinpic.com/tos-cn-i-dy/123cf9d08aa447b5a6134c3278d15e64~tplv-dy-cropcenter:323:430.jpeg?lk3s=138a59ce&x-expires=2091330000&x-signature=%2BwUowFG%2BYq%2FQVUu4gFdp9mvlLpo%3D&from=327834062&s=PackSourceEnum_PUBLISH&se=true&sh=323_430&sc=cover&biz_tag=pcweb_cover&l=202604121327330FAA23912496525D8B49",
    "duration": 936,
    "comment_count": null,
    "collect_count": null,
    "recommend_count": null,
    "share_count": null,
    "play_count": null,
    "digg_count": null,
    "created_at": "2026-04-12T13:28:10",
    "platform": 0
  },
  {
    "id": 9956,
    "sec_user_id": "3xk4cmsengbwp6i",
    "title": "杀人鲸",
    "author": "扶摇电影剪辑",
    "aweme_id": "3xm7jvrhfd6yhuw",
    "description": "",
    "video_url": "https://k0uday1dyc6y19zw2408x8722xd000x8x8000xx19z.djvod.ndcimgs.com/upic/2026/01/21/16/BMjAyNjAxMjExNjMzNDRfMzI5NTMyMjNfMTg1NTg3MTA5NTUwXzBfMw==_b_B5bcc3d10c0e8c9d66d9c7ba39e9e7fe5.mp4?tag=1-1775887321-unknown-0-mwyqkfmags-0d828dfefa622f05&provider=self&clientCacheKey=3xm7jvrhfd6yhuw_b.mp4&di=3d36ef59&bp=14730&x-ks-ptid=185587109550&kwai-not-alloc=self-cdn&kcdntag=p:Henan;i:ChinaUnicom;ft:UNKNOWN;h:COLD;pn:kuaishouVideoProjection&ocid=300000669&tt=b&ss=vps",
    "cover_url": "https://p2.a.yximgs.com/upic/2026/01/21/16/BMjAyNjAxMjExNjMzNDRfMzI5NTMyMjNfMTg1NTg3MTA5NTUwXzBfMw==_ccc_Bc0200430db1db628648be0b6bbecdff9.jpg?tag=1-1775887322-xpcwebprofile-0-6z0yu3o45p-9b7f7bb58fbcce2a&clientCacheKey=3xm7jvrhfd6yhuw_ccc.jpg&di=3d36ef59&bp=14734",
    "duration": 860,
    "comment_count": null,
    "collect_count": null,
    "recommend_count": null,
    "share_count": null,
    "play_count": null,
    "digg_count": null,
    "created_at": "2026-04-11T14:06:09",
    "platform": 1
  }
]
```

### `drama_collections`

**Rows**: 113,257  
**Columns**: 10  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `kuaishou_uid` | `varchar(50)` | N | MUL |  |  | 快手账号UID |
| `kuaishou_name` | `varchar(100)` | Y |  |  |  | 快手账号名称 |
| `device_serial` | `varchar(50)` | Y |  |  |  | 设备序列号 |
| `drama_name` | `varchar(200)` | N | MUL |  |  | 短剧名称 |
| `drama_url` | `varchar(500)` | Y |  |  |  | 短剧链接 |
| `plan_mode` | `varchar(20)` | Y | MUL | `spark` |  | 平台模式: spark=星火计划, firefly=萤火计划 |
| `actual_drama_name` | `varchar(200)` | Y |  | `` |  | 实际短剧名称 |
| `collected_at` | `datetime` | Y | MUL | `CURRENT_TIMESTAMP` |  | 收藏时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_collected_at` (`collected_at`)
  - `idx_drama_name` (`drama_name`)
  - `idx_kuaishou_uid` (`kuaishou_uid`)
  - `idx_plan_mode` (`plan_mode`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_uid_drama_mode` (UNIQUE `kuaishou_uid, drama_name, plan_mode`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 161818,
    "kuaishou_uid": "1987222806",
    "kuaishou_name": "清晨短剧",
    "device_serial": "6HJDU19610013225",
    "drama_name": "你若无情我便休",
    "drama_url": "https://www.kuaishou.com/f/X-2kbJ8AAAjjt2mO",
    "plan_mode": "spark",
    "actual_drama_name": "",
    "collected_at": "2026-04-17T13:22:28",
    "updated_at": "2026-04-17T13:22:28"
  },
  {
    "id": 161817,
    "kuaishou_uid": "2118741855",
    "kuaishou_name": "小詹剧场",
    "device_serial": "6HJDU19609002838",
    "drama_name": "跪乳之恩",
    "drama_url": "https://www.kuaishou.com/f/X-aWESa4kddPsARz",
    "plan_mode": "spark",
    "actual_drama_name": "",
    "collected_at": "2026-04-17T13:19:21",
    "updated_at": "2026-04-17T13:19:21"
  },
  {
    "id": 161816,
    "kuaishou_uid": "1948780671",
    "kuaishou_name": "杉杉短剧",
    "device_serial": "6HJDU19610013225",
    "drama_name": "真千金她命格无双",
    "drama_url": "https://www.kuaishou.com/f/X1Cxv2u4lXtz1uw",
    "plan_mode": "spark",
    "actual_drama_name": "",
    "collected_at": "2026-04-17T13:17:58",
    "updated_at": "2026-04-17T13:17:58"
  }
]
```

### `drama_execution_logs`

**Rows**: 0  
**Columns**: 10  
**Indexes**: 5

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment | 日志ID |
| `uid` | `varchar(50)` | N | MUL |  |  | 账号UID |
| `device_serial` | `varchar(50)` | Y | MUL | `` |  | 设备序列号 |
| `drama_name` | `varchar(200)` | Y |  | `` |  | 短剧名称 |
| `episode_number` | `int(11)` | Y |  | `0` |  | 集数 |
| `status` | `varchar(20)` | N | MUL |  |  | 状态：success/failed |
| `duration` | `int(11)` | Y |  | `0` |  | 执行时长(秒) |
| `error_message` | `text` | Y |  |  |  | 错误信息 |
| `created_at` | `datetime` | Y | MUL | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `config_data` | `json` | Y |  |  |  | 任务配置信息(JSON格式) |

**Indexes**:
  - `idx_created_at` (`created_at`)
  - `idx_device` (`device_serial`)
  - `idx_status` (`status`)
  - `idx_uid` (`uid`)
  - `PRIMARY` (UNIQUE `id`)


### `firefly_income`

**Rows**: 3,558  
**Columns**: 15  
**Indexes**: 8

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `income_date` | `date` | N | MUL |  |  | 收益时间 |
| `video_id` | `varchar(50)` | N |  |  |  | 视频ID |
| `video_url` | `varchar(500)` | Y |  | `` |  | 视频链接 |
| `author_id` | `varchar(50)` | N | MUL |  |  | 作者ID |
| `author_nickname` | `varchar(100)` | Y | MUL | `` |  | 作者昵称 |
| `task_name` | `varchar(200)` | Y | MUL | `` |  | 任务名称 |
| `monetize_type` | `varchar(50)` | Y |  | `` |  | 变现类型 |
| `upload_date` | `date` | Y |  |  |  | 上传日期 |
| `settlement_amount` | `decimal(10,2)` | Y |  | `0.00` |  | 达人结算金额 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |
| `commission_rate` | `decimal(5,2)` | Y | MUL | `100.00` |  | 分成比例(%)，默认100% |
| `settlement_status` | `varchar(20)` | Y | MUL | `unsettled` |  | 结算状态: settled=已结清, unsettled=未结清 |
| `commission_amount` | `decimal(10,2)` | Y |  |  | STORED GENERATED | 扣除分成金额（自动计算） |

**Indexes**:
  - `idx_author_id` (`author_id`)
  - `idx_author_nickname` (`author_nickname`)
  - `idx_commission_rate` (`commission_rate`)
  - `idx_income_date` (`income_date`)
  - `idx_settlement_status` (`settlement_status`)
  - `idx_task_name` (`task_name`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_date_video` (UNIQUE `income_date, video_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 3604,
    "income_date": "2026-02-24",
    "video_id": "188618602798",
    "video_url": "https://www.kuaishou.com/short-video/3xtbbmtruekypr2",
    "author_id": "5284074770",
    "author_nickname": "蒋道道",
    "task_name": "反千1",
    "monetize_type": "IAA",
    "upload_date": "2026-02-21",
    "settlement_amount": 0.01,
    "created_at": "2026-02-26T12:35:56",
    "updated_at": "2026-02-26T12:35:56",
    "commission_rate": 100.0,
    "settlement_status": "unsettled",
    "commission_amount": 0.01
  },
  {
    "id": 3603,
    "income_date": "2026-02-24",
    "video_id": "188593615087",
    "video_url": "https://www.kuaishou.com/short-video/3xcjmpt2q8a8m59",
    "author_id": "4786767305",
    "author_nickname": "开心每一天",
    "task_name": "花开染墨痕",
    "monetize_type": "IAA",
    "upload_date": "2026-02-21",
    "settlement_amount": 0.01,
    "created_at": "2026-02-26T12:35:56",
    "updated_at": "2026-02-26T12:35:56",
    "commission_rate": 100.0,
    "settlement_status": "unsettled",
    "commission_amount": 0.01
  },
  {
    "id": 3602,
    "income_date": "2026-02-24",
    "video_id": "188597851557",
    "video_url": "https://www.kuaishou.com/short-video/3xgqe2w8udxucie",
    "author_id": "430717902",
    "author_nickname": "一缕阳光短剧",
    "task_name": "再见只能说一次",
    "monetize_type": "IAP",
    "upload_date": "2026-02-21",
    "settlement_amount": 0.01,
    "created_at": "2026-02-26T12:35:56",
    "updated_at": "2026-02-26T12:35:56",
    "commission_rate": 100.0,
    "settlement_status": "unsettled",
    "commission_amount": 0.01
  }
]
```

### `firefly_members`

**Rows**: 218  
**Columns**: 12  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `author_id` | `varchar(100)` | N | UNI |  |  |  |
| `author_name` | `varchar(255)` | Y |  |  |  |  |
| `total_income` | `decimal(12,2)` | Y | MUL | `0.00` |  |  |
| `period_income` | `decimal(12,2)` | Y |  | `0.00` |  |  |
| `period_start` | `date` | Y |  |  |  |  |
| `period_end` | `date` | Y |  |  |  |  |
| `record_count` | `int(11)` | Y |  | `0` |  |  |
| `first_income_date` | `date` | Y |  |  |  |  |
| `last_income_date` | `date` | Y |  |  |  |  |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |

**Indexes**:
  - `author_id` (UNIQUE `author_id`)
  - `idx_author_id` (`author_id`)
  - `idx_total_income` (`total_income`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 317,
    "author_id": "5267053095",
    "author_name": "必看短剧",
    "total_income": 17.85,
    "period_income": 0.0,
    "period_start": "2026-02-25",
    "period_end": "2026-03-24",
    "record_count": 2,
    "first_income_date": "2026-02-24",
    "last_income_date": "2026-02-24",
    "created_at": "2026-02-26T12:35:56",
    "updated_at": "2026-02-26T12:35:56"
  },
  {
    "id": 316,
    "author_id": "5204036227",
    "author_name": "小桃木短剧",
    "total_income": 0.08,
    "period_income": 0.0,
    "period_start": "2026-02-25",
    "period_end": "2026-03-24",
    "record_count": 1,
    "first_income_date": "2026-02-24",
    "last_income_date": "2026-02-24",
    "created_at": "2026-02-26T12:35:56",
    "updated_at": "2026-02-26T12:35:56"
  },
  {
    "id": 315,
    "author_id": "5017032983",
    "author_name": "无必",
    "total_income": 0.05,
    "period_income": 0.0,
    "period_start": "2026-02-25",
    "period_end": "2026-03-24",
    "record_count": 1,
    "first_income_date": "2026-02-24",
    "last_income_date": "2026-02-24",
    "created_at": "2026-02-26T12:35:56",
    "updated_at": "2026-02-26T12:35:56"
  }
]
```

### `fluorescent_income`

**Rows**: 29,472  
**Columns**: 11  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment |  |
| `member_id` | `bigint(20)` | N | MUL |  |  | 成员ID |
| `member_name` | `varchar(100)` | N |  |  |  | 成员昵称 |
| `task_id` | `varchar(50)` | Y | MUL | `` |  | 任务ID |
| `task_name` | `varchar(200)` | Y |  | `` |  | 任务名称 |
| `task_start_time` | `varchar(20)` | Y | MUL | `` |  | 任务开始时间(YYYYMMDD) |
| `income` | `decimal(10,2)` | Y |  | `0.00` |  | 收益金额 |
| `settlement_status` | `varchar(20)` | N | MUL | `unsettled` |  | 结算状态: settled=已结清, unsettled=未结清 |
| `org_id` | `int(11) unsigned` | Y |  | `1` |  | 所属机构ID |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_member_id` (`member_id`)
  - `idx_settlement_status` (`settlement_status`)
  - `idx_task_id` (`task_id`)
  - `idx_task_start_time` (`task_start_time`)
  - `idx_unique` (UNIQUE `member_id, task_id`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 48762,
    "member_id": 3912528893,
    "member_name": "皮皮分享好物",
    "task_id": "335465",
    "task_name": "蓝道风云2",
    "task_start_time": "20260214",
    "income": 0.01,
    "settlement_status": "unsettled",
    "org_id": 5,
    "created_at": "2026-04-13T16:49:18",
    "updated_at": "2026-04-13T16:49:18"
  },
  {
    "id": 48761,
    "member_id": 3294687995,
    "member_name": "追剧小亮相",
    "task_id": "276997",
    "task_name": "爱恨难明1",
    "task_start_time": "20260203",
    "income": 0.01,
    "settlement_status": "unsettled",
    "org_id": 5,
    "created_at": "2026-04-13T16:49:12",
    "updated_at": "2026-04-13T16:49:12"
  },
  {
    "id": 48760,
    "member_id": 2112109818,
    "member_name": "仔子",
    "task_id": "250979",
    "task_name": "陆总今天要离婚",
    "task_start_time": "20260120",
    "income": 0.01,
    "settlement_status": "unsettled",
    "org_id": 5,
    "created_at": "2026-04-13T16:49:07",
    "updated_at": "2026-04-13T16:49:07"
  }
]
```

### `fluorescent_income_archive`

**Rows**: 12,489  
**Columns**: 16  
**Indexes**: 7

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment |  |
| `member_id` | `bigint(20)` | N | MUL |  |  | 成员ID |
| `member_name` | `varchar(100)` | N |  |  |  | 成员昵称 |
| `member_head` | `varchar(500)` | Y |  |  |  | 头像URL |
| `fans_count` | `int(11)` | Y | MUL | `0` |  | 粉丝数 |
| `in_limit` | `tinyint(1)` | Y |  | `0` |  | 是否限额(0=否,1=是) |
| `broker_name` | `varchar(50)` | Y | MUL | `未分配` |  | 经纪人名称 |
| `org_task_num` | `int(11)` | Y |  | `0` |  | 机构任务数 |
| `total_amount` | `decimal(10,2)` | Y |  | `0.00` |  | 总金额 |
| `settlement_status` | `varchar(20)` | N | MUL | `unsettled` |  | 结算状态: settled=已结清, unsettled=未结清 |
| `archive_month` | `int(11)` | N |  |  |  | 收益所属月份(1-12) |
| `archive_year` | `int(11)` | N | MUL |  |  | 收益所属年份 |
| `start_time` | `bigint(20)` | Y |  |  |  | 开始时间戳(毫秒) |
| `end_time` | `bigint(20)` | Y |  |  |  | 结束时间戳(毫秒) |
| `archived_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 存档时间 |
| `org_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |

**Indexes**:
  - `idx_archive_period` (`archive_year, archive_month`)
  - `idx_broker_name` (`broker_name`)
  - `idx_fans_count` (`fans_count`)
  - `idx_member_id` (`member_id`)
  - `idx_org_id` (`org_id`)
  - `idx_settlement_status` (`settlement_status`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 27826,
    "member_id": 5415016278,
    "member_name": "带玉的玉爱看短剧",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/04/02/13/BMjAyNjA0MDIxMzI0NTNfNTQxNTAxNjI3OF8yX2hkMTM3XzUw_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "settlement_status": "unsettled",
    "archive_month": 3,
    "archive_year": 2026,
    "start_time": 1772294400000,
    "end_time": 1774972799999,
    "archived_at": "2026-04-02T19:06:22",
    "org_id": 9
  },
  {
    "id": 27825,
    "member_id": 5414798964,
    "member_name": "欣紫爱看剧",
    "member_head": "https://p4-pro.a.yximgs.com/uhead/AB/2026/04/02/10/BMjAyNjA0MDIxMDExMzVfNTQxNDc5ODk2NF8xX2hkNDg0XzcxNQ==_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "settlement_status": "unsettled",
    "archive_month": 3,
    "archive_year": 2026,
    "start_time": 1772294400000,
    "end_time": 1774972799999,
    "archived_at": "2026-04-02T19:06:22",
    "org_id": 9
  },
  {
    "id": 27824,
    "member_id": 5414409087,
    "member_name": "菲菲爱短剧",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/04/01/23/BMjAyNjA0MDEyMzU1MTFfNTQxNDQwOTA4N18yX2hkOTM5XzU1_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "settlement_status": "unsettled",
    "archive_month": 3,
    "archive_year": 2026,
    "start_time": 1772294400000,
    "end_time": 1774972799999,
    "archived_at": "2026-04-02T19:06:22",
    "org_id": 9
  }
]
```

### `fluorescent_members`

**Rows**: 18,812  
**Columns**: 11  
**Indexes**: 7

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `member_id` | `bigint(20)` | N | PRI |  |  | 成员ID |
| `member_name` | `varchar(100)` | N | MUL |  |  | 成员昵称 |
| `member_head` | `varchar(500)` | Y |  |  |  | 头像URL |
| `fans_count` | `int(11)` | Y |  | `0` |  | 粉丝数 |
| `in_limit` | `tinyint(1)` | Y |  | `0` |  | 是否限额(0=否,1=是) |
| `broker_name` | `varchar(50)` | Y |  | `未分配` |  | 经纪人名称 |
| `org_task_num` | `int(11)` | Y |  | `0` |  | 机构任务数 |
| `total_amount` | `decimal(10,2)` | Y | MUL | `0.00` |  | 总金额 |
| `org_id` | `int(11) unsigned` | Y | MUL | `1` |  | 所属机构ID |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_member_id` (`member_id`)
  - `idx_member_name_search` (`member_name`)
  - `idx_member_org` (`member_id, org_id`)
  - `idx_org_id` (`org_id`)
  - `idx_org_member_cover` (`org_id, member_id`)
  - `idx_total_amount` (`total_amount`)
  - `PRIMARY` (UNIQUE `member_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "member_id": 5445062710,
    "member_name": "源君剧场",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/04/19/17/BMjAyNjA0MTkxNzUwMjhfNTQ0NTA2MjcxMF8xX2hkMTEzXzgzNw==_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "org_id": 1,
    "created_at": "2026-04-19T18:22:35",
    "updated_at": "2026-04-19T18:22:35"
  },
  {
    "member_id": 5445034939,
    "member_name": "君源剧场",
    "member_head": "https://p5-pro.a.yximgs.com/uhead/AB/2026/04/19/17/BMjAyNjA0MTkxNzM0NTJfNTQ0NTAzNDkzOV8xX2hkNjE4XzU4OA==_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "org_id": 1,
    "created_at": "2026-04-19T18:22:35",
    "updated_at": "2026-04-19T18:22:35"
  },
  {
    "member_id": 5444970634,
    "member_name": "   ",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/04/19/16/BMjAyNjA0MTkxNjU4MDlfNTQ0NDk3MDYzNF8yX2hkOTYwXzQ2Nw==_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "org_id": 1,
    "created_at": "2026-04-19T18:22:35",
    "updated_at": "2026-04-19T18:22:35"
  }
]
```

### `iqiyi_videos`

**Rows**: 7,313  
**Columns**: 16  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11) unsigned` | N | PRI |  | auto_increment |  |
| `block_id` | `varchar(32)` | Y | MUL | `` |  | Block唯一ID |
| `title` | `varchar(255)` | N | MUL | `` |  | 片名 |
| `subtitle` | `varchar(500)` | Y |  | `` |  | 副标题/宣传语 |
| `category` | `tinyint(1) unsigned` | N |  | `0` |  | 类型:1=电影,2=电视剧,4=动漫,6=综艺 |
| `score` | `varchar(50)` | Y |  | `` |  | 评分或集数状态 |
| `cover_url` | `varchar(500)` | Y |  | `` |  | 封面图URL |
| `status_mark` | `varchar(100)` | Y |  | `` |  | 播放状态标识 |
| `album_id` | `varchar(32)` | Y | MUL | `` |  | 专辑ID |
| `tv_id` | `varchar(32)` | Y |  | `` |  | 视频ID |
| `s_target` | `varchar(64)` | Y |  | `` |  | 搜索文档ID |
| `share_url` | `varchar(500)` | N |  | `` |  | 分享链接 |
| `raw_data` | `text` | Y |  |  |  | 原始JSON数据 |
| `createtime` | `int(11) unsigned` | Y |  |  |  |  |
| `updatetime` | `int(11) unsigned` | Y |  |  |  |  |
| `platform` | `tinyint(4) unsigned` | N |  | `0` |  | 平台: 0=爱奇艺,1=优酷 |

**Indexes**:
  - `album_id` (`album_id`)
  - `block_id` (`block_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `title_category_platform` (UNIQUE `title, category, platform`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 7902,
    "block_id": "",
    "title": "妻子的新世界",
    "subtitle": "",
    "category": 2,
    "score": "",
    "cover_url": "",
    "status_mark": "",
    "album_id": "",
    "tv_id": "",
    "s_target": "",
    "share_url": "",
    "raw_data": null,
    "createtime": 1776253728,
    "updatetime": 1776253728,
    "platform": 2
  },
  {
    "id": 7901,
    "block_id": "",
    "title": "火影忍者忍者之路",
    "subtitle": "",
    "category": 1,
    "score": "",
    "cover_url": "",
    "status_mark": "",
    "album_id": "",
    "tv_id": "",
    "s_target": "",
    "share_url": "",
    "raw_data": null,
    "createtime": 1776253728,
    "updatetime": 1776253728,
    "platform": 2
  },
  {
    "id": 7900,
    "block_id": "",
    "title": "摄影机不要停！",
    "subtitle": "",
    "category": 1,
    "score": "",
    "cover_url": "",
    "status_mark": "",
    "album_id": "",
    "tv_id": "",
    "s_target": "",
    "share_url": "",
    "raw_data": null,
    "createtime": 1776253728,
    "updatetime": 1776253728,
    "platform": 2
  }
]
```

### `ks_account`

**Rows**: 23,251  
**Columns**: 5  
**Indexes**: 2

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `username` | `varchar(255)` | Y |  |  |  | 账号名称 |
| `uid` | `varchar(255)` | Y |  |  |  | 快手号 |
| `device_num` | `varchar(255)` | Y | MUL |  |  | 设备码 |
| `uid_real` | `varchar(50)` | Y |  |  |  | 快手真实UID |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)
  - `uk_device_uid` (UNIQUE `device_num, uid`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 57976,
    "username": "cy.",
    "uid": "1434328025",
    "device_num": "b4170b2f-cd48-416d-8e5c-7146b7a117b8",
    "uid_real": "1434328025"
  },
  {
    "id": 57975,
    "username": "大润发购物商品",
    "uid": "su903609",
    "device_num": "c43ef331-b342-4e70-b6f2-faf697555f18",
    "uid_real": "1802884899"
  },
  {
    "id": 57974,
    "username": "陈嘉瑟",
    "uid": "1781536351",
    "device_num": "10a89c18-b2a8-47a8-a5db-d7cfcee72512",
    "uid_real": "1781536351"
  }
]
```

### `ks_episodes`

**Rows**: 1,043  
**Columns**: 22  
**Indexes**: 5

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment | 主键ID |
| `photo_id` | `varchar(64)` | N | UNI |  |  | 视频ID |
| `serial_id` | `varchar(64)` | Y | MUL |  |  | 剧集ID |
| `episode_number` | `int(11)` | Y | MUL |  |  | 集数 |
| `episode_name` | `varchar(100)` | Y |  |  |  | 集名 |
| `caption` | `text` | Y |  |  |  | 标题/描述 |
| `duration_ms` | `int(11)` | Y |  |  |  | 时长(毫秒) |
| `like_count` | `int(11)` | Y |  | `0` |  | 点赞数 |
| `view_count` | `int(11)` | Y |  | `0` |  | 播放量 |
| `comment_count` | `int(11)` | Y |  | `0` |  | 评论数 |
| `forward_count` | `int(11)` | Y |  | `0` |  | 转发数 |
| `serial_title` | `varchar(255)` | Y |  |  |  | 剧集名称 |
| `episode_count` | `int(11)` | Y |  |  |  | 总集数 |
| `author_user_id` | `bigint(20)` | Y | MUL |  |  | 作者用户ID |
| `author_user_name` | `varchar(100)` | Y |  |  |  | 作者用户名 |
| `video_url` | `text` | Y |  |  |  | 视频URL |
| `cover_url` | `text` | Y |  |  |  | 封面URL |
| `share_user_id` | `varchar(255)` | Y |  | `` |  | 分享用户id |
| `share_photo_id` | `varchar(255)` | Y |  | `` |  | 分享作品id |
| `raw_json` | `json` | Y |  |  |  | 原始JSON数据 |
| `created_at` | `timestamp` | N |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | N |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_author_user_id` (`author_user_id`)
  - `idx_episode_number` (`episode_number`)
  - `idx_serial_id` (`serial_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_photo_id` (UNIQUE `photo_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1108,
    "photo_id": "5215168549769632965",
    "serial_id": "15338428",
    "episode_number": 5,
    "episode_name": "第5集",
    "caption": "第5集｜#重生救赎路#重生救赎路免费全集",
    "duration_ms": 222366,
    "like_count": 1,
    "view_count": 18,
    "comment_count": 0,
    "forward_count": 0,
    "serial_title": "重生救赎路",
    "episode_count": 80,
    "author_user_id": 1975784546,
    "author_user_name": "小鹿爱看剧",
    "video_url": "http://v23-3.kwaicdn.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_b_B870d0766711f3842495afc76885d770a.mp4?pkey=AAVnkJ60K2X2IpKqMPfmWn3iuXHgk8U9tfIfzrtaHCoRDBpTb1cXZgMnzPtjvOB16i5VByBMJgivemDBO0KUopf2GZVguXc4J1Q2dAtkK-G9VaCoA9_U2VAorjxyQXmb24Y&tag=1-1774008654-collectionbase-0-j8qrodhwhg-989e4d63045701eb&clientCacheKey=3xfz7i5zwg66s26_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001",
    "cover_url": "http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_low_B58196672a2da9d7d58106b82fb498283.webp?tag=1-1774008654-collectionbase-0-m4dkfn8uoy-cdb271a86661bfbb&clientCacheKey=3xfz7i5zwg66s26_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001",
    "share_user_id": "3xs4fg4mnyqzm6u",
    "share_photo_id": "3xfz7i5zwg66s26",
    "raw_json": "{\"ptp\": \"\", \"tags\": [], \"time\": \"2025-12-08 21:43:06\", \"type\": 1, \"us_c\": 0, \"us_d\": 1, \"us_l\": true, \"liked\": 0, \"caption\": \"第5集｜#重生救赎路#重生救赎路免费全集\", \"exp_tag\": \"1_u/2009469870535023697_collectionbase0\", \"user_id\": 1975784546, \"duration\": 222366, \"editInfo\": {}, \"headurls\": [{\"cdn\": \"p4.a.yximgs.com\", \"url\": \"http://p4.a.yximgs.com/uhead/AB/2020/06/17/14/BMjAyMDA2MTcxNDQ1MzFfMTk3NTc4NDU0Nl8xX2hkODA0Xzg4MQ==_s.jpg\"}, {\"cdn\": \"p2.a.yximgs.com\", \"url\": \"http://p2.a.yximgs.com/uhead/AB/2020/06/17/14/BMjAyMDA2MTcxNDQ1MzFfMTk3NTc4NDU0Nl8xX2hkODA0Xzg4MQ==_s.jpg\"}], \"location\": {}, \"photo_id\": 5215168549769632965, \"recoTags\": [], \"user_sex\": \"F\", \"verified\": false, \"adminTags\": [], \"following\": 0, \"longVideo\": true, \"musicDisk\": {\"expand\": false}, \"sameFrame\": {\"allow\": false}, \"timestamp\": 1765201386836, \"user_name\": \"小鹿爱看剧\", \"ext_params\": {\"h\": 1280, \"w\": 720, \"color\": \"48280E\", \"mtype\": 3, \"sound\": 222379, \"video\": 222366, \"interval\": 30}, \"feedLogCtx\": {\"stExParams\": \"\", \"stidContainer\": \"Ck8xfDIwMDk0Njk4NzA1MzUwMjM2OTd8cGhvdG86NTIxNTE2ODU0OTc2OTYzMjk2NXx7InBnIjoiY29sbGVjdGlvbmJhc2UifXx7InIiOjB9\"}, \"fixedColor\": \"332d29\", \"frameStyle\": 0, \"like_count\": 1, \"shareGuide\": {\"playTimes\": 2, \"photoShareGuide\": false, \"minPlayDurationInSeconds\": 15, \"textDisplayDurationInSeconds\": 4}, \"share_info\": \"userId=3xs4fg4mnyqzm6u&photoId=3xfz7i5zwg66s26\", \"view_count\": 18, \"danmakuInfo\": {\"paster\": false, \"hetuList\": [5718, 52320, 483936], \"defaultDanmaku\": \"发个友善的弹幕吧\", \"photoDanmakuGuide\": false, \"danmakuShowDirection\": 2}, \"followShoot\": {\"isLipsSyncPhoto\": false}, \"recommended\": 2, \"share_count\": 0, \"supportType\": 0, \"feedSwitches\": {\"enablePlayerPanel\": true, \"disable61ActivityAnimation\": true, \"disableCommentLikeAnimation\": false, \"enablePictureCommentForPhoto\": true}, \"main_mv_urls\": [{\"cdn\": \"v23-3.kwaicdn.com\", \"url\": \"http://v23-3.kwaicdn.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_b_B870d0766711f3842495afc76885d770a.mp4?pkey=AAVnkJ60K2X2IpKqMPfmWn3iuXHgk8U9tfIfzrtaHCoRDBpTb1cXZgMnzPtjvOB16i5VByBMJgivemDBO0KUopf2GZVguXc4J1Q2dAtkK-G9VaCoA9_U2VAorjxyQXmb24Y&tag=1-1774008654-collectionbase-0-j8qrodhwhg-989e4d63045701eb&clientCacheKey=3xfz7i5zwg66s26_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\", \"feature\": [1]}, {\"cdn\": \"v4.oskwai.com\", \"url\": \"http://v4.oskwai.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_b_B870d0766711f3842495afc76885d770a.mp4?pkey=AAWXQQTA33SEGo292bNvnNcod5vODRR45LXkgFO5IGKY5Vkk-v3PC8NHc7djx6YGvGhr2bSAt2cGCb6P25T0ychR7EYNwWDrapr2xOAblaViZDtJ70_UiOpn5bnZR3-9FoY&tag=1-1774008654-collectionbase-1-ykeltjpuuk-ff6b85b6eb423bac&clientCacheKey=3xfz7i5zwg66s26_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\", \"feature\": [1]}], \"photo_status\": 0, \"serverExpTag\": \"feed_photo|5215168549769632965|1975784546|1_u/2009469870535023697_collectionbase0\", \"collect_count\": 0, \"comment_count\": 0, \"forward_count\": 0, \"myRecommended\": {\"recommended\": 2, \"recommendUsers\": 0, \"recommendTagGuideConfig\": {\"exitStyle\": {\"exitByUnClick\": [{\"exitTime\": 43200, \"showCount\": 5}, {\"exitTime\": 4320, \"showCount\": 3}, {\"exitTime\": 2880, \"showCount\": 2}]}, \"showStyle\": {\"type\": \"delay\", \"delayTime\": 3000}, \"frequencyStyle\": {\"showLimitByInterval\": {\"showInterval\": 72, \"maxShowCountByInterval\": 3}}}, \"recommendTextOnlyYouFormat\": \"你推荐了视频\", \"recommendTextOnlyFriendFormat\": \"%s位朋友推荐\", \"recommendTextYouAndFriendFormat\": \"你和%s位朋友推荐\"}, \"tag_hash_type\": 1, \"standardSerial\": {\"photo\": {\"caption\": \"第5集｜重生救赎路免费全集\", \"episodeName\": \"第5集\", \"episodeNumber\": 5, \"isLastEpisode\": false, \"originCaption\": \"#重生救赎路#重生救赎路免费全集\", \"isFirstEpisode\": false}, \"serial\": {\"id\": \"5xepyuzi3azutys\", \"type\": 1, \"title\": \"重生救赎路\", \"subType\": 2, \"decryptId\": \"15338428\", \"viewCount\": 565, \"panelTitle\": \"短剧 · 重生救赎路 | 共80集\", \"collectName\": \"短剧 · 重生救赎路\", \"isCollected\": false, \"moduleTitle\": \"合集 · 重生救赎路\", \"adoptionType\": 0, \"businessType\": 0, \"customParams\": {\"tags\": [], \"orgType\": 1, \"isFinished\": true, \"description\": \"剧情介绍：一场车祸，父亲和弟弟生命垂危，女儿却选择谁也不救，只因为十年前，父亲阻挠她与富二代在一起，她一直怀恨在心。 当父女二人带着各自的遗憾和怨恨重生，他们都做出了与上一世截然不同的选择。 父亲不再干涉女儿的选择，想到上一世因为贫困交不起手术费的场景，他下定决心搞钱，抓住风口炒股炒房很快成为富可敌国的神秘大佬。 而女儿坚定地选择富二代，认为父亲只会一辈子穷困潦倒拖累自己，毅然决然和他断绝父女关系，却不想富二代真如父亲所说，只是一个贪图她年轻美貌的人渣，甚至在父亲富可敌国的身份曝光后，富二代不惜利用她将亲弟弟骗出来绑架，以此勒索父亲。 生死一线，孝顺的儿子和不孝的女儿二选一，被伤透心的父亲又会怎样选择？\", \"nextEpisodeUrl\": \"\", \"seriesAdConfig\": {\"lessonId\": 0, \"seriesId\": 0, \"bannerAdGap\": 0, \"showNeoTask\": 0, \"iaaRightType\": 0, \"lookLateType\": 0, \"supportBannerAd\": false, \"hasSVipCardRight\": false, \"unlockSeriesAdType\": 0}, \"tubeStreamType\": 1, \"bottomNormalUrl\": \"kwai://episode/play?serialId=15338428&serialType=1&photoId=5215168549769632965&selectedPhotoId=5215168549769632965&sourcePhotoPage=collectionbase&autoShowPanel=true\", \"serialNameActionUrl\": \"kwai://episode/play?serialId=15338428&serialType=1&photoId=5215168549769632965&selectedPhotoId=5215168549769632965&sourcePhotoPage=collectionbase&autoShowPanel=true\", \"verticalTubeIaaAdTime\": 3, \"commercialMiniSeriesType\": 1, \"commercialBottomBarTagInfo\": {\"imageUrl\": \"https://p4-ad.adkwai.com/kcdn/cdn-kcdn111976/minfeibiaoqian.png\", \"imageWidth\": 26, \"imageHeight\": 16}, \"enabledNewCommercialTubeSelectionPanel\": true}, \"episodeCount\": 80, \"isFollowUpdate\": false, \"detailPhotoTags\": \"短剧 热血逆袭\", \"freeEpisodeCount\": 50, \"isMmuBackupTitle\": false, \"paidEpisodeCount\": 30, \"panelDescription\": \"重生救赎路\", \"tubeEntranceCard\": {\"payTag\": false, \"tubeTag\": \"热血逆袭\", \"tubeType\": 1, \"promptInfo\": \"观看完整短剧\", \"episodeInfo\": \"全80集\", \"playStrategy\": 0, \"tubeDescription\": \"一场车祸，父亲和弟弟生命垂危，女儿却选择谁也不救，只因为十年前，父亲阻挠她与富二代在一起，她一直怀恨在心。 当父女二人带着各自的遗憾和怨恨重生，他们都做出了与上一世截然不同的选择。 父亲不再干涉女儿的选择，想到上一世因为贫困交不起手术费的场景，他下定决心搞钱，抓住风口炒股炒房很快成为富可敌国的神秘大佬。 而女儿坚定地选择富二代，认为父亲只会一辈子穷困潦倒拖累自己，毅然决然和他断绝父女关系，却不想富二代真如父亲所说，只是一个贪图她年轻美貌的人渣，甚至在父亲富可敌国的身份曝光后，富二代不惜利用她将亲弟弟骗出来绑架，以此勒索父亲。 生死一线，孝顺的儿子和不孝的女儿二选一，被伤透心的父亲又会怎样选择？\", \"intoSquareActionUrl\": \"kwai://krn?bundleId=OperationTubeCenterHome&componentName=TubeCenterHome&useMultiTabContainer=1&sourceType=4&rootPhotoPage=collectionbase\", \"intoSquarePromptInfo\": \"更多短剧\"}, \"latestDescription\": \"共80集\", \"entranceDescription\": \"重生救赎路 · 更新至80集\", \"enableSerialNewStyle\": false, \"splitEntranceDescription\": {\"title\": \"短剧 · 重生救赎路\", \"continueInfo\": \"共80集\"}, \"isClusterSerialOrSubDetailFeed\": false, \"tubeInfoPanelElementMiniTkVersion\": 0}, \"contentType\": 0, \"tubePageUrl\": \"kwai://krn?bundleId=OperationTubeCenterHome&componentName=TubeCenterHome&useMultiTabContainer=1&sourceType=94&rootPhotoPage=tih\"}, \"streamManifest\": {\"version\": \"2.0.0\", \"videoId\": \"0ecdf0fb68b3b483\", \"hideAuto\": false, \"playInfo\": {\"bizType\": 1, \"strategyBus\": \"{\\n  \\\"photoFlag\\\" : 1,\\n  \\\"isFreeNode\\\" : 0,\\n  \\\"photoScore\\\" : {\\n    \\\"commonLightnessScore\\\" : 9,\\n    \\\"gmvClarityScore\\\" : 1,\\n    \\\"commonLightness2Score\\\" : 0,\\n    \\\"commonClarity3Score\\\" : 1,\\n    \\\"commonClarityScore\\\" : 6,\\n    \\\"gmvClarity2Score\\\" : 3,\\n    \\\"commonKs1080pScore\\\" : 0,\\n    \\\"commonLoudScore\\\" : 0,\\n    \\\"commonPunishScore\\\" : 0,\\n    \\\"commonStarScore\\\" : 0,\\n    \\\"commonClarity2Score\\\" : 90,\\n    \\\"adPostScore\\\" : 1,\\n    \\\"commonMarkScore\\\" : 0,\\n    \\\"commonGovScore\\\" : 0,\\n    \\\"commonNb1080pScore\\\" : 0,\\n    \\\"commonEqualizerScore\\\" : 0,\\n    \\\"gmvPostScore\\\" : 1,\\n    \\\"commonLpmScore\\\" : 9\\n  },\\n  \\\"trKvqLimit\\\" : 3.6\\n}\", \"cdnTimeRangeLevel\": 1}, \"mediaType\": 2, \"stereoType\": 0, \"audioFeature\": {\"audioSnr\": 11.6286, \"audioClip\": 0.2003, \"audioQuality\": 74.2585, \"musicProbability\": 0.4957, \"dialogProbability\": 0.4921, \"stereophonicRichness\": 99.9491, \"effectiveBandwidthInHz\": 15705.789, \"backgroundSoundProbability\": 0.0122}, \"businessType\": 2, \"videoFeature\": {\"yMean\": 107.34801, \"contrast\": 0.00059488416, \"mosScore\": 0.8553060293197632, \"yMeanMax\": 127.29128, \"yMeanMin\": 30.870518, \"avgEntropy\": 10.179308485984802, \"underExposed\": 0.000011116266, \"blurProbability\": 0.06474609673023224, \"blockyProbability\": 0.4992585778236389}, \"adaptationSet\": [{\"id\": 1, \"duration\": 222379, \"representation\": [{\"id\": 1, \"agc\": false, \"url\": \"http://k0u3by39ycy11zw240ex964xea00x71bxx11z.djvod.ndcimgs.com/ksc1/R32vX0DkQlSp76ccqGnKUnw5q2099gpAazkSapKljU_3wOsBKmGMpRCxBQwcxOmr0oDpmbqdWkfaIrU58iFcZYttPN2f3Pd6R5r7baFZwSDPmT7l8mohctoIOaBJKDt6n5HOL0_ABiiDK0zpqChQ_7x4Y0BMLNQyy5yIVc-pEfVyV-YkaflSYCPexg2GNQer.mp4?tag=1-1774008654-collectionbase-0-5ijdlxrwfv-ab8b28e16caf29ac&provider=self&clientCacheKey=3xfz7i5zwg66s26_b.mp4&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001&x-ks-ptid=181858472208&kwai-not-alloc=self-cdn&kcdntag=p:Fujian;i:ChinaTelecom;ft:UNKNOWN;h:COLD;pn:kuaishouVideoProjection&ocid=6&tt=b&ss=vpm\", \"mute\": false, \"width\": 720, \"height\": 1280, \"hidden\": false, \"comment\": \"videoId=0ecdf0fb68b3b483/ttExplain=AVC_VeryFast_720P_高码率_Basic/tt=b\", \"hdrType\": 0, \"quality\": 1.5, \"fileSize\": 34499440, \"kvqScore\": {\"FR\": -1, \"NR\": -1, \"FRPost\": -1, \"NRPost\": -1}, \"p2spCode\": \"{\\\"fRsn\\\":0,\\\"fixOpt\\\":-1,\\\"schTask\\\":\\\"\\\",\\\"schCode\\\":-1,\\\"schRes\\\":\\\"\\\",\\\"pushTask\\\":\\\"v=0&p=0&s=0&d=0\\\",\\\"pushCode\\\":-1}\", \"backupUrl\": [\"http://v23-3.kwaicdn.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_b_B870d0766711f3842495afc76885d770a.mp4?pkey=AAXQru__5OUnQZDA4Yj5KW-IsfuArjEpDhTinsVwvRxFrtIIx_5F4IM6aEDLrNrMu__yFdYM_w5Wr5KZFHAwHwv2JfJJI75NdgIIZwNbPnolBW-P5dnUiPaKxsy5NMYdovk&tag=1-1774008654-collectionbase-1-jb9lfa7xrf-0dc8a8f1512b1d1d&clientCacheKey=3xfz7i5zwg66s26_b.mp4&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001&kwai-not-alloc=0&type=cold&tt=b&ss=vpm\"], \"frameRate\": 30, \"minorInfo\": \"-b2f1\", \"avgBitrate\": 1241, \"makeupGain\": 0, \"maxBitrate\": 3300, \"videoCodec\": \"avc\", \"volumeInfo\": {\"th\": -23.3, \"tp\": 2.7, \"lra\": 7.8, \"lraTh\": -33.3, \"lraLow\": -17.7, \"lraHigh\": -10, \"loudness\": -13.1}, \"featureP2sp\": true, \"oriLoudness\": 0, \"qualityType\": \"720p\", \"adaptiveType\": 0, \"qualityLabel\": \"高清\", \"realLoudness\": -14.127, \"defaultSelect\": false, \"normalizeGain\": 0, \"bitratePattern\": [1508, 1093, 3040, 198, 409], \"disableAdaptive\": false, \"realNormalizeGain\": 1.259}]}], \"manualDefaultSelect\": false}, \"fastCommentType\": 1, \"plcResponseTime\": 1774008654779, \"sourcePhotoPage\": \"collectionbase\", \"showGrDetailPage\": false, \"videoColdStartType\": 0, \"cover_thumbnail_urls\": [{\"cdn\": \"ty2.a.kwimgs.com\", \"url\": \"http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_low_B58196672a2da9d7d58106b82fb498283.webp?tag=1-1774008654-collectionbase-0-m4dkfn8uoy-cdb271a86661bfbb&clientCacheKey=3xfz7i5zwg66s26_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}, {\"cdn\": \"hw2.a.kwimgs.com\", \"url\": \"http://hw2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_low_B58196672a2da9d7d58106b82fb498283.webp?tag=1-1774008654-collectionbase-1-rn7sudbucp-514990ed007b921e&clientCacheKey=3xfz7i5zwg66s26_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}], \"enableFullScreenPlay\": false, \"forward_stats_params\": {\"et\": \"1_u/2009469870535023697_collectionbase0\", \"fid\": \"4835409196\"}, \"enableCoronaViewLater\": true, \"noNeedToRequestPLCApi\": true, \"photoTextLocationInfo\": {\"topRatio\": 0.1151, \"leftRatio\": 0.04722, \"widthRatio\": 0.89351, \"heightRatio\": 0.86145}, \"plcFeatureEntryAbFlag\": 3, \"disableViewCountByFilm\": true, \"enableCoronaDetailPage\": false, \"ff_cover_thumbnail_urls\": [{\"cdn\": \"ty2.a.kwimgs.com\", \"url\": \"http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_ff_Be2316c04152f3027d75ebf39985e1a8e.kpg?tag=1-1774008654-collectionbase-0-g6fq3r9muz-f81a888fea3e4c7b&clientCacheKey=3xfz7i5zwg66s26_ff.kpg&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}, {\"cdn\": \"hw2.a.kwimgs.com\", \"url\": \"http://hw2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDRfMTk3NTc4NDU0Nl8xODE4NTg0NzIyMDhfMF8z_ff_Be2316c04152f3027d75ebf39985e1a8e.kpg?tag=1-1774008654-collectionbase-1-zfzih6v0xm-23add0592aad3468&clientCacheKey=3xfz7i5zwg66s26_ff.kpg&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}], \"profilePagePrefetchInfo\": {\"profilePageType\": 2}, \"showProgressEnterDetail\": true, \"canShowQuickCommentGuide\": true, \"savePlayProgressStrategy\": 1, \"slideCommentEntryDisabled\": false, \"plcHighPriorityThanBottomEntry\": false}",
    "created_at": "2026-03-20T20:11:35",
    "updated_at": "2026-03-20T20:11:35"
  },
  {
    "id": 1107,
    "photo_id": "5196309726264794954",
    "serial_id": "15338428",
    "episode_number": 4,
    "episode_name": "第4集",
    "caption": "第4集｜#重生救赎路#重生救赎路免费全集",
    "duration_ms": 237099,
    "like_count": 0,
    "view_count": 16,
    "comment_count": 0,
    "forward_count": 0,
    "serial_title": "重生救赎路",
    "episode_count": 80,
    "author_user_id": 1975784546,
    "author_user_name": "小鹿爱看剧",
    "video_url": "http://v4.oskwai.com/ksc1/B6W2zhOsQtot0EFO8XPTjHXHXQLvt755heqHNCLsEkKFhRdXgcME32pwjKr1xGlq_iHUdZ1lQ_uOGEHzdtzIbrC4Uls4s7I3V0dVwccJIxwp2NOiOtOr78wF0uW1l1IRrJB_tbwezNZPA-_MtSpyt-qnglYX1fuPPwehacf0fDBpYYTMycDPrqznTlGDYNgA.mp4?pkey=AAUhLQbKsfwJK6hlNPGa1rgUJgElAnnbWWjDkog--keFFHE_rabQKlGFf8npVhnETjKjmREli5b-QJX7RKN2ENU2-ORVUsOzE7mQ3D5iIAHdG6IckR5B1OOzonzXTdCQtm0&tag=1-1774008654-collectionbase-0-vlxbk3wkyi-1f4176cb24eb7780&clientCacheKey=3xu8jjcyk8tmkxs_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001",
    "cover_url": "http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDJfMTk3NTc4NDU0Nl8xODE4NTg0ODg5MzVfMF8z_low_Be2244b0299691c678dd7d44965cd8b87.webp?tag=1-1774008654-collectionbase-0-qobjuwb14d-d98a195a19b1e351&clientCacheKey=3xu8jjcyk8tmkxs_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001",
    "share_user_id": "3xs4fg4mnyqzm6u",
    "share_photo_id": "3xu8jjcyk8tmkxs",
    "raw_json": "{\"ptp\": \"\", \"tags\": [], \"time\": \"2025-12-08 21:43:07\", \"type\": 1, \"us_c\": 0, \"us_d\": 1, \"us_l\": true, \"liked\": 0, \"caption\": \"第4集｜#重生救赎路#重生救赎路免费全集\", \"exp_tag\": \"1_u/2009469870535023697_collectionbase0\", \"user_id\": 1975784546, \"duration\": 237099, \"editInfo\": {}, \"headurls\": [{\"cdn\": \"p4.a.yximgs.com\", \"url\": \"http://p4.a.yximgs.com/uhead/AB/2020/06/17/14/BMjAyMDA2MTcxNDQ1MzFfMTk3NTc4NDU0Nl8xX2hkODA0Xzg4MQ==_s.jpg\"}, {\"cdn\": \"p2.a.yximgs.com\", \"url\": \"http://p2.a.yximgs.com/uhead/AB/2020/06/17/14/BMjAyMDA2MTcxNDQ1MzFfMTk3NTc4NDU0Nl8xX2hkODA0Xzg4MQ==_s.jpg\"}], \"location\": {}, \"photo_id\": 5196309726264794954, \"recoTags\": [], \"user_sex\": \"F\", \"verified\": false, \"adminTags\": [], \"following\": 0, \"longVideo\": true, \"musicDisk\": {\"expand\": false}, \"sameFrame\": {\"allow\": false}, \"timestamp\": 1765201387930, \"user_name\": \"小鹿爱看剧\", \"ext_params\": {\"h\": 1280, \"w\": 720, \"color\": \"48280E\", \"mtype\": 3, \"sound\": 237147, \"video\": 237099, \"interval\": 30}, \"feedLogCtx\": {\"stExParams\": \"\", \"stidContainer\": \"Ck8xfDIwMDk0Njk4NzA1MzUwMjM2OTd8cGhvdG86NTE5NjMwOTcyNjI2NDc5NDk1NHx7InBnIjoiY29sbGVjdGlvbmJhc2UifXx7InIiOjB9\"}, \"fixedColor\": \"332d29\", \"frameStyle\": 0, \"like_count\": 0, \"shareGuide\": {\"playTimes\": 2, \"photoShareGuide\": false, \"minPlayDurationInSeconds\": 15, \"textDisplayDurationInSeconds\": 4}, \"share_info\": \"userId=3xs4fg4mnyqzm6u&photoId=3xu8jjcyk8tmkxs\", \"view_count\": 16, \"danmakuInfo\": {\"paster\": false, \"hetuList\": [8280, 181072], \"defaultDanmaku\": \"有趣的人都在发弹幕\", \"photoDanmakuGuide\": false, \"danmakuShowDirection\": 2}, \"followShoot\": {\"isLipsSyncPhoto\": false}, \"recommended\": 2, \"share_count\": 0, \"supportType\": 0, \"feedSwitches\": {\"enablePlayerPanel\": true, \"disable61ActivityAnimation\": true, \"disableCommentLikeAnimation\": false, \"enablePictureCommentForPhoto\": true}, \"main_mv_urls\": [{\"cdn\": \"v4.oskwai.com\", \"url\": \"http://v4.oskwai.com/ksc1/B6W2zhOsQtot0EFO8XPTjHXHXQLvt755heqHNCLsEkKFhRdXgcME32pwjKr1xGlq_iHUdZ1lQ_uOGEHzdtzIbrC4Uls4s7I3V0dVwccJIxwp2NOiOtOr78wF0uW1l1IRrJB_tbwezNZPA-_MtSpyt-qnglYX1fuPPwehacf0fDBpYYTMycDPrqznTlGDYNgA.mp4?pkey=AAUhLQbKsfwJK6hlNPGa1rgUJgElAnnbWWjDkog--keFFHE_rabQKlGFf8npVhnETjKjmREli5b-QJX7RKN2ENU2-ORVUsOzE7mQ3D5iIAHdG6IckR5B1OOzonzXTdCQtm0&tag=1-1774008654-collectionbase-0-vlxbk3wkyi-1f4176cb24eb7780&clientCacheKey=3xu8jjcyk8tmkxs_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\", \"feature\": [1]}, {\"cdn\": \"v23-3.kwaicdn.com\", \"url\": \"http://v23-3.kwaicdn.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDJfMTk3NTc4NDU0Nl8xODE4NTg0ODg5MzVfMF8z_b_B6c333e01467ad26b18924a0a6920f92c.mp4?pkey=AAVp7Y6dGqdpKfdYWfBKIGs9b8MaC_B0gDUnB9mJ6AKMF22L6VCsppVZFG9XFU2AvrM2RRtIeu4bW33QVEDH_5rCGHrJkA7Pr6Au-vcjmq8NNQMTND6nYZeHbDaKoVshgQ4&tag=1-1774008654-collectionbase-1-ikzynsudvq-40ed0b9a30f21e9f&clientCacheKey=3xu8jjcyk8tmkxs_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\", \"feature\": [1]}], \"photo_status\": 0, \"serverExpTag\": \"feed_photo|5196309726264794954|1975784546|1_u/2009469870535023697_collectionbase0\", \"collect_count\": 0, \"comment_count\": 0, \"forward_count\": 0, \"myRecommended\": {\"recommended\": 2, \"recommendUsers\": 0, \"recommendTagGuideConfig\": {\"exitStyle\": {\"exitByUnClick\": [{\"exitTime\": 43200, \"showCount\": 5}, {\"exitTime\": 4320, \"showCount\": 3}, {\"exitTime\": 2880, \"showCount\": 2}]}, \"showStyle\": {\"type\": \"delay\", \"delayTime\": 3000}, \"frequencyStyle\": {\"showLimitByInterval\": {\"showInterval\": 72, \"maxShowCountByInterval\": 3}}}, \"recommendTextOnlyYouFormat\": \"你推荐了视频\", \"recommendTextOnlyFriendFormat\": \"%s位朋友推荐\", \"recommendTextYouAndFriendFormat\": \"你和%s位朋友推荐\"}, \"tag_hash_type\": 1, \"standardSerial\": {\"photo\": {\"caption\": \"第4集｜重生救赎路免费全集\", \"episodeName\": \"第4集\", \"episodeNumber\": 4, \"isLastEpisode\": false, \"originCaption\": \"#重生救赎路#重生救赎路免费全集\", \"isFirstEpisode\": false}, \"serial\": {\"id\": \"5xepyuzi3azutys\", \"type\": 1, \"title\": \"重生救赎路\", \"subType\": 2, \"decryptId\": \"15338428\", \"viewCount\": 565, \"panelTitle\": \"短剧 · 重生救赎路 | 共80集\", \"collectName\": \"短剧 · 重生救赎路\", \"isCollected\": false, \"moduleTitle\": \"合集 · 重生救赎路\", \"adoptionType\": 0, \"businessType\": 0, \"customParams\": {\"tags\": [], \"orgType\": 1, \"isFinished\": true, \"description\": \"剧情介绍：一场车祸，父亲和弟弟生命垂危，女儿却选择谁也不救，只因为十年前，父亲阻挠她与富二代在一起，她一直怀恨在心。 当父女二人带着各自的遗憾和怨恨重生，他们都做出了与上一世截然不同的选择。 父亲不再干涉女儿的选择，想到上一世因为贫困交不起手术费的场景，他下定决心搞钱，抓住风口炒股炒房很快成为富可敌国的神秘大佬。 而女儿坚定地选择富二代，认为父亲只会一辈子穷困潦倒拖累自己，毅然决然和他断绝父女关系，却不想富二代真如父亲所说，只是一个贪图她年轻美貌的人渣，甚至在父亲富可敌国的身份曝光后，富二代不惜利用她将亲弟弟骗出来绑架，以此勒索父亲。 生死一线，孝顺的儿子和不孝的女儿二选一，被伤透心的父亲又会怎样选择？\", \"nextEpisodeUrl\": \"\", \"seriesAdConfig\": {\"lessonId\": 0, \"seriesId\": 0, \"bannerAdGap\": 0, \"showNeoTask\": 0, \"iaaRightType\": 0, \"lookLateType\": 0, \"supportBannerAd\": false, \"hasSVipCardRight\": false, \"unlockSeriesAdType\": 0}, \"tubeStreamType\": 1, \"bottomNormalUrl\": \"kwai://episode/play?serialId=15338428&serialType=1&photoId=5196309726264794954&selectedPhotoId=5196309726264794954&sourcePhotoPage=collectionbase&autoShowPanel=true\", \"serialNameActionUrl\": \"kwai://episode/play?serialId=15338428&serialType=1&photoId=5196309726264794954&selectedPhotoId=5196309726264794954&sourcePhotoPage=collectionbase&autoShowPanel=true\", \"verticalTubeIaaAdTime\": 3, \"commercialMiniSeriesType\": 1, \"commercialBottomBarTagInfo\": {\"imageUrl\": \"https://p4-ad.adkwai.com/kcdn/cdn-kcdn111976/minfeibiaoqian.png\", \"imageWidth\": 26, \"imageHeight\": 16}, \"enabledNewCommercialTubeSelectionPanel\": true}, \"episodeCount\": 80, \"isFollowUpdate\": false, \"detailPhotoTags\": \"短剧 热血逆袭\", \"freeEpisodeCount\": 50, \"isMmuBackupTitle\": false, \"paidEpisodeCount\": 30, \"panelDescription\": \"重生救赎路\", \"tubeEntranceCard\": {\"payTag\": false, \"tubeTag\": \"热血逆袭\", \"tubeType\": 1, \"promptInfo\": \"观看完整短剧\", \"episodeInfo\": \"全80集\", \"playStrategy\": 0, \"tubeDescription\": \"一场车祸，父亲和弟弟生命垂危，女儿却选择谁也不救，只因为十年前，父亲阻挠她与富二代在一起，她一直怀恨在心。 当父女二人带着各自的遗憾和怨恨重生，他们都做出了与上一世截然不同的选择。 父亲不再干涉女儿的选择，想到上一世因为贫困交不起手术费的场景，他下定决心搞钱，抓住风口炒股炒房很快成为富可敌国的神秘大佬。 而女儿坚定地选择富二代，认为父亲只会一辈子穷困潦倒拖累自己，毅然决然和他断绝父女关系，却不想富二代真如父亲所说，只是一个贪图她年轻美貌的人渣，甚至在父亲富可敌国的身份曝光后，富二代不惜利用她将亲弟弟骗出来绑架，以此勒索父亲。 生死一线，孝顺的儿子和不孝的女儿二选一，被伤透心的父亲又会怎样选择？\", \"intoSquareActionUrl\": \"kwai://krn?bundleId=OperationTubeCenterHome&componentName=TubeCenterHome&useMultiTabContainer=1&sourceType=4&rootPhotoPage=collectionbase\", \"intoSquarePromptInfo\": \"更多短剧\"}, \"latestDescription\": \"共80集\", \"entranceDescription\": \"重生救赎路 · 更新至80集\", \"enableSerialNewStyle\": false, \"splitEntranceDescription\": {\"title\": \"短剧 · 重生救赎路\", \"continueInfo\": \"共80集\"}, \"isClusterSerialOrSubDetailFeed\": false, \"tubeInfoPanelElementMiniTkVersion\": 0}, \"contentType\": 0, \"tubePageUrl\": \"kwai://krn?bundleId=OperationTubeCenterHome&componentName=TubeCenterHome&useMultiTabContainer=1&sourceType=94&rootPhotoPage=tih\"}, \"streamManifest\": {\"version\": \"2.0.0\", \"videoId\": \"df6ac7ce3f947a16\", \"hideAuto\": false, \"playInfo\": {\"bizType\": 1, \"strategyBus\": \"{\\n  \\\"isFreeNode\\\" : 0,\\n  \\\"photoScore\\\" : {\\n    \\\"commonLightnessScore\\\" : 9,\\n    \\\"gmvClarityScore\\\" : 1,\\n    \\\"commonLightness2Score\\\" : 0,\\n    \\\"commonClarity3Score\\\" : 1,\\n    \\\"commonClarityScore\\\" : 6,\\n    \\\"gmvClarity2Score\\\" : 3,\\n    \\\"commonKs1080pScore\\\" : 0,\\n    \\\"commonLoudScore\\\" : 0,\\n    \\\"commonPunishScore\\\" : 0,\\n    \\\"commonStarScore\\\" : 0,\\n    \\\"commonClarity2Score\\\" : 90,\\n    \\\"adPostScore\\\" : 1,\\n    \\\"commonMarkScore\\\" : 0,\\n    \\\"commonGovScore\\\" : 0,\\n    \\\"commonNb1080pScore\\\" : 0,\\n    \\\"commonEqualizerScore\\\" : 0,\\n    \\\"gmvPostScore\\\" : 1,\\n    \\\"commonLpmScore\\\" : 9\\n  },\\n  \\\"trKvqLimit\\\" : 3.6\\n}\", \"cdnTimeRangeLevel\": 1}, \"mediaType\": 2, \"stereoType\": 0, \"audioFeature\": {\"audioSnr\": 5.4833, \"audioClip\": 0.0144, \"audioQuality\": 86.4977, \"musicProbability\": 0.5191, \"dialogProbability\": 0.4274, \"stereophonicRichness\": 100, \"effectiveBandwidthInHz\": 12357.456, \"backgroundSoundProbability\": 0.0535}, \"businessType\": 2, \"videoFeature\": {\"yMean\": 122.78555, \"contrast\": 0.0005859703, \"mosScore\": 0.83935546875, \"yMeanMax\": 140.99246, \"yMeanMin\": 40.692287, \"avgEntropy\": 10.225509142875673, \"overExposed\": 0.0000000029802323, \"underExposed\": 0.000003898144, \"blurProbability\": 0.04396972805261612, \"blockyProbability\": 0.44518476724624634}, \"adaptationSet\": [{\"id\": 1, \"duration\": 237147, \"representation\": [{\"id\": 1, \"agc\": false, \"url\": \"http://k0u3by39ycy10zw240ex964xea00x71bxx10z.djvod.ndcimgs.com/ksc1/B6W2zhOsQtot0EFO8XPTjHXHXQLvt755heqHNCLsEkKFhRdXgcME32pwjKr1xGlq_iHUdZ1lQ_uOGEHzdtzIbrC4Uls4s7I3V0dVwccJIxwp2NOiOtOr78wF0uW1l1IRrJB_tbwezNZPA-_MtSpyt-qnglYX1fuPPwehacf0fDBpYYTMycDPrqznTlGDYNgA.mp4?tag=1-1774008654-collectionbase-0-b5zqbho7j7-08f5628758eb9c94&provider=self&clientCacheKey=3xu8jjcyk8tmkxs_b.mp4&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001&x-ks-ptid=181858488935&kwai-not-alloc=self-cdn&kcdntag=p:Fujian;i:ChinaTelecom;ft:UNKNOWN;h:COLD;pn:kuaishouVideoProjection&ocid=6&tt=b&ss=vpm\", \"mute\": false, \"width\": 720, \"height\": 1280, \"hidden\": false, \"comment\": \"videoId=df6ac7ce3f947a16/ttExplain=AVC_VeryFast_720P_高码率_Basic/tt=b\", \"hdrType\": 0, \"quality\": 1.5, \"fileSize\": 32806387, \"kvqScore\": {\"FR\": -1, \"NR\": -1, \"FRPost\": -1, \"NRPost\": -1}, \"p2spCode\": \"{\\\"fRsn\\\":0,\\\"fixOpt\\\":-1,\\\"schTask\\\":\\\"\\\",\\\"schCode\\\":-1,\\\"schRes\\\":\\\"\\\",\\\"pushTask\\\":\\\"v=0&p=0&s=0&d=0\\\",\\\"pushCode\\\":-1}\", \"backupUrl\": [\"http://v4.oskwai.com/ksc2/sDbzSdmNBTYVv6KaaQCMDOY1KQ1AtolL0Xtsr_ZOV9f6EKc3ySO41G91BVowzpZzCxxUyugilUpUT7JQRWpcjkren_WJcstswnqBqrdj2G6qq6N4ft19i56osnaNhtLN0I3Nj33SRAa6uJd1H43L-CjAIoKIQAmLXvSIyue9HJ-gA8Dr59o9-AsIIjiR18VP.mp4?pkey=AAWe_s3Ae76RkyqXtvY6ClRQM0oaUQEyCfCvvUb3eYaj7yo2ZnCqA0tfaUCKDUT-wO3tgQL5czSQyMCscDJ-_PsALjXEVcoaCwuYBJNgPt3PHhhAOCYQxmwT4wwGrhIkjHk&tag=1-1774008654-collectionbase-1-d8quwtvg8l-18fa727650301fa6&clientCacheKey=3xu8jjcyk8tmkxs_b.mp4&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001&kwai-not-alloc=0&type=cold&tt=b&ss=vpm\"], \"frameRate\": 30.000084, \"minorInfo\": \"-b2f1\", \"avgBitrate\": 1106, \"makeupGain\": 0, \"maxBitrate\": 3300, \"videoCodec\": \"avc\", \"volumeInfo\": {\"th\": -22, \"tp\": 2.5, \"lra\": 6.8, \"lraTh\": -32.1, \"lraLow\": -15.8, \"lraHigh\": -9, \"loudness\": -12}, \"featureP2sp\": true, \"oriLoudness\": 0, \"qualityType\": \"720p\", \"adaptiveType\": 0, \"qualityLabel\": \"高清\", \"realLoudness\": -12.565, \"defaultSelect\": false, \"normalizeGain\": 0, \"bitratePattern\": [2015, 1087, 2290, 58, 385], \"disableAdaptive\": false, \"realNormalizeGain\": 1.122}]}], \"manualDefaultSelect\": false}, \"fastCommentType\": 1, \"plcResponseTime\": 1774008654779, \"sourcePhotoPage\": \"collectionbase\", \"showGrDetailPage\": false, \"videoColdStartType\": 0, \"cover_thumbnail_urls\": [{\"cdn\": \"ty2.a.kwimgs.com\", \"url\": \"http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDJfMTk3NTc4NDU0Nl8xODE4NTg0ODg5MzVfMF8z_low_Be2244b0299691c678dd7d44965cd8b87.webp?tag=1-1774008654-collectionbase-0-qobjuwb14d-d98a195a19b1e351&clientCacheKey=3xu8jjcyk8tmkxs_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}, {\"cdn\": \"hw2.a.kwimgs.com\", \"url\": \"http://hw2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDJfMTk3NTc4NDU0Nl8xODE4NTg0ODg5MzVfMF8z_low_Be2244b0299691c678dd7d44965cd8b87.webp?tag=1-1774008654-collectionbase-1-15tijgdr9w-d388a85cabb49745&clientCacheKey=3xu8jjcyk8tmkxs_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}], \"enableFullScreenPlay\": false, \"forward_stats_params\": {\"et\": \"1_u/2009469870535023697_collectionbase0\", \"fid\": \"4835409196\"}, \"enableCoronaViewLater\": true, \"noNeedToRequestPLCApi\": true, \"photoTextLocationInfo\": {\"topRatio\": 0.0802, \"leftRatio\": 0.19629, \"widthRatio\": 0.74444, \"heightRatio\": 0.89739}, \"plcFeatureEntryAbFlag\": 3, \"disableViewCountByFilm\": true, \"enableCoronaDetailPage\": false, \"ff_cover_thumbnail_urls\": [{\"cdn\": \"ty2.a.kwimgs.com\", \"url\": \"http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDJfMTk3NTc4NDU0Nl8xODE4NTg0ODg5MzVfMF8z_ff_B69b073a1d71849242016ab28d0333636.kpg?tag=1-1774008654-collectionbase-0-w3lyvybq19-2a791e751e561da8&clientCacheKey=3xu8jjcyk8tmkxs_ff.kpg&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}, {\"cdn\": \"hw2.a.kwimgs.com\", \"url\": \"http://hw2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQyMDJfMTk3NTc4NDU0Nl8xODE4NTg0ODg5MzVfMF8z_ff_B69b073a1d71849242016ab28d0333636.kpg?tag=1-1774008654-collectionbase-1-zu8u602s1k-4d7b23f225ddb69f&clientCacheKey=3xu8jjcyk8tmkxs_ff.kpg&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}], \"profilePagePrefetchInfo\": {\"profilePageType\": 2}, \"showProgressEnterDetail\": true, \"canShowQuickCommentGuide\": true, \"savePlayProgressStrategy\": 1, \"slideCommentEntryDisabled\": false, \"plcHighPriorityThanBottomEntry\": false}",
    "created_at": "2026-03-20T20:11:35",
    "updated_at": "2026-03-20T20:11:35"
  },
  {
    "id": 1106,
    "photo_id": "5253449148734074120",
    "serial_id": "15338428",
    "episode_number": 3,
    "episode_name": "第3集",
    "caption": "第3集｜#重生救赎路#重生救赎路免费全集",
    "duration_ms": 138332,
    "like_count": 0,
    "view_count": 11,
    "comment_count": 0,
    "forward_count": 0,
    "serial_title": "重生救赎路",
    "episode_count": 80,
    "author_user_id": 1975784546,
    "author_user_name": "小鹿爱看剧",
    "video_url": "http://v4.oskwai.com/ksc1/VfQucAR88_jbqdqm1P1sO8mm4ol29glBVO-ureA8BGF5M6x-zKbhCPJDfSD9U5n2XLhdxpJLIPPsvuzuRkpdbvNkV3Yu9B5Y5xJCJFnScxAWoA_elFJyXpLsi9lbW1I17aNTlil_MqBk8bT6FuIi-yI1OHWf0ZUeSRIJ2Oww5DXYSWPzSTTMOpdLUvlazE4I.mp4?pkey=AAWn6JgxiyOXd5PqBEHi1iIi5C2M1bykyPvWGKgEKl2kPrQR3thHkiyu0TeB3nyDurn-S5zRXbXoliOAbEOv0Ovzo_oWnytDS__I2go3OxW9CpL7ge_EuJQog5Jh4fNh9Ro&tag=1-1774008654-collectionbase-0-gyfhderskm-daa47c26ac0085bd&clientCacheKey=3xbu5z68f8waecm_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001",
    "cover_url": "http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQxNTlfMTk3NTc4NDU0Nl8xODE4NTg0ODE0MzRfMF8z_low_B13d735e5e5c52f6d143d7661ccd19a95.webp?tag=1-1774008654-collectionbase-0-yoexoutfmf-b45c335e237b2f9d&clientCacheKey=3xbu5z68f8waecm_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001",
    "share_user_id": "3xs4fg4mnyqzm6u",
    "share_photo_id": "3xbu5z68f8waecm",
    "raw_json": "{\"ptp\": \"\", \"tags\": [], \"time\": \"2025-12-08 21:42:48\", \"type\": 1, \"us_c\": 0, \"us_d\": 1, \"us_l\": true, \"liked\": 0, \"caption\": \"第3集｜#重生救赎路#重生救赎路免费全集\", \"exp_tag\": \"1_u/2009469870535023697_collectionbase0\", \"user_id\": 1975784546, \"duration\": 138332, \"editInfo\": {}, \"headurls\": [{\"cdn\": \"p4.a.yximgs.com\", \"url\": \"http://p4.a.yximgs.com/uhead/AB/2020/06/17/14/BMjAyMDA2MTcxNDQ1MzFfMTk3NTc4NDU0Nl8xX2hkODA0Xzg4MQ==_s.jpg\"}, {\"cdn\": \"p2.a.yximgs.com\", \"url\": \"http://p2.a.yximgs.com/uhead/AB/2020/06/17/14/BMjAyMDA2MTcxNDQ1MzFfMTk3NTc4NDU0Nl8xX2hkODA0Xzg4MQ==_s.jpg\"}], \"location\": {}, \"photo_id\": 5253449148734074120, \"recoTags\": [], \"user_sex\": \"F\", \"verified\": false, \"adminTags\": [], \"following\": 0, \"longVideo\": true, \"musicDisk\": {\"expand\": false}, \"sameFrame\": {\"allow\": false}, \"timestamp\": 1765201368953, \"user_name\": \"小鹿爱看剧\", \"ext_params\": {\"h\": 1280, \"w\": 720, \"color\": \"48280E\", \"mtype\": 3, \"sound\": 138369, \"video\": 138332, \"interval\": 30}, \"feedLogCtx\": {\"stExParams\": \"\", \"stidContainer\": \"Ck8xfDIwMDk0Njk4NzA1MzUwMjM2OTd8cGhvdG86NTI1MzQ0OTE0ODczNDA3NDEyMHx7InBnIjoiY29sbGVjdGlvbmJhc2UifXx7InIiOjB9\"}, \"fixedColor\": \"332d29\", \"frameStyle\": 0, \"like_count\": 0, \"shareGuide\": {\"playTimes\": 2, \"photoShareGuide\": false, \"minPlayDurationInSeconds\": 15, \"textDisplayDurationInSeconds\": 4}, \"share_info\": \"userId=3xs4fg4mnyqzm6u&photoId=3xbu5z68f8waecm\", \"view_count\": 11, \"danmakuInfo\": {\"paster\": false, \"hetuList\": [10074, 178780], \"defaultDanmaku\": \"有趣的人都在发弹幕\", \"photoDanmakuGuide\": false, \"danmakuShowDirection\": 2}, \"followShoot\": {\"isLipsSyncPhoto\": false}, \"recommended\": 2, \"share_count\": 0, \"supportType\": 0, \"feedSwitches\": {\"enablePlayerPanel\": true, \"disable61ActivityAnimation\": true, \"disableCommentLikeAnimation\": false, \"enablePictureCommentForPhoto\": true}, \"main_mv_urls\": [{\"cdn\": \"v4.oskwai.com\", \"url\": \"http://v4.oskwai.com/ksc1/VfQucAR88_jbqdqm1P1sO8mm4ol29glBVO-ureA8BGF5M6x-zKbhCPJDfSD9U5n2XLhdxpJLIPPsvuzuRkpdbvNkV3Yu9B5Y5xJCJFnScxAWoA_elFJyXpLsi9lbW1I17aNTlil_MqBk8bT6FuIi-yI1OHWf0ZUeSRIJ2Oww5DXYSWPzSTTMOpdLUvlazE4I.mp4?pkey=AAWn6JgxiyOXd5PqBEHi1iIi5C2M1bykyPvWGKgEKl2kPrQR3thHkiyu0TeB3nyDurn-S5zRXbXoliOAbEOv0Ovzo_oWnytDS__I2go3OxW9CpL7ge_EuJQog5Jh4fNh9Ro&tag=1-1774008654-collectionbase-0-gyfhderskm-daa47c26ac0085bd&clientCacheKey=3xbu5z68f8waecm_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\", \"feature\": [1]}, {\"cdn\": \"v23-3.kwaicdn.com\", \"url\": \"http://v23-3.kwaicdn.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQxNTlfMTk3NTc4NDU0Nl8xODE4NTg0ODE0MzRfMF8z_b_B57f2774393cc3b519ed814505d9e0a88.mp4?pkey=AAUCO3QrF230LXqtg8UH-JBiUs8IWvxyAnagRBIY5ju8IDT1qscUzcpJIUFdUAZR5htlbYVE8baR0ptHHZ6HZNB5eS-54EwTXtkfKAdlLbLqBLH23t_AZq_yF29K3vXdJW8&tag=1-1774008654-collectionbase-1-fh4nefvgjm-cdc822ad9d97243f&clientCacheKey=3xbu5z68f8waecm_b.mp4&tt=b&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\", \"feature\": [1]}], \"photo_status\": 0, \"serverExpTag\": \"feed_photo|5253449148734074120|1975784546|1_u/2009469870535023697_collectionbase0\", \"collect_count\": 0, \"comment_count\": 0, \"forward_count\": 0, \"myRecommended\": {\"recommended\": 2, \"recommendUsers\": 0, \"recommendTagGuideConfig\": {\"exitStyle\": {\"exitByUnClick\": [{\"exitTime\": 43200, \"showCount\": 5}, {\"exitTime\": 4320, \"showCount\": 3}, {\"exitTime\": 2880, \"showCount\": 2}]}, \"showStyle\": {\"type\": \"delay\", \"delayTime\": 3000}, \"frequencyStyle\": {\"showLimitByInterval\": {\"showInterval\": 72, \"maxShowCountByInterval\": 3}}}, \"recommendTextOnlyYouFormat\": \"你推荐了视频\", \"recommendTextOnlyFriendFormat\": \"%s位朋友推荐\", \"recommendTextYouAndFriendFormat\": \"你和%s位朋友推荐\"}, \"tag_hash_type\": 1, \"standardSerial\": {\"photo\": {\"caption\": \"第3集｜重生救赎路免费全集\", \"episodeName\": \"第3集\", \"episodeNumber\": 3, \"isLastEpisode\": false, \"originCaption\": \"#重生救赎路#重生救赎路免费全集\", \"isFirstEpisode\": false}, \"serial\": {\"id\": \"5xepyuzi3azutys\", \"type\": 1, \"title\": \"重生救赎路\", \"subType\": 2, \"decryptId\": \"15338428\", \"viewCount\": 565, \"panelTitle\": \"短剧 · 重生救赎路 | 共80集\", \"collectName\": \"短剧 · 重生救赎路\", \"isCollected\": false, \"moduleTitle\": \"合集 · 重生救赎路\", \"adoptionType\": 0, \"businessType\": 0, \"customParams\": {\"tags\": [], \"orgType\": 1, \"isFinished\": true, \"description\": \"剧情介绍：一场车祸，父亲和弟弟生命垂危，女儿却选择谁也不救，只因为十年前，父亲阻挠她与富二代在一起，她一直怀恨在心。 当父女二人带着各自的遗憾和怨恨重生，他们都做出了与上一世截然不同的选择。 父亲不再干涉女儿的选择，想到上一世因为贫困交不起手术费的场景，他下定决心搞钱，抓住风口炒股炒房很快成为富可敌国的神秘大佬。 而女儿坚定地选择富二代，认为父亲只会一辈子穷困潦倒拖累自己，毅然决然和他断绝父女关系，却不想富二代真如父亲所说，只是一个贪图她年轻美貌的人渣，甚至在父亲富可敌国的身份曝光后，富二代不惜利用她将亲弟弟骗出来绑架，以此勒索父亲。 生死一线，孝顺的儿子和不孝的女儿二选一，被伤透心的父亲又会怎样选择？\", \"nextEpisodeUrl\": \"\", \"seriesAdConfig\": {\"lessonId\": 0, \"seriesId\": 0, \"bannerAdGap\": 0, \"showNeoTask\": 0, \"iaaRightType\": 0, \"lookLateType\": 0, \"supportBannerAd\": false, \"hasSVipCardRight\": false, \"unlockSeriesAdType\": 0}, \"tubeStreamType\": 1, \"bottomNormalUrl\": \"kwai://episode/play?serialId=15338428&serialType=1&photoId=5253449148734074120&selectedPhotoId=5253449148734074120&sourcePhotoPage=collectionbase&autoShowPanel=true\", \"serialNameActionUrl\": \"kwai://episode/play?serialId=15338428&serialType=1&photoId=5253449148734074120&selectedPhotoId=5253449148734074120&sourcePhotoPage=collectionbase&autoShowPanel=true\", \"verticalTubeIaaAdTime\": 3, \"commercialMiniSeriesType\": 1, \"commercialBottomBarTagInfo\": {\"imageUrl\": \"https://p4-ad.adkwai.com/kcdn/cdn-kcdn111976/minfeibiaoqian.png\", \"imageWidth\": 26, \"imageHeight\": 16}, \"enabledNewCommercialTubeSelectionPanel\": true}, \"episodeCount\": 80, \"isFollowUpdate\": false, \"detailPhotoTags\": \"短剧 热血逆袭\", \"freeEpisodeCount\": 50, \"isMmuBackupTitle\": false, \"paidEpisodeCount\": 30, \"panelDescription\": \"重生救赎路\", \"tubeEntranceCard\": {\"payTag\": false, \"tubeTag\": \"热血逆袭\", \"tubeType\": 1, \"promptInfo\": \"观看完整短剧\", \"episodeInfo\": \"全80集\", \"playStrategy\": 0, \"tubeDescription\": \"一场车祸，父亲和弟弟生命垂危，女儿却选择谁也不救，只因为十年前，父亲阻挠她与富二代在一起，她一直怀恨在心。 当父女二人带着各自的遗憾和怨恨重生，他们都做出了与上一世截然不同的选择。 父亲不再干涉女儿的选择，想到上一世因为贫困交不起手术费的场景，他下定决心搞钱，抓住风口炒股炒房很快成为富可敌国的神秘大佬。 而女儿坚定地选择富二代，认为父亲只会一辈子穷困潦倒拖累自己，毅然决然和他断绝父女关系，却不想富二代真如父亲所说，只是一个贪图她年轻美貌的人渣，甚至在父亲富可敌国的身份曝光后，富二代不惜利用她将亲弟弟骗出来绑架，以此勒索父亲。 生死一线，孝顺的儿子和不孝的女儿二选一，被伤透心的父亲又会怎样选择？\", \"intoSquareActionUrl\": \"kwai://krn?bundleId=OperationTubeCenterHome&componentName=TubeCenterHome&useMultiTabContainer=1&sourceType=4&rootPhotoPage=collectionbase\", \"intoSquarePromptInfo\": \"更多短剧\"}, \"latestDescription\": \"共80集\", \"entranceDescription\": \"重生救赎路 · 更新至80集\", \"enableSerialNewStyle\": false, \"splitEntranceDescription\": {\"title\": \"短剧 · 重生救赎路\", \"continueInfo\": \"共80集\"}, \"isClusterSerialOrSubDetailFeed\": false, \"tubeInfoPanelElementMiniTkVersion\": 0}, \"contentType\": 0, \"tubePageUrl\": \"kwai://krn?bundleId=OperationTubeCenterHome&componentName=TubeCenterHome&useMultiTabContainer=1&sourceType=94&rootPhotoPage=tih\"}, \"streamManifest\": {\"version\": \"2.0.0\", \"videoId\": \"03e5ce4b2aa55a41\", \"hideAuto\": false, \"playInfo\": {\"bizType\": 1, \"strategyBus\": \"{\\n  \\\"isFreeNode\\\" : 0,\\n  \\\"photoScore\\\" : {\\n    \\\"commonLightnessScore\\\" : 9,\\n    \\\"gmvClarityScore\\\" : 1,\\n    \\\"commonLightness2Score\\\" : 0,\\n    \\\"commonClarity3Score\\\" : 1,\\n    \\\"commonClarityScore\\\" : 6,\\n    \\\"gmvClarity2Score\\\" : 3,\\n    \\\"commonKs1080pScore\\\" : 0,\\n    \\\"commonLoudScore\\\" : 2,\\n    \\\"commonPunishScore\\\" : 0,\\n    \\\"commonStarScore\\\" : 0,\\n    \\\"commonClarity2Score\\\" : 90,\\n    \\\"adPostScore\\\" : 1,\\n    \\\"commonMarkScore\\\" : 0,\\n    \\\"commonGovScore\\\" : 0,\\n    \\\"commonNb1080pScore\\\" : 0,\\n    \\\"commonEqualizerScore\\\" : 0,\\n    \\\"gmvPostScore\\\" : 1,\\n    \\\"commonLpmScore\\\" : 9\\n  },\\n  \\\"trKvqLimit\\\" : 3.6\\n}\", \"cdnTimeRangeLevel\": 1}, \"mediaType\": 2, \"stereoType\": 0, \"audioFeature\": {\"audioSnr\": 6.9553, \"audioClip\": 0.0039, \"audioQuality\": 84.153, \"musicProbability\": 0.6849, \"dialogProbability\": 0.1221, \"stereophonicRichness\": 90.6082, \"effectiveBandwidthInHz\": 14725.789, \"backgroundSoundProbability\": 0.193}, \"businessType\": 2, \"videoFeature\": {\"yMean\": 120.78955, \"contrast\": 0.010342523, \"mosScore\": 0.8605142831802368, \"yMeanMax\": 142.6325, \"yMeanMin\": 41.28516, \"avgEntropy\": 9.242505478858948, \"overExposed\": 0.0000000923872, \"underExposed\": 0.00003964901, \"blurProbability\": 0.16164550185203552, \"blockyProbability\": 0.4954254925251007}, \"adaptationSet\": [{\"id\": 1, \"duration\": 138369, \"representation\": [{\"id\": 1, \"agc\": false, \"url\": \"http://k0u3by39ycy17zw240ex964xea00x71bxx17z.djvod.ndcimgs.com/ksc1/VfQucAR88_jbqdqm1P1sO8mm4ol29glBVO-ureA8BGF5M6x-zKbhCPJDfSD9U5n2XLhdxpJLIPPsvuzuRkpdbvNkV3Yu9B5Y5xJCJFnScxAWoA_elFJyXpLsi9lbW1I17aNTlil_MqBk8bT6FuIi-yI1OHWf0ZUeSRIJ2Oww5DXYSWPzSTTMOpdLUvlazE4I.mp4?tag=1-1774008654-collectionbase-0-qjr76ifeux-b83e46a904f508a3&provider=self&clientCacheKey=3xbu5z68f8waecm_b.mp4&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001&x-ks-ptid=181858481434&kwai-not-alloc=self-cdn&kcdntag=p:Fujian;i:ChinaTelecom;ft:UNKNOWN;h:COLD;pn:kuaishouVideoProjection&ocid=6&tt=b&ss=vpm\", \"mute\": false, \"width\": 720, \"height\": 1280, \"hidden\": false, \"comment\": \"videoId=03e5ce4b2aa55a41/ttExplain=AVC_VeryFast_720P_高码率_Basic/tt=b\", \"hdrType\": 0, \"quality\": 1.5, \"fileSize\": 20968181, \"kvqScore\": {\"FR\": -1, \"NR\": -1, \"FRPost\": -1, \"NRPost\": -1}, \"p2spCode\": \"{\\\"fRsn\\\":0,\\\"fixOpt\\\":-1,\\\"schTask\\\":\\\"\\\",\\\"schCode\\\":-1,\\\"schRes\\\":\\\"\\\",\\\"pushTask\\\":\\\"v=0&p=0&s=0&d=0\\\",\\\"pushCode\\\":-1}\", \"backupUrl\": [\"http://v4.oskwai.com/ksc2/hLxOoO6nVebZHu-fsbU-ErwhlGl2DA0Qt5n58ybJZEToPt97NPR1C6r1OK68UQdPLgy9x-zRGp0IgRY2Xd15kaIepfcD59roKbhWthmwZcwaXJLCvUYM_idofVqk2QvgD8pO5Wxon7MetzY80-mBwdEz98irPdYXE9OGi1EAHi3omcgBghsUl6pjKSqx9eep.mp4?pkey=AAURyg0BiaU88S_j7k30joXh5lVyfptftDeqdN0eGmUqNdlU2JPfdJGSvbPOf10gdATkfAkoTCArziJLAlmFB4xw-k1WOkdbMU2QKzphfU52V91VZTaRSMnwctaHMvw6f9c&tag=1-1774008654-collectionbase-1-gtv0hf3tzf-cd589b8a8f440717&clientCacheKey=3xbu5z68f8waecm_b.mp4&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001&kwai-not-alloc=0&type=cold&tt=b&ss=vpm\"], \"frameRate\": 30.000145, \"minorInfo\": \"-b2f1\", \"avgBitrate\": 1212, \"makeupGain\": 0, \"maxBitrate\": 3300, \"videoCodec\": \"avc\", \"volumeInfo\": {\"th\": -24.6, \"tp\": 0.8, \"lra\": 6.2, \"lraTh\": -34.7, \"lraLow\": -18.2, \"lraHigh\": -11.9, \"loudness\": -14.6}, \"featureP2sp\": true, \"oriLoudness\": 0, \"qualityType\": \"720p\", \"adaptiveType\": 0, \"qualityLabel\": \"高清\", \"realLoudness\": -15.167, \"defaultSelect\": false, \"normalizeGain\": 0, \"bitratePattern\": [2285, 1136, 2938, 170, 481], \"disableAdaptive\": false, \"realNormalizeGain\": 1.413}]}], \"manualDefaultSelect\": false}, \"fastCommentType\": 1, \"plcResponseTime\": 1774008654779, \"sourcePhotoPage\": \"collectionbase\", \"showGrDetailPage\": false, \"videoColdStartType\": 0, \"cover_thumbnail_urls\": [{\"cdn\": \"ty2.a.kwimgs.com\", \"url\": \"http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQxNTlfMTk3NTc4NDU0Nl8xODE4NTg0ODE0MzRfMF8z_low_B13d735e5e5c52f6d143d7661ccd19a95.webp?tag=1-1774008654-collectionbase-0-yoexoutfmf-b45c335e237b2f9d&clientCacheKey=3xbu5z68f8waecm_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}, {\"cdn\": \"hw2.a.kwimgs.com\", \"url\": \"http://hw2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQxNTlfMTk3NTc4NDU0Nl8xODE4NTg0ODE0MzRfMF8z_low_B13d735e5e5c52f6d143d7661ccd19a95.webp?tag=1-1774008654-collectionbase-1-svecezdoqd-8483b025a9872634&clientCacheKey=3xbu5z68f8waecm_low.webp&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}], \"enableFullScreenPlay\": false, \"forward_stats_params\": {\"et\": \"1_u/2009469870535023697_collectionbase0\", \"fid\": \"4835409196\"}, \"enableCoronaViewLater\": true, \"noNeedToRequestPLCApi\": true, \"photoTextLocationInfo\": {\"topRatio\": 0.00885, \"leftRatio\": 0, \"widthRatio\": 0.94074, \"heightRatio\": 0.96666}, \"plcFeatureEntryAbFlag\": 3, \"disableViewCountByFilm\": true, \"enableCoronaDetailPage\": false, \"ff_cover_thumbnail_urls\": [{\"cdn\": \"ty2.a.kwimgs.com\", \"url\": \"http://ty2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQxNTlfMTk3NTc4NDU0Nl8xODE4NTg0ODE0MzRfMF8z_ff_Bd28c5305c8d5cd873a8be7d2d5254903.kpg?tag=1-1774008654-collectionbase-0-eeygaetoe1-c6d47821c7f75a4b&clientCacheKey=3xbu5z68f8waecm_ff.kpg&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}, {\"cdn\": \"hw2.a.kwimgs.com\", \"url\": \"http://hw2.a.kwimgs.com/upic/2025/12/08/21/BMjAyNTEyMDgyMTQxNTlfMTk3NTc4NDU0Nl8xODE4NTg0ODE0MzRfMF8z_ff_Bd28c5305c8d5cd873a8be7d2d5254903.kpg?tag=1-1774008654-collectionbase-1-aougfz6xqp-a469690a8731173b&clientCacheKey=3xbu5z68f8waecm_ff.kpg&di=JA4DeVOsbBCgEZXSGXp_qw==&bp=10001\"}], \"profilePagePrefetchInfo\": {\"profilePageType\": 2}, \"showProgressEnterDetail\": true, \"canShowQuickCommentGuide\": true, \"savePlayProgressStrategy\": 1, \"slideCommentEntryDisabled\": false, \"plcHighPriorityThanBottomEntry\": false}",
    "created_at": "2026-03-20T20:11:35",
    "updated_at": "2026-03-20T20:11:35"
  }
]
```

### `kuaishou_accounts`

**Rows**: 23,075  
**Columns**: 26  
**Indexes**: 13

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `uid` | `varchar(50)` | N | UNI |  |  | 快手账号UID |
| `device_serial` | `varchar(50)` | Y | MUL |  |  | 设备序列号 |
| `nickname` | `varchar(100)` | Y |  |  |  | 账号昵称 |
| `is_mcm_member` | `tinyint(1)` | Y | MUL | `0` |  | 是否加入MCM机构 |
| `mcm_join_date` | `datetime` | Y |  |  |  | MCM加入日期 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 记录创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 记录更新时间 |
| `group_id` | `int(11)` | Y | MUL |  |  |  |
| `owner_id` | `int(11)` | Y | MUL |  |  | 所属用户ID |
| `is_blacklisted` | `tinyint(1)` | Y |  | `0` |  | 是否被拉黑 |
| `blacklist_reason` | `varchar(255)` | Y |  |  |  | 拉黑原因 |
| `blacklisted_at` | `datetime` | Y |  |  |  | 拉黑时间 |
| `blacklisted_by` | `int(11)` | Y |  |  |  | 拉黑操作人ID |
| `account_status` | `varchar(50)` | Y |  | `normal` |  | 账号状态: normal/marked/suspended |
| `status_note` | `varchar(255)` | Y |  |  |  | 状态备注 |
| `platform` | `tinyint(4)` | Y |  | `1` |  | 账号所属平台 1.短剧精灵 2.快手小精灵 |
| `contract_status` | `varchar(50)` | Y |  |  |  | 签约状态: 邀约发送等待接受/已签约/邀约已拒绝/邀约已过期 |
| `org_note` | `text` | Y |  |  |  | 机构备注（实名-团长格式） |
| `phone_number` | `varchar(20)` | Y |  |  |  | 手机号码 |
| `invite_time` | `datetime` | Y |  |  |  | 邀约时间 |
| `invitation_success_count` | `int(11)` | Y |  | `0` |  | 邀约成功次数 |
| `uid_real` | `varchar(50)` | Y | MUL |  |  | 快手真实UID |
| `real_name` | `varchar(50)` | Y |  |  |  | 实名（从备注或开通星火时填写） |
| `organization_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |
| `commission_rate` | `decimal(5,2)` | Y |  |  |  | 账号分成比例(%),NULL时使用所属用户的分成比例 |

**Indexes**:
  - `idx_device` (`device_serial`)
  - `idx_group_id` (`group_id`)
  - `idx_mcm_member` (`is_mcm_member`)
  - `idx_organization_id` (`organization_id`)
  - `idx_owner_group` (`owner_id, group_id`)
  - `idx_owner_id` (`owner_id`)
  - `idx_owner_uid_real_cover` (`owner_id, uid_real, uid`)
  - `idx_uid` (`uid`)
  - `idx_uid_real` (`uid_real`)
  - `idx_uid_real_owner` (`uid_real, owner_id`)
  - `idx_uid_uid_real` (`uid, uid_real`)
  - `PRIMARY` (UNIQUE `id`)
  - `uid` (UNIQUE `uid`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 49189,
    "uid": "1434328025",
    "device_serial": null,
    "nickname": null,
    "is_mcm_member": 0,
    "mcm_join_date": null,
    "created_at": "2026-04-20T01:23:53",
    "updated_at": "2026-04-20T01:38:36",
    "group_id": null,
    "owner_id": 1373,
    "is_blacklisted": 0,
    "blacklist_reason": null,
    "blacklisted_at": null,
    "blacklisted_by": null,
    "account_status": "normal",
    "status_note": null,
    "platform": 1,
    "contract_status": "签约成功，未开通星火",
    "org_note": "陈锋浩-qtl081522",
    "phone_number": "181****2931",
    "invite_time": "2026-04-20T01:23:53",
    "invitation_success_count": 3,
    "uid_real": "1434328025",
    "real_name": "陈锋浩",
    "organization_id": 1,
    "commission_rate": 65.0
  },
  {
    "id": 49188,
    "uid": "4",
    "device_serial": null,
    "nickname": "快手用户1776598786195",
    "is_mcm_member": 0,
    "mcm_join_date": null,
    "created_at": "2026-04-20T00:22:30",
    "updated_at": "2026-04-20T00:52:34",
    "group_id": null,
    "owner_id": 1475,
    "is_blacklisted": 0,
    "blacklist_reason": null,
    "blacklisted_at": null,
    "blacklisted_by": null,
    "account_status": "normal",
    "status_note": null,
    "platform": 2,
    "contract_status": "邀约发送等待接受",
    "org_note": "林-13915578543",
    "phone_number": "152****1713",
    "invite_time": "2026-04-20T00:22:30",
    "invitation_success_count": 0,
    "uid_real": "5445268672",
    "real_name": "林",
    "organization_id": 5,
    "commission_rate": 70.0
  },
  {
    "id": 49187,
    "uid": "5445716706",
    "device_serial": null,
    "nickname": "凡夫俗子",
    "is_mcm_member": 0,
    "mcm_join_date": null,
    "created_at": "2026-04-20T00:15:44",
    "updated_at": "2026-04-20T01:08:34",
    "group_id": null,
    "owner_id": 1283,
    "is_blacklisted": 0,
    "blacklist_reason": null,
    "blacklisted_at": null,
    "blacklisted_by": null,
    "account_status": "normal",
    "status_note": null,
    "platform": 2,
    "contract_status": "签约成功，未开通星火",
    "org_note": "周艺3-chuhengguanggao",
    "phone_number": "147****2896",
    "invite_time": "2026-04-20T00:15:44",
    "invitation_success_count": 2,
    "uid_real": "5445716706",
    "real_name": "周艺3",
    "organization_id": 5,
    "commission_rate": 70.0
  }
]
```

### `kuaishou_account_bindings`

**Rows**: 2  
**Columns**: 8  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `kuaishou_id` | `varchar(50)` | N | MUL |  |  | 快手号 |
| `machine_id` | `varchar(100)` | N | MUL |  |  | 机器码 |
| `operator_account` | `varchar(100)` | N | MUL |  |  | 操作员登录账号 |
| `bind_time` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 绑定时间 |
| `last_used_time` | `datetime` | Y |  |  |  | 最后使用时间 |
| `status` | `enum('active','disabled')` | Y | MUL | `active` |  | 状态 |
| `remark` | `varchar(255)` | Y |  |  |  | 备注 |

**Indexes**:
  - `idx_kuaishou` (`kuaishou_id`)
  - `idx_machine` (`machine_id`)
  - `idx_operator` (`operator_account`)
  - `idx_status` (`status`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_kuaishou_machine_operator` (UNIQUE `kuaishou_id, machine_id, operator_account`)

**Sample (top 2 rows, sensitive fields redacted):**
```json
[
  {
    "id": 17,
    "kuaishou_id": "3078950457",
    "machine_id": "5CA7C4E8-9AA5-438F-9EB7-C3F73DE1FD45",
    "operator_account": "team22",
    "bind_time": "2026-01-24T18:29:01",
    "last_used_time": "2026-01-24T18:29:01",
    "status": "active",
    "remark": null
  },
  {
    "id": 10,
    "kuaishou_id": "5245022408",
    "machine_id": "1EF2304D-279E-4C21-A944-026791F487DE",
    "operator_account": "team22",
    "bind_time": "2026-01-24T12:53:42",
    "last_used_time": "2026-01-24T12:53:42",
    "status": "disabled",
    "remark": null
  }
]
```

### `kuaishou_urls`

**Rows**: 1,734,694  
**Columns**: 5  
**Indexes**: 1

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `url` | `varchar(255)` | N |  | `` |  | 短剧链接 |
| `name` | `varchar(255)` | Y |  |  |  | 短剧名称 |
| `uid` | `varchar(255)` | Y |  |  |  | 用户id |
| `nickname` | `varchar(255)` | Y |  |  |  | 用户名 |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1745056,
    "url": "https://v.kuaishou.com/7eFa6nJb",
    "name": "一切从无敌开始-高燃版",
    "uid": "4629447270",
    "nickname": "麻薯剧场"
  },
  {
    "id": 1745055,
    "url": "https://www.kuaishou.com/f/X-2ooihmQ0BH91wX",
    "name": "母望子归",
    "uid": "4334437230",
    "nickname": "楊軍"
  },
  {
    "id": 1745054,
    "url": "https://v.kuaishou.com/Jbp9QcAJ",
    "name": "八零飒妻要发家",
    "uid": "5261541043",
    "nickname": "老实人短剧"
  }
]
```

### `mcm_organizations`

**Rows**: 17  
**Columns**: 8  
**Indexes**: 2

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `org_name` | `varchar(100)` | N | MUL |  |  | 机构名称 |
| `org_code` | `mediumtext` | Y |  |  |  | 机构代码/Cookie |
| `description` | `text` | Y |  |  |  | 机构描述 |
| `is_active` | `tinyint(1)` | Y |  | `1` |  | 是否启用 |
| `include_video_collaboration` | `tinyint(1)` | Y |  | `1` |  | 是否需要发送视频邀约: 1=需要, 0=不需要 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_org_name` (`org_name`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 19,
    "org_name": "爱佳文化",
    "org_code": "1",
    "description": "",
    "is_active": 1,
    "include_video_collaboration": 0,
    "created_at": "2026-04-18T13:36:12",
    "updated_at": "2026-04-18T13:36:19"
  },
  {
    "id": 18,
    "org_name": "数智精灵",
    "org_code": "1",
    "description": "",
    "is_active": 1,
    "include_video_collaboration": 0,
    "created_at": "2026-04-10T16:35:00",
    "updated_at": "2026-04-10T16:35:05"
  },
  {
    "id": 17,
    "org_name": "探界传媒",
    "org_code": "1",
    "description": "",
    "is_active": 1,
    "include_video_collaboration": 0,
    "created_at": "2026-04-09T21:21:35",
    "updated_at": "2026-04-09T21:21:38"
  }
]
```

### `mcn_verification_logs`

**Rows**: 493,549  
**Columns**: 7  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `uid` | `varchar(50)` | Y | MUL |  |  | 账号UID |
| `client_ip` | `varchar(50)` | Y |  |  |  | 客户端IP |
| `status` | `varchar(20)` | Y | MUL |  |  | 验证状态: SUCCESS, FAILED |
| `is_mcn_member` | `tinyint(1)` | Y |  |  |  | 是否为MCN成员 |
| `error_message` | `text` | Y |  |  |  | 错误信息 |
| `created_at` | `datetime` | Y | MUL |  |  | 创建时间 |

**Indexes**:
  - `idx_created_at` (`created_at`)
  - `idx_status` (`status`)
  - `idx_uid` (`uid`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 494444,
    "uid": "1715190696",
    "client_ip": "120.214.150.57",
    "status": "SUCCESS",
    "is_mcn_member": 1,
    "error_message": null,
    "created_at": "2026-04-20T06:36:06"
  },
  {
    "id": 494443,
    "uid": "4255355921",
    "client_ip": "182.126.144.198",
    "status": "SUCCESS",
    "is_mcn_member": 1,
    "error_message": null,
    "created_at": "2026-04-20T06:36:02"
  },
  {
    "id": 494442,
    "uid": "5039739887",
    "client_ip": "120.214.150.57",
    "status": "SUCCESS",
    "is_mcn_member": 1,
    "error_message": null,
    "created_at": "2026-04-20T06:35:39"
  }
]
```

### `operator_quota`

**Rows**: 0  
**Columns**: 5  
**Indexes**: 2

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `operator_account` | `varchar(100)` | N | UNI |  |  | 操作员账号 |
| `max_accounts` | `int(11)` | Y |  | `10` |  | 最大可绑定账号数 |
| `created_time` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_time` | `datetime` | Y |  |  | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `operator_account` (UNIQUE `operator_account`)
  - `PRIMARY` (UNIQUE `id`)


### `page_permissions`

**Rows**: 21,578  
**Columns**: 6  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `user_id` | `int(11)` | N | MUL |  |  |  |
| `page_key` | `varchar(50)` | N | MUL |  |  | 页面标识 |
| `is_allowed` | `tinyint(1)` | Y |  | `1` |  | 是否允许访问: 1=允许, 0=禁止 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |

**Indexes**:
  - `idx_page_key` (`page_key`)
  - `idx_user_id` (`user_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `unique_user_page` (UNIQUE `user_id, page_key`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 39376,
    "user_id": 1502,
    "page_key": "video_collection",
    "is_allowed": 1,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 39375,
    "user_id": 1502,
    "page_key": "task_queue",
    "is_allowed": 1,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 39374,
    "user_id": 1502,
    "page_key": "task_history",
    "is_allowed": 1,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  }
]
```

### `role_default_permissions`

**Rows**: 246  
**Columns**: 7  
**Indexes**: 2

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `role` | `varchar(50)` | N | MUL |  |  | 角色: operator/captain/normal_user |
| `perm_type` | `varchar(50)` | N |  |  |  | 权限类型: account_button/user_mgmt_button/web_page |
| `perm_key` | `varchar(100)` | N |  |  |  | 权限标识 |
| `is_allowed` | `tinyint(1)` | Y |  | `1` |  | 是否默认开启 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)
  - `uk_role_type_key` (UNIQUE `role, perm_type, perm_key`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 8406,
    "role": "normal_user",
    "perm_type": "client_page",
    "perm_key": "elf_film_tv_activity",
    "is_allowed": 0,
    "created_at": "2026-04-18T18:44:36",
    "updated_at": "2026-04-18T18:52:45"
  },
  {
    "id": 8391,
    "role": "captain",
    "perm_type": "client_page",
    "perm_key": "elf_film_tv_activity",
    "is_allowed": 0,
    "created_at": "2026-04-18T18:44:35",
    "updated_at": "2026-04-18T18:44:35"
  },
  {
    "id": 8376,
    "role": "operator",
    "perm_type": "client_page",
    "perm_key": "elf_film_tv_activity",
    "is_allowed": 0,
    "created_at": "2026-04-18T18:44:34",
    "updated_at": "2026-04-18T18:44:34"
  }
]
```

### `spark_drama_info`

**Rows**: 126,296  
**Columns**: 25  
**Indexes**: 7

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20) unsigned` | N | PRI |  | auto_increment | 主键ID |
| `biz_id` | `bigint(20)` | N | UNI |  |  | 业务ID |
| `business_type` | `int(11)` | Y | MUL |  |  | 业务类型 |
| `ref_business_id` | `bigint(20)` | Y |  |  |  | 关联业务ID |
| `title` | `varchar(500)` | Y | MUL |  |  | 短剧标题 |
| `icon` | `varchar(1000)` | Y |  |  |  | 封面图URL |
| `start_time` | `bigint(20)` | Y |  |  |  | 开始时间戳 |
| `end_time` | `bigint(20)` | Y |  |  |  | 结束时间戳 |
| `promotion_type` | `int(11)` | Y | MUL |  |  | 推广类型 |
| `promotion_type_desc` | `varchar(100)` | Y |  |  |  | 推广类型描述 |
| `redirect_url` | `varchar(1000)` | Y |  |  |  | 跳转URL |
| `tags` | `json` | Y |  |  |  | 标签(JSON格式) |
| `classifications` | `json` | Y |  |  |  | 分类(JSON格式) |
| `label` | `varchar(500)` | Y |  |  |  | 标签 |
| `description` | `text` | Y |  |  |  | 描述 |
| `income_desc` | `varchar(100)` | Y |  |  |  | 收入描述 |
| `joined` | `tinyint(4)` | Y | MUL | `0` |  | 是否已加入: 1-是, 0-否 |
| `view_status` | `int(11)` | Y |  |  |  | 查看状态 |
| `commission_rate` | `decimal(5,2)` | Y |  | `0.00` |  | 佣金比例 |
| `raw_data` | `json` | Y |  |  |  | 原始数据(JSON格式) |
| `created_at` | `datetime` | N | MUL | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | N |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |
| `platform` | `tinyint(3) unsigned` | N |  | `1` |  | 平台 1-星火计划 2-荧光计划 |
| `jump_url` | `varchar(1000)` | Y |  | `` |  | 试看url |
| `serial_id` | `varchar(255)` | Y |  | `` |  |  |

**Indexes**:
  - `idx_business_type` (`business_type`)
  - `idx_created_at` (`created_at`)
  - `idx_joined` (`joined`)
  - `idx_promotion_type` (`promotion_type`)
  - `idx_title` (`title`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_biz_id` (UNIQUE `biz_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 427455,
    "biz_id": 180473,
    "business_type": null,
    "ref_business_id": null,
    "title": "悔不当初",
    "icon": null,
    "start_time": null,
    "end_time": null,
    "promotion_type": null,
    "promotion_type_desc": null,
    "redirect_url": "kwai://krn?bundleId=CommercialTubeTaskDetail&componentName=CommercialTubeTaskDetail&themeStyle=1&taskId=180473",
    "tags": "[\"真人剧\", \"都市\"]",
    "classifications": null,
    "label": null,
    "description": null,
    "income_desc": null,
    "joined": 0,
    "view_status": null,
    "commission_rate": 0.0,
    "raw_data": null,
    "created_at": "2026-04-17T16:13:21",
    "updated_at": "2026-04-17T16:13:21",
    "platform": 2,
    "jump_url": "",
    "serial_id": ""
  },
  {
    "id": 427451,
    "biz_id": 134663,
    "business_type": null,
    "ref_business_id": null,
    "title": "如果爱忘了",
    "icon": null,
    "start_time": null,
    "end_time": null,
    "promotion_type": null,
    "promotion_type_desc": null,
    "redirect_url": "kwai://krn?bundleId=CommercialTubeTaskDetail&componentName=CommercialTubeTaskDetail&themeStyle=1&taskId=134663",
    "tags": "[\"真人剧\", \"都市\"]",
    "classifications": null,
    "label": null,
    "description": null,
    "income_desc": null,
    "joined": 0,
    "view_status": null,
    "commission_rate": 0.0,
    "raw_data": null,
    "created_at": "2026-04-17T16:13:20",
    "updated_at": "2026-04-17T16:13:20",
    "platform": 2,
    "jump_url": "",
    "serial_id": ""
  },
  {
    "id": 427450,
    "biz_id": 167979,
    "business_type": null,
    "ref_business_id": null,
    "title": "超凡的男人",
    "icon": null,
    "start_time": null,
    "end_time": null,
    "promotion_type": null,
    "promotion_type_desc": null,
    "redirect_url": "kwai://krn?bundleId=CommercialTubeTaskDetail&componentName=CommercialTubeTaskDetail&themeStyle=1&taskId=167979",
    "tags": "[\"真人剧\", \"乡村\", \"古风\", \"武侠\"]",
    "classifications": null,
    "label": null,
    "description": null,
    "income_desc": null,
    "joined": 0,
    "view_status": null,
    "commission_rate": 0.0,
    "raw_data": null,
    "created_at": "2026-04-17T16:13:19",
    "updated_at": "2026-04-17T16:13:19",
    "platform": 2,
    "jump_url": "",
    "serial_id": ""
  }
]
```

### `spark_highincome_dramas`

**Rows**: 432  
**Columns**: 3  
**Indexes**: 2

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11) unsigned` | N | PRI |  | auto_increment |  |
| `title` | `varchar(100)` | Y | UNI |  |  | 短剧标题 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 创建时间 |

**Indexes**:
  - `idx_title_unique` (UNIQUE `title`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 1172,
    "title": "蛇年到系统喊我迎财神",
    "created_at": "2026-04-14T17:22:42"
  },
  {
    "id": 1171,
    "title": "蛇债难偿",
    "created_at": "2026-04-14T17:22:42"
  },
  {
    "id": 1170,
    "title": "母望子归",
    "created_at": "2026-04-14T17:22:42"
  }
]
```

### `spark_income`

**Rows**: 80  
**Columns**: 12  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment |  |
| `member_id` | `bigint(20)` | N | MUL |  |  | 成员ID |
| `member_name` | `varchar(100)` | Y |  |  |  | 成员昵称 |
| `task_id` | `varchar(50)` | N | MUL |  |  | 任务ID |
| `task_name` | `varchar(200)` | Y |  |  |  | 任务名称 |
| `task_period` | `varchar(100)` | Y |  |  |  | 任务周期(如: 2025.11.25 ~ 2026.11.30) |
| `income` | `decimal(10,2)` | Y | MUL | `0.00` |  | 收益金额 |
| `start_date` | `date` | Y |  |  |  | 任务开始日期 |
| `end_date` | `date` | Y |  |  |  | 任务结束日期 |
| `org_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_income` (`income`)
  - `idx_member_id` (`member_id`)
  - `idx_member_task` (UNIQUE `member_id, task_id`)
  - `idx_spark_income_org_id` (`org_id`)
  - `idx_task_id` (`task_id`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 114633,
    "member_id": 475213298,
    "member_name": "刚刚短剧",
    "task_id": "3963528",
    "task_name": "青山难越风掠去",
    "task_period": "2025.10.20 ~ 2026.10.31",
    "income": 0.4,
    "start_date": "2025-10-20",
    "end_date": "2026-10-31",
    "org_id": 14,
    "created_at": "2026-04-09T16:03:15",
    "updated_at": "2026-04-09T16:03:15"
  },
  {
    "id": 114632,
    "member_id": 4619807639,
    "member_name": "瑶瑶追剧",
    "task_id": "4242825",
    "task_name": "落花村隐秘",
    "task_period": "2025.12.12 ~ 2026.12.12",
    "income": 0.03,
    "start_date": "2025-12-12",
    "end_date": "2026-12-12",
    "org_id": 14,
    "created_at": "2026-04-09T16:03:13",
    "updated_at": "2026-04-09T16:03:13"
  },
  {
    "id": 114631,
    "member_id": 4619807639,
    "member_name": "瑶瑶追剧",
    "task_id": "4572421",
    "task_name": "麻雀怎能同雁飞",
    "task_period": "2026.01.28 ~ 2027.01.31",
    "income": 0.16,
    "start_date": "2026-01-28",
    "end_date": "2027-01-31",
    "org_id": 14,
    "created_at": "2026-04-09T16:03:13",
    "updated_at": "2026-04-09T16:03:13"
  }
]
```

### `spark_income_archive`

**Rows**: 3,315  
**Columns**: 18  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment |  |
| `member_id` | `bigint(20)` | N | MUL |  |  | 成员ID |
| `member_name` | `varchar(100)` | N |  |  |  | 成员昵称 |
| `member_head` | `varchar(500)` | Y |  |  |  | 头像URL |
| `fans_count` | `int(11)` | Y | MUL | `0` |  | 粉丝数 |
| `in_limit` | `tinyint(1)` | Y |  | `0` |  | 是否限额(0=否,1=是) |
| `broker_name` | `varchar(50)` | Y | MUL | `未分配` |  | 经纪人名称 |
| `org_task_num` | `int(11)` | Y |  | `0` |  | 机构任务数 |
| `total_amount` | `decimal(10,2)` | Y |  | `0.00` |  | 总金额 |
| `archive_month` | `int(11)` | N |  |  |  | 收益所属月份(1-12) |
| `archive_year` | `int(11)` | N | MUL |  |  | 收益所属年份 |
| `start_time` | `bigint(20)` | Y |  |  |  | 开始时间戳(毫秒) |
| `end_time` | `bigint(20)` | Y |  |  |  | 结束时间戳(毫秒) |
| `archived_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 存档时间 |
| `settlement_status` | `varchar(20)` | Y |  | `unsettled` |  | 结算状态: settled=已结清, unsettled=未结清 |
| `commission_rate` | `decimal(5,2)` | Y | MUL | `100.00` |  | 分成比例(%)，默认100% |
| `commission_amount` | `decimal(10,2)` | Y |  |  | STORED GENERATED | 扣除分成金额（自动计算） |
| `org_id` | `int(10) unsigned` | N |  | `1` |  | 机构id |

**Indexes**:
  - `idx_archive_period` (`archive_year, archive_month`)
  - `idx_broker_name` (`broker_name`)
  - `idx_commission_rate` (`commission_rate`)
  - `idx_fans_count` (`fans_count`)
  - `idx_member_id` (`member_id`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 4788,
    "member_id": 1710025549,
    "member_name": "星荧墨砚",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/02/11/09/BMjAyNjAyMTEwOTE0MjhfMTcxMDAyNTU0OV8yX2hkMTIwXzY3OQ==_s.jpg",
    "fans_count": 0,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "archive_month": 3,
    "archive_year": 2026,
    "start_time": 1772035200000,
    "end_time": 1774454399999,
    "archived_at": "2026-04-02T19:03:33",
    "settlement_status": "unsettled",
    "commission_rate": 80.0,
    "commission_amount": 0.0,
    "org_id": 1
  },
  {
    "id": 4787,
    "member_id": 5259650625,
    "member_name": "英英蓓",
    "member_head": "https://p5-pro.a.yximgs.com/uhead/AB/2026/01/31/19/BMjAyNjAxMzExOTU4NTRfNTI1OTY1MDYyNV8yX2hkMjMyXzU2MA==_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "俞磊",
    "org_task_num": 0,
    "total_amount": 0.0,
    "archive_month": 3,
    "archive_year": 2026,
    "start_time": 1772035200000,
    "end_time": 1774454399999,
    "archived_at": "2026-04-02T19:03:33",
    "settlement_status": "unsettled",
    "commission_rate": 78.0,
    "commission_amount": 0.0,
    "org_id": 1
  },
  {
    "id": 4786,
    "member_id": 5181492498,
    "member_name": "鹏鹏看好剧",
    "member_head": "https://p5-pro.a.yximgs.com/uhead/AB/2025/12/05/20/BMjAyNTEyMDUyMDA2NThfNTE4MTQ5MjQ5OF8xX2hkOThfNTI0_s.jpg",
    "fans_count": 1,
    "in_limit": 0,
    "broker_name": "俞磊",
    "org_task_num": 0,
    "total_amount": 0.0,
    "archive_month": 3,
    "archive_year": 2026,
    "start_time": 1772035200000,
    "end_time": 1774454399999,
    "archived_at": "2026-04-02T19:03:33",
    "settlement_status": "unsettled",
    "commission_rate": 78.0,
    "commission_amount": 0.0,
    "org_id": 1
  }
]
```

### `spark_members`

**Rows**: 1,198  
**Columns**: 13  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment |  |
| `member_id` | `bigint(20)` | N | UNI |  |  | 成员ID |
| `member_name` | `varchar(100)` | N |  |  |  | 成员昵称 |
| `member_head` | `varchar(500)` | Y |  |  |  | 头像URL |
| `fans_count` | `int(11)` | Y | MUL | `0` |  | 粉丝数 |
| `in_limit` | `tinyint(1)` | Y |  | `0` |  | 是否限额(0=否,1=是) |
| `broker_name` | `varchar(50)` | Y | MUL | `未分配` |  | 经纪人名称 |
| `org_task_num` | `int(11)` | Y |  | `0` |  | 机构任务数 |
| `total_amount` | `decimal(10,2)` | Y |  | `0.00` |  | 总金额 |
| `org_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |
| `best_publish_times` | `text` | Y |  |  |  | AI分析的最佳发布时间(JSON格式) |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_broker_name` (`broker_name`)
  - `idx_fans_count` (`fans_count`)
  - `idx_member_id` (`member_id`)
  - `idx_spark_members_org_id` (`org_id`)
  - `member_id` (UNIQUE `member_id`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 179308,
    "member_id": 5358212422,
    "member_name": "aa短剧",
    "member_head": "https://p4-pro.a.yximgs.com/uhead/AB/2026/03/01/19/BMjAyNjAzMDExOTMxMDhfNTM1ODIxMjQyMl8yX2hkNzlfNzMx_s.jpg",
    "fans_count": 4,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "org_id": 1,
    "best_publish_times": null,
    "created_at": "2026-04-19T13:18:26",
    "updated_at": "2026-04-19T13:18:26"
  },
  {
    "id": 179297,
    "member_id": 1808025061,
    "member_name": "云朵剧场",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/04/18/08/BMjAyNjA0MTgwODA5NTBfMTgwODAyNTA2MV8xX2hkNjA0XzY1MA==_s.jpg",
    "fans_count": 8,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "org_id": 1,
    "best_publish_times": null,
    "created_at": "2026-04-19T13:18:26",
    "updated_at": "2026-04-19T13:18:26"
  },
  {
    "id": 179266,
    "member_id": 5439388863,
    "member_name": "小艾追剧",
    "member_head": "https://p5-pro.a.yximgs.com/uhead/AB/2026/04/16/18/BMjAyNjA0MTYxODEzMDNfNTQzOTM4ODg2M18xX2hkMzc3XzM4OQ==_s.jpg",
    "fans_count": 58,
    "in_limit": 0,
    "broker_name": "未分配",
    "org_task_num": 0,
    "total_amount": 0.0,
    "org_id": 1,
    "best_publish_times": null,
    "created_at": "2026-04-19T13:18:26",
    "updated_at": "2026-04-19T13:18:26"
  }
]
```

### `spark_org_members`

**Rows**: 6,029  
**Columns**: 25  
**Indexes**: 7

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment | 主键ID |
| `member_id` | `bigint(20)` | N | UNI |  |  | 成员ID |
| `user_id` | `bigint(20)` | Y |  |  |  | 用户ID |
| `member_name` | `varchar(255)` | Y |  |  |  | 成员昵称 |
| `member_head` | `varchar(512)` | Y |  |  |  | 成员头像URL |
| `fans_count` | `int(11)` | Y |  | `0` |  | 粉丝数 |
| `broker_id` | `bigint(20)` | Y | MUL | `0` |  | 经纪人ID |
| `broker_name` | `varchar(255)` | Y |  |  |  | 经纪人姓名 |
| `agreement_types` | `varchar(255)` | Y |  |  |  | 合作类型列表(逗号分隔): 4视频合作MCN, 13星火计划, 14原生短剧推广计划 |
| `broker_type` | `int(11)` | Y |  | `-1` |  | 经纪人类型 |
| `last_photo_time` | `bigint(20)` | Y |  |  |  | 最后发作品时间戳(毫秒) |
| `last_photo_date` | `datetime` | Y |  |  |  | 最后发作品时间 |
| `last_live_time` | `bigint(20)` | Y |  |  |  | 最后直播时间戳(毫秒) |
| `last_live_date` | `datetime` | Y |  |  |  | 最后直播时间 |
| `content_category` | `varchar(50)` | Y |  | `-` |  | 内容分类 |
| `contract_renew_status` | `int(11)` | Y | MUL | `-1` |  | 续约状态: 8已开启自动续约 |
| `contract_expire_time` | `bigint(20)` | Y |  |  |  | 合同过期时间戳(毫秒) |
| `contract_expire_date` | `datetime` | Y |  |  |  | 合同过期时间 |
| `comment` | `text` | Y |  |  |  | 备注 |
| `join_time` | `bigint(20)` | Y |  |  |  | 加入机构时间戳(毫秒) |
| `join_date` | `datetime` | Y | MUL |  |  | 加入机构时间 |
| `mcn_grade` | `varchar(50)` | Y |  |  |  | MCN等级 |
| `org_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |
| `created_at` | `timestamp` | N | MUL | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | N |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_broker_id` (`broker_id`)
  - `idx_contract_renew_status` (`contract_renew_status`)
  - `idx_created_at` (`created_at`)
  - `idx_join_date` (`join_date`)
  - `idx_spark_org_members_org_id` (`org_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_member_id` (UNIQUE `member_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 55181,
    "member_id": 5340738693,
    "user_id": 5340738693,
    "member_name": "开欣剧场",
    "member_head": "https://p2-pro.a.yximgs.com/uhead/AB/2026/04/06/18/BMjAyNjA0MDYxODQ1NTBfNTM0MDczODY5M18yX2hkMTA5XzUwNA==_s.jpg",
    "fans_count": 1,
    "broker_id": 0,
    "broker_name": "",
    "agreement_types": "14",
    "broker_type": -1,
    "last_photo_time": 0,
    "last_photo_date": null,
    "last_live_time": 1771723824642,
    "last_live_date": "2026-02-22T09:30:24",
    "content_category": "-",
    "contract_renew_status": 8,
    "contract_expire_time": 1807027200000,
    "contract_expire_date": "2027-04-07T00:00:00",
    "comment": "",
    "join_time": 1775473981259,
    "join_date": "2026-04-06T19:13:01",
    "mcn_grade": null,
    "org_id": 18,
    "created_at": "2026-04-10T17:00:36",
    "updated_at": "2026-04-10T17:00:36"
  },
  {
    "id": 55180,
    "member_id": 5340703959,
    "user_id": 5340703959,
    "member_name": "乐乐来了",
    "member_head": "https://p4-pro.a.yximgs.com/uhead/AB/2026/02/22/09/BMjAyNjAyMjIwOTEzMjVfNTM0MDcwMzk1OV8yX2hkNDQzXzYwMw==_s.jpg",
    "fans_count": 1,
    "broker_id": 0,
    "broker_name": "",
    "agreement_types": "14",
    "broker_type": -1,
    "last_photo_time": 0,
    "last_photo_date": null,
    "last_live_time": 1771723393278,
    "last_live_date": "2026-02-22T09:23:13",
    "content_category": "-",
    "contract_renew_status": 8,
    "contract_expire_time": 1807027200000,
    "contract_expire_date": "2027-04-07T00:00:00",
    "comment": "",
    "join_time": 1775474681260,
    "join_date": "2026-04-06T19:24:41",
    "mcn_grade": null,
    "org_id": 18,
    "created_at": "2026-04-10T17:00:36",
    "updated_at": "2026-04-10T17:00:36"
  },
  {
    "id": 55179,
    "member_id": 5421884690,
    "user_id": 5421884690,
    "member_name": "泰然剧场",
    "member_head": "",
    "fans_count": 6,
    "broker_id": 0,
    "broker_name": "",
    "agreement_types": "14",
    "broker_type": -1,
    "last_photo_time": 1775392740493,
    "last_photo_date": "2026-04-05T20:39:00",
    "last_live_time": 0,
    "last_live_date": null,
    "content_category": "-",
    "contract_renew_status": 8,
    "contract_expire_time": 1807027200000,
    "contract_expire_date": "2027-04-07T00:00:00",
    "comment": "",
    "join_time": 1775475548695,
    "join_date": "2026-04-06T19:39:08",
    "mcn_grade": null,
    "org_id": 18,
    "created_at": "2026-04-10T17:00:36",
    "updated_at": "2026-04-10T17:00:36"
  }
]
```

### `spark_photos`

**Rows**: 0  
**Columns**: 17  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `bigint(20)` | N | PRI |  | auto_increment |  |
| `photo_id` | `varchar(50)` | N | UNI |  |  | 作品ID |
| `member_id` | `bigint(20)` | N | MUL |  |  | 成员ID |
| `member_name` | `varchar(100)` | Y |  |  |  | 成员昵称 |
| `title` | `varchar(500)` | Y |  |  |  | 作品标题 |
| `view_count` | `int(11)` | Y | MUL | `0` |  | 播放量 |
| `like_count` | `int(11)` | Y |  | `0` |  | 点赞数 |
| `comment_count` | `int(11)` | Y |  | `0` |  | 评论数 |
| `duration` | `varchar(20)` | Y |  |  |  | 时长(如: 08:31) |
| `publish_time` | `bigint(20)` | Y | MUL |  |  | 发布时间戳(毫秒) |
| `publish_date` | `datetime` | Y |  |  |  | 发布时间 |
| `cover_url` | `varchar(500)` | Y |  |  |  | 封面URL |
| `play_url` | `varchar(500)` | Y |  |  |  | 播放URL |
| `avatar_url` | `varchar(500)` | Y |  |  |  | 作者头像URL |
| `org_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_member_id` (`member_id`)
  - `idx_publish_time` (`publish_time`)
  - `idx_spark_photos_org_id` (`org_id`)
  - `idx_view_count` (`view_count`)
  - `photo_id` (UNIQUE `photo_id`)
  - `PRIMARY` (UNIQUE `id`)


### `spark_violation_dramas`

**Rows**: 2,434  
**Columns**: 20  
**Indexes**: 6

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment | 主键ID |
| `drama_title` | `varchar(200)` | N | UNI |  |  | 短剧标题（从作品标题中提取 #快来看短剧 前面的内容） |
| `source_photo_id` | `varchar(50)` | Y |  |  |  | 来源作品ID |
| `source_caption` | `text` | Y |  |  |  | 原始作品标题 |
| `user_id` | `bigint(20)` | Y | MUL |  |  | 用户ID |
| `username` | `varchar(100)` | Y |  |  |  | 用户昵称 |
| `violation_count` | `int(11)` | Y | MUL | `1` |  | 违规次数 |
| `last_violation_time` | `bigint(20)` | Y | MUL |  |  | 最近一次违规时间戳 |
| `last_violation_date` | `datetime` | Y |  |  |  | 最近一次违规时间 |
| `sub_biz` | `varchar(50)` | Y |  |  |  | 最新违规类型 |
| `status_desc` | `varchar(50)` | Y |  |  |  | 最新状态描述 |
| `reason` | `text` | Y |  |  |  | 最新违规原因 |
| `media_url` | `text` | Y |  |  |  | 作品视频URL |
| `thumb_url` | `text` | Y |  |  |  | 作品封面URL |
| `broker_name` | `varchar(100)` | Y |  |  |  | 经纪人姓名 |
| `is_blacklisted` | `tinyint(4)` | Y | MUL | `0` |  | 是否已拉黑: 0-未拉黑, 1-已拉黑 |
| `blacklisted_at` | `timestamp` | Y |  |  |  | 拉黑时间 |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |
| `org_id` | `int(10) unsigned` | N |  | `1` |  | 机构id |

**Indexes**:
  - `idx_is_blacklisted` (`is_blacklisted`)
  - `idx_last_violation_time` (`last_violation_time`)
  - `idx_user_id` (`user_id`)
  - `idx_violation_count` (`violation_count`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_drama_title` (UNIQUE `drama_title`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 24262,
    "drama_title": "薪资谜雾，丈夫的隐秘账本",
    "source_photo_id": "3x8ahzpwcewiggu",
    "source_caption": "薪资谜雾，丈夫的隐秘账本#快来看短剧  #别睡了铁子起来折腾吧  #这世界突然填满色彩  #美人不是凡胎生 ",
    "user_id": 5141918197,
    "username": "萌宝",
    "violation_count": 1,
    "last_violation_time": 1776378945323,
    "last_violation_date": "2026-04-17T06:35:45",
    "sub_biz": "限制流量",
    "status_desc": "不可申诉",
    "reason": "该作品与目前快手上已存在的作品高度相似。",
    "media_url": "http://tymov2.a.kwimgs.com/upic/2026/04/13/09/BMjAyNjA0MTMwOTMwNTVfNTE0MTkxODE5N18xOTI5NjUzNjE0MTJfMF8z_b_Bcd11e497c9b1fa56cf245cd937107919.mp4?tag=1-1776601698-unknown-0-m8czyopccp-4c656a9277596cfb&clientCacheKey=3x8ahzpwcewiggu_b.mp4&tt=b&di=d210ab32&bp=13290",
    "thumb_url": "http://ty2.a.kwimgs.com/upic/2026/04/13/09/BMjAyNjA0MTMwOTMwNTVfNTE0MTkxODE5N18xOTI5NjUzNjE0MTJfMF8z_B9d2c13c10ea8258029a401da380646e4.jpg?tag=1-1776601698-unknown-0-rvqh2kmyh0-18498b5a1c04f21d&clientCacheKey=3x8ahzpwcewiggu.jpg&di=d210ab32&bp=13290",
    "broker_name": "--",
    "is_blacklisted": 0,
    "blacklisted_at": null,
    "created_at": "2026-04-19T20:28:28",
    "updated_at": "2026-04-19T20:28:28",
    "org_id": 1
  },
  {
    "id": 24256,
    "drama_title": "拆迁款的秘密",
    "source_photo_id": "3xpwy6auh2dpxa2",
    "source_caption": "拆迁款的秘密#快来看短剧 ",
    "user_id": 898083133,
    "username": "东兴漫剧",
    "violation_count": 1,
    "last_violation_time": 1776379581214,
    "last_violation_date": "2026-04-17T06:46:21",
    "sub_biz": "限制流量",
    "status_desc": "不可申诉",
    "reason": "不符合社区规定",
    "media_url": "",
    "thumb_url": "/rest/polar/negative/download?key=photo-thumb@193288305769",
    "broker_name": "--",
    "is_blacklisted": 0,
    "blacklisted_at": null,
    "created_at": "2026-04-19T20:28:26",
    "updated_at": "2026-04-19T20:28:26",
    "org_id": 1
  },
  {
    "id": 24085,
    "drama_title": "昨夜长风今消散",
    "source_photo_id": "3xvmpjfnijvaxgc",
    "source_caption": "昨夜长风今消散#快来看短剧 ",
    "user_id": 5032195265,
    "username": "喵猫剧场",
    "violation_count": 1,
    "last_violation_time": 1776390233434,
    "last_violation_date": "2026-04-17T09:43:53",
    "sub_biz": "屏蔽流量",
    "status_desc": "可申诉",
    "reason": "不符合社区规定",
    "media_url": "",
    "thumb_url": "/rest/polar/negative/download?key=photo-thumb-with-watermark@193255411589",
    "broker_name": "--",
    "is_blacklisted": 0,
    "blacklisted_at": null,
    "created_at": "2026-04-19T20:28:14",
    "updated_at": "2026-04-19T20:28:14",
    "org_id": 1
  }
]
```

### `spark_violation_photos`

**Rows**: 32,497  
**Columns**: 31  
**Indexes**: 7

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment | 主键ID |
| `photo_id` | `varchar(50)` | N | UNI |  |  | 作品ID |
| `user_id` | `bigint(20)` | Y | MUL |  |  | 用户ID |
| `username` | `varchar(100)` | Y |  |  |  | 用户昵称 |
| `caption` | `text` | Y |  |  |  | 作品标题 |
| `like_count` | `int(11)` | Y |  | `0` |  | 点赞数 |
| `view_count` | `int(11)` | Y |  | `0` |  | 播放量 |
| `forward_count` | `int(11)` | Y |  | `0` |  | 转发数 |
| `comment_count` | `int(11)` | Y |  | `0` |  | 评论数 |
| `media_url` | `text` | Y |  |  |  | 视频URL |
| `thumb_url` | `text` | Y |  |  |  | 封面URL |
| `avatar_url` | `text` | Y |  |  |  | 头像URL |
| `publish_time` | `bigint(20)` | Y | MUL |  |  | 发布时间戳(毫秒) |
| `publish_date` | `datetime` | Y |  |  |  | 发布时间 |
| `fans_count` | `int(11)` | Y |  | `0` |  | 粉丝数 |
| `broker_id` | `bigint(20)` | Y |  |  |  | 经纪人ID |
| `broker_name` | `varchar(100)` | Y |  |  |  | 经纪人姓名 |
| `sub_biz_id` | `int(11)` | Y |  |  |  | 违规类型ID |
| `sub_biz` | `varchar(50)` | Y | MUL |  |  | 违规类型名称 |
| `status` | `int(11)` | Y |  |  |  | 状态: 1-可申诉, 2-申诉中, 3-不可申诉 |
| `status_desc` | `varchar(50)` | Y |  |  |  | 状态描述 |
| `negative_audit_time` | `bigint(20)` | Y |  |  |  | 违规审核时间戳 |
| `reason` | `text` | Y |  |  |  | 违规原因 |
| `suggestion` | `text` | Y |  |  |  | 改进建议 |
| `appeal_status` | `int(11)` | Y |  |  |  | 申诉状态 |
| `appeal_status_desc` | `varchar(50)` | Y |  |  |  | 申诉状态描述 |
| `appeal_detail` | `text` | Y |  |  |  | 申诉详情 |
| `punish_time` | `bigint(20)` | Y | MUL |  |  | 处罚时间戳 |
| `org_id` | `int(11)` | Y | MUL | `1` |  | 所属机构ID |
| `created_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |

**Indexes**:
  - `idx_publish_time` (`publish_time`)
  - `idx_punish_time` (`punish_time`)
  - `idx_spark_violation_photos_org_id` (`org_id`)
  - `idx_sub_biz` (`sub_biz`)
  - `idx_user_id` (`user_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_photo_id` (UNIQUE `photo_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 40104,
    "photo_id": "3xu38mxghvck6pc",
    "user_id": 398631686,
    "username": "阿剧追剧",
    "caption": "毛毛姐多用途洗衣膏小白鞋清洁【QT】 #膏小白鞋 #QT #毛毛 #洗衣",
    "like_count": 0,
    "view_count": 1,
    "forward_count": 0,
    "comment_count": 0,
    "media_url": "http://tymov2.a.kwimgs.com/upic/2026/04/17/05/BMjAyNjA0MTcwNTEyMTRfMzk4NjMxNjg2XzE5MzI4NjI1NjEwMF8wXzM=_b_Bed3da0352532a20e3a312584f6754095.mp4?tag=1-1776601702-unknown-0-z8xgkubz2o-733e4865319fb05a&clientCacheKey=3xu38mxghvck6pc_b.mp4&tt=b&di=d210ab32&bp=13290",
    "thumb_url": "http://ty2.a.kwimgs.com/upic/2026/04/17/05/BMjAyNjA0MTcwNTEyMTRfMzk4NjMxNjg2XzE5MzI4NjI1NjEwMF8wXzM=_B237a8643bfafc20eeffe7b83f81ea365.jpg?tag=1-1776601702-unknown-0-bmh1odwuy1-3ce3a4084dadaf0b&clientCacheKey=3xu38mxghvck6pc.jpg&di=d210ab32&bp=13290",
    "avatar_url": "https://p4-pro.a.yximgs.com/uhead/AB/2026/04/15/22/BMjAyNjA0MTUyMjQwMDVfMzk4NjMxNjg2XzJfaGQ1NjJfODky_s.jpg",
    "publish_time": 1776374021661,
    "publish_date": "2026-04-17T05:13:41",
    "fans_count": 2220,
    "broker_id": 0,
    "broker_name": "--",
    "sub_biz_id": 2,
    "sub_biz": "限制流量",
    "status": 3,
    "status_desc": "不可申诉",
    "negative_audit_time": 1776374143858,
    "reason": "该作品与目前快手上已存在的作品高度相似。",
    "suggestion": "作品与平台内存在的其他作品相似，或存在简单二次创作的行为，建议您：\n1.提升作品的多样性，增加更丰富的元素和解说，避免使用和他人作品一样的图片、视频素材，或是重复发布同样的作品；\n2.谨慎使用网络热门素材，坚持原创，尽可能使用自己的素材和创意制作作品；\n3.更换背景、字幕、配乐或特效。",
    "appeal_status": 3,
    "appeal_status_desc": "不可申诉",
    "appeal_detail": "该判罚不支持申诉，如有疑问请联系客服",
    "punish_time": 1776374143858,
    "org_id": 1,
    "created_at": "2026-04-19T20:28:32",
    "updated_at": "2026-04-19T20:28:32"
  },
  {
    "id": 40103,
    "photo_id": "3x667xtzxyxfjcy",
    "user_id": 3589568899,
    "username": "流星追剧",
    "caption": "寒门出贵子#快来看短剧 ",
    "like_count": 0,
    "view_count": 1,
    "forward_count": 0,
    "comment_count": 0,
    "media_url": "",
    "thumb_url": "/rest/polar/negative/download?key=photo-thumb-with-watermark@193216480249",
    "avatar_url": "https://p5-pro.a.yximgs.com/uhead/AB/2026/03/14/18/BMjAyNjAzMTQxODEwMTlfMzU4OTU2ODg5OV8yX2hkODFfNDc4_s.jpg",
    "publish_time": 1776308046049,
    "publish_date": "2026-04-16T10:54:06",
    "fans_count": 81,
    "broker_id": 0,
    "broker_name": "--",
    "sub_biz_id": 1,
    "sub_biz": "屏蔽流量",
    "status": 1,
    "status_desc": "可申诉",
    "negative_audit_time": 1776374145195,
    "reason": "不符合社区规定",
    "suggestion": "作品可能含有以下内容：\n1.对站内部分特定魔法表情/特效存在商业化的使用与展示，如挂小黄车等；\n2.作品含有其他平台的水印、标识、名字或相关信息；\n3.出现侵犯他人合法权益的内容，如著作权、肖像权、隐私权、名誉权等；\n4.出现低俗性暗示的内容，或色情推广信息，如展示色情网址、色情图片；\n5.出现引导至站外平台的内容；\n6.出现血腥暴力、观感不佳、封建迷信、非正规传教等内容；\n7.推广不合规的产品及服务，或存在夸大宣传、保证疗效等内容。\n请遵守平台规则，避免发布此类作品，您可以调整创作方向，在快手，正能量的作品将收获更多喜爱。",
    "appeal_status": 1,
    "appeal_status_desc": "可申诉",
    "appeal_detail": "",
    "punish_time": 1776374145195,
    "org_id": 1,
    "created_at": "2026-04-19T20:28:32",
    "updated_at": "2026-04-19T20:28:32"
  },
  {
    "id": 40102,
    "photo_id": "3xxs9v3c2xwfid9",
    "user_id": 1770223540,
    "username": "吴东红452",
    "caption": "老婆大人别想逃#快来看短剧 ",
    "like_count": 0,
    "view_count": 301,
    "forward_count": 0,
    "comment_count": 0,
    "media_url": "",
    "thumb_url": "/rest/polar/negative/download?key=photo-thumb-with-watermark@193238587917",
    "avatar_url": "http://p2.a.yximgs.com/s1/i/def/head_f.png",
    "publish_time": 1776326967157,
    "publish_date": "2026-04-16T16:09:27",
    "fans_count": 21,
    "broker_id": 0,
    "broker_name": "--",
    "sub_biz_id": 1,
    "sub_biz": "屏蔽流量",
    "status": 1,
    "status_desc": "可申诉",
    "negative_audit_time": 1776374148344,
    "reason": "不符合社区规定",
    "suggestion": "作品可能含有以下内容：\n1.对站内部分特定魔法表情/特效存在商业化的使用与展示，如挂小黄车等；\n2.作品含有其他平台的水印、标识、名字或相关信息；\n3.出现侵犯他人合法权益的内容，如著作权、肖像权、隐私权、名誉权等；\n4.出现低俗性暗示的内容，或色情推广信息，如展示色情网址、色情图片；\n5.出现引导至站外平台的内容；\n6.出现血腥暴力、观感不佳、封建迷信、非正规传教等内容；\n7.推广不合规的产品及服务，或存在夸大宣传、保证疗效等内容。\n请遵守平台规则，避免发布此类作品，您可以调整创作方向，在快手，正能量的作品将收获更多喜爱。",
    "appeal_status": 1,
    "appeal_status_desc": "可申诉",
    "appeal_detail": "",
    "punish_time": 1776374148344,
    "org_id": 1,
    "created_at": "2026-04-19T20:28:32",
    "updated_at": "2026-04-19T20:28:32"
  }
]
```

### `system_announcements`

**Rows**: 4  
**Columns**: 13  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment | 公告ID |
| `title` | `varchar(200)` | N |  |  |  | 公告标题 |
| `content` | `text` | N |  |  |  | 公告内容 |
| `link_url` | `varchar(500)` | Y |  |  |  | 链接地址(可选) |
| `link_text` | `varchar(100)` | Y |  |  |  | 链接文字(可选) |
| `is_enabled` | `tinyint(1)` | Y | MUL | `1` |  | 是否启用: 1=启用, 0=禁用 |
| `priority` | `int(11)` | Y | MUL | `0` |  | 优先级(数字越大越优先) |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |
| `target_roles` | `text` | Y |  |  |  | 目标角色(JSON数组) |
| `target_users` | `text` | Y |  |  |  | 目标用户ID(JSON数组) |
| `attachments` | `text` | Y |  |  |  | 附件列表(JSON数组) |
| `platform` | `varchar(20)` | Y | MUL | `web` |  | 平台类型: web=网页版, client=客户端 |

**Indexes**:
  - `idx_enabled` (`is_enabled`)
  - `idx_platform` (`platform`)
  - `idx_priority` (`priority`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 14,
    "title": "测试2",
    "content": "测试2",
    "link_url": null,
    "link_text": "测试2",
    "is_enabled": 1,
    "priority": 0,
    "created_at": "2026-04-13T12:24:33",
    "updated_at": "2026-04-13T12:24:33",
    "target_roles": null,
    "target_users": "[2]",
    "attachments": null,
    "platform": "both"
  },
  {
    "id": 13,
    "title": "版本更新",
    "content": "快手短剧精灵多线程版本更新了  更新地址点击下方链接进行进入更新。目前最新版本是1.8.6",
    "link_url": "https://share.feijipan.com/s/6Z1klYpb",
    "link_text": "快手短剧精灵多线程版本更新地址",
    "is_enabled": 1,
    "priority": 2,
    "created_at": "2026-04-12T20:50:16",
    "updated_at": "2026-04-15T12:12:09",
    "target_roles": null,
    "target_users": "[2]",
    "attachments": null,
    "platform": "client"
  },
  {
    "id": 12,
    "title": "星火计划12月26日-1月25日收益结算",
    "content": "@所有人，星火计划12月26日-1月25日收益均已经结算完毕， 支付宝查询后台查收，还没结算到收益的，请联系团长结算！",
    "link_url": null,
    "link_text": null,
    "is_enabled": 1,
    "priority": 1,
    "created_at": "2026-03-22T21:21:44",
    "updated_at": "2026-03-22T21:21:44",
    "target_roles": null,
    "target_users": null,
    "attachments": null,
    "platform": "web"
  }
]
```

### `task_statistics`

**Rows**: 84,212  
**Columns**: 13  
**Indexes**: 12

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `uid` | `varchar(50)` | N | MUL |  |  | 快手账号UID |
| `device_serial` | `varchar(50)` | Y | MUL |  |  | 设备序列号 |
| `drama_link` | `varchar(500)` | Y |  |  |  | 短剧链接 |
| `drama_name` | `varchar(200)` | Y | MUL |  |  | 短剧名称 |
| `task_type` | `varchar(50)` | Y | MUL |  |  | 任务类型（短剧/商品/合集） |
| `task_config` | `json` | Y |  |  |  | 任务配置（JSON格式） |
| `status` | `varchar(20)` | N | MUL |  |  | 任务状态（success/failed/pending） |
| `error_message` | `text` | Y |  |  |  | 错误信息 |
| `start_time` | `datetime` | Y |  |  |  | 开始时间 |
| `end_time` | `datetime` | Y |  |  |  | 结束时间 |
| `duration` | `int(11)` | Y |  |  |  | 执行时长（秒） |
| `created_at` | `datetime` | Y | MUL | `CURRENT_TIMESTAMP` |  | 记录创建时间 |

**Indexes**:
  - `idx_created_at` (`created_at`)
  - `idx_device` (`device_serial`)
  - `idx_status` (`status`)
  - `idx_task_created_at` (`created_at`)
  - `idx_task_created_status` (`created_at, status`)
  - `idx_task_drama_name` (`drama_name`)
  - `idx_task_status` (`status`)
  - `idx_task_type` (`task_type`)
  - `idx_task_uid` (`uid`)
  - `idx_task_uid_created` (`uid, created_at`)
  - `idx_uid` (`uid`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 90127,
    "uid": "API:前夫请自重",
    "device_serial": "API_MODE",
    "drama_link": "",
    "drama_name": "API搜索: 前夫请自重",
    "task_type": "api_video_collection",
    "task_config": "{\"keyword\": \"前夫请自重\", \"max_pages\": 4, \"task_type\": \"api_video_collection\", \"drama_name\": \"API搜索: 前夫请自重\", \"tag_filter\": \"快来看短剧\", \"target_count\": 80, \"min_like_count\": 600, \"min_play_count\": 10000, \"min_comment_count\": 0}",
    "status": "success",
    "error_message": null,
    "start_time": "2026-04-20T01:06:07",
    "end_time": "2026-04-20T01:07:41",
    "duration": 91,
    "created_at": "2026-04-20T01:06:07"
  },
  {
    "id": 90126,
    "uid": "API:前任请自重",
    "device_serial": "API_MODE",
    "drama_link": "",
    "drama_name": "API搜索: 前任请自重",
    "task_type": "api_video_collection",
    "task_config": "{\"keyword\": \"前任请自重\", \"max_pages\": 4, \"task_type\": \"api_video_collection\", \"drama_name\": \"API搜索: 前任请自重\", \"tag_filter\": \"快来看短剧\", \"target_count\": 80, \"min_like_count\": 600, \"min_play_count\": 10000, \"min_comment_count\": 0}",
    "status": "success",
    "error_message": null,
    "start_time": "2026-04-20T01:04:45",
    "end_time": "2026-04-20T01:06:06",
    "duration": 81,
    "created_at": "2026-04-20T01:04:45"
  },
  {
    "id": 90125,
    "uid": "API:大小姐她心动了",
    "device_serial": "API_MODE",
    "drama_link": "",
    "drama_name": "API搜索: 大小姐她心动了",
    "task_type": "api_video_collection",
    "task_config": "{\"keyword\": \"大小姐她心动了\", \"max_pages\": 4, \"task_type\": \"api_video_collection\", \"drama_name\": \"API搜索: 大小姐她心动了\", \"tag_filter\": \"快来看短剧\", \"target_count\": 80, \"min_like_count\": 600, \"min_play_count\": 10000, \"min_comment_count\": 0}",
    "status": "success",
    "error_message": null,
    "start_time": "2026-04-20T01:04:13",
    "end_time": "2026-04-20T01:04:43",
    "duration": 30,
    "created_at": "2026-04-20T01:04:13"
  }
]
```

### `tv_dramas`

**Rows**: 391  
**Columns**: 5  
**Indexes**: 1

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  |  |  |
| `platform` | `varchar(50)` | Y |  |  |  |  |
| `drama_name` | `varchar(200)` | Y |  |  |  |  |
| `category` | `varchar(50)` | Y |  |  |  |  |
| `hashtag` | `varchar(100)` | Y |  |  |  |  |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 422,
    "platform": "腾讯",
    "drama_name": "岁岁青莲",
    "category": "电视剧",
    "hashtag": "#岁岁青莲"
  },
  {
    "id": 419,
    "platform": "腾讯",
    "drama_name": "君子盟",
    "category": "电视剧",
    "hashtag": "#君子盟"
  },
  {
    "id": 418,
    "platform": "腾讯",
    "drama_name": "黑土无言",
    "category": "电视剧",
    "hashtag": "#黑土无言"
  }
]
```

### `tv_episodes`

**Rows**: 7,496  
**Columns**: 24  
**Indexes**: 5

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment | 主键ID |
| `photo_id` | `varchar(64)` | N | UNI |  |  | 视频ID |
| `collection_id` | `varchar(64)` | N | MUL |  |  | 合集ID |
| `collection_name` | `varchar(255)` | Y |  |  |  | 合集名称 |
| `collection_like_count` | `bigint(20)` | Y |  | `0` |  | 合集点赞数 |
| `collection_view_count` | `bigint(20)` | Y |  | `0` |  | 合集播放量 |
| `episode_number` | `int(11)` | Y | MUL |  |  | 集数 |
| `episode_name` | `varchar(100)` | Y |  |  |  | 集名 |
| `caption` | `text` | Y |  |  |  | 标题/描述 |
| `duration_ms` | `int(11)` | Y |  |  |  | 时长(毫秒) |
| `like_count` | `int(11)` | Y |  | `0` |  | 点赞数 |
| `view_count` | `int(11)` | Y |  | `0` |  | 播放量 |
| `comment_count` | `int(11)` | Y |  | `0` |  | 评论数 |
| `forward_count` | `int(11)` | Y |  | `0` |  | 转发数 |
| `collect_count` | `int(11)` | Y |  | `0` |  | 收藏数 |
| `share_count` | `int(11)` | Y |  | `0` |  | 分享数 |
| `author_user_id` | `bigint(20)` | Y | MUL |  |  | 作者用户ID |
| `author_user_name` | `varchar(100)` | Y |  |  |  | 作者用户名 |
| `timestamp` | `bigint(20)` | Y |  |  |  | 发布时间戳 |
| `created_at` | `timestamp` | N |  | `CURRENT_TIMESTAMP` |  | 创建时间 |
| `updated_at` | `timestamp` | N |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 更新时间 |
| `share_user_id` | `varchar(255)` | Y |  | `` |  | 分享用户id |
| `share_photo_id` | `varchar(255)` | Y |  | `` |  | 分享作品id |
| `drama_id` | `int(11)` | Y |  |  |  | 剧集id |

**Indexes**:
  - `idx_author_user_id` (`author_user_id`)
  - `idx_collection_id` (`collection_id`)
  - `idx_episode_number` (`episode_number`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_photo_id` (UNIQUE `photo_id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 7845,
    "photo_id": "5205316870024195633",
    "collection_id": "5xdyrrvskdnt49i",
    "collection_name": "长风渡",
    "collection_like_count": 42035,
    "collection_view_count": 8629209,
    "episode_number": 100,
    "episode_name": "第100集",
    "caption": "第100集｜ 对手连赢六局 最后一局却认输了  #白敬亭  #宋轶 ",
    "duration_ms": 80249,
    "like_count": 134,
    "view_count": 31661,
    "comment_count": 1,
    "forward_count": 0,
    "collect_count": 11,
    "share_count": 6,
    "author_user_id": 1918012815,
    "author_user_name": "幸福剧乐部",
    "timestamp": 1708947000020,
    "created_at": "2026-03-18T20:01:20",
    "updated_at": "2026-03-18T20:01:20",
    "share_user_id": "3xru29nub2gmij9",
    "share_photo_id": "3xaivfyhb8cc4ck",
    "drama_id": 55
  },
  {
    "id": 7844,
    "photo_id": "5214042595950021584",
    "collection_id": "5xdyrrvskdnt49i",
    "collection_name": "长风渡",
    "collection_like_count": 42035,
    "collection_view_count": 8629209,
    "episode_number": 99,
    "episode_name": "第99集",
    "caption": "第99集｜ 作为首富的儿子 我还要努力干嘛？ #白敬亭  #宋轶 ",
    "duration_ms": 77272,
    "like_count": 52,
    "view_count": 12313,
    "comment_count": 1,
    "forward_count": 0,
    "collect_count": 7,
    "share_count": 3,
    "author_user_id": 1918012815,
    "author_user_name": "幸福剧乐部",
    "timestamp": 1708947000224,
    "created_at": "2026-03-18T20:01:20",
    "updated_at": "2026-03-18T20:01:20",
    "share_user_id": "3xru29nub2gmij9",
    "share_photo_id": "3xtgjd3w48nrwfa",
    "drama_id": 55
  },
  {
    "id": 7843,
    "photo_id": "5218264718322897791",
    "collection_id": "5xdyrrvskdnt49i",
    "collection_name": "长风渡",
    "collection_like_count": 42035,
    "collection_view_count": 8629209,
    "episode_number": 98,
    "episode_name": "第98集",
    "caption": "第98集｜ 老公突然献殷勤 目的究竟是为啥  #白敬亭  #宋轶 ",
    "duration_ms": 68400,
    "like_count": 125,
    "view_count": 18282,
    "comment_count": 2,
    "forward_count": 0,
    "collect_count": 11,
    "share_count": 3,
    "author_user_id": 1918012815,
    "author_user_name": "幸福剧乐部",
    "timestamp": 1708947000358,
    "created_at": "2026-03-18T20:01:20",
    "updated_at": "2026-03-18T20:01:20",
    "share_user_id": "3xru29nub2gmij9",
    "share_photo_id": "3xcphgdga2r4igq",
    "drama_id": 55
  }
]
```

### `tv_publish_record`

**Rows**: 6  
**Columns**: 6  
**Indexes**: 1

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11) unsigned` | N | PRI |  | auto_increment |  |
| `drama_id` | `int(11)` | Y |  |  |  | 剧集id |
| `uid` | `int(11)` | Y |  |  |  | 快手号 |
| `collection_id` | `varchar(64)` | N |  |  |  | 合集ID |
| `episode_number` | `int(11)` | Y |  |  |  | 集数 |
| `photo_id` | `varchar(64)` | Y |  | `` |  | 作品id |

**Indexes**:
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 8,
    "drama_id": 11,
    "uid": 783076297,
    "collection_id": "5xrna3hbd97hmbq",
    "episode_number": 7,
    "photo_id": "190716450285"
  },
  {
    "id": 7,
    "drama_id": 11,
    "uid": 783076297,
    "collection_id": "5xrna3hbd97hmbq",
    "episode_number": 6,
    "photo_id": "190714751166"
  },
  {
    "id": 6,
    "drama_id": 11,
    "uid": 783076297,
    "collection_id": "5xrna3hbd97hmbq",
    "episode_number": 5,
    "photo_id": "190668134698"
  }
]
```

### `user_button_permissions`

**Rows**: 57,042  
**Columns**: 6  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `user_id` | `int(11)` | N | MUL |  |  | 用户ID |
| `button_key` | `varchar(100)` | N | MUL |  |  | 按钮标识 |
| `is_allowed` | `tinyint(1)` | Y |  | `1` |  | 是否允许: 1=允许, 0=禁止 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |

**Indexes**:
  - `idx_button_key` (`button_key`)
  - `idx_user_id` (`user_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_user_button` (UNIQUE `user_id, button_key`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 64043,
    "user_id": 1502,
    "button_key": "user_create_captain",
    "is_allowed": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 64042,
    "user_id": 1502,
    "button_key": "user_assign_operator",
    "is_allowed": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 64041,
    "user_id": 1502,
    "button_key": "user_change_role",
    "is_allowed": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  }
]
```

### `user_page_permissions`

**Rows**: 33,564  
**Columns**: 6  
**Indexes**: 4

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `user_id` | `int(11)` | N | MUL |  |  | 用户ID |
| `page_key` | `varchar(100)` | N | MUL |  |  | 页面标识 |
| `is_allowed` | `tinyint(1)` | Y |  | `1` |  | 是否允许: 1=允许, 0=禁止 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` |  |  |
| `updated_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP |  |

**Indexes**:
  - `idx_page_key` (`page_key`)
  - `idx_user_id` (`user_id`)
  - `PRIMARY` (UNIQUE `id`)
  - `uk_user_page` (UNIQUE `user_id, page_key`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 39433,
    "user_id": 1502,
    "page_key": "page:cxt-videos",
    "is_allowed": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 39432,
    "user_id": 1502,
    "page_key": "page:cxt-user",
    "is_allowed": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  },
  {
    "id": 39431,
    "user_id": 1502,
    "page_key": "page:fluorescent-income",
    "is_allowed": 0,
    "created_at": "2026-04-19T22:31:14",
    "updated_at": "2026-04-19T22:31:14"
  }
]
```

### `wait_collect_videos`

**Rows**: 21,170  
**Columns**: 7  
**Indexes**: 3

| Column | Type | Null | Key | Default | Extra | Comment |
|---|---|---|---|---|---|---|
| `id` | `int(11)` | N | PRI |  | auto_increment |  |
| `name` | `varchar(255)` | Y | MUL |  |  | 短剧名称 |
| `username` | `varchar(50)` | Y | MUL |  |  | 所属用户 |
| `created_at` | `datetime` | Y |  | `CURRENT_TIMESTAMP` | on update CURRENT_TIMESTAMP | 创建时间 |
| `url` | `text` | N |  |  |  | 短剧链接 |
| `platform` | `tinyint(1)` | N |  | `1` |  | 平台类型: 1=快手, 2=抖音 |
| `cover_url` | `text` | Y |  |  |  | 封面链接 |

**Indexes**:
  - `idx_name` (`name`)
  - `idx_user_created` (`username, created_at`)
  - `PRIMARY` (UNIQUE `id`)

**Sample (top 3 rows, sensitive fields redacted):**
```json
[
  {
    "id": 127700,
    "name": "透视狂少2",
    "username": "lidonghai888",
    "created_at": "2026-04-20T06:27:17",
    "url": "https://www.kuaishou.com/f/XUIhOXiGUvv2c6",
    "platform": 1,
    "cover_url": "https://p5.a.yximgs.com/upic/2026/04/19/21/BMjAyNjA0MTkyMTU3MDhfMjU5Njg5NTYxMF8xOTM1ODYwMDk5NDJfMl8z_cccev2_B0084b9f7baccbf4e06b4df1acc6b2923.jpg?tag=1-1776637409-xpcwebprofile-0-ryvwya7di5-40620c94f14c9bff&clientCacheKey=3xgcc93uggribk2_cccev2.jpg&di=JA4DQSAJaACVhmn55HdrKA==&bp=14734"
  },
  {
    "id": 127699,
    "name": "父母偏心，替弟下乡前我把家搬空了",
    "username": "lidonghai888",
    "created_at": "2026-04-20T06:27:17",
    "url": "https://www.kuaishou.com/f/X1f14avBTPbs14E",
    "platform": 1,
    "cover_url": "https://p5.a.yximgs.com/upic/2026/04/19/22/BMjAyNjA0MTkyMjAwMTdfMjU5Njg5NTYxMF8xOTM1ODYyOTc4MzhfMl8z_cccev2_B34a5a7003ec3bfbe94fde15dac7a29ea.jpg?tag=1-1776637409-xpcwebprofile-0-st17ugtw0o-44691983aaa4bf93&clientCacheKey=3xcaz6qid8z5g89_cccev2.jpg&di=JA4DQSAJaACVhmn55HdrKA==&bp=14734"
  },
  {
    "id": 127698,
    "name": "一份猪脚饭惹的祸",
    "username": "lidonghai888",
    "created_at": "2026-04-20T06:27:17",
    "url": "https://www.kuaishou.com/f/X-3xmsh1Goms45VO",
    "platform": 1,
    "cover_url": "https://p2.a.yximgs.com/upic/2026/04/20/00/BMjAyNjA0MjAwMDQzMTdfMjU5Njg5NTYxMF8xOTM1OTU4MTY5NjdfMl8z_cccev2_Ba33ac00ba8e37af3992e40e590b1b7d2.jpg?tag=1-1776637409-xpcwebprofile-0-vnnfaggr4b-05f1f60095dd2f42&clientCacheKey=3xxwdfvxz8v633q_cccev2.jpg&di=JA4DQSAJaACVhmn55HdrKA==&bp=14734"
  }
]
```
