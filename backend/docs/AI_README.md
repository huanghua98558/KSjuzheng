# 🚨 AI 接手 ksjuzheng 必读 — 双表读写规则

> **任何 AI / 开发者改 ksjuzheng 代码前, 先读这一份**.
> 最后更新: 2026-04-28
> 适用范围: ksjuzheng 后台 (FastAPI + Vue3) + huoshijie 数据库

---

## 1. 系统全景

```
┌──────────────────────────────────────────────────────────────────┐
│  数据源 (上游)                                                    │
│  ├─ MCN MySQL 5.7 (im.zhongxiangbao.com:3306, shortju 库)         │
│  │   ├─ 51 张业务表 (admin_users / kuaishou_urls / firefly_*..)   │
│  │   └─ 数据由真 MCN 后台 (mcn.zhongxiangbao.com:88) 持续生产      │
│  │                                                               │
│  └─ ksjuzheng 后台用户 (我们火视界 SaaS 自营)                      │
│      ├─ 我们自己的运营人员 (admin_users 老表)                       │
│      └─ 我们自己创建的账号/分组/cookie                              │
│                                                                  │
│  ↓ ↓ ↓                                                          │
│                                                                  │
│  数据库 (CynosDB MySQL 8.0, 内网 10.5.0.12:3306, 库 huoshijie)    │
│  ├─ 51 张老表 (无前缀)         ← ksjuzheng 业务读+写               │
│  └─ 51 张 mcn_xxx 镜像表        ← sync_daemon 写, ksjuzheng 只读    │
│                                                                  │
│  ↓ ↓ ↓                                                          │
│                                                                  │
│  ksjuzheng 后台 (FastAPI :8800 → Nginx :80/:443)                  │
│  ├─ 业务层: source_mysql_service.py / api/* / models/*            │
│  └─ UI 层: ks-admin-vue (Vue3 + Element Plus)                     │
└──────────────────────────────────────────────────────────────────┘

同步机制:
  另有 mcn-sync.service (在同一台 ubuntu 上跑) 通过 SSH 反向隧道
  把 MCN 源表实时同步到本地 mcn_xxx 镜像
  代码: /home/ubuntu/mcn_sync/  (与 /opt/ksjuzheng 是独立服务)
```

---

## 2. ⚠️ 红线规则 (违反必出问题)

### R1. ksjuzheng 永远写老表, 永远不写 mcn_xxx

```python
# ✅ 正确
db.execute("INSERT INTO admin_users (...) VALUES (...)")
db.execute("UPDATE kuaishou_accounts SET ...")
db.execute("DELETE FROM account_groups WHERE id=...")

# ❌ 错误 (mcn_xxx 是 sync_daemon 的领地, 你写进去会被覆盖)
db.execute("INSERT INTO mcn_admin_users ...")     # 禁止
db.execute("UPDATE mcn_kuaishou_accounts ...")    # 禁止
```

### R2. ksjuzheng SELECT 时通过 source 参数选数据源

老表 (清空后等业务自己写):
```python
# 看自己业务数据
SELECT * FROM admin_users WHERE ...
```

镜像表 (sync 持续写, MCN 真实数据):
```python
# 看 MCN 全平台数据
SELECT * FROM mcn_admin_users WHERE ...
```

合并显示 (默认行为):
```python
SELECT *, '我的' AS _src FROM admin_users
UNION ALL
SELECT *, 'MCN' AS _src FROM mcn_admin_users
```

### R3. INSERT/UPDATE/DELETE 永远不带 source 参数

API 路由设计:
```python
# ✅ 正确
@router.get("/admin/users")
def list_users(source: str = "all", ...): ...    # GET 加 source

@router.post("/admin/users")
def create_user(payload, ...): ...                # POST/PUT/DELETE 不要 source

# ❌ 错误
@router.post("/admin/users?source=mcn")          # 没意义, 写永远写老表
```

### R4. 配置表保留, 不清空

