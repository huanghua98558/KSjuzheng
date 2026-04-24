# MCN MySQL Deep Probe Report

- **Generated**: 2026-04-20T06:48:37
- **Source**: `im.zhongxiangbao.com:3306/shortju`

## A. 全量小表 (≤100 行的字典/配置表)

### `drama_execution_logs` (0 行)

_empty_
### `operator_quota` (0 行)

_empty_
### `spark_photos` (0 行)

_empty_
### `kuaishou_account_bindings` (2 行)

| id | kuaishou_id | machine_id | operator_account | bind_time | last_used_time | status | remark |
|---|---|---|---|---|---|---|---|
| 10 | 5245022408 | 1EF2304D-279E-4C21-A944-026791F487DE | team22 | 2026-01-24T12:53:42 | 2026-01-24T12:53:42 | disabled |  |
| 17 | 3078950457 | 5CA7C4E8-9AA5-438F-9EB7-C3F73DE1FD45 | team22 | 2026-01-24T18:29:01 | 2026-01-24T18:29:01 | active |  |

### `system_announcements` (4 行)

| id | title | created_at |
|---|---|---|
| 11 | 结算规则公告 | 2026-03-09T16:50:28 |
| 12 | 星火计划12月26日-1月25日收益结算 | 2026-03-22T21:21:44 |
| 13 | 版本更新 | 2026-04-12T20:50:16 |
| 14 | 测试2 | 2026-04-13T12:24:33 |

### `tv_publish_record` (6 行)

| id | drama_id | uid | collection_id | episode_number | photo_id |
|---|---|---|---|---|---|
| 3 | 11 | 783076297 | 5xrna3hbd97hmbq | 1 | 190663589203 |
| 4 | 11 | 783076297 | 5xrna3hbd97hmbq | 2 | 190663671693 |
| 5 | 11 | 783076297 | 5xrna3hbd97hmbq | 4 | 190667677082 |
| 6 | 11 | 783076297 | 5xrna3hbd97hmbq | 5 | 190668134698 |
| 7 | 11 | 783076297 | 5xrna3hbd97hmbq | 6 | 190714751166 |
| 8 | 11 | 783076297 | 5xrna3hbd97hmbq | 7 | 190716450285 |

### `card_keys` (8 行)

| id | card_code | status | created_at |
|---|---|---|---|
| 13 | 90ttotqlyngpz81f | active | 2026-02-12T15:44:35 |
| 14 | q4fq9fn5m3jxmj9h | active | 2026-02-12T18:07:33 |
| 15 | 77ipvgz1uc84z37h | active | 2026-02-12T21:00:41 |
| 16 | ea5d0gqjzf2uzk40 | active | 2026-02-12T21:00:41 |
| 17 | tuflqv65eopwojni | unused | 2026-02-12T21:00:41 |
| 18 | tkdt1kvt7swne6e8 | unused | 2026-02-12T21:00:41 |
| 19 | rgs0v3ngj4oshjtp | unused | 2026-02-12T21:00:41 |
| 20 | i86jmmvzre6t0vl6 | active | 2026-02-12T22:06:39 |

### `mcm_organizations` (17 行)

| id | org_name | org_code | description | is_active | include_video_collaboration | created_at | updated_at |
|---|---|---|---|---|---|---|---|
| 1 | 赤磐众享娱乐 |  |  | 1 | 1 | 2026-02-28T13:31:50 | 2026-02-28T15:18:08 |
| 2 | 测试机构 |  |  | 1 | 1 | 2026-02-28T15:42:51 | 2026-02-28T15:42:51 |
| 4 | 福州鑫河传媒 | weblogger_did=web_29494917611E81F5; _did=web_98... | 福州鑫河传媒 | 1 | 0 | 2026-03-05T17:42:22 | 2026-03-06T17:29:59 |
| 5 | 荣昌科技 | weblogger_did=web_538762496DD849A3; _did=web_15... | 荣昌科技 | 1 | 0 | 2026-03-10T14:20:21 | 2026-03-25T15:03:17 |
| 6 | 骁恒剧场 | did=web_9df5265ca7a04786aabfe05b741a349e; didv=... |  | 1 | 1 | 2026-03-10T16:28:38 | 2026-03-10T16:28:38 |
| 8 | 道道传媒 | _did=web_22116119486DC538; did=web_a3de43ce366c... |  | 1 | 0 | 2026-03-21T12:48:47 | 2026-03-24T12:50:09 |
| 9 | 书亦文化 | _did=web_359820161E65CFD0; bUserId=100045992987... |  | 1 | 0 | 2026-03-21T22:17:00 | 2026-03-22T13:56:53 |
| 10 | 火视界短剧 | 11 |  | 1 | 0 | 2026-04-01T16:05:52 | 2026-04-01T16:05:59 |
| 11 | 播播基 | _did=web_343254512F22576B; did=web_09536892d036... |  | 1 | 0 | 2026-04-02T18:54:11 | 2026-04-02T18:54:17 |
| 12 | 君寒 | _did=web_249232782D37FD4F; did=web_814de79f2c85... |  | 1 | 0 | 2026-04-03T10:50:49 | 2026-04-03T10:50:54 |
| 13 | 宸耀助手 | 1 |  | 1 | 0 | 2026-04-04T13:50:05 | 2026-04-04T13:50:12 |
| 14 | 斯塔克文化传媒 | _did=web_8579774834796C37; did=web_31e9f994baf7... |  | 1 | 0 | 2026-04-05T16:51:31 | 2026-04-05T16:51:37 |
| 15 | 可易短剧 | 1 |  | 1 | 0 | 2026-04-06T20:46:27 | 2026-04-06T20:46:32 |
| 16 | 启明星短剧 | _did=web_968976329BE6FA7E; did=web_f48534d49f4a... |  | 1 | 0 | 2026-04-09T19:55:23 | 2026-04-09T19:55:29 |
| 17 | 探界传媒 | 1 |  | 1 | 0 | 2026-04-09T21:21:35 | 2026-04-09T21:21:38 |
| 18 | 数智精灵 | 1 |  | 1 | 0 | 2026-04-10T16:35:00 | 2026-04-10T16:35:05 |
| 19 | 爱佳文化 | 1 |  | 1 | 0 | 2026-04-18T13:36:12 | 2026-04-18T13:36:19 |

