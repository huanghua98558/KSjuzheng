# 权限点完整清单

> **版本**: v1.0
> **日期**: 2026-04-25
> **来源**: `MODULE_SPEC.md` 26 页面所有按钮 + KS184 真实后台 4 角色分级
> **用途**: `init_db --seed` 把整套权限批量写入 `permissions` + `default_role_permissions` 表.

---

## 一、4 内置角色

| 角色 | code | level | 数据范围 | 默认场景 |
|---|---|---:|---|---|
| 超级管理员 | `super_admin` | 100 | 全平台 | 我们运营 |
| 团长 | `operator` | 50 | 自己的机构 + 下级 captain + normal | 用户 = MCN 团长 |
| 队长 | `captain` | 30 | 自己 + 下属 normal | 团长 → 队长分级 |
| 普通用户 | `normal_user` | 10 | 仅 assigned_user_id = self | 队员 |

**约定**:
- 数据范围用 `tenant_scope.organization_ids` + `tenant_scope.user_ids` 表达
- 高层级对低层级**必须可见可管**; 反之不可
- `level` 数字越大权限越大, 用作快速比较

---

## 二、页面权限点 (page perm)

控制**菜单是否可见 + 路由是否可进**. 26 页 → 26 个 page perm.

| code | 页面中文 | 模块 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|---|
| `dashboard:view` | 数据概览 | dashboard | ✅ | ✅ | ✅ | ✅ |
| `account:view` | 软件账号 | account | ✅ | ✅ | ✅ | ✅ |
| `ks-account:view` | KS账号 | account | ✅ | ✅ | ❌ | ❌ |
| `cloud-cookie:view` | 云Cookie | account | ✅ | ✅ | ❌ | ❌ |
| `org-member:view` | 机构成员 | member | ✅ | ✅ | ✅ | ❌ |
| `member-query:view` | 成员查询 | member | ✅ | ✅ | ✅ | ❌ |
| `violation:view` | 账号违规 | spark | ✅ | ✅ | ✅ | ✅ |
| `user:view` | 用户管理 | auth | ✅ | ✅ | ❌ | ❌ |
| `wallet:view` | 钱包信息 | wallet | ✅ | ✅ | ✅ | ✅ |
| `firefly:view-monthly` | 萤光-本月 | firefly | ✅ | ✅ | ✅ | ✅ |
| `firefly:view-archive` | 萤光-历史 | firefly | ✅ | ✅ | ✅ | ❌ |
| `firefly:view-detail` | 萤光-明细 | firefly | ✅ | ✅ | ✅ | ✅ |
| `spark:view-monthly` | 星火-本月 | spark | ✅ | ✅ | ✅ | ✅ |
| `spark:view-archive` | 星火-历史 | spark | ✅ | ✅ | ✅ | ❌ |
| `spark:view-detail` | 星火-明细 | spark | ✅ | ✅ | ✅ | ✅ |
| `fluorescent:view` | 荧光收益 | fluorescent | ✅ | ✅ | ✅ | ✅ |
| `collect-pool:view` | 短剧收藏池 | drama | ✅ | ✅ | ✅ | ❌ |
| `high-income:view` | 高转化短剧 | drama | ✅ | ✅ | ✅ | ❌ |
| `drama-statistics:view` | 短剧链接统计 | drama | ✅ | ✅ | ✅ | ❌ |
| `drama-collection:view` | 短剧收藏记录 | drama | ✅ | ✅ | ✅ | ❌ |
| `external-stats:view` | 外部URL统计 | external | ✅ | ✅ | ❌ | ❌ |
| `cxt-user:view` | 橙星推用户 | cxt | ✅ | ✅ | ❌ | ❌ |
| `cxt-video:view` | 橙星推视频 | cxt | ✅ | ✅ | ❌ | ❌ |
| `org:view` | 机构信息 | settings | ✅ | ❌ | ❌ | ❌ |
| `announcement:view` | 公告管理 | settings | ✅ | ✅ | ✅ | ✅ |
| `settings:view-basic` | 系统配置-基本 | settings | ✅ | ❌ | ❌ | ❌ |
| `settings:view-role-defaults` | 系统配置-默认权限 | settings | ✅ | ❌ | ❌ | ❌ |
| `settings:view-about` | 系统配置-关于 | settings | ✅ | ✅ | ✅ | ✅ |
| `audit-log:view` | 操作日志 | audit | ✅ | ✅ | ❌ | ❌ |

合计 **29 个 page perm** (含 settings 4 个子页).

---

## 三、按钮权限点 (button perm)

控制**单个操作按钮是否可点 + API 是否可调**. 一共 ~120 个.

