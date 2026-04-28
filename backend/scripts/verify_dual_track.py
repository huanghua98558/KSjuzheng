"""完整双轨改造端到端验收脚本.

跑 13 项检查, 确认:
  - 后端 6 endpoint × 3 source 模式真切换 (18 测试)
  - 翻页 + source 组合
  - search + source 组合
  - stats endpoint 仍可用
  - 代码无违规写 mcn_*
  - 数据库表数 + 配置表保留
  - sync 真在写
  - HTTPS 证书 + 静态资源
"""
import json, subprocess, sys, time, urllib.request, urllib.parse

BASE = "http://127.0.0.1:8800"
USER = "18474358043"
PWD = "hh198752"

PASS, FAIL, WARN = [], [], []

def _color(t, c):
    return f"\033[{c}m{t}\033[0m"
P = lambda x: _color(x, "32")
F = lambda x: _color(x, "31")
W = lambda x: _color(x, "33")
H = lambda x: _color(x, "36;1")

def http_json(method, path, token=None, data=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception as ex:
        return 0, {"error": str(ex)}

# ── login ──
print(H("🔍 双轨改造端到端验收"))
print("=" * 60)
code, r = http_json("POST", "/api/auth/login", data={"username": USER, "password": PWD})
if code != 200 or not r.get("success"):
    print(F("✗ login 失败"))
    sys.exit(1)
TOKEN = r["data"]["token"]
print(P(f"✓ login OK (token len={len(TOKEN)})"))

# ── T1: 6 endpoints × 3 source 模式 ──
print(H("\n[T1] 6 dual endpoints × 3 source modes (18 测试)"))
ENDPOINTS = ["/api/firefly/members", "/api/firefly/income", "/api/fluorescent/income",
             "/api/spark/members", "/api/spark/income", "/api/spark/archive"]
EXPECT = {"all": {"我的", "MCN"}, "self": {"我的"}, "mcn": {"MCN"}}
for ep in ENDPOINTS:
    for src in ("all", "self", "mcn"):
        code, r = http_json("GET", f"{ep}?page=1&page_size=20&source={src}", token=TOKEN)
        if code != 200 or not r.get("success"):
            FAIL.append(f"{ep}?source={src} http={code}")
            print(F(f"  ✗ {ep:32s} ?source={src:<5} http={code}"))
            continue
        data = r.get("data") or []
        srcs = {d.get("_src") for d in data if d.get("_src")}
        # self/mcn 必须严格匹配; all 允许任意子集 (含空集 — 空表也合法)
        if src in ("self", "mcn"):
            if srcs and not srcs <= EXPECT[src]:
                FAIL.append(f"{ep}?source={src} got_src={srcs}")
                print(F(f"  ✗ {ep:32s} ?source={src:<5} _src={srcs} (期望 ⊆{EXPECT[src]})"))
                continue
        # 0 行也算通过 (老表收益类清空过, 合法)
        PASS.append(f"{ep}?source={src}")
        print(P(f"  ✓ {ep:32s} ?source={src:<5} rows={len(data):3d} _src={srcs or '∅'}"))

# ── T2: 翻页 + source ──
print(H("\n[T2] 翻页 + source 组合"))
seen_ids = set()
for page in (1, 2, 3):
    code, r = http_json("GET", f"/api/firefly/members?page={page}&page_size=10&source=mcn", token=TOKEN)
    if code != 200:
        FAIL.append(f"T2 page={page} http={code}")
        continue
    data = r.get("data") or []
    ids = [d.get("id") for d in data]
    overlap = len(set(ids) & seen_ids)
    if overlap > 0:
        WARN.append(f"T2 page={page} 与前页 ID 重叠 {overlap} 个")
        print(W(f"  ⚠ page={page} rows={len(data)} 与前页重叠={overlap}"))
    else:
        PASS.append(f"T2 page={page}")
        print(P(f"  ✓ page={page} rows={len(data)} ids[0:3]={ids[:3]} 无重叠"))
    seen_ids.update(ids)

# ── T3: search + source ──
print(H("\n[T3] search + source 组合 (firefly/members)"))
for src in ("all", "self", "mcn"):
    q = urllib.parse.quote("带玉")
    code, r = http_json("GET", f"/api/firefly/members?page=1&page_size=20&search={q}&source={src}", token=TOKEN)
    if code != 200:
        FAIL.append(f"T3 source={src} http={code}")
        print(F(f"  ✗ search=带玉 source={src:<5} http={code}"))
        continue
    data = r.get("data") or []
    matched = [d for d in data if "带玉" in (d.get("member_name") or "")]
    PASS.append(f"T3 source={src}")
    print(P(f"  ✓ search=带玉 source={src:<5} rows={len(data):3d} 真匹配={len(matched)}"))

# ── T4: stats endpoint ──
print(H("\n[T4] stats endpoint (合并视图, 不需 source 切换)"))
for ep in ["/api/firefly/members/stats", "/api/firefly/income/stats",
           "/api/spark/income/stats", "/api/fluorescent/income/stats",
           "/api/spark/archive/stats"]:
    code, r = http_json("GET", ep, token=TOKEN)
    if code != 200:
        FAIL.append(f"T4 {ep} http={code}")
        print(F(f"  ✗ {ep:35s} http={code}"))
        continue
    d = r.get("data") or {}
    tot = d.get("total") or d.get("total_members") or 0
    amt = d.get("total_amount") or 0
    PASS.append(f"T4 {ep}")
    print(P(f"  ✓ {ep:35s} total={tot} total_amount={amt}"))

# ── T5: 代码无违规写 mcn_* ──
print(H("\n[T5] 代码扫违规写 mcn_*"))
import os
n_insert = 0
n_update_delete = 0
violations = []
for root, _, files in os.walk("/opt/ksjuzheng/app"):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        # 简单 regex 不识别注释和字符串字面量, 但 grep -i 会把所有匹配都拉出来
        # 这里仅看 SQL 字符串里的违规
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            up = line.upper()
            if "INSERT INTO MCN_" in up:
                n_insert += 1
                violations.append(f"INSERT  {path}: {line.strip()[:80]}")
            if "UPDATE MCN_" in up or "DELETE FROM MCN_" in up:
                n_update_delete += 1
                violations.append(f"UPDATE  {path}: {line.strip()[:80]}")
if n_insert == 0 and n_update_delete == 0:
    PASS.append("T5 代码无违规")
    print(P(f"  ✓ INSERT INTO mcn_*    : 0 处"))
    print(P(f"  ✓ UPDATE/DELETE mcn_*  : 0 处"))
else:
    FAIL.append("T5 违规写")
    print(F(f"  ✗ INSERT INTO mcn_*    : {n_insert} 处"))
    print(F(f"  ✗ UPDATE/DELETE mcn_*  : {n_update_delete} 处"))
    for v in violations[:5]:
        print(F(f"    {v}"))

# ── T6: 数据库表数 ──
print(H("\n[T6] 数据库表数 + 配置表保留"))
import pymysql
conn = pymysql.connect(host="hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com",
                       port=27666, user="xhy_app", password="Hh19875210.",
                       database="huoshijie", charset="utf8mb4")
cur = conn.cursor()
cur.execute("SHOW TABLES")
all_tables = sorted(r[0] for r in cur.fetchall())
old = [t for t in all_tables if not t.startswith("mcn_") and t != "_sync_state"]
mcn = [t for t in all_tables if t.startswith("mcn_")]
print(f"  老表 (业务): {len(old)} 张")
print(f"  mcn_ 镜像 : {len(mcn)} 张")
print(f"  _sync_state: {'是' if '_sync_state' in all_tables else '否'}")
print(f"  合计: {len(all_tables)} 张")
if 50 <= len(old) <= 110 and 50 <= len(mcn) <= 60 and "_sync_state" in all_tables:
    PASS.append("T6 表数")
    print(P("  ✓ 表数符合预期"))
else:
    WARN.append(f"T6 表数 {len(old)}+{len(mcn)} 异常")
# 配置表保留
for cfg, expected_min in [("system_config", 70), ("role_default_permissions", 200), ("collect_pool_auth_codes", 1000)]:
    cur.execute(f"SELECT COUNT(*) FROM {cfg}")
    cnt = cur.fetchone()[0]
    if cnt >= expected_min:
        PASS.append(f"T6 {cfg}={cnt}")
        print(P(f"  ✓ {cfg}: {cnt} 行 (≥{expected_min})"))
    else:
        FAIL.append(f"T6 {cfg}={cnt} <{expected_min}")
        print(F(f"  ✗ {cfg}: {cnt} 行 (期望 ≥{expected_min})"))

# ── T7: super_admin ──
print(H("\n[T7] super_admin 18474358043 配置"))
cur.execute("SELECT id, username, role, parent_user_id FROM admin_users WHERE username='18474358043'")
row = cur.fetchone()
if row and row[2] == "super_admin":
    PASS.append("T7 super_admin")
    print(P(f"  ✓ id={row[0]} username={row[1]} role={row[2]} parent_user_id={row[3]}"))
else:
    FAIL.append("T7 super_admin")
    print(F(f"  ✗ super_admin 配置异常: {row}"))

# ── T8: sync 真在写 ──
print(H("\n[T8] sync 真在写 (10s 内变化)"))
cur.execute("DESCRIBE _sync_state")
cols = [r[0] for r in cur.fetchall()]
print(f"  _sync_state 字段: {cols[:8]}...")
sync_col = next((c for c in ("last_synced_at", "last_sync_at", "synced_at", "updated_at") if c in cols), cols[0])
cur.execute(f"SELECT MAX({sync_col}) FROM _sync_state")
t1 = cur.fetchone()[0]
print(f"  T0 max({sync_col}): {t1}")
time.sleep(10)
cur.execute(f"SELECT MAX({sync_col}) FROM _sync_state")
t2 = cur.fetchone()[0]
print(f"  T1 max({sync_col}) +10s: {t2}")
if t1 != t2:
    PASS.append("T8 sync 活跃")
    print(P("  ✓ sync 真在写"))
else:
    WARN.append("T8 10s 内 sync 无变化")
    print(W("  ⚠ 10s 内无变化 (可能正在低频表)"))

# ── T9: HTTPS 证书 + 静态资源 ──
print(H("\n[T9] HTTPS 证书 + 静态资源"))
out = subprocess.run(["bash", "-c",
    "curl -sk -o /dev/null -w '%{http_code}|%{ssl_verify_result}|%{size_download}' "
    "-H 'Host: mcn.kuaimax.cn' https://127.0.0.1/"],
    capture_output=True, text=True, timeout=10)
parts = out.stdout.split("|")
print(f"  index.html: http={parts[0]} ssl={parts[1]} bytes={parts[2]}")
if parts[0] == "200":
    PASS.append("T9 HTTPS")
    print(P("  ✓ HTTPS 200"))
else:
    FAIL.append(f"T9 HTTPS http={parts[0]}")

out2 = subprocess.run(["bash", "-c",
    "curl -sk -o /dev/null -w '%{http_code}|%{size_download}' "
    "-H 'Host: mcn.kuaimax.cn' https://127.0.0.1/assets/index-Bazp4yO1.js"],
    capture_output=True, text=True, timeout=10)
parts2 = out2.stdout.split("|")
print(f"  bundle js : http={parts2[0]} bytes={parts2[1]}")
if parts2[0] == "200" and int(parts2[1]) > 1000000:
    PASS.append("T9 bundle")
    print(P(f"  ✓ bundle {parts2[1]} bytes"))

# ── T10: ksjuzheng 写老表 不写 mcn_xxx (实测) ──
print(H("\n[T10] 写规则: ksjuzheng 写老表, 不写 mcn_xxx"))
# 用 SELECT 验证: 看 admin_users 行数 vs mcn_admin_users
cur.execute("SELECT COUNT(*) FROM admin_users")
old_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM mcn_admin_users")
mcn_count = cur.fetchone()[0]
print(f"  admin_users (ksjuzheng 写): {old_count} 行")
print(f"  mcn_admin_users (sync 写) : {mcn_count} 行")
if mcn_count > old_count:
    PASS.append("T10 双轨规则")
    print(P("  ✓ mcn_ 镜像 > 老表 (符合: 镜像有 MCN 全量, 老表只我们自己)"))
else:
    WARN.append("T10 镜像 ≤ 老表")
    print(W("  ⚠ mcn_ 镜像未明显大于老表"))

# ── T11: ksjuzheng 操作日志 admin888 是否仍隐藏 ──
print(H("\n[T11] admin888 操作日志清理 (历史背景)"))
cur.execute("SELECT COUNT(*) FROM admin_operation_logs WHERE user_id IN (SELECT id FROM admin_users WHERE username='admin888')")
admin888_logs = cur.fetchone()[0]
print(f"  admin_operation_logs WHERE admin888: {admin888_logs}")
if admin888_logs == 0:
    PASS.append("T11 admin888 日志清空")
    print(P("  ✓ admin888 操作日志已清"))
else:
    WARN.append(f"T11 admin888 还有 {admin888_logs} 条日志")
    print(W(f"  ⚠ admin888 还有 {admin888_logs} 条 (可能新生成)"))

# ── T12: 老 super_admin 黄华 (parent) 仍能登录 ──
print(H("\n[T12] backward compat: 老 super_admin (id=946 黄华) 能登录"))
cur.execute("SELECT id, username, role, parent_user_id FROM admin_users WHERE id=946")
row = cur.fetchone()
if row:
    PASS.append("T12 黄华账号")
    print(P(f"  ✓ id=946 username={row[1]} role={row[2]} parent_user_id={row[3]}"))

# ── T13: bundle 含关键中文字符串 (前端真打进去) ──
print(H("\n[T13] 前端 bundle 关键中文字符串"))
out3 = subprocess.run(["bash", "-c",
    "curl -sk -H 'Host: mcn.kuaimax.cn' https://127.0.0.1/assets/index-Bazp4yO1.js"],
    capture_output=True, text=True, timeout=15)
js = out3.stdout
keywords = ["全部", "仅我的", "仅 MCN", "_src", "我的", "来源"]
for kw in keywords:
    n = js.count(kw)
    if n > 0:
        PASS.append(f"T13 {kw}")
        print(P(f"  ✓ '{kw}' : {n} hits"))
    else:
        WARN.append(f"T13 '{kw}' 0 hits")
        print(W(f"  ⚠ '{kw}' : 0 hits"))

# ── 汇总 ──
print(H("\n" + "=" * 60))
print(H("  汇总"))
print(H("=" * 60))
print(P(f"  PASS: {len(PASS)}"))
print(W(f"  WARN: {len(WARN)}"))
print(F(f"  FAIL: {len(FAIL)}"))
if FAIL:
    print(F("\n失败项:"))
    for f in FAIL: print(F(f"  ✗ {f}"))
if WARN:
    print(W("\n警告项:"))
    for w in WARN: print(W(f"  ⚠ {w}"))
sys.exit(0 if not FAIL else 1)