### `card_usage_logs` (54 行)

| id | card_code | auth_code | action | created_at |
|---|---|---|---|---|
| 1 | 90ttotqlyngpz81f | cpkj888 | activated | 2026-02-12T15:44:58 |
| 2 | 90ttotqlyngpz81f | cpkj888 | verified | 2026-02-12T16:46:53 |
| 3 | 90ttotqlyngpz81f | cpkj888 | verified | 2026-02-12T17:06:59 |
| 4 | 90ttotqlyngpz81f | cpkj888 | verified | 2026-02-12T17:09:55 |
| 5 | 90ttotqlyngpz81f | cpkj888 | verified | 2026-02-12T17:21:31 |
| 6 | q4fq9fn5m3jxmj9h | cpkj888 | activated | 2026-02-12T19:36:23 |
| 7 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T19:40:00 |
| 8 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T19:56:48 |
| 9 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T20:04:31 |
| 10 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T20:23:27 |
| 11 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T20:25:45 |
| 12 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T20:31:22 |
| 13 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-12T20:35:50 |
| 14 | i86jmmvzre6t0vl6 | cpkj888 | activated | 2026-02-12T22:09:36 |
| 15 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:20:45 |
| 16 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:22:24 |
| 17 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:23:30 |
| 18 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:24:32 |
| 19 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:25:34 |
| 20 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:39:37 |
| 21 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:40:50 |
| 22 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:42:04 |
| 23 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:43:12 |
| 24 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:44:22 |
| 25 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T22:45:30 |
| 26 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-12T23:08:26 |
| 27 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T00:10:19 |
| 28 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T00:49:36 |
| 29 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T00:58:50 |
| 30 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T01:08:07 |
| 31 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T01:11:31 |
| 32 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T01:14:26 |
| 33 | ea5d0gqjzf2uzk40 | hdw888666 | activated | 2026-02-13T18:23:20 |
| 34 | ea5d0gqjzf2uzk40 | hdw888666 | verified | 2026-02-13T18:24:13 |
| 35 | ea5d0gqjzf2uzk40 | hdw888666 | verified | 2026-02-13T18:26:44 |
| 36 | ea5d0gqjzf2uzk40 | hdw888666 | verified | 2026-02-13T18:27:43 |
| 37 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-13T19:37:23 |
| 38 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T22:44:39 |
| 39 | 77ipvgz1uc84z37h | hdw888666 | activated | 2026-02-13T22:48:29 |
| 40 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-13T22:49:12 |
| 41 | 77ipvgz1uc84z37h | hdw888666 | verified | 2026-02-13T22:49:16 |
| 42 | 77ipvgz1uc84z37h | hdw888666 | verified | 2026-02-13T22:58:49 |
| 43 | 77ipvgz1uc84z37h | hdw888666 | verified | 2026-02-13T23:08:25 |
| 44 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-14T10:49:43 |
| 45 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-14T19:11:16 |
| 46 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-14T20:05:52 |
| 47 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-14T20:12:23 |
| 48 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-14T20:14:03 |
| 49 | q4fq9fn5m3jxmj9h | cpkj888 | verified | 2026-02-14T20:23:03 |
| 50 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-19T17:25:04 |
| 51 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-02-19T17:26:11 |
| 52 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-03-02T20:18:35 |
| 53 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-03-24T10:35:11 |
| 54 | i86jmmvzre6t0vl6 | cpkj888 | verified | 2026-04-11T14:23:23 |

### `spark_income` (80 行)

