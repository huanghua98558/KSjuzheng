"""Patch demo_compat.py — 短剧管理 4 endpoint UNION 合并 (老表 + mcn_镜像).

目标 (按用户 R4b 规则: 短剧合并显示 + 来源 tag):
  /collect-pool             wait_collect_videos       + mcn_wait_collect_videos
  /high-income-dramas       spark_highincome_dramas   + mcn_spark_highincome_dramas
  /statistics/drama-links   task_statistics           + mcn_task_statistics  (GROUP BY)
  /collections/accounts     drama_collections         + mcn_drama_collections (GROUP BY)

每行附 _src='我的'/'MCN' 字段透传到前端做 tag.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_drama"
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
        print(f"  ✗ {label}: {cnt} 处, 跳过")
        return False
    text = text.replace(old, new)
    print(f"  ✓ {label}")
    n += 1
    return True


# ── P1 /collect-pool: 简单 UNION ALL ──
patch("P1 /collect-pool 合并",
"""        total = _source_count(db, "wait_collect_videos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM wait_collect_videos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_collect_pool_payload(dict(row)) for row in rows], total=total)""",
"""        total = (_source_count(db, "wait_collect_videos", where, params)
                 + _source_count(db, "mcn_wait_collect_videos", where, params))
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"(SELECT *, '我的' AS _src FROM wait_collect_videos WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, 'MCN' AS _src FROM mcn_wait_collect_videos WHERE {sql_where}) "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        def _payload_with_src(r):
            d = _source_collect_pool_payload(dict(r))
            d["_src"] = r.get("_src")
            return d
        return _success([_payload_with_src(r) for r in rows], total=total)""")


# ── P2 /collect-pool/stats: stats 也合并 ──
patch("P2 /collect-pool/stats 合并",
"""        row = db.execute(
            text(
                \"\"\"
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN url IS NOT NULL AND url <> '' THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN url IS NULL OR url = '' THEN 1 ELSE 0 END) AS abnormal
                FROM wait_collect_videos
                \"\"\"
            )
        ).mappings().one()
        return _success({"total": int(row["total"] or 0), "active": int(row["active"] or 0), "abnormal": int(row["abnormal"] or 0)})""",
"""        row = db.execute(
            text(
                \"\"\"
                SELECT SUM(total) AS total, SUM(active) AS active, SUM(abnormal) AS abnormal FROM (
                  SELECT COUNT(*) AS total,
                         SUM(CASE WHEN url IS NOT NULL AND url <> '' THEN 1 ELSE 0 END) AS active,
                         SUM(CASE WHEN url IS NULL OR url = '' THEN 1 ELSE 0 END) AS abnormal
                  FROM wait_collect_videos
                  UNION ALL
                  SELECT COUNT(*),
                         SUM(CASE WHEN url IS NOT NULL AND url <> '' THEN 1 ELSE 0 END),
                         SUM(CASE WHEN url IS NULL OR url = '' THEN 1 ELSE 0 END)
                  FROM mcn_wait_collect_videos
                ) u
                \"\"\"
            )
        ).mappings().one()
        return _success({"total": int(row["total"] or 0), "active": int(row["active"] or 0), "abnormal": int(row["abnormal"] or 0)})""")


# ── P3 /high-income-dramas: 简单 UNION ──
patch("P3 /high-income-dramas 合并",
"""        total = _source_count(db, "spark_highincome_dramas", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_highincome_dramas WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "title": row["title"],
                "name": row["title"],
                "task_name": row["title"],
                "drama_name": row["title"],
                "source_program": "spark",
                "income": None,
                "income_amount": None,
                "notes": None,
                "organization_id": None,
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        return _success({"list": data, "total": total}, total=total)""",
"""        total = (_source_count(db, "spark_highincome_dramas", where, params)
                 + _source_count(db, "mcn_spark_highincome_dramas", where, params))
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"(SELECT *, '我的' AS _src FROM spark_highincome_dramas WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, 'MCN' AS _src FROM mcn_spark_highincome_dramas WHERE {sql_where}) "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "title": row["title"],
                "name": row["title"],
                "task_name": row["title"],
                "drama_name": row["title"],
                "source_program": "spark",
                "income": None,
                "income_amount": None,
                "notes": None,
                "organization_id": None,
                "created_at": _dt(row["created_at"]),
                "_src": row.get("_src"),
            }
            for row in rows
        ]
        return _success({"list": data, "total": total}, total=total)""")


# ── P4 /collections/accounts: GROUP BY 在 UNION 子查询外 ──
patch("P4 /collections/accounts 合并",
"""        rows = db.execute(
            text(
                \"\"\"
                SELECT MIN(id) AS id,
                       kuaishou_uid,
                       kuaishou_name,
                       device_serial,
                       COUNT(*) AS total_count,
                       SUM(CASE WHEN plan_mode = 'spark' THEN 1 ELSE 0 END) AS spark_count,
                       SUM(CASE WHEN plan_mode IN ('firefly', 'fluorescent', 'yingguang') THEN 1 ELSE 0 END) AS firefly_count,
                       MAX(collected_at) AS last_collected_at,
                       MAX(updated_at) AS updated_at
                FROM drama_collections
                GROUP BY kuaishou_uid, kuaishou_name, device_serial
                ORDER BY total_count DESC
                LIMIT 1000
                \"\"\"
            )
        ).mappings().all()""",
"""        rows = db.execute(
            text(
                \"\"\"
                SELECT MIN(id) AS id,
                       kuaishou_uid,
                       kuaishou_name,
                       device_serial,
                       MAX(_src) AS _src,
                       SUM(_count) AS total_count,
                       SUM(_spark) AS spark_count,
                       SUM(_firefly) AS firefly_count,
                       MAX(last_collected_at) AS last_collected_at,
                       MAX(updated_at) AS updated_at
                FROM (
                  SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at,
                         '我的' AS _src,
                         1 AS _count,
                         CASE WHEN plan_mode = 'spark' THEN 1 ELSE 0 END AS _spark,
                         CASE WHEN plan_mode IN ('firefly', 'fluorescent', 'yingguang') THEN 1 ELSE 0 END AS _firefly
                  FROM drama_collections
                  UNION ALL
                  SELECT id, kuaishou_uid, kuaishou_name, device_serial, plan_mode, collected_at, updated_at,
                         'MCN' AS _src,
                         1 AS _count,
                         CASE WHEN plan_mode = 'spark' THEN 1 ELSE 0 END AS _spark,
                         CASE WHEN plan_mode IN ('firefly', 'fluorescent', 'yingguang') THEN 1 ELSE 0 END AS _firefly
                  FROM mcn_drama_collections
                ) u
                GROUP BY kuaishou_uid, kuaishou_name, device_serial
                ORDER BY total_count DESC
                LIMIT 1000
                \"\"\"
            )
        ).mappings().all()""")


# ── 写回 + AST 校验 ──
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ 总改动: {n}/4 项")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
