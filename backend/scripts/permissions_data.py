"""权限点完整常量 — 由 init_db --seed 写入 permissions 表 +
default_role_permissions 表.

对应文档: docs/PERMISSIONS_CATALOG.md (29 page perm + ~95 button perm).
"""
from __future__ import annotations


# ============================================================
# Page Permissions (29)
# ============================================================
# (code, resource, action, description, default_for_roles[])

PAGE_PERMISSIONS = [
    ("dashboard:view",                "dashboard",      "view", "数据概览",            ["super_admin","operator","captain","normal_user"]),
    ("account:view",                  "account",        "view", "软件账号",            ["super_admin","operator","captain","normal_user"]),
    ("ks-account:view",               "ks-account",     "view", "KS 账号",             ["super_admin","operator"]),
    ("cloud-cookie:view",             "cloud-cookie",   "view", "云端 Cookie",         ["super_admin","operator"]),
    ("org-member:view",               "org-member",     "view", "机构成员",            ["super_admin","operator","captain"]),
    ("member-query:view",             "member-query",   "view", "成员查询",            ["super_admin","operator","captain"]),
    ("violation:view",                "violation",      "view", "账号违规",            ["super_admin","operator","captain","normal_user"]),
    ("user:view",                     "user",           "view", "用户管理",            ["super_admin","operator"]),
    ("wallet:view",                   "wallet",         "view", "钱包信息",            ["super_admin","operator","captain","normal_user"]),
    ("firefly:view-monthly",          "firefly",        "view-monthly", "萤光-本月", ["super_admin","operator","captain","normal_user"]),
    ("firefly:view-archive",          "firefly",        "view-archive", "萤光-历史", ["super_admin","operator","captain"]),
    ("firefly:view-detail",           "firefly",        "view-detail",  "萤光-明细", ["super_admin","operator","captain","normal_user"]),
    ("spark:view-monthly",            "spark",          "view-monthly", "星火-本月", ["super_admin","operator","captain","normal_user"]),
    ("spark:view-archive",            "spark",          "view-archive", "星火-历史", ["super_admin","operator","captain"]),
    ("spark:view-detail",             "spark",          "view-detail",  "星火-明细", ["super_admin","operator","captain","normal_user"]),
    ("fluorescent:view",              "fluorescent",    "view", "荧光收益",            ["super_admin","operator","captain","normal_user"]),
    ("collect-pool:view",             "collect-pool",   "view", "短剧收藏池",          ["super_admin","operator","captain"]),
    ("high-income:view",              "high-income",    "view", "高转化短剧",          ["super_admin","operator","captain"]),
    ("drama-statistics:view",         "drama-statistics","view","短剧链接统计",         ["super_admin","operator","captain"]),
    ("drama-collection:view",         "drama-collection","view","短剧收藏记录",         ["super_admin","operator","captain"]),
    ("external-stats:view",           "external-stats", "view", "外部 URL 统计",        ["super_admin","operator"]),
    ("cxt-user:view",                 "cxt-user",       "view", "橙星推用户",          ["super_admin","operator"]),
    ("cxt-video:view",                "cxt-video",      "view", "橙星推视频",          ["super_admin","operator"]),
    ("org:view",                      "org",            "view", "机构信息",            ["super_admin"]),
    ("announcement:view",             "announcement",   "view", "公告管理",            ["super_admin","operator","captain","normal_user"]),
    ("settings:view-basic",           "settings",       "view-basic", "系统配置-基本", ["super_admin"]),
    ("settings:view-role-defaults",   "settings",       "view-role-defaults","默认权限",["super_admin"]),
    ("settings:view-about",           "settings",       "view-about", "系统配置-关于", ["super_admin","operator","captain","normal_user"]),
    ("audit-log:view",                "audit-log",      "view", "操作日志",            ["super_admin","operator"]),
]


# ============================================================
# Button Permissions (95)
# ============================================================