| id | created_at |
|---|---|
| 111331 | 2026-02-15T21:11:41 |
| 111705 | 2026-02-16T18:41:18 |
| 111706 | 2026-02-16T18:41:18 |
| 111707 | 2026-02-16T18:41:18 |
| 111708 | 2026-02-16T18:41:18 |
| 113658 | 2026-02-19T20:49:13 |
| 113659 | 2026-02-19T20:49:13 |
| 113660 | 2026-02-19T20:49:13 |
| 113661 | 2026-02-19T20:49:13 |
| 113662 | 2026-02-19T20:49:14 |
| 113663 | 2026-02-19T20:49:14 |
| 113669 | 2026-02-19T20:49:19 |
| 113671 | 2026-02-19T20:49:21 |
| 113674 | 2026-02-19T20:49:21 |
| 113675 | 2026-02-19T20:49:21 |
| 113676 | 2026-02-19T20:49:21 |
| 114545 | 2026-02-20T20:14:53 |
| 114546 | 2026-02-20T20:14:53 |
| 114547 | 2026-02-20T20:14:53 |
| 114548 | 2026-02-20T20:14:53 |
| 114550 | 2026-02-20T20:14:53 |
| 114554 | 2026-02-20T20:14:53 |
| 114555 | 2026-02-20T20:14:53 |
| 114556 | 2026-02-20T20:14:53 |
| 114557 | 2026-02-20T20:14:54 |
| 114559 | 2026-02-20T20:14:54 |
| 114578 | 2026-02-20T20:15:01 |
| 114579 | 2026-02-20T20:15:01 |
| 114580 | 2026-04-09T16:02:44 |
| 114581 | 2026-04-09T16:02:45 |
| 114582 | 2026-04-09T16:02:45 |
| 114583 | 2026-04-09T16:02:47 |
| 114584 | 2026-04-09T16:02:47 |
| 114585 | 2026-04-09T16:02:50 |
| 114586 | 2026-04-09T16:02:51 |
| 114587 | 2026-04-09T16:02:51 |
| 114588 | 2026-04-09T16:02:53 |
| 114589 | 2026-04-09T16:03:06 |
| 114590 | 2026-04-09T16:03:06 |
| 114591 | 2026-04-09T16:03:06 |
| 114592 | 2026-04-09T16:03:06 |
| 114593 | 2026-04-09T16:03:06 |
| 114594 | 2026-04-09T16:03:06 |
| 114595 | 2026-04-09T16:03:06 |
| 114596 | 2026-04-09T16:03:06 |
| 114597 | 2026-04-09T16:03:06 |
| 114598 | 2026-04-09T16:03:06 |
| 114599 | 2026-04-09T16:03:06 |
| 114600 | 2026-04-09T16:03:06 |
| 114601 | 2026-04-09T16:03:07 |
| 114602 | 2026-04-09T16:03:07 |
| 114603 | 2026-04-09T16:03:07 |
| 114604 | 2026-04-09T16:03:07 |
| 114605 | 2026-04-09T16:03:07 |
| 114606 | 2026-04-09T16:03:07 |
| 114607 | 2026-04-09T16:03:07 |
| 114608 | 2026-04-09T16:03:07 |
| 114609 | 2026-04-09T16:03:07 |
| 114610 | 2026-04-09T16:03:08 |
| 114611 | 2026-04-09T16:03:08 |
| 114612 | 2026-04-09T16:03:08 |
| 114613 | 2026-04-09T16:03:09 |
| 114614 | 2026-04-09T16:03:09 |
| 114615 | 2026-04-09T16:03:09 |
| 114616 | 2026-04-09T16:03:09 |
| 114617 | 2026-04-09T16:03:09 |
| 114618 | 2026-04-09T16:03:09 |
| 114619 | 2026-04-09T16:03:09 |
| 114620 | 2026-04-09T16:03:09 |
| 114621 | 2026-04-09T16:03:09 |
| 114622 | 2026-04-09T16:03:09 |
| 114623 | 2026-04-09T16:03:10 |
| 114624 | 2026-04-09T16:03:10 |
| 114625 | 2026-04-09T16:03:10 |
| 114628 | 2026-04-09T16:03:12 |
| 114629 | 2026-04-09T16:03:12 |
| 114630 | 2026-04-09T16:03:12 |
| 114631 | 2026-04-09T16:03:13 |
| 114632 | 2026-04-09T16:03:13 |
| 114633 | 2026-04-09T16:03:15 |

---

## B. 字段值分布 (enum/status/role/type)

### `admin_operation_logs`
- **action**: `login`=14,286, `create`=11,098, `update`=1,850, `reset_password`=45, `update_oem`=43, `delete`=35
- **status**: `success`=27,357

### `admin_users`
- **role**: `normal_user`=1,164, `captain`=149, `operator`=104, `super_admin`=2
- **is_active**: `1`=1,369, `0`=50
- **user_level**: `enterprise`=1,397, `normal`=22
- **cooperation_type**: `cooperative`=1,419
- **is_oem**: `0`=1,375, `1`=44

### `auto_devices`
- **is_online**: `0`=472

### `auto_task_history`
- **task_type**: `KUAISHOU_COLLECT_BATCH`=17,044, `KUAISHOU_GET_ACCOUNTS`=2,425, `process-video`=114
- **plan_type**: `None`=17,493, `spark`=1,743, `fluorescent`=347
- **status**: `COMPLETED`=15,029, `PENDING`=2,933, `FAILED`=1,349, `RUNNING`=228, `DISPATCHED`=44

### `card_keys`
- **card_type**: `monthly`=7, `quarterly`=1
- **status**: `active`=5, `unused`=3

### `card_usage_logs`
- **action**: `verified`=49, `activated`=5

### `cloud_cookie_accounts`
- **login_status**: `logged_in`=875, `not_logged_in`=1

### `collect_pool_auth_codes`
- **is_active**: `1`=1,423

### `cxt_author`
- **type**: `1`=251, `0`=47

### `cxt_titles`
- **type**: `1`=4,477, `0`=1,619

### `cxt_user`
- **status**: `1`=147, `2`=3

### `drama_execution_logs`

### `firefly_income`
- **monetize_type**: `IAA`=3,364, `IAP`=194
- **settlement_status**: `unsettled`=3,558

### `fluorescent_income`
- **settlement_status**: `unsettled`=29,422, `settled`=1

### `fluorescent_income_archive`
- **settlement_status**: `unsettled`=12,535, `settled`=500

### `iqiyi_videos`
- **status_mark**: `base_surface_mianfei`=3,051, ``=3,042, `1`=986, `2`=212, `base_surface_xianmianzhong`=10, `base_surface_dolby_atmos_vip_tag`=8, `base_surface_gaoqingjingdian_icon`=4

### `kuaishou_account_bindings`
- **status**: `active`=1, `disabled`=1

### `kuaishou_accounts`
- **is_mcm_member**: `0`=19,837, `1`=4,256
- **is_blacklisted**: `0`=23,887, `1`=206
- **account_status**: `normal`=24,093
- **status_note**: `None`=24,093
- **contract_status**: `签约成功，未开通星火`=17,820, `None`=4,696, `全部签约`=1,195, `邀约发送等待接受`=199, `移除成员`=147, `待用户确认星火签约`=36

### `mcm_organizations`
- **is_active**: `1`=17

### `mcn_verification_logs`
- **status**: `SUCCESS`=494,637
- **is_mcn_member**: `1`=490,667, `0`=3,970

### `page_permissions`
- **is_allowed**: `1`=14,022, `0`=7,288