### 3.1 模块: account (软件账号 + KS账号 + Cookie)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `account:create` | 添加账号 | ✅ | ✅ | ❌ | ❌ |
| `account:edit` | 编辑账号 | ✅ | ✅ | ✅ | ❌ |
| `account:delete` | 删除 | ✅ | ✅ | ❌ | ❌ |
| `account:batch-import` | 批量导入 | ✅ | ✅ | ❌ | ❌ |
| `account:batch-authorize` | 批量授权 MCN | ✅ | ✅ | ❌ | ❌ |
| `account:batch-revoke` | 取消授权 | ✅ | ✅ | ❌ | ❌ |
| `account:batch-invite` | 直邀 | ✅ | ✅ | ❌ | ❌ |
| `account:batch-open-spark` | 批量开通星火 | ✅ | ✅ | ❌ | ❌ |
| `account:batch-update-income` | 批量更新收益 | ✅ | ✅ | ❌ | ❌ |
| `account:batch-update-status` | 启用/停用 | ✅ | ✅ | ✅ | ❌ |
| `account:batch-delete` | 批量删除 | ✅ | ❌ | ❌ | ❌ |
| `account:assign-user` | 分配用户 | ✅ | ✅ | ❌ | ❌ |
| `account:set-group` | 分组 | ✅ | ✅ | ✅ | ❌ |
| `account:change-org` | 修改机构 | ✅ | ❌ | ❌ | ❌ |
| `account:change-commission` | 修改分成比例 | ✅ | ✅ | ❌ | ❌ |
| `account:control` | 账号管控 (限速/封禁) | ✅ | ✅ | ❌ | ❌ |
| `account:view-task-records` | 查看任务记录 | ✅ | ✅ | ✅ | ✅ |
| `ks-account:delete` | 删除 KS 账号 | ✅ | ✅ | ❌ | ❌ |
| `ks-account:batch-delete` | 批量删除 KS 账号 | ✅ | ❌ | ❌ | ❌ |
| `cloud-cookie:create` | 添加 Cookie | ✅ | ✅ | ❌ | ❌ |
| `cloud-cookie:batch-import` | 批量导入 Cookie | ✅ | ✅ | ❌ | ❌ |
| `cloud-cookie:batch-update-owner` | 批量改归属 | ✅ | ❌ | ❌ | ❌ |
| `cloud-cookie:batch-delete` | 批量删 Cookie | ✅ | ❌ | ❌ | ❌ |
| `cloud-cookie:edit` | 编辑 Cookie | ✅ | ✅ | ❌ | ❌ |
| `cloud-cookie:reveal-plaintext` | **查看明文** | ✅ | ❌ | ❌ | ❌ |
| `cloud-cookie:refresh-status` | 刷新登录状态 | ✅ | ✅ | ✅ | ❌ |

### 3.2 模块: member (机构成员 + 成员查询)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `org-member:sync` | 同步成员 | ✅ | ✅ | ❌ | ❌ |
| `org-member:import` | 导入 Excel | ✅ | ✅ | ❌ | ❌ |
| `org-member:export` | 导出 | ✅ | ✅ | ✅ | ❌ |
| `member-query:execute` | 查询执行 | ✅ | ✅ | ✅ | ❌ |
| `member-query:export` | 查询导出 | ✅ | ✅ | ❌ | ❌ |

### 3.3 模块: spark (星火 + 违规)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `spark:import` | 上传 Excel | ✅ | ✅ | ❌ | ❌ |
| `spark:sync` | 同步数据 | ✅ | ✅ | ❌ | ❌ |
| `spark:batch-settlement` | 批量结清 | ✅ | ✅ | ❌ | ❌ |
| `spark:settlement` | 单条标结 | ✅ | ✅ | ✅ | ❌ |
| `spark:add-to-high-income` | 加入高转化 | ✅ | ✅ | ✅ | ❌ |
| `spark:sync-commission-rate` | 同步分成比例 | ✅ | ✅ | ❌ | ❌ |
| `spark:first-release-id` | 维护首播加 ID | ✅ | ✅ | ❌ | ❌ |
| `violation:edit` | 编辑违规记录 | ✅ | ✅ | ❌ | ❌ |
| `violation:delete` | 删除违规记录 | ✅ | ❌ | ❌ | ❌ |
| `violation:appeal` | 提交申诉 | ✅ | ✅ | ✅ | ❌ |

### 3.4 模块: firefly (萤光)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `firefly:import` | 上传 Excel | ✅ | ✅ | ❌ | ❌ |
| `firefly:sync` | 同步数据 | ✅ | ✅ | ❌ | ❌ |
| `firefly:batch-settlement` | 批量结清 | ✅ | ✅ | ❌ | ❌ |
| `firefly:settlement` | 单条标结 | ✅ | ✅ | ✅ | ❌ |
| `firefly:add-to-high-income` | 加入高转化 | ✅ | ✅ | ✅ | ❌ |

### 3.5 模块: fluorescent (荧光)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `fluorescent:add-to-high-income` | 加入高转化 | ✅ | ✅ | ✅ | ❌ |

