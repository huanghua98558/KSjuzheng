"""服务器端 smoke test - 通过环境变量 KS_TEST_COOKIE 接收 cookie

服务器运行：
    KS_TEST_COOKIE='userId=...; bUserId=...; ...' python -m app.integrations.kuaishou.server_smoke
"""
from __future__ import annotations

import json
import os
import sys

from app.integrations.kuaishou import KuaishouClient
from app.integrations.kuaishou.errors import KuaishouAPIError


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main():
    cookie = os.environ.get("KS_TEST_COOKIE", "").strip()
    if not cookie or len(cookie) < 50:
        print("[fatal] missing or invalid KS_TEST_COOKIE env var")
        sys.exit(1)

    client = KuaishouClient.from_cookie_string(cookie)

    section("0. CookieJar 解析")
    print(f"  kind = {client.jar.kind}")
    print(f"  user_id = {client.jar.user_id}")
    print(f"  has_passToken = {bool(client.jar.pass_token)}")
    print(f"  api_ph = {(client.jar.api_ph or '')[:24]}...")
    print(f"  can_access_cp_business = {client.jar.can_access_cp_business}")

    section("1. verify_cookie")
    v = client.verify_cookie()
    print(f"  valid={v['valid']}  user={v.get('user_name')}  fans={v.get('fans_num')}")
    if v.get("error"):
        print(f"  error: {v['error']}")
    if not v["valid"]:
        sys.exit(2)

    section("2. cp_analysis_overview (近 7 天)")
    try:
        r = client.cp_analysis_overview(time_type=1)
        bd = r.get("data", {}).get("basicData") or []
        for m in bd[:5]:
            print(f"  {(m.get('name') or '?'):8} 总={m.get('sumCount'):<10} 当日={m.get('endDayCount')}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("3. cp_photo_list")
    try:
        r = client.cp_photo_list()
        items = (r.get("data", {}) or {}).get("list") or []
        print(f"  total={len(items)}")
        for it in items[:3]:
            print(f"    workId={it.get('workId')}  title={(it.get('title') or '')[:40]}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("4. cp_income")
    try:
        r = client.cp_income()
        print(f"  income={r.get('data', {}).get('income')}  banance={r.get('data', {}).get('banance')}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("5. jigou_account_current")
    try:
        r = client.jigou_account_current()
        ui = (r.get("data") or {}).get("userInfo") or {}
        print(f"  userName={ui.get('userName')}  userId={ui.get('userId')}  fans={ui.get('fansCount')}")
    except KuaishouAPIError as e:
        print(f"  ERR: {e.user_facing_message}")

    section("Server Smoke Test 完成 ✅")


if __name__ == "__main__":
    main()