### `role_default_permissions`
- **role**: `operator`=82, `normal_user`=82, `captain`=82
- **perm_type**: `web_page`=75, `account_button`=69, `user_mgmt_button`=54, `client_page`=48
- **is_allowed**: `1`=128, `0`=118

### `spark_drama_info`
- **business_type**: `None`=128,750, `2`=5,270
- **promotion_type**: `None`=128,750, `7`=5,270
- **promotion_type_desc**: `None`=128,750, `效果计费`=5,270
- **view_status**: `None`=128,750, `1`=5,270

### `spark_income_archive`
- **settlement_status**: `unsettled`=2,475, `settled`=840

### `spark_org_members`
- **agreement_types**: `4,14`=2,090, `14`=1,997, `14,4`=686, `4,14,13`=674, `14,4,13`=492, `14,13`=42, `4,13,14`=33, `4,13`=8
- **broker_type**: `-1`=6,029
- **contract_renew_status**: `8`=5,962, `1`=67

### `spark_violation_dramas`
- **status_desc**: `不可申诉`=2,039, `可申诉`=395
- **is_blacklisted**: `0`=2,434

### `spark_violation_photos`
- **status**: `3`=24,359, `1`=7,706, `5`=3,321, `2`=69
- **status_desc**: `不可申诉`=27,749, `可申诉`=7,706
- **appeal_status**: `3`=24,359, `1`=7,706, `5`=3,321, `2`=69
- **appeal_status_desc**: `不可申诉`=27,749, `可申诉`=7,706

### `system_announcements`
- **is_enabled**: `1`=4

### `task_statistics`
- **task_type**: `网页短剧`=80,478, `短剧`=6,543, `api_video_collection`=1,672, `drama_mode2`=877, `video_collection`=323, `drama_favorite`=218, `api_profile_collection`=4
- **status**: `success`=65,428, `pending`=16,729, `failed`=7,958

### `user_button_permissions`
- **is_allowed**: `0`=30,545, `1`=24,951

### `user_page_permissions`
- **is_allowed**: `0`=19,490, `1`=14,495

---

## C. 我们的痕迹搜索 (本租户标识符)

| 标识符 | 值 | 命中表数 | 命中详情 (table.column=count) |
|---|---|---|---|
| captain_phone | `REPLACE_WITH_YOUR_PHONE` | 8 | `admin_operation_logs.username`=152, `admin_operation_logs.target`=136, `admin_operation_logs.detail`=15, `admin_users.username`=1, `collect_pool_auth_codes.auth_code`=1, `kuaishou_accounts.org_note`=12, `kuaishou_accounts.phone_number`=2, `wait_collect_videos.username`=17 |
| captain_owner | `黄华` | 6 | `admin_operation_logs.detail`=3, `cloud_cookie_accounts.owner_code`=13, `ks_account.username`=1, `kuaishou_accounts.org_note`=5, `kuaishou_accounts.real_name`=5, `spark_org_members.comment`=2 |
| captain_uid | `946` | 73 | `account_summary.uid`=4, `admin_operation_logs.username`=87, `admin_operation_logs.target`=134, `admin_operation_logs.detail`=191, `admin_operation_logs.user_agent`=24, `admin_users.username`=1, `admin_users.password_hash`=14, `admin_users.password_salt`=11, `admin_users.alipay_info`=3, `auto_device_accounts.device_id`=5 + 63 more |
| kuaishou_uid_str | `3xmne9bjww75dt9` | 1 | `cloud_cookie_accounts.kuaishou_uid`=1 |
| kuaishou_uid_num | `887329560` | 6 | `admin_operation_logs.target`=1, `admin_operation_logs.detail`=1, `cloud_cookie_accounts.cookies`=1, `kuaishou_accounts.uid`=1, `kuaishou_accounts.uid_real`=1, `mcn_verification_logs.uid`=23 |
| card_token | `TKKN3hjF3i1ThK5CRXDT6AAGKC4DCGT5FC` | 0 | _(none)_ |
| auth_code | `cpkj888` | 10 | `admin_operation_logs.username`=266, `admin_operation_logs.target`=42, `admin_users.username`=1, `admin_users.default_auth_code`=1, `auto_devices.auth_code`=41, `card_keys.used_by_auth_code`=3, `card_usage_logs.auth_code`=46, `collect_pool_auth_codes.auth_code`=1, `cxt_user.auth_code`=65, `wait_collect_videos.username`=908 |
| our_org_id | `10` | 7 | `admin_users.organization_access`=37, `fluorescent_income.org_id`=9, `fluorescent_income_archive.org_task_num`=137, `fluorescent_members.org_task_num`=234, `fluorescent_members.org_id`=630, `kuaishou_accounts.organization_id`=702, `spark_income_archive.org_task_num`=76 |
| spark_org_id | `14` | 7 | `admin_users.organization_access`=8, `fluorescent_income_archive.org_task_num`=81, `fluorescent_members.org_task_num`=97, `fluorescent_members.org_id`=112, `kuaishou_accounts.organization_id`=118, `spark_income.org_id`=52, `spark_income_archive.org_task_num`=53 |
| machine_id | `103876290866` | 0 | _(none)_ |

---

## D. 跨表字段名关联 (隐式 FK candidates)

> 同名字段出现在 2+ 表 → 可能是隐式外键. 排除 id/created_at/status 等通用字段.

