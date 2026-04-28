"""KuaishouClient 端到端 smoke test

直接拿真实 cookie 跑核心 API，确认集成层工作。

本地运行（开发期）:
    py -3 D:/APP2/docs/mcn_research/server_integration/smoke_test.py

服务器运行（部署后）:
    cd /opt/ksjuzheng && python -m app.integrations.kuaishou.smoke_test
"""
from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 本地 / 服务器双路径兼容：本地直接跑时按 server_integration 包导入
sys.path.insert(0, str(HERE.parent))

try:
    # 服务器部署后会用这个路径
    from app.integrations.kuaishou import KuaishouClient
    from app.integrations.kuaishou.errors import KuaishouAPIError
except ImportError:
    # 本地开发期用这个
    from server_integration import KuaishouClient
    from server_integration.errors import KuaishouAPIError


MIRROR_DB = r"D:/KS184/mcn/local_mirror/mcn_full_mirror.db"


def get_test_cookie(offset: int = 0):
    """从镜像 DB 取一个 logged_in 个人 cookie。仅本地测试用。"""
    conn = sqlite3.connect(MIRROR_DB)
    c = conn.cursor()
    c.execute(
        "SELECT id, account_name, kuaishou_uid, cookies FROM mcn_cloud_cookie_accounts "
        "WHERE login_status='logged_in' ORDER BY updated_at DESC LIMIT 1 OFFSET ?",
        (offset,),
    )
    r = c.fetchone()
    conn.close()
    if not r:
        return None, None, None, None
    print(f"[cookie] id={r[0]} name={r[1]} uid={r[2]} len={len(r[3])}")
    return r


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def show(label: str, data, max_chars: int = 400):
    body = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    if len(body) > max_chars:
        body = body[:max_chars] + "..."
    print(f"  {label}: {body}")


def main():
    cid, name, uid, cookie = get_test_cookie(0)
    if not cookie:
        print("[fatal] no cookie")
        sys.exit(1)

    client = KuaishouClient.from_cookie_string(cookie)

    section("0. CookieJar 解析 + 类型识别")
    print(f"  kind = {client.jar.kind}")
    print(f"  user_id = {client.jar.user_id}")
    print(f"  has_passToken = {bool(client.jar.pass_token)}")
    print(f"  api_ph = {(client.jar.api_ph or '')[:20]}...")
    print(f"  can_access_cp_business = {client.jar.can_access_cp_business}")

    section("1. verify_cookie (核心检查)")
    v = client.verify_cookie()
    show("verify", v)

    if not v["valid"]:
        print(f"\n[fatal] cookie 不可用: {v.get('error')}")
        sys.exit(2)

    section("2. cp_creator_info_v2 (主页统计)")
    try:
        r = client.cp_creator_info_v2()
        show("data", r.get("data", {}))
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("3. cp_analysis_overview (数据总览, time_type=1=近7天)")
    try:
        r = client.cp_analysis_overview(time_type=1)
        bd = r.get("data", {}).get("basicData") or []
        for m in bd[:5]:
            print(f"  {(m.get('name') or '?'):8} sumCount={m.get('sumCount'):<10} endDayCount={m.get('endDayCount')}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("4. cp_photo_list (已发布视频)")
    try:
        r = client.cp_photo_list()
        items = (r.get("data", {}) or {}).get("list") or []
        print(f"  total={len(items)}")
        for it in items[:3]:
            print(f"    workId={it.get('workId')}  title={(it.get('title') or '')[:40]}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("5. cp_income (收益)")
    try:
        r = client.cp_income()
        show("income", r.get("data", {}))
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("6. cp_home_comment_list (作品评论)")
    try:
        r = client.cp_home_comment_list()
        items = (r.get("data", {}) or {}).get("list") or []
        print(f"  total={len(items)}")
        for c in items[:2]:
            print(f"    {c.get('authorName')}: {(c.get('content') or '')[:30]}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("7. cp_notif_unread (未读消息)")
    try:
        r = client.cp_notif_unread()
        show("data", r.get("data", {}))
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("8. www_vision_profile (公开 GraphQL，查任意 uid)")
    try:
        target_uid = client.jar.fields.get("userId", "3xqpap3wpucy4sc")
        r = client.www_vision_profile(user_id=target_uid)
        up = (r.get("data") or {}).get("visionProfile") or {}
        show("user", up.get("userProfile", {}))
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("9. jigou_account_current (机构平台身份)")
    try:
        r = client.jigou_account_current()
        ui = (r.get("data") or {}).get("userInfo") or {}
        print(f"  userName={ui.get('userName')} userId={ui.get('userId')} fans={ui.get('fansCount')}")
        print(f"  settled={r.get('data', {}).get('settled')}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("Smoke Test 完成 ✅")


if __name__ == "__main__":
    main()
