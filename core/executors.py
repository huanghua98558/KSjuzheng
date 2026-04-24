# -*- coding: utf-8 -*-
"""task_queue 执行器注册中心.

为每个 TASK_TYPES 提供真实的执行函数, 挂载到 TaskQueue.

执行器签名:
    def fn(task: Task) -> dict
        return {"success": bool, "message": str, ...}
    raise exception → 触发重试

真正对接现有 core/ 模块:
    COLLECT          → drama_collector.fetch_profile_feed
    DOWNLOAD         → stub (下游未接入)
    PROCESS          → stub
    PUBLISH_A        → publisher.publish_video
    PUBLISH_B        → stub (Selenium 通道)
    VERIFY           → 查 publish_results
    MCN_SYNC         → mcn_business.sync_members
    MCN_BIND_VERIFY  → mcn_business.sync_account_bindings
    HEALTH_CHECK     → data_collector.snapshot_all_accounts
    ANALYZE          → 触发一次 orchestrator
    FEEDBACK         → stub
    EXPERIMENT / SCALE → stub
"""
from __future__ import annotations

import time
import traceback
from typing import Any

from core.logger import get_logger
from core.task_queue import Task

log = get_logger("executors")


# ---------------------------------------------------------------------------
# 每个执行器都接 (db, task) -> dict
# ---------------------------------------------------------------------------

def exec_collect(db, task: Task) -> dict:
    """采集该账号的 profile/feed.
    params: {author_uid, max_pages, ...}  (默认拉自己 uid)
    """
    from core.cookie_manager import CookieManager
    from core.drama_collector import DramaCollector
    cm = CookieManager(db)
    collector = DramaCollector(db, cm)
    author_uid = task.params.get("author_uid", task.account_id)
    account_pk = int(task.params.get("account_pk", 0)) or _resolve_account_pk(db, task.account_id)
    max_pages = int(task.params.get("max_pages", 2))
    if not author_uid or not account_pk:
        raise ValueError(f"missing author_uid={author_uid} or account_pk={account_pk}")
    photos = collector.fetch_profile_feed(author_uid, account_pk, max_pages=max_pages)
    return {"success": True, "photo_count": len(photos),
            "message": f"采集 {len(photos)} 条"}


def exec_download(db, task: Task) -> dict:
    """真实下载 — share URL → m3u8 → N_m3u8DL-RE.

    params 支持:
      drama_url:   可以是 share URL (kuaishou.com/f/XXX) 或直接 m3u8
      drama_id:    drama_links.id (可选, 回写 status)
    输出: {success, output_path, m3u8_url, message}
    """
    from core.video_downloader import VideoDownloader
    from core.cookie_manager import CookieManager
    url = task.params.get("drama_url") or task.params.get("url")
    if not url:
        raise ValueError("缺 drama_url")
    account_pk = _resolve_account_pk(db, task.account_id)
    drama_name = task.drama_name or task.params.get("drama_name") or "unknown"
    drama_id = task.params.get("drama_id")

    # 回写 drama_links.status=downloading
    if drama_id:
        try:
            db.conn.execute(
                "UPDATE drama_links SET status='downloading' WHERE id=?",
                (drama_id,),
            )
            db.conn.commit()
        except Exception:
            pass

    downloader = VideoDownloader()

    # Step 1: 如果是 share URL, 先解析出 m3u8
    m3u8_url = url
    if "kuaishou.com/f/" in url or "/f/" in url or ".m3u8" not in url.lower():
        cookie_str = ""
        if account_pk:
            try:
                cm = CookieManager(db)
                cookie_str = cm.get_cookie_string(account_pk, domain="all") or ""
            except Exception:
                pass
        m3u8_url = downloader.get_m3u8_url_from_drama_page(url, cookie_str)
        if not m3u8_url:
            if drama_id:
                try:
                    db.conn.execute(
                        "UPDATE drama_links SET status='failed' WHERE id=?",
                        (drama_id,),
                    )
                    db.conn.commit()
                except Exception:
                    pass
            raise RuntimeError(f"无法从 share URL 解析 m3u8: {url[:80]}")

    # Step 2: 下载 m3u8
    output = downloader.download_video(
        m3u8_url=m3u8_url,
        account_id=str(account_pk or task.account_id),
        drama_name=drama_name,
    )
    if not output:
        if drama_id:
            try:
                db.conn.execute(
                    "UPDATE drama_links SET status='failed' WHERE id=?",
                    (drama_id,),
                )
                db.conn.commit()
            except Exception:
                pass
        raise RuntimeError(f"VideoDownloader 返回空: {m3u8_url[:80]}")
    return {
        "success": True, "output_path": output,
        "m3u8_url": m3u8_url,
        "drama_id": drama_id,
        "message": f"已下载 {drama_name}",
    }