```
✅ 保留 (ksjuzheng 启动需要):
  system_config              (78 行 key/value)
  role_default_permissions   (249 行 角色权限定义)
  collect_pool_auth_codes    (1822 行 授权码池)

❌ 清空 (业务数据, ksjuzheng 自己重新生成):
  其余 48 张老表
```

---

## 3. 表对照速查 (51 + 51)

| 老表 (你写, 暂为空) | mcn_xxx 镜像 (sync 写) | 含义 |
|---|---|---|
| admin_users | mcn_admin_users | 后台用户 (含 18474358043 super_admin) |
| account_groups | mcn_account_groups | 账号分组 |
| kuaishou_accounts | mcn_kuaishou_accounts | 快手账号矩阵 |
| mcm_organizations | mcn_mcm_organizations | MCN 机构 |
| cloud_cookie_accounts | mcn_cloud_cookie_accounts | Cookie 池 |
| firefly_income | mcn_firefly_income | 老萤光收益 (已弃用) |
| fluorescent_income | mcn_fluorescent_income | 萤光收益 (主用, ★) |
| fluorescent_members | mcn_fluorescent_members | 萤光成员 (主用, ★) |
| spark_income | mcn_spark_income | 星火收益 |
| spark_members | mcn_spark_members | 星火成员 |
| spark_drama_info | mcn_spark_drama_info | 星火剧库 (含 banner_task_id) |
| kuaishou_urls | mcn_kuaishou_urls | 短链/CDN URL 池 (200万+) |
| drama_collections | mcn_drama_collections | 剧采集 |
| wait_collect_videos | mcn_wait_collect_videos | 待采集视频 |
| spark_violation_dramas | mcn_spark_violation_dramas | 违规剧 |
| spark_violation_photos | mcn_spark_violation_photos | 违规图 |
| admin_operation_logs | mcn_admin_operation_logs | 操作日志 |
| mcn_verification_logs | mcn_mcn_verification_logs | MCN 验证日志 |
| ... 其余 ~33 张同模式 ... |

完整 102 张表 SQL: `huoshijie 库 SHOW TABLES`

---

## 4. UI 层规则

### 4a. 默认合并显示 + _src tag

每个 list 页面默认 `?source=all`, 列表显示 `_src` 字段, 用 tag 区分:

```
┌─────┬─────────────┬──────────────┬──────────┐
│ ID  │ 用户名       │ 创建时间      │ 来源 _src│
├─────┼─────────────┼──────────────┼──────────┤
│ 1   │ cpkj888     │ 2025-12-02   │ 🔵 MCN   │
│ 1817│ admin       │ 2026-01-14   │ 🔵 MCN   │
│ 9001│ 客服 A       │ 2026-04-28   │ 🟢 我的  │
└─────┴─────────────┴──────────────┴──────────┘
```

### 4b. 短剧管理也合并 + 显示来源 (跟其他页一致)

短剧管理页打开默认就能看到所有剧 (老表 + mcn_), 来源 tag 区分。

### 4c. 顶部下拉切换数据源

```
源筛选: ▼ 全部 (默认) / 仅我的 / 仅 MCN
```

切到"仅 MCN"时, GenericTableView 调 `?source=mcn`, 后端只 SELECT mcn_xxx 表。

---

## 5. 后端实现模板

### A. 通用 dual_source helper

参见 `app/services/dual_source.py` (本次改造新增)

```python
from app.services.dual_source import dual_source_select

@router.get("/firefly/income")
def list_firefly_income(source: str = "all",
                         page: int = 1, page_size: int = 20,
                         db = Depends(get_db)):
    return dual_source_select(
        db=db,
        table="firefly_income",       # 自动加 mcn_ 前缀
        source=source,
        page=page,
        page_size=page_size,
    )
```