BUTTON_PERMISSIONS = [
    # ---- account ----
    ("account:create",                "account", "create",      "添加账号",          ["super_admin","operator"]),
    ("account:edit",                  "account", "edit",        "编辑账号",          ["super_admin","operator","captain"]),
    ("account:delete",                "account", "delete",      "删除账号",          ["super_admin","operator"]),
    ("account:batch-import",          "account", "batch-import","批量导入",          ["super_admin","operator"]),
    ("account:batch-authorize",       "account", "batch-authorize","批量授权 MCN",   ["super_admin","operator"]),
    ("account:batch-revoke",          "account", "batch-revoke","取消授权",          ["super_admin","operator"]),
    ("account:batch-invite",          "account", "batch-invite","直邀",              ["super_admin","operator"]),
    ("account:batch-open-spark",      "account", "batch-open-spark","批量开通星火", ["super_admin","operator"]),
    ("account:batch-update-income",   "account", "batch-update-income","批量更新收益",["super_admin","operator"]),
    ("account:batch-update-status",   "account", "batch-update-status","启用/停用",  ["super_admin","operator","captain"]),
    ("account:batch-delete",          "account", "batch-delete","批量删除",          ["super_admin"]),
    ("account:assign-user",           "account", "assign-user","分配用户",           ["super_admin","operator"]),
    ("account:set-group",             "account", "set-group",   "分组",              ["super_admin","operator","captain"]),
    ("account:change-org",            "account", "change-org", "修改机构",           ["super_admin"]),
    ("account:change-commission",     "account", "change-commission","修改分成",     ["super_admin","operator"]),
    ("account:control",               "account", "control",     "账号管控",          ["super_admin","operator"]),
    ("account:view-task-records",     "account", "view-tasks", "查看任务记录",       ["super_admin","operator","captain","normal_user"]),

    # ---- ks-account ----
    ("ks-account:delete",             "ks-account","delete",   "删除 KS 账号",       ["super_admin","operator"]),
    ("ks-account:batch-delete",       "ks-account","batch-delete","批量删 KS",       ["super_admin"]),

    # ---- cloud-cookie ----
    ("cloud-cookie:create",           "cloud-cookie","create", "添加 Cookie",        ["super_admin","operator"]),
    ("cloud-cookie:edit",             "cloud-cookie","edit",   "编辑 Cookie",        ["super_admin","operator"]),
    ("cloud-cookie:batch-import",     "cloud-cookie","batch-import","批量导入",      ["super_admin","operator"]),
    ("cloud-cookie:batch-update-owner","cloud-cookie","batch-update-owner","批量改归属",["super_admin"]),
    ("cloud-cookie:batch-delete",     "cloud-cookie","batch-delete","批量删",        ["super_admin"]),
    ("cloud-cookie:reveal-plaintext", "cloud-cookie","reveal", "查看 Cookie 明文",   ["super_admin"]),
    ("cloud-cookie:refresh-status",   "cloud-cookie","refresh","刷新登录状态",       ["super_admin","operator","captain"]),

    # ---- member ----
    ("org-member:sync",               "org-member","sync",     "同步成员",           ["super_admin","operator"]),
    ("org-member:import",             "org-member","import",   "导入 Excel",         ["super_admin","operator"]),
    ("org-member:export",             "org-member","export",   "导出",               ["super_admin","operator","captain"]),
    ("member-query:execute",          "member-query","execute","成员查询执行",       ["super_admin","operator","captain"]),
    ("member-query:export",           "member-query","export", "成员查询导出",       ["super_admin","operator"]),

    # ---- spark ----
    ("spark:import",                  "spark", "import",       "上传 Excel",         ["super_admin","operator"]),
    ("spark:sync",                    "spark", "sync",         "同步数据",           ["super_admin","operator"]),
    ("spark:batch-settlement",        "spark", "batch-settlement","批量结清",        ["super_admin","operator"]),
    ("spark:settlement",              "spark", "settlement",   "单条标结",           ["super_admin","operator","captain"]),
    ("spark:add-to-high-income",      "spark", "add-to-high-income","加入高转化",   ["super_admin","operator","captain"]),
    ("spark:sync-commission-rate",    "spark", "sync-commission-rate","同步分成比例",["super_admin","operator"]),
    ("spark:first-release-id",        "spark", "first-release-id","维护首播加 ID",  ["super_admin","operator"]),

    # ---- violation ----
    ("violation:edit",                "violation","edit",      "编辑违规",           ["super_admin","operator"]),
    ("violation:delete",              "violation","delete",    "删除违规",           ["super_admin"]),
    ("violation:appeal",              "violation","appeal",    "提交申诉",           ["super_admin","operator","captain"]),

    # ---- firefly ----
    ("firefly:import",                "firefly","import",      "上传 Excel",         ["super_admin","operator"]),
    ("firefly:sync",                  "firefly","sync",        "同步数据",           ["super_admin","operator"]),
    ("firefly:batch-settlement",      "firefly","batch-settlement","批量结清",       ["super_admin","operator"]),
    ("firefly:settlement",            "firefly","settlement",  "单条标结",           ["super_admin","operator","captain"]),
    ("firefly:add-to-high-income",    "firefly","add-to-high-income","加入高转化",  ["super_admin","operator","captain"]),

    # ---- fluorescent ----
    ("fluorescent:add-to-high-income","fluorescent","add-to-high-income","加入高转化",["super_admin","operator","captain"]),

    # ---- drama ----
    ("collect-pool:create",           "collect-pool","create", "添加",               ["super_admin","operator","captain"]),
    ("collect-pool:edit",             "collect-pool","edit",   "编辑",               ["super_admin","operator","captain"]),
    ("collect-pool:batch-import",     "collect-pool","batch-import","批量导入",      ["super_admin","operator","captain"]),
    ("collect-pool:deduplicate",      "collect-pool","deduplicate","去重复制",       ["super_admin","operator"]),
    ("collect-pool:refresh-status",   "collect-pool","refresh","刷新状态",           ["super_admin","operator","captain"]),
    ("collect-pool:batch-delete",     "collect-pool","batch-delete","批量删",        ["super_admin","operator"]),
    ("high-income:create",            "high-income","create",  "添加高转化",         ["super_admin","operator","captain"]),
    ("high-income:delete",            "high-income","delete",  "删除高转化",         ["super_admin","operator"]),
    ("drama-statistics:export",       "drama-statistics","export","导出统计",        ["super_admin","operator","captain"]),
    ("drama-statistics:batch-delete", "drama-statistics","batch-delete","批量删",    ["super_admin"]),
    ("drama-statistics:clear",        "drama-statistics","clear","清空",             ["super_admin"]),

    # ---- user / wallet ----
    ("user:create",                   "user","create",        "创建用户",           ["super_admin","operator"]),
    ("user:edit",                     "user","edit",          "编辑用户",           ["super_admin","operator"]),
    ("user:delete",                   "user","delete",        "删除用户",           ["super_admin"]),
    ("user:reset-password",           "user","reset-password","改密",               ["super_admin","operator"]),
    ("user:set-permissions",          "user","set-permissions","改权限",            ["super_admin","operator"]),
    ("user:set-commission",           "user","set-commission","改分成",             ["super_admin","operator"]),
    ("user:set-commission-visibility","user","set-commission-visibility","改分成可见",["super_admin","operator"]),
    ("user:assign-accounts",          "user","assign-accounts","账号授权",          ["super_admin","operator"]),
    ("user:set-role",                 "user","set-role",      "改角色",             ["super_admin"]),
    ("user:view-wallet-others",       "user","view-wallet-others","查别人钱包",     ["super_admin"]),
    ("wallet:edit",                   "wallet","edit",         "改自己钱包",         ["super_admin","operator","captain","normal_user"]),

    # ---- settings ----
    ("org:create",                    "org","create",          "创建机构",           ["super_admin"]),
    ("org:edit",                      "org","edit",            "编辑机构",           ["super_admin"]),
    ("org:delete",                    "org","delete",          "删除机构",           ["super_admin"]),
    ("org:set-cookie",                "org","set-cookie",      "配机构 Cookie",      ["super_admin"]),
    ("org:reveal-cookie",             "org","reveal-cookie",   "看机构 Cookie 明文", ["super_admin"]),
    ("announcement:create",           "announcement","create", "发公告",             ["super_admin","operator"]),
    ("announcement:edit",             "announcement","edit",   "改公告",             ["super_admin","operator"]),
    ("announcement:delete",           "announcement","delete", "删公告",             ["super_admin"]),
    ("settings:edit-basic",           "settings","edit-basic", "改基本设置",         ["super_admin"]),
    ("settings:edit-role-defaults",   "settings","edit-role-defaults","改默认权限", ["super_admin"]),
    ("audit-log:export",              "audit-log","export",    "导出审计",           ["super_admin","operator"]),

    # ---- cxt ----
    ("cxt-user:import",               "cxt-user","import",     "导入 cxt 用户",      ["super_admin","operator"]),
    ("cxt-video:batch-import",        "cxt-video","batch-import","导入 cxt 视频",   ["super_admin","operator"]),
]


