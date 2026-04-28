"""V6 phase 2 — 改 4 个剩余 endpoint:
  /cloud-cookies     cloud_cookie_accounts
  /cxt-user          cxt_user
  /cxt-videos        cxt_videos
  /spark/photos      spark_photos
+ 修 P2c violation-photos payload _src (上 V6 phase 1 没改成).
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v6b"
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


# ── violation-photos payload _src (more unique context) ──
patch("violation-photos payload _src",
'''                    "publish_date": _dt(row["publish_date"]),
                    "publish_time": row["publish_time"],
                    "organization_id": row["org_id"],
                    "org_id": row["org_id"],
                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                }
                for row in rows''',
'''                    "publish_date": _dt(row["publish_date"]),
                    "publish_time": row["publish_time"],
                    "organization_id": row["org_id"],
                    "org_id": row["org_id"],
                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                    "_src": row.get("_src"),
                }
                for row in rows''')


# ── /cloud-cookies ──
patch("/cloud-cookies + source",
'''@router.get("/cloud-cookies")
async def cloud_cookies(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        total = _source_count(db, "cloud_cookie_accounts", [], {})
        rows = db.execute(
            text("SELECT * FROM cloud_cookie_accounts ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {"limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "uid": row["kuaishou_uid"] or row["account_id"],
                "nickname": row["kuaishou_name"] or row["account_name"],
                "owner_code": row["owner_code"],
                "login_status": row["login_status"],
                "cookies": (row["cookies"][:77] + "...") if row["cookies"] and len(row["cookies"]) > 80 else row["cookies"],
                "device_serial": row["device_serial"],
                "success_count": row["success_count"],
                "fail_count": row["fail_count"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]
        return _success(data, pagination={"total": total, "page": page, "page_size": per_page})''',
'''@router.get("/cloud-cookies")
async def cloud_cookies(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, source: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        rows, total = _dual_select(db, "cloud_cookie_accounts", [], {}, page, per_page, source)
        data = [
            {
                "id": row["id"],
                "uid": row["kuaishou_uid"] or row["account_id"],
                "nickname": row["kuaishou_name"] or row["account_name"],
                "owner_code": row["owner_code"],
                "login_status": row["login_status"],
                "cookies": (row["cookies"][:77] + "...") if row["cookies"] and len(row["cookies"]) > 80 else row["cookies"],
                "device_serial": row["device_serial"],
                "success_count": row["success_count"],
                "fail_count": row["fail_count"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
                "_src": row.get("_src"),
            }
            for row in rows
        ]
        return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})''')


# ── /cxt-user ──
patch("/cxt-user + source",
'''@router.get("/cxt-user")
async def cxt_users(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, status: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    try:
        where = ["1=1"]
        params: dict[str, Any] = {}
        if search:
            where.append("(uid LIKE :search OR note LIKE :search OR auth_code LIKE :search)")
            params["search"] = f"%{search}%"
        if status not in (None, ""):
            where.append("status = :status")
            params["status"] = status
        where_sql = " AND ".join(where)
        total = int(db.execute(text(f"SELECT COUNT(*) FROM cxt_user WHERE {where_sql}"), params).scalar() or 0)
        rows = db.execute(
            text(
                f"""
                SELECT id, uid, note, auth_code, status
                FROM cxt_user
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "uid": row["uid"],
                "sec_user_id": row["uid"],
                "nickname": row["note"],
                "note": row["note"],
                "auth_code": row["auth_code"],
                "status": row["status"],
            }
            for row in rows
        ]
        return _success({"list": data, "total": total})
    except Exception:''',
'''@router.get("/cxt-user")
async def cxt_users(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, status: str | None = None, source: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    try:
        where: list[str] = []
        params: dict[str, Any] = {}
        if search:
            where.append("(uid LIKE :search OR note LIKE :search OR auth_code LIKE :search)")
            params["search"] = f"%{search}%"
        if status not in (None, ""):
            where.append("status = :status")
            params["status"] = status
        rows, total = _dual_select(db, "cxt_user", where, params, page, per_page, source)
        data = [
            {
                "id": row["id"],
                "uid": row["uid"],
                "sec_user_id": row["uid"],
                "nickname": row["note"],
                "note": row["note"],
                "auth_code": row["auth_code"],
                "status": row["status"],
                "_src": row.get("_src"),
            }
            for row in rows
        ]
        return _success({"list": data, "total": total})
    except Exception:''')


# ── /cxt-videos ──
patch("/cxt-videos + source",
'''@router.get("/cxt-videos")
async def cxt_videos(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, title: str | None = None, author: str | None = None, aweme_id: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if title:
            where.append("title LIKE :title")
            params["title"] = f"%{title}%"
        if author:
            where.append("author LIKE :author")
            params["author"] = f"%{author}%"
        if aweme_id:
            where.append("aweme_id LIKE :aweme_id")
            params["aweme_id"] = f"%{aweme_id}%"
        total = _source_count(db, "cxt_videos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM cxt_videos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()''',
'''@router.get("/cxt-videos")
async def cxt_videos(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, title: str | None = None, author: str | None = None, aweme_id: str | None = None, source: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if title:
            where.append("title LIKE :title")
            params["title"] = f"%{title}%"
        if author:
            where.append("author LIKE :author")
            params["author"] = f"%{author}%"
        if aweme_id:
            where.append("aweme_id LIKE :aweme_id")
            params["aweme_id"] = f"%{aweme_id}%"
        rows, total = _dual_select(db, "cxt_videos", where, params, page, per_page, source)''')


# 给 /cxt-videos payload 加 _src
patch("/cxt-videos payload _src",
'''                "platform": row["platform"],
                "status": "active",
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        stats = {
            "totalCount": total,
            "totalPlay": sum(item["play_count"] for item in data),''',
'''                "platform": row["platform"],
                "status": "active",
                "created_at": _dt(row["created_at"]),
                "_src": row.get("_src"),
            }
            for row in rows
        ]
        stats = {
            "totalCount": total,
            "totalPlay": sum(item["play_count"] for item in data),''')


# ── /spark/photos ──
patch("/spark/photos + source",
'''@router.get("/spark/photos")
async def spark_photos(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(photo_id LIKE :search OR title LIKE :search OR member_name LIKE :search)")
            params["search"] = f"%{search}%"
        total = _source_count(db, "spark_photos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        if total:
            rows = db.execute(
                text(f"SELECT * FROM spark_photos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()''',
'''@router.get("/spark/photos")
async def spark_photos(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, source: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(photo_id LIKE :search OR title LIKE :search OR member_name LIKE :search)")
            params["search"] = f"%{search}%"
        rows, total = _dual_select(db, "spark_photos", where, params, page, per_page, source)
        if total:
            pass''')


# 给 /spark/photos payload 加 _src
patch("/spark/photos payload _src",
'''                        "organization_id": row["org_id"],
                        "account_id": None,
                        "created_at": _dt(row["created_at"]),
                        "updated_at": _dt(row["updated_at"]),
                    }
                    for row in rows
                ]
        else:''',
'''                        "organization_id": row["org_id"],
                        "account_id": None,
                        "created_at": _dt(row["created_at"]),
                        "updated_at": _dt(row["updated_at"]),
                        "_src": row.get("_src"),
                    }
                    for row in rows
                ]
        else:''')


# ── 写回 + AST ──
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V6b 改动: {n} 项")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