- `org_id` → in 10 tables: `fluorescent_income`, `fluorescent_income_archive`, `fluorescent_members`, `spark_income`, `spark_income_archive`, `spark_members` +4
- `uid` → in 9 tables: `account_summary`, `cxt_user`, `drama_execution_logs`, `ks_account`, `kuaishou_accounts`, `kuaishou_urls` +3
- `platform` → in 8 tables: `cxt_author`, `cxt_videos`, `iqiyi_videos`, `kuaishou_accounts`, `spark_drama_info`, `system_announcements` +2
- `member_id` → in 8 tables: `fluorescent_income`, `fluorescent_income_archive`, `fluorescent_members`, `spark_income`, `spark_income_archive`, `spark_members` +2
- `member_name` → in 8 tables: `fluorescent_income`, `fluorescent_income_archive`, `fluorescent_members`, `spark_income`, `spark_income_archive`, `spark_members` +2
- `user_id` → in 7 tables: `admin_operation_logs`, `page_permissions`, `spark_org_members`, `spark_violation_dramas`, `spark_violation_photos`, `user_button_permissions` +1
- `title` → in 7 tables: `cxt_titles`, `cxt_videos`, `iqiyi_videos`, `spark_drama_info`, `spark_highincome_dramas`, `spark_photos` +1
- `broker_name` → in 7 tables: `fluorescent_income_archive`, `fluorescent_members`, `spark_income_archive`, `spark_members`, `spark_org_members`, `spark_violation_dramas` +1
- `username` → in 6 tables: `admin_operation_logs`, `admin_users`, `ks_account`, `spark_violation_dramas`, `spark_violation_photos`, `wait_collect_videos`
- `fans_count` → in 6 tables: `fluorescent_income_archive`, `fluorescent_members`, `spark_income_archive`, `spark_members`, `spark_org_members`, `spark_violation_photos`
- `commission_rate` → in 5 tables: `admin_users`, `firefly_income`, `kuaishou_accounts`, `spark_drama_info`, `spark_income_archive`
- `device_serial` → in 5 tables: `cloud_cookie_accounts`, `drama_collections`, `drama_execution_logs`, `kuaishou_accounts`, `task_statistics`
- `cover_url` → in 5 tables: `cxt_videos`, `iqiyi_videos`, `ks_episodes`, `spark_photos`, `wait_collect_videos`
- `comment_count` → in 5 tables: `cxt_videos`, `ks_episodes`, `spark_photos`, `spark_violation_photos`, `tv_episodes`
- `member_head` → in 5 tables: `fluorescent_income_archive`, `fluorescent_members`, `spark_income_archive`, `spark_members`, `spark_org_members`
- `photo_id` → in 5 tables: `ks_episodes`, `spark_photos`, `spark_violation_photos`, `tv_episodes`, `tv_publish_record`
- `description` → in 4 tables: `account_groups`, `cxt_videos`, `mcm_organizations`, `spark_drama_info`
- `nickname` → in 4 tables: `admin_users`, `auto_device_accounts`, `kuaishou_accounts`, `kuaishou_urls`
- `auth_code` → in 4 tables: `auto_devices`, `card_usage_logs`, `collect_pool_auth_codes`, `cxt_user`
- `name` → in 4 tables: `collect_pool_auth_codes`, `cxt_author`, `kuaishou_urls`, `wait_collect_videos`
- `duration` → in 4 tables: `cxt_videos`, `drama_execution_logs`, `spark_photos`, `task_statistics`
- `drama_name` → in 4 tables: `drama_collections`, `drama_execution_logs`, `task_statistics`, `tv_dramas`
- `episode_number` → in 4 tables: `drama_execution_logs`, `ks_episodes`, `tv_episodes`, `tv_publish_record`
- `settlement_status` → in 4 tables: `firefly_income`, `fluorescent_income`, `fluorescent_income_archive`, `spark_income_archive`
- `in_limit` → in 4 tables: `fluorescent_income_archive`, `fluorescent_members`, `spark_income_archive`, `spark_members`
- `org_task_num` → in 4 tables: `fluorescent_income_archive`, `fluorescent_members`, `spark_income_archive`, `spark_members`
- `total_amount` → in 4 tables: `fluorescent_income_archive`, `fluorescent_members`, `spark_income_archive`, `spark_members`
- `start_time` → in 4 tables: `fluorescent_income_archive`, `spark_drama_info`, `spark_income_archive`, `task_statistics`
- `end_time` → in 4 tables: `fluorescent_income_archive`, `spark_drama_info`, `spark_income_archive`, `task_statistics`
- `like_count` → in 4 tables: `ks_episodes`, `spark_photos`, `spark_violation_photos`, `tv_episodes`
- `view_count` → in 4 tables: `ks_episodes`, `spark_photos`, `spark_violation_photos`, `tv_episodes`
- `is_allowed` → in 4 tables: `page_permissions`, `role_default_permissions`, `user_button_permissions`, `user_page_permissions`
- `device_id` → in 3 tables: `auto_device_accounts`, `auto_devices`, `auto_task_history`
- `task_id` → in 3 tables: `auto_task_history`, `fluorescent_income`, `spark_income`
- `author_id` → in 3 tables: `cxt_author`, `firefly_income`, `firefly_members`
- `video_url` → in 3 tables: `cxt_videos`, `firefly_income`, `ks_episodes`
- `error_message` → in 3 tables: `drama_execution_logs`, `mcn_verification_logs`, `task_statistics`
- `task_name` → in 3 tables: `firefly_income`, `fluorescent_income`, `spark_income`
- `caption` → in 3 tables: `ks_episodes`, `spark_violation_photos`, `tv_episodes`
- `forward_count` → in 3 tables: `ks_episodes`, `spark_violation_photos`, `tv_episodes`
- `owner_id` → in 2 tables: `account_groups`, `kuaishou_accounts`
- `action` → in 2 tables: `admin_operation_logs`, `card_usage_logs`
- `role` → in 2 tables: `admin_users`, `role_default_permissions`
- `device_number` → in 2 tables: `auto_devices`, `auto_task_history`
- `task_type` → in 2 tables: `auto_task_history`, `task_statistics`
- `card_code` → in 2 tables: `card_keys`, `card_usage_logs`
- `created_by` → in 2 tables: `card_keys`, `collect_pool_auth_codes`
- `kuaishou_uid` → in 2 tables: `cloud_cookie_accounts`, `drama_collections`
- `kuaishou_name` → in 2 tables: `cloud_cookie_accounts`, `drama_collections`
- `type` → in 2 tables: `cxt_author`, `cxt_titles`

