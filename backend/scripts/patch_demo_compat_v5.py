"""Patch demo_compat.py V5 — 让 source 参数真生效.

V3/V4 现状: helper 永远 UNION, source 参数被忽略.
V5 目标: helper 加 source 参数 (None/all=合并, self=老表, mcn=镜像)
        6 个 router 加 source query 参数 + 透传 helper.

策略:
  1. _source_member_list 签名 + 函数体改 (三档分支, 默认 None 仍合并)
  2. _source_income_list  签名 + 函数体改 (三档分支)
  3. 6 个 router 函数加 source: str | None = None + helper 调用加 source=source

AST 校验 + 自动回滚.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v5"
shutil.copy(PATH, BACKUP)
print(f"  备份: {BACKUP}")

text = open(PATH, encoding="utf-8").read()
n = 0


def patch(label: str, old: str, new: str) -> bool:
    """安全替换 — old 必须出现且仅一次."""
    global text, n
    cnt = text.count(old)
    if cnt == 0:
        print(f"  ✗ {label}: 没找到目标 (0 matches)")
        return False
    if cnt > 1:
        print(f"  ✗ {label}: 多处匹配 ({cnt}), 跳过避免误改")
        return False
    text = text.replace(old, new)
    print(f"  ✓ {label}")
    n += 1
    return True


# ── Patch 1: _source_member_list 签名加 source ────────────────────────
patch(
    "P1: _source_member_list 签名加 source",
    """    sort_field: str | None = None,
    sort_order: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where, params = _source_org_clause(user, "org_id")
    if org_id and user.is_superadmin:
        where.append("org_id = :org_id")
        params["org_id"] = org_id""",
    """    sort_field: str | None = None,
    sort_order: str | None = None,
    source: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where, params = _source_org_clause(user, "org_id")
    if org_id and user.is_superadmin:
        where.append("org_id = :org_id")
        params["org_id"] = org_id""",
)


# ── Patch 2: _source_member_list 函数体三档分支 ──────────────────────
patch(
    "P2: _source_member_list 函数体三档",
    """    total = _source_count(db, table, where, params)
    order_map = {
        "member_id": "member_id",
        "member_name": "member_name",
        "fans_count": "fans_count",
        "org_task_num": "org_task_num",
        "total_amount": "total_amount",
        "created_at": "created_at",
    }
    order_col = order_map.get(sort_field or "total_amount", "total_amount")
    direction = "ASC" if sort_order == "ascending" else "DESC"
    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    # 双轨合并: 老表 (我的) + mcn_xxx 镜像 (MCN)
    total = total + _source_count(db, mcn_table, where, params)
    rows = db.execute(
        text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
             f"UNION ALL "
             f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
             f"ORDER BY {order_col} {direction} LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total""",
    """    order_map = {
        "member_id": "member_id",
        "member_name": "member_name",
        "fans_count": "fans_count",
        "org_task_num": "org_task_num",
        "total_amount": "total_amount",
        "created_at": "created_at",
    }
    order_col = order_map.get(sort_field or "total_amount", "total_amount")
    direction = "ASC" if sort_order == "ascending" else "DESC"
    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    src = (source or "all").lower()
    if src == "self":
        total = _source_count(db, table, where, params)
        rows = db.execute(
            text(f"SELECT *, '我的' AS _src FROM {table} WHERE {sql_where} "
                 f"ORDER BY {order_col} {direction} LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    elif src == "mcn":
        total = _source_count(db, mcn_table, where, params)
        rows = db.execute(
            text(f"SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where} "
                 f"ORDER BY {order_col} {direction} LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    else:  # all = 合并
        total = (_source_count(db, table, where, params)
                 + _source_count(db, mcn_table, where, params))
        rows = db.execute(
            text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
                 f"ORDER BY {order_col} {direction} LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total""",
)


# ── Patch 3: _source_income_list 签名加 source ───────────────────────
patch(
    "P3: _source_income_list 签名加 source",
    """    task_name: str | None = None,
    org_column: str | None = "org_id",
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if org_column and not user.is_superadmin:""",
    """    task_name: str | None = None,
    org_column: str | None = "org_id",
    source: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if org_column and not user.is_superadmin:""",
)


# ── Patch 4: _source_income_list 函数体三档分支 ──────────────────────
patch(
    "P4: _source_income_list 函数体三档",
    """    total = _source_count(db, table, where, params)
    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    # 双轨合并: 老表 (我的) + mcn_xxx 镜像 (MCN)
    total = total + _source_count(db, mcn_table, where, params)
    rows = db.execute(
        text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
             f"UNION ALL "
             f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
             f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_income_payload(dict(row), program=program) for row in rows], total""",
    """    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    src = (source or "all").lower()
    if src == "self":
        total = _source_count(db, table, where, params)
        rows = db.execute(
            text(f"SELECT *, '我的' AS _src FROM {table} WHERE {sql_where} "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    elif src == "mcn":
        total = _source_count(db, mcn_table, where, params)
        rows = db.execute(
            text(f"SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where} "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    else:  # all = 合并
        total = (_source_count(db, table, where, params)
                 + _source_count(db, mcn_table, where, params))
        rows = db.execute(
            text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    return [_source_income_payload(dict(row), program=program) for row in rows], total""",
)