def exec_process(db, task: Task) -> dict:
    """真实剪辑 — 对接 VideoProcessor (Mode6 是主力).

    params:
      input_path:  上一步 DOWNLOAD 的 output_path
      mode:        mode1(原片)/mode3(变速)/mode4(镜像)/mode6(合成, 默认)
    输出: {success, output_path, mode, message}
    """
    from core.video_processor import VideoProcessor
    from core.config import VIDEO_PROCESSED_DIR

    input_path = task.params.get("input_path") or task.params.get("video_path")
    if not input_path:
        raise ValueError("缺 input_path")
    import os
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"input 不存在: {input_path}")

    drama_name = task.drama_name or "processed"
    mode = task.params.get("mode", "mode6")

    if mode == "mode1":
        # 原片: 直接 copy (已有 VideoProcessor 对 mode6 实现, 其他 mode 暂简化成直接复用原片)
        return {"success": True, "output_path": input_path, "mode": "mode1",
                "message": "mode1 原片直接用"}

    processor = VideoProcessor()
    output = processor.process_video(
        input_path=input_path,
        output_dir=VIDEO_PROCESSED_DIR,
        drama_name=drama_name,
    )
    if not output:
        raise RuntimeError("VideoProcessor 返回空")
    return {
        "success": True, "output_path": output,
        "mode": mode,
        "message": f"{mode} 剪辑完成",
    }


def exec_publish_a(db, task: Task) -> dict:
    """CP API 发布 — 修复了 Publisher 构造参数 + 写 publish_results 全 trace."""
    from core.cookie_manager import CookieManager
    from core.sig_service import SigService
    from core.mcn_client import MCNClient
    from core.publisher import KuaishouPublisher

    video_path = (task.params.get("video_path") or
                  task.params.get("output_path") or
                  task.params.get("output_asset_id"))
    drama_name = task.drama_name or task.params.get("drama_name")
    account_pk = _resolve_account_pk(db, task.account_id)
    if not video_path or not drama_name or not account_pk:
        raise ValueError(
            f"missing video_path={video_path}/drama={drama_name}/account_pk={account_pk}")

    publisher = KuaishouPublisher(
        cookie_manager=CookieManager(db),
        sig_service=SigService(),
        mcn_client=MCNClient(),
        db_manager=db,
    )
    result = publisher.publish_video(
        account_id=account_pk,
        video_path=video_path,
        drama_name=drama_name,
        caption=task.params.get("caption"),
        # trace 全链路回灌
        task_queue_id=str(task.id or ""),
        batch_id=task.batch_id or "",
        input_asset_id=task.params.get("input_asset_id") or video_path,
    )
    if not result.get("success"):
        raise RuntimeError(
            f"publish failed: {result.get('message','unknown')}")
    return result


def exec_publish_b(db, task: Task) -> dict:
    """Selenium 备用通道 — 占位."""
    time.sleep(1)
    return {"success": False, "message": "PUBLISH_B stub — Selenium 未接入"}