---

## E. 表活跃度 (按 created_at)

| Table | 24h | 7d | 30d | 起始 | 最新 |
|---|---|---|---|---|---|
| `mcn_verification_logs` | 18,949 | 145,283 | 352,126 | 2025-11-23T12:14:43 | 2026-04-20T06:45:58 |
| `spark_violation_photos` | 9,991 | 9,991 | 28,889 | 2025-12-29T15:24:19 | 2026-04-19T20:28:32 |
| `admin_operation_logs` | 1,826 | 12,687 | 27,357 | 2026-04-01T13:23:11 | 2026-04-20T06:45:18 |
| `user_button_permissions` | 1,474 | 15,004 | 37,253 | 2026-01-04T20:01:56 | 2026-04-19T22:31:14 |
| `fluorescent_members` | 1,304 | 12,232 | 18,477 | 2026-03-10T16:32:59 | 2026-04-19T18:22:35 |
| `user_page_permissions` | 900 | 9,138 | 22,595 | 2026-01-05T12:15:01 | 2026-04-19T22:31:14 |
| `kuaishou_accounts` | 861 | 5,477 | 16,320 | 2025-11-22T15:53:49 | 2026-04-20T01:23:53 |
| `wait_collect_videos` | 681 | 9,212 | 21,534 | 2026-03-24T00:48:17 | 2026-04-20T06:27:17 |
| `page_permissions` | 621 | 7,258 | 21,226 | 2026-03-14T16:55:14 | 2026-04-19T22:31:14 |
| `spark_violation_dramas` | 162 | 162 | 1,501 | 2025-12-29T15:24:19 | 2026-04-19T20:28:28 |
| `account_groups` | 38 | 376 | 1,049 | 2025-12-02T13:57:27 | 2026-04-19T22:31:14 |
| `admin_users` | 36 | 363 | 913 | 2025-12-02T13:57:26 | 2026-04-19T22:31:14 |
| `collect_pool_auth_codes` | 36 | 365 | 915 | 2025-12-21T16:53:47 | 2026-04-19T22:31:14 |
| `task_statistics` | 20 | 313 | 4,204 | 2025-11-22T16:14:54 | 2026-04-20T01:06:07 |
| `spark_members` | 4 | 4 | 1,178 | 2026-02-08T18:57:12 | 2026-04-19T13:18:26 |
| `auto_device_accounts` | 0 | 0 | 3 | 2026-01-30T14:23:32 | 2026-04-07T14:24:35 |
| `auto_devices` | 0 | 0 | 1 | 2026-01-30T14:12:16 | 2026-04-07T14:23:32 |
| `auto_task_history` | 0 | 1 | 657 | 2026-01-30T14:23:18 | 2026-04-14T08:19:16 |
| `card_usage_logs` | 0 | 0 | 2 | 2026-02-12T15:44:58 | 2026-04-11T14:23:23 |
| `cloud_cookie_accounts` | 0 | 65 | 772 | 2025-12-26T15:53:41 | 2026-04-19T00:13:40 |
| `cxt_videos` | 0 | 1 | 1,503 | 2026-04-04T13:02:05 | 2026-04-18T18:58:47 |
| `fluorescent_income` | 0 | 5,504 | 16,930 | 2026-02-28T15:25:40 | 2026-04-13T16:49:18 |
| `mcm_organizations` | 0 | 1 | 12 | 2026-02-28T13:31:50 | 2026-04-18T13:36:12 |
| `role_default_permissions` | 0 | 6 | 246 | 2026-03-30T12:52:43 | 2026-04-18T18:44:36 |
| `spark_drama_info` | 0 | 40,059 | 67,791 | 2026-01-11T16:58:24 | 2026-04-17T16:13:21 |
| `spark_highincome_dramas` | 0 | 240 | 432 | 2026-03-25T20:21:32 | 2026-04-14T17:22:42 |
| `spark_income` | 0 | 0 | 52 | 2026-02-15T21:11:41 | 2026-04-09T16:03:15 |
| `spark_org_members` | 0 | 0 | 1,308 | 2026-01-03T13:03:27 | 2026-04-10T17:00:36 |
| `system_announcements` | 0 | 1 | 3 | 2026-03-09T16:50:28 | 2026-04-13T12:24:33 |

### 💀 死表 / 历史归档 (近 30 天 0 写入)
- `card_keys` (last write: 2026-02-12T22:06:39, ts col=`created_at`)
- `firefly_income` (last write: 2026-02-26T12:35:56, ts col=`created_at`)
- `firefly_members` (last write: 2026-02-26T12:35:56, ts col=`created_at`)
- `tv_episodes` (last write: 2026-03-18T20:01:20, ts col=`created_at`)
- `ks_episodes` (last write: 2026-03-20T20:11:35, ts col=`created_at`)

---

## F. TOP 15 大表字段画像 (NULL率 / distinct)

### `kuaishou_urls` (1,734,828 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 1,745,095 |
| `url` | `varchar(255)` | 0.0% | 514,022 |
| `name` | `varchar(255)` | 0.0% | 14,581 |
| `uid` | `varchar(255)` | 0.0% | 15,636 |
| `nickname` | `varchar(255)` | 0.0% | 14,497 |

### `mcn_verification_logs` (493,742 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 494,637 |
| `uid` | `varchar(50)` | 0.0% | 4,398 |
| `client_ip` | `varchar(50)` | 0.0% | 677 |
| `status` | `varchar(20)` | 0.0% | 1 |
| `is_mcn_member` | `tinyint(1)` | 0.0% | 2 |
| `error_message` | `text` | 100.0% | 0 |
| `created_at` | `datetime` | 0.0% | 368,843 |