### 3.6 模块: drama (短剧)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `collect-pool:create` | 添加 | ✅ | ✅ | ✅ | ❌ |
| `collect-pool:edit` | 编辑 | ✅ | ✅ | ✅ | ❌ |
| `collect-pool:batch-import` | 批量导入 | ✅ | ✅ | ✅ | ❌ |
| `collect-pool:deduplicate` | 去重复制 | ✅ | ✅ | ❌ | ❌ |
| `collect-pool:refresh-status` | 刷新状态 | ✅ | ✅ | ✅ | ❌ |
| `collect-pool:batch-delete` | 批量删 | ✅ | ✅ | ❌ | ❌ |
| `high-income:create` | 添加高转化 | ✅ | ✅ | ✅ | ❌ |
| `high-income:delete` | 删除高转化 | ✅ | ✅ | ❌ | ❌ |
| `drama-statistics:export` | 导出统计 | ✅ | ✅ | ✅ | ❌ |
| `drama-statistics:batch-delete` | 批量删 | ✅ | ❌ | ❌ | ❌ |
| `drama-statistics:clear` | 清空 | ✅ | ❌ | ❌ | ❌ |

### 3.7 模块: auth + user

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `user:create` | 创建用户 | ✅ | ✅ | ❌ | ❌ |
| `user:edit` | 编辑用户 | ✅ | ✅ | ❌ | ❌ |
| `user:delete` | 删除用户 | ✅ | ❌ | ❌ | ❌ |
| `user:reset-password` | 改密 | ✅ | ✅ | ❌ | ❌ |
| `user:set-permissions` | 改页面/按钮权限 | ✅ | ✅ | ❌ | ❌ |
| `user:set-commission` | 改分成比例 | ✅ | ✅ | ❌ | ❌ |
| `user:set-commission-visibility` | 改分成可见性 | ✅ | ✅ | ❌ | ❌ |
| `user:assign-accounts` | 账号授权 | ✅ | ✅ | ❌ | ❌ |
| `user:set-role` | 改角色 | ✅ | ❌ | ❌ | ❌ |
| `user:view-wallet-others` | 查别人钱包 | ✅ | ❌ | ❌ | ❌ |
| `wallet:edit` | 改自己钱包 | ✅ | ✅ | ✅ | ✅ |

### 3.8 模块: settings + 系统

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `org:create` | 创建机构 | ✅ | ❌ | ❌ | ❌ |
| `org:edit` | 编辑机构 | ✅ | ❌ | ❌ | ❌ |
| `org:delete` | 删除机构 | ✅ | ❌ | ❌ | ❌ |
| `org:set-cookie` | 配机构 Cookie | ✅ | ❌ | ❌ | ❌ |
| `org:reveal-cookie` | 看机构 Cookie 明文 | ✅ | ❌ | ❌ | ❌ |
| `announcement:create` | 发公告 | ✅ | ✅ | ❌ | ❌ |
| `announcement:edit` | 改公告 | ✅ | ✅ | ❌ | ❌ |
| `announcement:delete` | 删公告 | ✅ | ❌ | ❌ | ❌ |
| `settings:edit-basic` | 改基本设置 | ✅ | ❌ | ❌ | ❌ |
| `settings:edit-role-defaults` | 改默认权限 | ✅ | ❌ | ❌ | ❌ |
| `audit-log:export` | 导出审计 | ✅ | ✅ | ❌ | ❌ |

### 3.9 模块: cxt (橙星推)

| code | 中文 | super_admin | operator | captain | normal_user |
|---|---|---|---|---|---|
| `cxt-user:import` | 导入 cxt 用户 | ✅ | ✅ | ❌ | ❌ |
| `cxt-video:batch-import` | 导入视频 | ✅ | ✅ | ❌ | ❌ |

合计 **~95 个 button perm**.

---

## 四、敏感字段可见性 (字段级)

不同于按钮权限, 这些是数据字段读权限, 在 service 层统一脱敏:

| user 字段 | 默认 | 控制内容 |
|---|---|---|
| `commission_rate_visible` | 1 | 收益相关页面是否显示分成比例 |
| `commission_amount_visible` | 1 | 是否显示扣除分成金额 |
| `total_income_visible` | 1 | 是否显示总金额 |
| `wallet_visible_to_self` | 1 | 自己是否能看自己钱包 |

```python
def mask_income_record(record: dict, user: User) -> dict:
    if not user.commission_rate_visible:
        record.pop("commission_rate", None)
    if not user.commission_amount_visible:
        record.pop("commission_amount", None)
    if not user.total_income_visible:
        record.pop("total_amount", None)
    return record
```

---

## 五、数据隔离规则 (tenant_scope)

每个角色对应不同的 scope 计算:

