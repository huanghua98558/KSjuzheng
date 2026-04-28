"""V6 patch — 6 个 endpoint 加 source 三档支持 + 通用 _dual_select helper.

覆盖:
  /org-members          spark_org_members
  /spark/violation-photos spark_violation_photos
  /cloud-cookies        cloud_cookie_accounts
  /cxt-user             cxt_user
  /cxt-videos           cxt_videos
  /spark/photos         spark_photos

效果: 前端 sourceTabs Tab 切换时, 后端按 source=self/mcn 切表, source=all 合并.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v6"
shutil.copy(PATH, BACKUP)
print(f"  备份: {BACKUP}")
text = open(PATH, encoding="utf-8").read()
n = 0


def patch(label, old, new):
    global text, n
    cnt = text.count(old)
    if cnt == 0:
        print(f"  ✗ {label}: 没找到")
        return False
    if cnt > 1:
        print(f"  ✗ {label}: {cnt} 处 跳过")
        return False
    text = text.replace(old, new)
    print(f"  ✓ {label}")
    n += 1
    return True


# ── P0: 加 _dual_select helper (放在 _source_count 之后) ──
HELPER = '''def _source_count(db: Session, table: str, where: list[str], params: dict[str, Any]) -> int:
    sql_where = " AND ".join(where) if where else "1=1"
    return int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"), params).scalar_one())


def _source_member_payload'''

NEW_HELPER = '''def _source_count(db: Session, table: str, where: list[str], params: dict[str, Any]) -> int:
    sql_where = " AND ".join(where) if where else "1=1"
    return int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"), params).scalar_one())


def _dual_select(db: Session, table: str, where: list[str], params: dict[str, Any],
                 page: int, per_page: int, source: str | None,
                 order_by: str = "id DESC") -> tuple[list, int]:
    """双轨数据源通用查询 — source: 'self'/'mcn'/None(默认 all 合并)."""
    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    src = (source or "all").lower()
    base = {**params, "limit": per_page, "offset": (page - 1) * per_page}
    if src == "self":
        total = _source_count(db, table, where, params)
        rows = db.execute(text(
            f"SELECT *, '我的' AS _src FROM {table} WHERE {sql_where} "
            f"ORDER BY {order_by} LIMIT :limit OFFSET :offset"), base).mappings().all()
    elif src == "mcn":
        total = _source_count(db, mcn_table, where, params)
        rows = db.execute(text(
            f"SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where} "
            f"ORDER BY {order_by} LIMIT :limit OFFSET :offset"), base).mappings().all()
    else:
        total = (_source_count(db, table, where, params)
                 + _source_count(db, mcn_table, where, params))
        rows = db.execute(text(
            f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
            f"UNION ALL "
            f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
            f"ORDER BY {order_by} LIMIT :limit OFFSET :offset"), base).mappings().all()
    return list(rows), total


def _source_member_payload'''

patch("P0 加 _dual_select helper", HELPER, NEW_HELPER)


# ── P1 /org-members ──
patch("P1 /org-members + source",
'''@router.get("/org-members")
async def org_members(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    broker_name: str | None = None,
    contract_renew_status: str | None = None,
    agreement_type: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(CAST(member_id AS CHAR) LIKE :search OR member_name LIKE :search OR comment LIKE :search)")
            params["search"] = f"%{search}%"
        if broker_name:
            where.append("broker_name = :broker_name")
            params["broker_name"] = broker_name
        if contract_renew_status:
            where.append("CAST(contract_renew_status AS CHAR) = :contract_renew_status")
            params["contract_renew_status"] = str(contract_renew_status)
        if agreement_type:
            where.append("agreement_types LIKE :agreement_type")
            params["agreement_type"] = f"%{agreement_type}%"
        total = _source_count(db, "spark_org_members", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_org_members WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_org_member_payload(dict(row)) for row in rows], total=total)''',
'''@router.get("/org-members")
async def org_members(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    broker_name: str | None = None,
    contract_renew_status: str | None = None,
    agreement_type: str | None = None,
    source: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(CAST(member_id AS CHAR) LIKE :search OR member_name LIKE :search OR comment LIKE :search)")
            params["search"] = f"%{search}%"
        if broker_name:
            where.append("broker_name = :broker_name")
            params["broker_name"] = broker_name
        if contract_renew_status:
            where.append("CAST(contract_renew_status AS CHAR) = :contract_renew_status")
            params["contract_renew_status"] = str(contract_renew_status)
        if agreement_type:
            where.append("agreement_types LIKE :agreement_type")
            params["agreement_type"] = f"%{agreement_type}%"
        rows, total = _dual_select(db, "spark_org_members", where, params, page, per_page, source)
        def _p(r):
            d = _source_org_member_payload(dict(r))
            d["_src"] = r.get("_src")
            return d
        return _success([_p(r) for r in rows], total=total)''')


# ── P2 /spark/violation-photos ──
patch("P2 /spark/violation-photos + source",
'''        total = _source_count(db, "spark_violation_photos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_violation_photos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()''',
'''        rows, total = _dual_select(db, "spark_violation_photos", where, params, page, per_page, source)''')


# 给 /spark/violation-photos 函数签名加 source 参数
patch("P2b /spark/violation-photos 签名",
'''@router.get("/spark/violation-photos")
async def spark_violation_photos(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    sub_biz: str | None = None,
    broker_name: str | None = None,
):''',
'''@router.get("/spark/violation-photos")
async def spark_violation_photos(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    sub_biz: str | None = None,
    broker_name: str | None = None,
    source: str | None = None,
):''')


# 给 /spark/violation-photos payload 加 _src
patch("P2c /spark/violation-photos payload _src",
'''                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                }
                for row in rows
            ],
            total=total,
        )''',
'''                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                    "_src": row.get("_src"),
                }
                for row in rows
            ],
            total=total,
        )''')


# 写回看下 cloud-cookies / cxt-user / cxt-videos / spark/photos 真实代码,
# 它们结构略不同, 我们先做完前 2 个验证, 后面单独写
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V6 阶段 1 改动: {n} 项")

ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
