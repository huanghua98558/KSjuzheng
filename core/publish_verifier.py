# -*- coding: utf-8 -*-
"""发布后 feed 回查 — 真正的 silent-fail 检测.

用途:
  publisher 返回 "success + photoId" 只代表**HTTP 响应成功**, 不代表**视频真的在 feed 里**.
  快手有 silent reject: 返回 200 但后台拒绝 (重复内容 / 限流 / 风控).

验证方法:
  发布 5-10 分钟后, 查账号 profile feed, 看 photo_id 是否出现.
  - 出现 → 真成功
  - 未出现 (发布 30min 内) → silent reject

接入:
  - task_queue.status=success 后 6 分钟, Watchdog 调 verify_published_photo
  - 结果写 publish_results.verified_at / verified_status
  - silent_reject 案例触发 SelfHealing

这不需要破解 :50002 响应加密, 直接利用公开 feed API.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _check_short_video_url(photo_id: str, timeout: int = 10) -> dict:
    """⚠️ SPA 渲染警告 (2026-04-21 修):
    www.kuaishou.com/short-video/{photo_id} 是 JS 渲染的 SPA, 服务器返回的静态 HTML
    **永远不含具体 photo_id**, 无论视频是否真实存在. 本函数仅能区分:
    - 3xx redirect → 作品删除
    - 404 → 作品不存在
    - 200 → ★ 无法判断是否 silent_reject ★ (必须用 MCN 收益反推)

    (2026-04-21 诊断: photo=193491728405 + 其他 7 条 success 全返 html_no_photo,
     但 MCN delta_tasks 证明账号活着 → html_no_photo 是 **SPA 假阳** 不是 silent_reject)
    """
    import requests
    url = f"https://www.kuaishou.com/short-video/{photo_id}"
    try:
        r = requests.get(
            url, timeout=timeout, allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"},
        )
        # 200: SPA 渲染, HTML 几乎永远不含 photo_id → 不可靠判定
        if r.status_code == 200:
            if photo_id in r.text:
                # 罕见情况 (可能 SPA prefetch 了 JSON inline), 仍视为强信号
                return {"exists": True, "status": "found",
                        "http_code": 200}
            # 200 但无 photo_id → SPA 特性, 不判 silent_reject
            return {"exists": None, "status": "unreliable_spa",
                    "http_code": 200,
                    "note": "SPA 渲染, 需用 MCN delta_tasks 反推"}
        # 3xx 重定向 → 作品删除/不存在 (强信号)
        if 300 <= r.status_code < 400:
            return {"exists": False, "status": "redirect",
                    "http_code": r.status_code,
                    "location": r.headers.get("Location", "")[:100]}
        # 404
        if r.status_code == 404:
            return {"exists": False, "status": "not_found",
                    "http_code": 404}
        return {"exists": False, "status": "http_error",
                "http_code": r.status_code}
    except requests.exceptions.Timeout:
        return {"exists": None, "status": "timeout"}
    except Exception as e:
        return {"exists": None, "status": "error", "error": str(e)[:200]}


def verify_via_mcn_delta(
    account_id: int,
    published_at: datetime,
    window_days: int = 3,
) -> dict:
    """用 MCN snapshot 的 org_task_num 增量反推 — 2026-04-21 主路径.

    逻辑:
      1. 查 device_accounts.numeric_uid
      2. 查 mcn_member_snapshots WHERE member_id=numeric_uid
         AND snapshot_date BETWEEN published_date AND published_date + window_days
      3. SUM(delta_tasks) > 0 → MCN 有新 task 进账 → likely_verified
      4. published_at 已过 24h 但 SUM(delta_tasks)==0 → likely_silent_reject
      5. published_at < 24h → pending (MCN 快照按日更新, 需等下一日)

    优势: MCN 数据是 ground truth, 客户端无法伪造
    局限: 账号级别, 不 photo 级别 — 同一天发 2 条 delta_tasks=1 无法区分是哪条
    """
    try:
        with _connect() as c:
            row = c.execute(
                "SELECT numeric_uid FROM device_accounts WHERE id=?",
                (account_id,),
            ).fetchone()
            if not row or not row["numeric_uid"]:
                return {
                    "verdict": "unknown",
                    "reason": "no numeric_uid for account",
                }
            uid = int(row["numeric_uid"])
    except Exception as e:
        return {"verdict": "error", "error": str(e)[:200]}

    # 发布时间判断是否有足够观察窗口
    elapsed_h = (datetime.now() - published_at).total_seconds() / 3600
    if elapsed_h < 24:
        return {
            "verdict": "pending",
            "reason": f"等 MCN 下次 snapshot, 发布至今 {elapsed_h:.1f}h < 24h",
            "elapsed_hours": round(elapsed_h, 1),
            "numeric_uid": uid,
        }

    pub_date = published_at.strftime("%Y-%m-%d")
    end_date_dt = published_at + timedelta(days=window_days)
    end_date = end_date_dt.strftime("%Y-%m-%d")

    with _connect() as c:
        snap_rows = c.execute(
            """SELECT snapshot_date, org_task_num, total_amount,
                      delta_amount, delta_tasks
               FROM mcn_member_snapshots
               WHERE member_id=?
                 AND snapshot_date BETWEEN ? AND ?
               ORDER BY snapshot_date""",
            (uid, pub_date, end_date),
        ).fetchall()

    snaps = [dict(r) for r in snap_rows]
    sum_delta_tasks = sum(s.get("delta_tasks", 0) or 0 for s in snaps)
    sum_delta_amount = sum(s.get("delta_amount", 0) or 0 for s in snaps)

    if sum_delta_tasks > 0:
        verdict = "likely_verified"
    elif sum_delta_amount > 0:
        verdict = "likely_verified_income_only"
    elif len(snaps) == 0:
        verdict = "no_snapshot"
    else:
        # 有 snapshot 但无增量 + 已过 24h → 高概率 silent_reject
        verdict = "likely_silent_reject"

    return {
        "verdict": verdict,
        "numeric_uid": uid,
        "window_days": window_days,
        "published_date": pub_date,
        "snapshots_count": len(snaps),
        "sum_delta_tasks": sum_delta_tasks,
        "sum_delta_amount": round(sum_delta_amount, 4),
        "elapsed_hours": round(elapsed_h, 1),
        "snapshots": snaps,
    }


def _get_account_feed(account_id: int, max_items: int = 30) -> list[dict]:
    """[legacy] 拿账号 profile feed — 需要 __NS_hxfalcon 签名, 多数时候失败.

    保留为备用, 主路径用 _check_short_video_url.
    """
    try:
        from core.db_manager import DBManager
        import requests

        # 拿 cookies (instance method)
        db = DBManager()
        try:
            cookies_data = db.get_account_cookies(account_id)
        finally:
            db.close()
        if not cookies_data:
            return []
        # cookies_data 可能是 dict (含 cookies/creator_cookie/shop_cookie)
        # cookies_data dict 含: cookies(list) / creator_cookie(str) / main_cookie / etc.
        cookies_str = ""
        if isinstance(cookies_data, dict):
            # c.kuaishou.com 用 main / all domain, 优先 'cookies' (all)
            cookies_list = cookies_data.get("cookies")
            if isinstance(cookies_list, list) and cookies_list:
                cookies_str = "; ".join(
                    f"{c.get('name')}={c.get('value')}"
                    for c in cookies_list if c.get("name")
                )
            # fallback creator_cookie (cp 域, 含 userId)
            if not cookies_str:
                cookies_str = cookies_data.get("creator_cookie") or ""
        elif isinstance(cookies_data, list):
            cookies_str = "; ".join(
                f"{c.get('name')}={c.get('value')}"
                for c in cookies_data if c.get("name")
            )

        # 拿 numeric_uid
        with _connect() as c:
            r = c.execute(
                "SELECT numeric_uid FROM device_accounts WHERE id=?",
                (account_id,),
            ).fetchone()
            if not r or not r["numeric_uid"]:
                return []
            uid = r["numeric_uid"]

        url = f"https://c.kuaishou.com/rest/wd/feed/profile"
        params = {
            "userId": str(uid),
            "count": str(max_items),
        }
        headers = {
            "Cookie": cookies_str,
            "User-Agent": "Mozilla/5.0",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            log.warning("[verifier] feed %s HTTP %s", uid, resp.status_code)
            return []
        data = resp.json()
        feeds = data.get("data", {}).get("feeds", []) or data.get("feeds", [])
        return feeds
    except Exception as e:
        log.warning("[verifier] fetch feed failed: %s", e)
        return []


def verify_published_photo(
    account_id: int,
    photo_id: str,
    published_at: datetime | None = None,
    grace_minutes: int = 10,
) -> dict[str, Any]:
    """查发布的 photo_id 是否在账号 feed.

    Args:
        account_id: device_accounts.id
        photo_id: 要查的 photoIdStr
        published_at: 发布时间 (判断是否过了 grace 期)
        grace_minutes: 发布后多久才算过 silent-fail 判定期

    Returns:
        {
            "verified": bool,             # 是否在 feed
            "in_feed": bool,              # 当前是否可见
            "feed_total": int,            # 账号最近作品数
            "photo_in_feed": {...}|None,  # 匹配到的 feed entry
            "verification_status": str,   # verified / silent_reject / pending / error
            "error": str | None,
        }
    """
    # Grace 期未到 → pending
    if published_at:
        elapsed_min = (datetime.now() - published_at).total_seconds() / 60
        if elapsed_min < grace_minutes:
            return {
                "verified": False,
                "in_feed": False,
                "verification_status": "pending",
                "grace_remaining_min": round(grace_minutes - elapsed_min, 1),
            }

    # 第 1 路: short-video URL 作为 **强信号** — 只在 3xx/404 时判拒
    check = _check_short_video_url(str(photo_id))
    status = check.get("status", "error")

    # 强信号: 作品页面明确不存在/已删除
    if status in ("redirect", "not_found"):
        return {
            "verified": False,
            "in_feed": False,
            "verification_status": "silent_reject",
            "http_code": check.get("http_code"),
            "short_video_status": status,
            "note": f"作品页面 {status} — 强信号判拒",
        }
    # 罕见但强: HTML 含 photo_id → 真存在
    if check.get("exists") is True:
        return {
            "verified": True,
            "in_feed": True,
            "verification_status": "verified",
            "http_code": check.get("http_code"),
            "note": "short-video URL 含 photo_id — 强信号通过",
        }

    # 第 2 路: SPA 渲染时 (200 unreliable_spa) — 用 MCN delta 反推
    if published_at:
        mcn = verify_via_mcn_delta(account_id, published_at, window_days=3)
        verdict = mcn.get("verdict")
        if verdict == "likely_verified":
            return {
                "verified": True,
                "in_feed": True,
                "verification_status": "verified",
                "note": f"MCN 有新 task: delta_tasks={mcn.get('sum_delta_tasks')}",
                "short_video_status": status,
                "mcn_evidence": mcn,
            }
        if verdict == "likely_verified_income_only":
            return {
                "verified": True,
                "in_feed": True,
                "verification_status": "verified",
                "note": f"MCN 有收益增长: ¥{mcn.get('sum_delta_amount')}",
                "short_video_status": status,
                "mcn_evidence": mcn,
            }
        if verdict == "likely_silent_reject":
            return {
                "verified": False,
                "in_feed": False,
                "verification_status": "silent_reject",
                "note": "MCN 3 天无增量 + SPA 无法判定 → 高概率 silent_reject",
                "short_video_status": status,
                "mcn_evidence": mcn,
            }
        # pending / no_snapshot / unknown / error → 继续观察
        return {
            "verified": False,
            "in_feed": False,
            "verification_status": "pending",
            "note": f"SPA 渲染不可判, MCN {verdict}",
            "short_video_status": status,
            "mcn_evidence": mcn,
        }

    # 无 published_at → 无法用 MCN 反推
    return {
        "verified": False,
        "in_feed": False,
        "verification_status": "pending",
        "http_code": check.get("http_code"),
        "short_video_status": status,
        "note": f"SPA 渲染不可判 + 缺 published_at — 保持 pending",
    }


def verify_pending_publishes(grace_minutes: int = 10,
                               max_age_hours: int = 24) -> dict[str, Any]:
    """批量验证近期发布的 photos.

    查 publish_results 表里 status=success 且 verified_at IS NULL 的,
    依次调 verify_published_photo.
    """
    stats = {"checked": 0, "verified": 0, "silent_reject": 0,
             "pending": 0, "error": 0}

    with _connect() as c:
        # 可能没有 verified_at / verified_status 字段, 补一下
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(publish_results)").fetchall()]
            if "verified_at" not in cols:
                c.execute("ALTER TABLE publish_results ADD COLUMN verified_at TEXT")
            if "verified_status" not in cols:
                c.execute("ALTER TABLE publish_results ADD COLUMN verified_status TEXT")
            c.commit()
        except Exception as e:
            log.warning("[verifier] schema check: %s", e)

        rows = c.execute(
            """SELECT id, account_id, photo_id, created_at
               FROM publish_results
               WHERE publish_status='success'
                 AND photo_id IS NOT NULL AND photo_id != ''
                 AND (verified_at IS NULL)
                 AND datetime(created_at) >= datetime('now', ?)
               ORDER BY created_at DESC
               LIMIT 50""",
            (f"-{max_age_hours} hours",),
        ).fetchall()

    log.info("[verifier] %d pending verifications", len(rows))

    for row in rows:
        try:
            pub_at = datetime.fromisoformat(row["created_at"].replace("Z", ""))
        except Exception:
            pub_at = None

        r = verify_published_photo(
            account_id=int(row["account_id"]),
            photo_id=row["photo_id"],
            published_at=pub_at,
            grace_minutes=grace_minutes,
        )
        status = r["verification_status"]
        stats["checked"] += 1
        stats[status.replace("verified", "verified").replace("silent_reject", "silent_reject")
              .replace("pending", "pending").replace("error", "error")] += 1

        # 写回 DB (pending 不写, 下次再查)
        if status != "pending":
            with _connect() as c:
                c.execute(
                    """UPDATE publish_results
                       SET verified_at=datetime('now','localtime'),
                           verified_status=?
                       WHERE id=?""",
                    (status, row["id"]),
                )
                c.commit()

        if status == "silent_reject":
            log.warning("[verifier] SILENT REJECT account=%s photo=%s",
                         row["account_id"], row["photo_id"])

    return stats


if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, help="验证单个账号 + photo_id")
    ap.add_argument("--photo-id", type=str, help="photo_id")
    ap.add_argument("--batch", action="store_true",
                    help="批量验证所有待验证的")
    ap.add_argument("--grace", type=int, default=10,
                    help="发布后多少分钟算过 grace 期")
    args = ap.parse_args()

    if args.batch:
        r = verify_pending_publishes(grace_minutes=args.grace)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.account and args.photo_id:
        r = verify_published_photo(
            account_id=args.account,
            photo_id=args.photo_id,
            grace_minutes=args.grace,
        )
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        ap.print_help()