```python
def compute_tenant_scope(user: User) -> TenantScope:
    if user.is_superadmin or user.role == "super_admin":
        return TenantScope.UNRESTRICTED        # 全平台

    if user.role == "operator":
        # 团长: 自己的机构 + 自己组织下所有用户
        org_ids = [user.organization_id]                # 1.可扩多机构
        user_ids = subordinate_user_ids(user.id)        # captain+normal 全部
        return TenantScope(organization_ids=org_ids, user_ids=user_ids + [user.id])

    if user.role == "captain":
        org_ids = [user.organization_id]
        user_ids = subordinate_user_ids(user.id)        # 仅 normal
        return TenantScope(organization_ids=org_ids, user_ids=user_ids + [user.id])

    if user.role == "normal_user":
        return TenantScope(
            organization_ids=[user.organization_id],
            user_ids=[user.id],                          # 仅自己
            account_filter="assigned_user_id_eq_self",   # 强约束
        )
```

### 应用方式

每个 GET 列表 API 的 service 层入口:

```python
def list_accounts(db, user, params):
    scope = compute_tenant_scope(user)
    stmt = select(Account)
    if not scope.unrestricted:
        stmt = stmt.where(Account.organization_id.in_(scope.organization_ids))
        if scope.account_filter == "assigned_user_id_eq_self":
            stmt = stmt.where(Account.assigned_user_id == user.id)
        elif user.role in ("captain", "operator"):
            # 看自己 + 下属
            stmt = stmt.where(
                or_(
                    Account.assigned_user_id.in_(scope.user_ids),
                    Account.assigned_user_id.is_(None),  # 未分配的, operator 可看
                )
            )
    return db.execute(stmt.where(...filters...)).scalars().all()
```

---

## 六、Phase 1.5 init_db 增量

`init_db.py::seed_permissions / seed_roles` 接收下面常量:

```python
# scripts/permissions_data.py (新建)

PAGE_PERMISSIONS = [...]   # 29 条 (上面 §2)
BUTTON_PERMISSIONS = [...] # ~95 条 (上面 §3)

DEFAULT_ROLE_PERMS = {
    "super_admin": ["*"],                              # 通配
    "operator": [
        "dashboard:view", "account:view",
        "account:create", "account:edit",
        # ... (按 §2 §3 表中 operator=✅ 的)
    ],
    "captain": [...],
    "normal_user": [...],
}
```

实际产物: `D:\KS184\bendi\scripts\permissions_data.py` Phase 2 第一步直接生成.

---

## 七、审计粒度

`operation_logs` 表必填字段:

| 写场景 | action | module | target_type | target_id | detail |
|---|---|---|---|---|---|
| 登录成功 | `login` | `auth` | `user` | `<user_id>` | `{ip, ua, fingerprint}` |
| 登录失败 | `login_fail` | `auth` | `user` | `<username>` | `{ip, reason}` |
| 创建账号 | `create` | `account` | `account` | `<id>` | `{kuaishou_id, organization_id}` |
| 批量授权 | `batch_authorize` | `account` | `account` | `<ids[]>` | `{count, organization_id}` |
| 看 Cookie 明文 | `reveal` | `cloud-cookie` | `cookie` | `<id>` | `{}` |
| 标结 | `settlement` | `firefly`/`spark` | `archive` | `<id>` | `{settled_amount}` |
| 改分成比例 | `change_commission` | `account` | `account` | `<id>` | `{old, new}` |
| 改用户角色 | `change_role` | `user` | `user` | `<id>` | `{old, new}` |
| 改默认权限 | `set_role_defaults` | `settings` | `role` | `<role>` | `{added, removed}` |

---

## 八、装饰器规范

```python
# app/core/permissions.py (Phase 2 实现)

def require_perm(*perm_codes: str):
    """装饰路由函数, 检查用户是否有任一权限."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(*args, **kw):
            user: User = kw.get("user") or kw.get("current_user")
            if not user:
                raise AuthError(AUTH_401)
            if not user_has_any_perm(user, perm_codes):
                raise AuthError(AUTH_403, message="无此操作权限")
            return await fn(*args, **kw)
        return wrapper
    return deco


# 用法
@router.post("/accounts/batch-authorize")
@require_perm("account:batch-authorize")
async def post_batch_authorize(...): ...
```

权限检查逻辑:
```python
def user_has_any_perm(user, perm_codes) -> bool:
    if user.is_superadmin: return True
    user_perms = load_user_perms(user.id)        # cache 5min
    return any(p in user_perms for p in perm_codes)


def load_user_perms(user_id) -> set[str]:
    """按 user_button_permissions + user_page_permissions + role default 合并."""
    perms = set(query_user_button_perms(user_id))
    perms.update(query_user_page_perms(user_id))
    role = query_user_role(user_id)
    perms.update(query_default_role_perms(role))
    return perms
```