### `spark_drama_info` (126,296 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `bigint(20) unsigned` | 0.0% | 134,020 |
| `biz_id` | `bigint(20)` | 0.0% | 134,020 |
| `business_type` | `int(11)` | 96.1% | 1 |
| `ref_business_id` | `bigint(20)` | 96.1% | 5,270 |
| `title` | `varchar(500)` | 0.0% | 48,688 |
| `icon` | `varchar(1000)` | 57.8% | 52,198 |
| `start_time` | `bigint(20)` | 96.1% | 137 |
| `end_time` | `bigint(20)` | 96.1% | 14 |
| `promotion_type` | `int(11)` | 96.1% | 1 |
| `promotion_type_desc` | `varchar(100)` | 96.1% | 1 |
| `redirect_url` | `varchar(1000)` | 5.3% | 126,968 |
| `tags` | `json` | 5.3% | 2,267 |
| `classifications` | `json` | 96.1% | 3 |
| `label` | `varchar(500)` | 96.1% | 1 |
| `description` | `text` | 96.1% | 13 |
| `income_desc` | `varchar(100)` | 57.8% | 5,145 |
| `joined` | `tinyint(4)` | 0.0% | 2 |
| `view_status` | `int(11)` | 96.1% | 1 |
| `commission_rate` | `decimal(5,2)` | 0.0% | 3 |
| `raw_data` | `json` | 57.8% | 56,586 |
| `created_at` | `datetime` | 0.0% | 59,261 |
| `updated_at` | `datetime` | 0.0% | 60,960 |
| `platform` | `tinyint(3) unsigned` | 0.0% | 2 |
| `jump_url` | `varchar(1000)` | 0.0% | 12,344 |
| `serial_id` | `varchar(255)` | 0.0% | 12,344 |

### `drama_collections` (113,257 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 135,392 |
| `kuaishou_uid` | `varchar(50)` | 0.0% | 689 |
| `kuaishou_name` | `varchar(100)` | 0.0% | 729 |
| `device_serial` | `varchar(50)` | 0.0% | 348 |
| `drama_name` | `varchar(200)` | 0.0% | 5,362 |
| `drama_url` | `varchar(500)` | 0.0% | 17,425 |
| `plan_mode` | `varchar(20)` | 0.0% | 2 |
| `actual_drama_name` | `varchar(200)` | 0.0% | 120 |
| `collected_at` | `datetime` | 0.0% | 113,049 |
| `updated_at` | `datetime` | 0.0% | 107,357 |

### `task_statistics` (84,212 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 90,115 |
| `uid` | `varchar(50)` | 0.0% | 1,359 |
| `device_serial` | `varchar(50)` | 0.0% | 330 |
| `drama_link` | `varchar(500)` | 0.0% | 22,182 |
| `drama_name` | `varchar(200)` | 0.0% | 7,127 |
| `task_type` | `varchar(50)` | 0.0% | 7 |
| `task_config` | `json` | 0.0% | 32,182 |
| `status` | `varchar(20)` | 0.0% | 3 |
| `error_message` | `text` | 91.2% | 17 |
| `start_time` | `datetime` | 0.0% | 69,965 |
| `end_time` | `datetime` | 18.6% | 70,784 |
| `duration` | `int(11)` | 18.6% | 4,464 |
| `created_at` | `datetime` | 0.0% | 69,965 |

### `user_button_permissions` (57,042 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 55,496 |
| `user_id` | `int(11)` | 0.0% | 1,430 |
| `button_key` | `varchar(100)` | 0.0% | 43 |
| `is_allowed` | `tinyint(1)` | 0.0% | 2 |
| `created_at` | `datetime` | 0.0% | 1,678 |
| `updated_at` | `datetime` | 0.0% | 1,680 |

### `user_page_permissions` (33,564 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 33,985 |
| `user_id` | `int(11)` | 0.0% | 1,428 |
| `page_key` | `varchar(100)` | 0.0% | 25 |
| `is_allowed` | `tinyint(1)` | 0.0% | 2 |
| `created_at` | `datetime` | 0.0% | 1,518 |
| `updated_at` | `datetime` | 0.0% | 1,522 |

### `spark_violation_photos` (32,497 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 35,455 |
| `photo_id` | `varchar(50)` | 0.0% | 35,455 |
| `user_id` | `bigint(20)` | 0.0% | 5,091 |
| `username` | `varchar(100)` | 0.0% | 4,860 |
| `caption` | `text` | 0.0% | 9,507 |
| `like_count` | `int(11)` | 0.0% | 334 |
| `view_count` | `int(11)` | 0.0% | 2,431 |
| `forward_count` | `int(11)` | 0.0% | 1 |
| `comment_count` | `int(11)` | 0.0% | 71 |
| `media_url` | `text` | 0.0% | 19,475 |
| `thumb_url` | `text` | 0.0% | 35,455 |
| `avatar_url` | `text` | 0.0% | 9,131 |
| `publish_time` | `bigint(20)` | 0.0% | 31,884 |
| `publish_date` | `datetime` | 0.0% | 31,252 |
| `fans_count` | `int(11)` | 0.0% | 2,316 |
| `broker_id` | `bigint(20)` | 0.0% | 4 |
| `broker_name` | `varchar(100)` | 0.0% | 4 |
| `sub_biz_id` | `int(11)` | 0.0% | 2 |
| `sub_biz` | `varchar(50)` | 0.0% | 2 |
| `status` | `int(11)` | 0.0% | 4 |
| `status_desc` | `varchar(50)` | 0.0% | 2 |
| `negative_audit_time` | `bigint(20)` | 0.0% | 35,448 |
| `reason` | `text` | 0.0% | 12 |
| `suggestion` | `text` | 0.0% | 15 |
| `appeal_status` | `int(11)` | 0.0% | 4 |
| `appeal_status_desc` | `varchar(50)` | 0.0% | 2 |
| `appeal_detail` | `text` | 0.0% | 4 |
| `punish_time` | `bigint(20)` | 0.0% | 35,448 |
| `org_id` | `int(11)` | 0.0% | 1 |
| `created_at` | `timestamp` | 0.0% | 540 |
| `updated_at` | `timestamp` | 0.0% | 333 |