# ── Patch 5: firefly_members router 加 source ────────────────────────
patch(
    "P5: firefly_members router + helper 透传",
    """@router.get("/firefly/members")
async def firefly_members(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    org_id: int | None = None,
    organization_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
    broker_name: str | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        data, total = _source_member_list(
            db,
            user,
            table="fluorescent_members",
            program="firefly",
            page=page,
            per_page=per_page,
            search=search,
            broker_name=broker_name,
            org_id=org_id or organization_id,
            sort_field=sort_field,
            sort_order=sort_order,
        )
        return _success(data, total=total)""",
    """@router.get("/firefly/members")
async def firefly_members(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    org_id: int | None = None,
    organization_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
    broker_name: str | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
    source: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        data, total = _source_member_list(
            db,
            user,
            table="fluorescent_members",
            program="firefly",
            page=page,
            per_page=per_page,
            search=search,
            broker_name=broker_name,
            org_id=org_id or organization_id,
            sort_field=sort_field,
            sort_order=sort_order,
            source=source,
        )
        return _success(data, total=total)""",
)


# ── Patch 6: spark_members router + 调用透传 source ──────────────────
patch(
    "P6: spark_members router + helper 透传",
    """@router.get("/spark/members")
async def spark_members(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, broker_name: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        source_total = _source_count(db, "spark_members", *_source_org_clause(user, "org_id"))
        if source_total:
            data, total = _source_member_list(
                db,
                user,
                table="spark_members",
                program="spark",
                page=page,
                per_page=per_page,
                search=search,
                broker_name=broker_name,
                sort_field="org_task_num",
            )
            return _success(data, total=total)""",
    """@router.get("/spark/members")
async def spark_members(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, broker_name: str | None = None, source: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        # spark: 总是查双轨, 不再短路 (老逻辑只 _source_count 一表会漏)
        data, total = _source_member_list(
            db,
            user,
            table="spark_members",
            program="spark",
            page=page,
            per_page=per_page,
            search=search,
            broker_name=broker_name,
            sort_field="org_task_num",
            source=source,
        )
        if total:
            return _success(data, total=total)
        # 都空时 fallback 到 spark_org_members 老逻辑
        if False:
            return _success(data, total=total)""",
)


# ── Patch 7: firefly_income router + 调用透传 source ──────────────────
patch(
    "P7: firefly_income router + helper 透传",
    """@router.get("/firefly/income")
async def firefly_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="fluorescent_income_archive", program="firefly", page=page, per_page=per_page, task_name=task_name, org_column="org_id"
        )
        return _success(data, total=total)""",
    """@router.get("/firefly/income")
async def firefly_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None, source: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="fluorescent_income_archive", program="firefly", page=page, per_page=per_page, task_name=task_name, org_column="org_id", source=source,
        )
        return _success(data, total=total)""",
)


# ── Patch 8: spark_income router + 调用透传 source ──────────────────
patch(
    "P8: spark_income router + helper 透传",
    """@router.get("/spark/income")
async def spark_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="spark_income", program="spark", page=page, per_page=per_page, task_name=task_name, org_column="org_id"
        )
        return _success(data, total=total)""",
    """@router.get("/spark/income")
async def spark_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None, source: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="spark_income", program="spark", page=page, per_page=per_page, task_name=task_name, org_column="org_id", source=source,
        )
        return _success(data, total=total)""",
)


# ── Patch 9: fluorescent_income router + 调用透传 source ──────────────
patch(
    "P9: fluorescent_income router + helper 透传",
    """@router.get("/fluorescent/income")
async def fluorescent_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="fluorescent_income_archive", program="fluorescent", page=page, per_page=per_page, task_name=task_name, org_column="org_id"
        )
        return _success(data, total=total)""",
    """@router.get("/fluorescent/income")
async def fluorescent_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None, source: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="fluorescent_income_archive", program="fluorescent", page=page, per_page=per_page, task_name=task_name, org_column="org_id", source=source,
        )
        return _success(data, total=total)""",
)


# ── Patch 10: spark_archive router + 调用透传 source ──────────────────
patch(
    "P10: spark_archive router + helper 透传",
    """@router.get("/spark/archive")
async def spark_archive(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        data, total = _source_income_list(
            db, user, table="spark_income_archive", program="spark", page=page, per_page=per_page, org_column="org_id"
        )
        return _success(data, total=total)""",
    """@router.get("/spark/archive")
async def spark_archive(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, source: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        data, total = _source_income_list(
            db, user, table="spark_income_archive", program="spark", page=page, per_page=per_page, org_column="org_id", source=source,
        )
        return _success(data, total=total)""",
)


# ── 写回 + AST 校验 ────────────────────────────────────────────────────
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ 总改动: {n}/10 项")

ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 语法错误! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST 语法 OK")
