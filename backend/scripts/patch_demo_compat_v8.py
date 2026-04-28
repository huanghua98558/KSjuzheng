"""V8 — 加权限隔离: 非 super_admin 强制 source='self' (只看老表/我们读写库).

按用户铁令:
  超管 + AI → 看全部 (老表 + mcn_xxx 镜像)
  其他用户 → 只能看老表 (huoshijie 我们读写的)

实施:
  1. _dual_select helper 加 viewer 参数, 内部强制 source='self'
  2. 13 处 _dual_select 调用都加 viewer=user
  3. 短剧 3 个 router (合并 UNION 模式) 加判断: 非 super 退化为只查老表
  4. /accounts source=mcn 跨表分支 + /auth/users source=mcn 分支 加同样保护
"""
import os, sys, shutil, re

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v8"
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


# ── P0: _dual_select 加 viewer 参数 + 强制权限 ──
patch("P0 _dual_select 加 viewer 强制",
'''def _dual_select(db: Session, table: str, where: list[str], params: dict[str, Any],
                 page: int, per_page: int, source: str | None,
                 order_by: str = "id DESC") -> tuple[list, int]:
    """双轨数据源通用查询 — source: \'self\'/\'mcn\'/None(默认 all 合并)."""
    sql_where = " AND ".join(where) if where else "1=1"''',
'''def _dual_select(db: Session, table: str, where: list[str], params: dict[str, Any],
                 page: int, per_page: int, source: str | None,
                 order_by: str = "id DESC", viewer: Any = None) -> tuple[list, int]:
    """双轨数据源通用查询 — source: \'self\'/\'mcn\'/None(默认 all 合并).

    权限隔离 (按用户铁令):
      非 super_admin viewer 强制 source=\'self\' (只看老表/读写库).
    """
    if viewer is not None and not getattr(viewer, "is_superadmin", False):
        source = "self"
    sql_where = " AND ".join(where) if where else "1=1"''')


# ── 13 处 _dual_select 调用加 viewer=user ──
# 模式: rows, total = _dual_select(db, "TABLE", where, params, page, per_page, source)
# 改成: rows, total = _dual_select(db, "TABLE", where, params, page, per_page, source, viewer=user)

# 用 regex 批量加 viewer=user
pattern = re.compile(
    r'(_dual_select\(\s*db,\s*"[a-z_]+",\s*\w+,\s*\w+,\s*\w+,\s*\w+,\s*\w+)(\))',
    re.MULTILINE,
)
matches = list(pattern.finditer(text))
print(f"\n  找到 {len(matches)} 处 _dual_select 调用 (无 viewer)")
# 反向替换避免 offset 漂移
for m in reversed(matches):
    text = text[:m.start(2)] + ", viewer=user)" + text[m.end(2):]
    n += 1
    print(f"    ✓ 加 viewer=user @ pos {m.start()}")


# ── /accounts source=mcn 直接跨表分支 加保护 ──
patch("/accounts mcn 分支加 super_admin 校验",
'''        if (source or "").lower() == "mcn":
            # source=mcn: 直接查 mcn_accounts VIEW (字段已对齐 ksjuzheng accounts)
            # VIEW 由 mcn_kuaishou_accounts 映射, sync_daemon 自动维护数据''',
'''        if (source or "").lower() == "mcn":
            # 权限保护: 非 super_admin 不允许查 mcn 镜像
            if not user.is_superadmin:
                return _success({"accounts": [], "total": 0, "mcn_count": 0, "normal_count": 0,
                                  "user_role": user.role, "_perm": "mcn_blocked"}, total=0)
            # source=mcn: 直接查 mcn_accounts VIEW (字段已对齐 ksjuzheng accounts)
            # VIEW 由 mcn_kuaishou_accounts 映射, sync_daemon 自动维护数据''')


# ── /ks-accounts source=mcn 加保护 ──
patch("/ks-accounts mcn 分支加保护",
'''        if (source or "").lower() == "mcn":
            # source=mcn: 直接查 mcn_kuaishou_accounts 镜像''',
'''        if (source or "").lower() == "mcn":
            if not user.is_superadmin:
                return _success([], total=0, pagination={"total": 0, "page": page, "page_size": per_page})
            # source=mcn: 直接查 mcn_kuaishou_accounts 镜像''')


# ── /auth/users source=mcn 加保护 ──
patch("/auth/users mcn 分支加保护",
'''        if (source or "").lower() == "mcn":
            # source=mcn: 直接查 mcn_admin_users 镜像''',
'''        if (source or "").lower() == "mcn":
            if not user.is_superadmin:
                return _success([], total=0, pagination={"total": 0, "page": page, "page_size": per_page})
            # source=mcn: 直接查 mcn_admin_users 镜像''')


