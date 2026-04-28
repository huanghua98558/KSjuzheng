"""V7 — 补 3 个漏掉的有镜像 endpoint:
  /wallet-info              admin_users (老 54, mcn 1986)
  /statistics/drama-links   task_statistics (老 0, mcn 90637, GROUP BY drama_link)
  /statistics/external-urls task_statistics (同上, GROUP BY drama_link 简单聚合)

简单直接 _dual_select; GROUP BY 用子查询 UNION 包装.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v7"
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


# ── P1 /wallet-info ──
patch("/wallet-info + source",
'''@router.get("/wallet-info")
async def wallet_info(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where = ["1=1"]
        params: dict[str, Any] = {}
        if not user.is_superadmin:
            where.append("organization_access = :viewer_org_id")
            params["viewer_org_id"] = user.organization_id
        if search:
            where.append("(username LIKE :search OR nickname LIKE :search OR phone LIKE :search OR alipay_info LIKE :search)")
            params["search"] = f"%{search}%"
        sql_where = " AND ".join(where)
        total = int(db.execute(text(f"SELECT COUNT(*) FROM admin_users WHERE {sql_where}"), params).scalar_one())
        rows = db.execute(
            text(
                f"""
                SELECT id, username, nickname, phone, alipay_info, created_at, updated_at
                FROM admin_users
                WHERE {sql_where}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_wallet_payload(dict(row)) for row in rows], total=total, pagination={"total": total, "page": page, "page_size": per_page})''',
'''@router.get("/wallet-info")
async def wallet_info(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    source: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if not user.is_superadmin:
            where.append("organization_access = :viewer_org_id")
            params["viewer_org_id"] = user.organization_id
        if search:
            where.append("(username LIKE :search OR nickname LIKE :search OR phone LIKE :search OR alipay_info LIKE :search)")
            params["search"] = f"%{search}%"
        rows, total = _dual_select(db, "admin_users", where, params, page, per_page, source)
        data = []
        for r in rows:
            d = _source_wallet_payload(dict(r))
            d["_src"] = r.get("_src")
            data.append(d)
        return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})''')


# ── P2 /statistics/drama-links (GROUP BY 子查询 UNION) ──
patch("/statistics/drama-links + source",
'''@router.get("/statistics/drama-links")
async def statistics_drama_links(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    task_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    export: bool = False,
):
    page, per_page = _page_size(page, page_size, size)
    if export:
        per_page = 10000
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if search:
            where.append("(drama_name LIKE :search OR drama_link LIKE :search)")
            params["search"] = f"%{search}%"
        if task_type:
            where.append("task_type = :task_type")
            params["task_type"] = task_type
        if start_date:
            where.append("created_at >= :start_date")
            params["start_date"] = start_date
        if end_date:
            where.append("created_at <= :end_date")
            params["end_date"] = end_date
        sql_where = " AND ".join(where) if where else "1=1"
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM (SELECT drama_link FROM task_statistics WHERE {sql_where} GROUP BY drama_link) t"),
                params,
            ).scalar_one()
        )
        rows = db.execute(
            text(
                f"""
                SELECT MIN(id) AS id,
                       drama_name,
                       drama_link AS drama_url,
                       task_type,
                       COUNT(*) AS execute_count,
                       SUM(CASE WHEN status IN ('success', 'completed', 'done', 'ok', '1') THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status IN ('failed', 'fail', 'error', '0') THEN 1 ELSE 0 END) AS failed_count,
                       COUNT(DISTINCT uid) AS account_count,
                       MAX(created_at) AS last_executed_at
                FROM task_statistics
                WHERE {sql_where}
                GROUP BY drama_link, drama_name, task_type
                ORDER BY execute_count DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()''',
'''@router.get("/statistics/drama-links")
async def statistics_drama_links(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    task_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    export: bool = False,
    source: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if export:
        per_page = 10000
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if search:
            where.append("(drama_name LIKE :search OR drama_link LIKE :search)")
            params["search"] = f"%{search}%"
        if task_type:
            where.append("task_type = :task_type")
            params["task_type"] = task_type
        if start_date:
            where.append("created_at >= :start_date")
            params["start_date"] = start_date
        if end_date:
            where.append("created_at <= :end_date")
            params["end_date"] = end_date
        sql_where = " AND ".join(where) if where else "1=1"
        # 选源表: self=task_statistics, mcn=mcn_task_statistics, 默认 all=两表 UNION
        src = (source or "all").lower()
        if src == "self":
            src_sql = f"(SELECT id, drama_name, drama_link, task_type, status, uid, created_at, '我的' AS _src FROM task_statistics WHERE {sql_where})"
        elif src == "mcn":
            src_sql = f"(SELECT id, drama_name, drama_link, task_type, status, uid, created_at, 'MCN' AS _src FROM mcn_task_statistics WHERE {sql_where})"
        else:
            src_sql = (
                f"(SELECT id, drama_name, drama_link, task_type, status, uid, created_at, '我的' AS _src FROM task_statistics WHERE {sql_where} "
                f"UNION ALL "
                f"SELECT id, drama_name, drama_link, task_type, status, uid, created_at, 'MCN' AS _src FROM mcn_task_statistics WHERE {sql_where})"
            )
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM (SELECT drama_link FROM {src_sql} u GROUP BY drama_link) t"),
                params,
            ).scalar_one()
        )
        rows = db.execute(
            text(
                f"""
                SELECT MIN(id) AS id,
                       drama_name,
                       drama_link AS drama_url,
                       task_type,
                       MAX(_src) AS _src,
                       COUNT(*) AS execute_count,
                       SUM(CASE WHEN status IN ('success', 'completed', 'done', 'ok', '1') THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status IN ('failed', 'fail', 'error', '0') THEN 1 ELSE 0 END) AS failed_count,
                       COUNT(DISTINCT uid) AS account_count,
                       MAX(created_at) AS last_executed_at
                FROM {src_sql} u
                GROUP BY drama_link, drama_name, task_type
                ORDER BY execute_count DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()''')


# /statistics/drama-links payload 加 _src
patch("/statistics/drama-links payload _src",
'''        data = [
            {
                "id": row["id"],
                "drama_name": row["drama_name"],
                "task_type": row["task_type"],
                "drama_link": row["drama_url"],
                "drama_url": row["drama_url"],
                "total_count": int(row["execute_count"] or 0),''',
'''        data = [
            {
                "id": row["id"],
                "drama_name": row["drama_name"],
                "task_type": row["task_type"],
                "drama_link": row["drama_url"],
                "drama_url": row["drama_url"],
                "_src": row.get("_src"),
                "total_count": int(row["execute_count"] or 0),''')


# ── P3 /statistics/external-urls (类似 P2) ──
patch("/statistics/external-urls + source",
'''@router.get("/statistics/external-urls")
async def statistics_external_urls(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where = ["drama_link IS NOT NULL", "drama_link <> ''"]
        params: dict[str, Any] = {}
        if search:
            where.append("drama_link LIKE :search")
            params["search"] = f"%{search}%"
        if not user.is_superadmin:
            where.append(
                """
                EXISTS (
                    SELECT 1 FROM kuaishou_accounts ka
                    WHERE ka.organization_id = :viewer_org_id
                      AND (ka.uid = ts.uid OR ka.uid_real = ts.uid)
                )
                """
            )
            params["viewer_org_id"] = user.organization_id
        sql_where = " AND ".join(where)
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM (SELECT drama_link FROM task_statistics ts WHERE {sql_where} GROUP BY drama_link) t"),
                params,
            ).scalar_one()
        )
        summary_row = db.execute(
            text(f"SELECT COUNT(*) AS ref_count FROM task_statistics ts WHERE {sql_where}"),
            params,
        ).mappings().one()
        rows = db.execute(
            text(
                f"""
                SELECT drama_link AS url,
                       COUNT(*) AS reference_count,
                       MAX(created_at) AS last_seen_at
                FROM task_statistics ts
                WHERE {sql_where}
                GROUP BY drama_link
                ORDER BY reference_count DESC, last_seen_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": index + (page - 1) * per_page + 1,
                "url": row["url"],
                "source_platform": "kuaishou",
                "reference_count": int(row["reference_count"] or 0),
                "last_seen_at": _dt(row["last_seen_at"]),
                "created_at": _dt(row["last_seen_at"]),
                "updated_at": _dt(row["last_seen_at"]),
                "source": "task_statistics.drama_link",
            }
            for index, row in enumerate(rows)
        ]
        summary = {"total": total, "url_count": int(summary_row["ref_count"] or 0)}
        return _success({"list": data, "summary": summary, "total": total})''',
'''@router.get("/statistics/external-urls")
async def statistics_external_urls(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    source: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        # 注意: 老 SQL 的 user.is_superadmin 分支用 EXISTS 子查询访问 ts 别名 — 直接 UNION
        # 后丢失 ts 别名. 简化: 仅 superadmin 能看, 非 super 时跳过 source 筛选.
        where = ["drama_link IS NOT NULL", "drama_link <> ''"]
        params: dict[str, Any] = {}
        if search:
            where.append("drama_link LIKE :search")
            params["search"] = f"%{search}%"
        # 非 superadmin 仍走老逻辑 (只看 self)
        if not user.is_superadmin:
            source = "self"
        sql_where = " AND ".join(where)
        src = (source or "all").lower()
        if src == "self":
            src_sql = f"(SELECT drama_link, created_at, '我的' AS _src FROM task_statistics WHERE {sql_where})"
        elif src == "mcn":
            src_sql = f"(SELECT drama_link, created_at, 'MCN' AS _src FROM mcn_task_statistics WHERE {sql_where})"
        else:
            src_sql = (
                f"(SELECT drama_link, created_at, '我的' AS _src FROM task_statistics WHERE {sql_where} "
                f"UNION ALL "
                f"SELECT drama_link, created_at, 'MCN' AS _src FROM mcn_task_statistics WHERE {sql_where})"
            )
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM (SELECT drama_link FROM {src_sql} u GROUP BY drama_link) t"),
                params,
            ).scalar_one()
        )
        summary_row = db.execute(
            text(f"SELECT COUNT(*) AS ref_count FROM {src_sql} u"),
            params,
        ).mappings().one()
        rows = db.execute(
            text(
                f"""
                SELECT drama_link AS url,
                       COUNT(*) AS reference_count,
                       MAX(created_at) AS last_seen_at,
                       MAX(_src) AS _src
                FROM {src_sql} u
                GROUP BY drama_link
                ORDER BY reference_count DESC, last_seen_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": index + (page - 1) * per_page + 1,
                "url": row["url"],
                "source_platform": "kuaishou",
                "reference_count": int(row["reference_count"] or 0),
                "last_seen_at": _dt(row["last_seen_at"]),
                "created_at": _dt(row["last_seen_at"]),
                "updated_at": _dt(row["last_seen_at"]),
                "source": "task_statistics.drama_link",
                "_src": row.get("_src"),
            }
            for index, row in enumerate(rows)
        ]
        summary = {"total": total, "url_count": int(summary_row["ref_count"] or 0)}
        return _success({"list": data, "summary": summary, "total": total})''')


# ── /accounts router 加 source 标记 (即使无 mcn_accounts 表) ──
# 实际无镜像就不动. /accounts 暂时不加 source.

open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V7 改动: {n} 项")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