def exec_verify(db, task: Task) -> dict:
    """查 publish_results 确认发布, 且把 verify_status pending→verified.

    触发方式: 上游 PUBLISH_A 成功后入队 VERIFY, params.photo_id 从
    PUBLISH_A 的 result 拿. 若拿不到 photo_id 就按 (account_id, drama_name)
    取最近一条 success 记录验证.
    """
    photo_id = task.params.get("photo_id")
    account_id = task.account_id
    drama_name = task.drama_name

    if photo_id:
        row = db.conn.execute(
            """SELECT id, publish_status, verify_status, failure_reason
               FROM publish_results
               WHERE photo_id=? ORDER BY id DESC LIMIT 1""",
            (photo_id,),
        ).fetchone()
    elif account_id and drama_name:
        row = db.conn.execute(
            """SELECT id, publish_status, verify_status, failure_reason
               FROM publish_results
               WHERE account_id=? AND drama_name=?
               ORDER BY id DESC LIMIT 1""",
            (str(account_id), drama_name),
        ).fetchone()
    else:
        raise ValueError("缺 photo_id 或 (account_id+drama_name)")

    if not row:
        return {"success": False, "message": "未找到 publish_results 记录"}

    row_id, p_status, v_status, fail = row
    ok = (p_status == "success")

    # VERIFY 成功 → 把 pending 置 verified + verified_at
    if ok and v_status == "pending":
        try:
            db.conn.execute(
                """UPDATE publish_results SET
                     verify_status='verified',
                     verified_at=datetime('now','localtime'),
                     updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (row_id,),
            )
            db.conn.commit()
            v_status = "verified"
        except Exception as e:
            # 不致命, 让 task 仍标 success, 下轮 SelfHealing 会再试
            log.warning(f"[exec_verify] promote verified failed: {e}")

    return {
        "success": ok,
        "publish_result_id": row_id,
        "publish_status": p_status,
        "verify_status": v_status,
        "failure_reason": fail,
        "photo_id": photo_id,
    }


def exec_mcn_sync(db, task: Task) -> dict:
    """同步 MCN 萤光计划成员."""
    from core.mcn_business import MCNBusiness
    biz = MCNBusiness(db)
    n_bindings = biz.sync_account_bindings()
    n_members = biz.sync_members()
    n_income = biz.snapshot_daily_income()
    return {
        "success": True, "bindings": n_bindings,
        "members": n_members, "income_snapshots": n_income,
        "message": f"MCN 同步完成: 绑定 {n_bindings} / 成员 {n_members} / 收入快照 {n_income}",
    }


def exec_mcn_bind_verify(db, task: Task) -> dict:
    """仅做绑定校验, 不同步收入."""
    from core.mcn_business import MCNBusiness
    biz = MCNBusiness(db)
    n = biz.sync_account_bindings()
    return {"success": True, "bindings": n,
            "message": f"MCN 绑定校验: {n} 条"}


def exec_mcn_invite(db, task: Task) -> dict:
    """邀请某账号加入萤光计划."""
    from core.mcn_business import MCNBusiness
    target_uid = task.params.get("target_uid") or task.account_id
    target_name = task.params.get("target_name", "")
    if not target_uid:
        raise ValueError("缺 target_uid")
    biz = MCNBusiness(db)
    result = biz.invite_and_persist(target_uid=str(target_uid), target_name=target_name)
    return {"success": bool(result), "result": result,
            "message": f"invite {target_uid}: {result}"}


def exec_health_check(db, task: Task) -> dict:
    """全矩阵健康采集快照."""
    from core.cookie_manager import CookieManager
    from core.data_collector import DataCollector
    cm = CookieManager(db)
    dc = DataCollector(db, cm)
    res = dc.snapshot_all_accounts()
    return {
        "success": (res.get("accounts_failed", 0) == 0),
        "processed": res.get("accounts_processed", 0),
        "failed": res.get("accounts_failed", 0),
        "works_captured": res.get("total_works_captured", 0),
        "message": f"Health check: {res.get('accounts_processed',0)} OK, "
                   f"{res.get('accounts_failed',0)} failed",
    }


def exec_analyze(db, task: Task) -> dict:
    """触发一次 Orchestrator (含 LLM 决策)."""
    from core.agents.orchestrator import Orchestrator
    orc = Orchestrator(db)
    resp = orc.run({
        "group": task.params.get("group", ""),
        "lifecycle_stage": task.params.get("lifecycle_stage", ""),
    })
    return {
        "success": resp.get("status") in ("ok", "degraded"),
        "batch_id": resp.get("meta", {}).get("batch_id"),
        "findings_count": len(resp.get("findings", [])),
        "plan_count": len(resp.get("meta", {}).get("execution_plan", [])),
        "message": f"Orchestrator done: "
                   f"{len(resp.get('findings', []))} findings",
    }


def exec_feedback(db, task: Task) -> dict:
    """反馈 outcome (views/cpm/approved) 回 decision_history — 占位."""
    return {"success": True, "message": "FEEDBACK stub"}


def exec_experiment(db, task: Task) -> dict:
    """启动 / 记录实验 — 占位."""
    return {"success": True, "message": "EXPERIMENT stub"}


def exec_scale(db, task: Task) -> dict:
    """放大 winner 到更多账号 — 占位."""
    return {"success": True, "message": "SCALE stub"}


def exec_mcn_poll(db, task: Task) -> dict:
    from core.mcn_business import MCNBusiness
    uid = task.params.get("target_uid") or task.account_id
    return MCNBusiness(db).poll_invitation_status(str(uid))


def exec_mcn_heartbeat(db, task: Task) -> dict:
    return {"success": True, "message": "MCN_HEARTBEAT stub"}


def exec_qc(db, task: Task) -> dict:
    return {"success": True, "message": "QC stub"}


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_EXECUTORS: dict[str, Any] = {
    "COLLECT":          exec_collect,
    "DOWNLOAD":         exec_download,
    "PROCESS":          exec_process,
    "PUBLISH_A":        exec_publish_a,
    "PUBLISH_B":        exec_publish_b,
    "VERIFY":           exec_verify,
    "MCN_SYNC":         exec_mcn_sync,
    "MCN_BIND_VERIFY":  exec_mcn_bind_verify,
    "MCN_INVITE":       exec_mcn_invite,
    "MCN_POLL":         exec_mcn_poll,
    "MCN_HEARTBEAT":    exec_mcn_heartbeat,
    "HEALTH_CHECK":     exec_health_check,
    "ANALYZE":          exec_analyze,
    "FEEDBACK":         exec_feedback,
    "EXPERIMENT":       exec_experiment,
    "SCALE":            exec_scale,
    "QC":               exec_qc,
}


def register_all(task_queue, db_manager) -> list[str]:
    """把所有执行器挂到 TaskQueue 实例上."""
    registered = []
    for task_type, fn in _EXECUTORS.items():
        # 包一层 lambda 传入 db_manager
        bound_fn = lambda task, _db=db_manager, _fn=fn: _exec_wrapper(_fn, _db, task)
        try:
            task_queue.set_executor(task_type, bound_fn)
            registered.append(task_type)
        except Exception as e:
            log.warning("register %s failed: %s", task_type, e)
    return registered


def _exec_wrapper(fn, db, task: Task) -> dict:
    """统一包装: 记录 start/end 日志 + 异常扎带 trace."""
    start = time.time()
    log.info("[exec] START %s id=%s account=%s drama=%s",
             task.task_type, task.id, task.account_id, task.drama_name)
    try:
        result = fn(db, task)
        elapsed = int((time.time() - start) * 1000)
        log.info("[exec]    OK %s id=%s %dms | %s",
                 task.task_type, task.id, elapsed,
                 result.get("message", ""))
        return result
    except Exception as exc:
        elapsed = int((time.time() - start) * 1000)
        log.error("[exec]  FAIL %s id=%s %dms: %s\n%s",
                  task.task_type, task.id, elapsed, exc,
                  traceback.format_exc()[:800])
        raise


# ---------------------------------------------------------------------------

def _resolve_account_pk(db, account_id: str | int) -> int:
    """把 kuaishou_uid 或 account_name 解析成 device_accounts.id."""
    if isinstance(account_id, int) or (isinstance(account_id, str) and account_id.isdigit() and len(account_id) < 6):
        try:
            return int(account_id)
        except Exception:
            pass
    row = db.conn.execute(
        """SELECT id FROM device_accounts
           WHERE kuaishou_uid=? OR account_name=? LIMIT 1""",
        (str(account_id), str(account_id)),
    ).fetchone()
    return int(row[0]) if row else 0