# ── 短剧 3 endpoint 加权限保护 ──
# /collect-pool: 非 super 退化为只查老表
patch("/collect-pool 加权限保护",
'''        total = (_source_count(db, "wait_collect_videos", where, params)
                 + _source_count(db, "mcn_wait_collect_videos", where, params))
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"(SELECT *, \'我的\' AS _src FROM wait_collect_videos WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, \'MCN\' AS _src FROM mcn_wait_collect_videos WHERE {sql_where}) "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        def _payload_with_src(r):
            d = _source_collect_pool_payload(dict(r))
            d["_src"] = r.get("_src")
            return d
        return _success([_payload_with_src(r) for r in rows], total=total)''',
'''        sql_where = " AND ".join(where) if where else "1=1"
        if user.is_superadmin:
            # 超管: 合并显示
            total = (_source_count(db, "wait_collect_videos", where, params)
                     + _source_count(db, "mcn_wait_collect_videos", where, params))
            rows = db.execute(
                text(f"(SELECT *, \'我的\' AS _src FROM wait_collect_videos WHERE {sql_where}) "
                     f"UNION ALL "
                     f"(SELECT *, \'MCN\' AS _src FROM mcn_wait_collect_videos WHERE {sql_where}) "
                     f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
        else:
            # 非超管: 只看老表
            total = _source_count(db, "wait_collect_videos", where, params)
            rows = db.execute(
                text(f"SELECT *, \'我的\' AS _src FROM wait_collect_videos WHERE {sql_where} "
                     f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
        def _payload_with_src(r):
            d = _source_collect_pool_payload(dict(r))
            d["_src"] = r.get("_src")
            return d
        return _success([_payload_with_src(r) for r in rows], total=total)''')


# /high-income-dramas 加权限
patch("/high-income-dramas 加权限保护",
'''        total = (_source_count(db, "spark_highincome_dramas", where, params)
                 + _source_count(db, "mcn_spark_highincome_dramas", where, params))
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"(SELECT *, \'我的\' AS _src FROM spark_highincome_dramas WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, \'MCN\' AS _src FROM mcn_spark_highincome_dramas WHERE {sql_where}) "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()''',
'''        sql_where = " AND ".join(where) if where else "1=1"
        if user.is_superadmin:
            total = (_source_count(db, "spark_highincome_dramas", where, params)
                     + _source_count(db, "mcn_spark_highincome_dramas", where, params))
            rows = db.execute(
                text(f"(SELECT *, \'我的\' AS _src FROM spark_highincome_dramas WHERE {sql_where}) "
                     f"UNION ALL "
                     f"(SELECT *, \'MCN\' AS _src FROM mcn_spark_highincome_dramas WHERE {sql_where}) "
                     f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
        else:
            total = _source_count(db, "spark_highincome_dramas", where, params)
            rows = db.execute(
                text(f"SELECT *, \'我的\' AS _src FROM spark_highincome_dramas WHERE {sql_where} "
                     f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()''')


# /collections/accounts (drama-collections) 加权限保护
patch("/collections/accounts 加权限保护",
'''        rows = db.execute(
            text(
                """
                SELECT MIN(id) AS id,
                       kuaishou_uid,
                       kuaishou_name,
                       device_serial,
                       MAX(_src) AS _src,
                       SUM(_count) AS total_count,
                       SUM(_spark) AS spark_count,
                       SUM(_firefly) AS firefly_count,
                       MAX(collected_at) AS last_collected_at,
                       MAX(updated_at) AS updated_at
                FROM (
                  SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at,
                         \'我的\' AS _src,
                         1 AS _count,
                         CASE WHEN plan_mode = \'spark\' THEN 1 ELSE 0 END AS _spark,
                         CASE WHEN plan_mode IN (\'firefly\', \'fluorescent\', \'yingguang\') THEN 1 ELSE 0 END AS _firefly
                  FROM drama_collections
                  UNION ALL
                  SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at,
                         \'MCN\' AS _src,
                         1 AS _count,
                         CASE WHEN plan_mode = \'spark\' THEN 1 ELSE 0 END AS _spark,
                         CASE WHEN plan_mode IN (\'firefly\', \'fluorescent\', \'yingguang\') THEN 1 ELSE 0 END AS _firefly
                  FROM mcn_drama_collections
                ) u
                GROUP BY kuaishou_uid, kuaishou_name, device_serial
                ORDER BY total_count DESC
                LIMIT 1000
                """
            )
        ).mappings().all()''',
'''        if user.is_superadmin:
            sub_sql = (
                "SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at, "
                "\'我的\' AS _src, 1 AS _count, "
                "CASE WHEN plan_mode = \'spark\' THEN 1 ELSE 0 END AS _spark, "
                "CASE WHEN plan_mode IN (\'firefly\', \'fluorescent\', \'yingguang\') THEN 1 ELSE 0 END AS _firefly "
                "FROM drama_collections "
                "UNION ALL "
                "SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at, "
                "\'MCN\' AS _src, 1, "
                "CASE WHEN plan_mode = \'spark\' THEN 1 ELSE 0 END, "
                "CASE WHEN plan_mode IN (\'firefly\', \'fluorescent\', \'yingguang\') THEN 1 ELSE 0 END "
                "FROM mcn_drama_collections"
            )
        else:
            sub_sql = (
                "SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at, "
                "\'我的\' AS _src, 1 AS _count, "
                "CASE WHEN plan_mode = \'spark\' THEN 1 ELSE 0 END AS _spark, "
                "CASE WHEN plan_mode IN (\'firefly\', \'fluorescent\', \'yingguang\') THEN 1 ELSE 0 END AS _firefly "
                "FROM drama_collections"
            )
        rows = db.execute(
            text(
                f"SELECT MIN(id) AS id, kuaishou_uid, kuaishou_name, device_serial, "
                f"MAX(_src) AS _src, SUM(_count) AS total_count, SUM(_spark) AS spark_count, "
                f"SUM(_firefly) AS firefly_count, MAX(collected_at) AS last_collected_at, "
                f"MAX(updated_at) AS updated_at "
                f"FROM ({sub_sql}) u "
                f"GROUP BY kuaishou_uid, kuaishou_name, device_serial "
                f"ORDER BY total_count DESC LIMIT 1000"
            )
        ).mappings().all()''')


open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V8 改动: {n} 项")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