# ============================================================
# Roles (4 内置)
# ============================================================

BUILTIN_ROLES = [
    # (code, name, level, description)
    ("super_admin", "超级管理员", 100, "全平台权限"),
    ("operator",    "团长",       50,  "自己的机构 + 下级"),
    ("captain",     "队长",       30,  "自己 + 下属普通用户"),
    ("normal_user", "普通用户",   10,  "仅 assigned_user_id = self"),
]


def all_perms() -> list[tuple]:
    """合并 page + button perm, 给 init_db 用."""
    out = []
    for code, resource, action, desc, _roles in PAGE_PERMISSIONS:
        out.append((code, resource, action, desc, "page"))
    for code, resource, action, desc, _roles in BUTTON_PERMISSIONS:
        out.append((code, resource, action, desc, "button"))
    return out


def default_role_perms_map() -> dict[str, list[tuple[str, str]]]:
    """{role: [(perm_type, perm_code)]} 用于 default_role_permissions 表."""
    out: dict[str, list[tuple[str, str]]] = {r[0]: [] for r in BUILTIN_ROLES}
    for code, _r, _a, _d, roles in PAGE_PERMISSIONS:
        for role in roles:
            out[role].append(("page", code))
    for code, _r, _a, _d, roles in BUTTON_PERMISSIONS:
        for role in roles:
            out[role].append(("button", code))
    # super_admin 通配 (实际表里仍写全, 便于查)
    return out