### `fluorescent_income` (29,472 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `bigint(20)` | 0.0% | 29,423 |
| `member_id` | `bigint(20)` | 0.0% | 6,089 |
| `member_name` | `varchar(100)` | 0.0% | 5,651 |
| `task_id` | `varchar(50)` | 0.0% | 3,143 |
| `task_name` | `varchar(200)` | 0.0% | 2,639 |
| `task_start_time` | `varchar(20)` | 0.0% | 132 |
| `income` | `decimal(10,2)` | 0.0% | 2,480 |
| `settlement_status` | `varchar(20)` | 0.0% | 2 |
| `org_id` | `int(11) unsigned` | 0.0% | 3 |
| `created_at` | `datetime` | 0.0% | 9,561 |
| `updated_at` | `datetime` | 0.0% | 7,746 |

### `admin_operation_logs` (27,466 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 27,357 |
| `user_id` | `int(11)` | 0.0% | 1,030 |
| `username` | `varchar(50)` | 0.0% | 1,029 |
| `action` | `varchar(50)` | 0.0% | 6 |
| `module` | `varchar(50)` | 0.0% | 14 |
| `target` | `varchar(100)` | 1.7% | 12,609 |
| `detail` | `text` | 0.0% | 12,024 |
| `ip` | `varchar(50)` | 0.0% | 295 |
| `user_agent` | `varchar(500)` | 0.0% | 1,242 |
| `status` | `varchar(20)` | 0.0% | 1 |
| `created_at` | `datetime` | 0.0% | 26,948 |

### `ks_account` (23,251 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 23,306 |
| `username` | `varchar(255)` | 0.0% | 15,828 |
| `uid` | `varchar(255)` | 0.0% | 17,873 |
| `device_num` | `varchar(255)` | 0.0% | 2,024 |
| `uid_real` | `varchar(50)` | 8.2% | 16,640 |

### `kuaishou_accounts` (23,075 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 24,093 |
| `uid` | `varchar(50)` | 0.0% | 24,093 |
| `device_serial` | `varchar(50)` | 79.3% | 311 |
| `nickname` | `varchar(100)` | 27.8% | 13,931 |
| `is_mcm_member` | `tinyint(1)` | 0.0% | 2 |
| `mcm_join_date` | `datetime` | 82.2% | 1,494 |
| `created_at` | `datetime` | 0.0% | 19,852 |
| `updated_at` | `datetime` | 0.0% | 16,093 |
| `group_id` | `int(11)` | 61.3% | 353 |
| `owner_id` | `int(11)` | 0.0% | 1,005 |
| `is_blacklisted` | `tinyint(1)` | 0.0% | 2 |
| `blacklist_reason` | `varchar(255)` | 99.1% | 2 |
| `blacklisted_at` | `datetime` | 99.1% | 3 |
| `blacklisted_by` | `int(11)` | 99.1% | 1 |
| `account_status` | `varchar(50)` | 0.0% | 1 |
| `status_note` | `varchar(255)` | 100.0% | 0 |
| `platform` | `tinyint(4)` | 0.0% | 2 |
| `contract_status` | `varchar(50)` | 19.5% | 5 |
| `org_note` | `text` | 16.6% | 14,517 |
| `phone_number` | `varchar(20)` | 19.3% | 16,734 |
| `invite_time` | `datetime` | 19.3% | 19,376 |
| `invitation_success_count` | `int(11)` | 0.0% | 15 |
| `uid_real` | `varchar(50)` | 0.9% | 23,866 |
| `real_name` | `varchar(50)` | 19.7% | 13,114 |
| `organization_id` | `int(11)` | 0.0% | 16 |
| `commission_rate` | `decimal(5,2)` | 0.0% | 36 |

### `page_permissions` (21,578 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 21,310 |
| `user_id` | `int(11)` | 0.0% | 1,418 |
| `page_key` | `varchar(50)` | 0.0% | 16 |
| `is_allowed` | `tinyint(1)` | 0.0% | 2 |
| `created_at` | `datetime` | 0.0% | 1,484 |
| `updated_at` | `datetime` | 0.0% | 1,502 |

### `wait_collect_videos` (21,170 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `id` | `int(11)` | 0.0% | 21,534 |
| `name` | `varchar(255)` | 0.0% | 2,851 |
| `username` | `varchar(50)` | 0.0% | 167 |
| `created_at` | `datetime` | 0.0% | 4,500 |
| `url` | `text` | 0.0% | 15,433 |
| `platform` | `tinyint(1)` | 0.0% | 2 |
| `cover_url` | `text` | 35.1% | 10,224 |

### `fluorescent_members` (18,812 行)

| Column | Type | NULL% | Distinct |
|---|---|---|---|
| `member_id` | `bigint(20)` | 0.0% | 18,806 |
| `member_name` | `varchar(100)` | 0.0% | 15,978 |
| `member_head` | `varchar(500)` | 0.0% | 17,976 |
| `fans_count` | `int(11)` | 0.0% | 2,846 |
| `in_limit` | `tinyint(1)` | 0.0% | 1 |
| `broker_name` | `varchar(50)` | 0.0% | 6 |
| `org_task_num` | `int(11)` | 0.0% | 36 |
| `total_amount` | `decimal(10,2)` | 0.0% | 3,017 |
| `org_id` | `int(11) unsigned` | 0.0% | 15 |
| `created_at` | `datetime` | 0.0% | 189 |
| `updated_at` | `datetime` | 0.0% | 73 |