helper 内部逻辑:
```python
def dual_source_select(db, table, source, page, page_size):
    if source == "self":
        sql = f"SELECT *, '我的' AS _src FROM `{table}`"
    elif source == "mcn":
        sql = f"SELECT *, 'MCN' AS _src FROM `mcn_{table}`"
    else:  # all
        sql = f"""
            (SELECT *, '我的' AS _src FROM `{table}`)
            UNION ALL
            (SELECT *, 'MCN' AS _src FROM `mcn_{table}`)
            ORDER BY id DESC
        """
    return paginated_execute(db, sql, page, page_size)
```

---

## 6. 前端实现模板

### A. pageConfigs.ts 加 _src 列

```typescript
'/firefly-members': {
  endpoint: '/firefly/members',
  filters: [
    // ↓ 新加: 顶部下拉
    { key: 'source', placeholder: '来源', type: 'select', source: 'sources' },
    ...
  ],
  columns: [
    { key: 'member_name', label: '昵称' },
    ...
    // ↓ 新加: 来源列
    { key: '_src', label: '来源', tag: true, width: 80 },
  ],
}
```

### B. GenericTableView.vue 内置 SOURCE_OPTIONS

```typescript
const SOURCE_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '仅我的', value: 'self' },
  { label: '仅 MCN', value: 'mcn' },
]

function optionsFor(source?: string) {
  if (source === 'sources') return SOURCE_OPTIONS
  return selectOptions[source] || []
}
```

---

## 7. 凭证 + 端口

### 数据库
```
内网 (ksjuzheng / mcn-sync 都用):  10.5.0.12:3306
公网 (本机 dev):                    hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com:27666
账号:                               xhy_app / Hh19875210.
库:                                 huoshijie
```

### 后台超管 (登录 ksjuzheng)
```
用户名:  18474358043
密码:    hh198752
角色:    super_admin (org_id=10 火视界)
```

### 服务地址
```
ksjuzheng FastAPI:  127.0.0.1:8800 (Nginx 反代到 80/443)
mcn-sync 隧道:      127.0.0.1:13306 (反向 SSH 到本机能连 MCN)
```

---

## 8. 服务运维

### 重启 ksjuzheng
```bash
sudo systemctl restart ksjuzheng
sudo journalctl -u ksjuzheng -f
```

### 重启 mcn-sync
```bash
sudo systemctl restart mcn-sync
sudo journalctl -u mcn-sync -f
```

### 健康检查
```bash
python3 /opt/ksjuzheng/scripts/health_check.py
```

---

## 9. 中长期路径 (V2)

火视界 SaaS v2 设计文档: `D:\APP2\docs\huoshijie_server_design_v2.md`

```
当前 (测试期, 本文档涵盖):
  ksjuzheng = MCN 后台克隆 + huoshijie 51+51 双轨
  ↓
3-6 个月后 (中期):
  引入 v2 设计的 hsj_* 25 张表 (5 级层级 + 分账树)
  ksjuzheng 业务逐步迁移到 hsj_*
  老表 + mcn_xxx 双轨保留作过渡期数据源
  ↓
生产期 (1 年):
  完全切到 hsj_*
  脱离中翔宝, 自营 sig3 / MCN 邀请 / 收益
  老 admin_users / kuaishou_accounts 等弃用
```

⚠️ **任何对当前 ksjuzheng 的改动**, 都应该在脑海里问:
  - "v2 重构时这段代码会不会被替换?"
  - 如果是, 不要写得太死, 用配置/常量隔离表名

---

## 10. 验证你没破规则

跑一下:
```bash
python3 /opt/ksjuzheng/scripts/health_check.py
```

检查 12 项 (全 ✓ 才能上线):
- 数据完整性 (4)
- 同步活跃度 (2)
- 双轨规则不破 (4)
- 服务运行 (2)

---

## 11. 备份

源代码 GitHub: https://github.com/huanghua98558/KSjuzheng
- backend/   ← /opt/ksjuzheng 镜像
- frontend/  ← D:\KS184\ks-admin-vue 镜像

数据库备份: /home/ubuntu/backups/huoshijie_*.sql.gz

---

## 联系

服务器: ubuntu@43.161.249.108 (SSH alias: xhy-app)
数据库主: 黄华 (admin888 / hh198752)
