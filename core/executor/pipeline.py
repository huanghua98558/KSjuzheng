# -*- coding: utf-8 -*-
"""Pipeline — 一个 PUBLISH 任务的完整 4 阶段流水线.

阶段:
  1. download  - core.downloader.download_drama()
  2. process   - core.processor.process_video()
  3. publish   - core.publisher.KuaishouPublisher.publish_video()
  4. verify    - (可选) 查快手公开页确认 photo_id 可见 (Week 3)

每个阶段:
  - 更新 task_queue.status + stage_updates_json
  - 失败 → 写 error_message, 触发重试或 dead_letter
  - 成功 → 推进到下一阶段

这是**无状态**函数 — 由 account_executor.py 在 worker 线程里调用.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.app_config import get as cfg_get
from core.notifier import notify

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# task_queue 状态更新 helpers
# ─────────────────────────────────────────────────────────────────

def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    c.execute("PRAGMA busy_timeout=10000")
    return c


# ─────────────────────────────────────────────────────────────────
# S-5 (2026-04-20) recipe 强度校验 — 防 config 覆盖导致降级
# ─────────────────────────────────────────────────────────────────

def _record_recipe_performance(
    task_id: str, recipe: str, task_params: dict,
    account_id: int, verdict: str, income_delta: float | None = None,
) -> None:
    """S-8 (2026-04-20): pipeline 完成时记 recipe_performance 埋点.

    analyzer 每日跑 rebuild_knowledge_from_performance 反推 knowledge 星.

    Args:
        task_id:
        recipe:
        task_params: task.params (含 account_tier, task_source, plan_item_id)
        account_id:
        verdict: "success" / "failed" / "blocked"
        income_delta: 收益差 (analyzer 从 publish_daily_metrics 补)
    """
    if not cfg_get("ai.recipe_performance.enabled", True):
        return
    try:
        # 从 scenario_scorer 生成 tag
        tier = task_params.get("account_tier", "")
        source = task_params.get("task_source", "planner")
        plan_item_id = task_params.get("plan_item_id")

        try:
            from core.scenario_scorer import score_scenario
            scen = score_scenario(
                account={"id": account_id, "tier": tier},
                drama_name="", task_source=source,
            )
            scenario_tag = scen.get("scenario_tag", f"{source}_{tier}")
        except Exception:
            scenario_tag = f"{source}_{tier}"

        with _connect() as c:
            c.execute(
                """INSERT INTO recipe_performance
                     (recipe_name, account_id, account_tier, task_source,
                      scenario_tag, verdict, income_delta, task_id, plan_item_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (recipe, account_id, tier, source, scenario_tag, verdict,
                 income_delta, task_id, plan_item_id),
            )
            c.commit()
        log.info("[pipeline][perf] recipe=%s verdict=%s tag=%s task=%s",
                 recipe, verdict, scenario_tag, task_id)
    except Exception as e:
        log.debug("[pipeline][perf] record failed: %s", e)


def _validate_recipe_strength(recipe: str, task_params: dict,
                                task_id: str = "") -> str:
    """校验 recipe 是否在 recipe_knowledge 里 + 是否满足 task 场景要求.

    场景:
      Case A: recipe 在 knowledge 表 → 比对强度是否符合 task 里的 tier/source
              如果不符合 → 记 warning, 不降级 (由 task 上游已决策)
      Case B: recipe 不在 knowledge 表 → 未知, 记 warning

    不自动降级: 尊重 task_queue 里写的 recipe (那是 planner 决策的结果).
    这个函数只做 **audit** 日志 + recipe_performance 埋点准备.

    Returns: recipe (原样, 不修改)
    """
    if not cfg_get("ai.recipe_knowledge.enabled", True):
        return recipe
    try:
        with _connect() as c:
            c.row_factory = sqlite3.Row
            r = c.execute(
                "SELECT strength_overall, ks184_alignment, alignment_status, "
                "beat_l3_phash "
                "FROM recipe_knowledge WHERE recipe_name=?",
                (recipe,),
            ).fetchone()
    except Exception as e:
        log.debug("[pipeline] recipe knowledge lookup failed: %s", e)
        return recipe

    if not r:
        log.warning("[pipeline][audit] recipe=%s 不在 knowledge 表, task=%s",
                    recipe, task_id)
        return recipe

    tier = task_params.get("account_tier", "")
    source = task_params.get("task_source", "planner")

    # 对照 scenario_scorer 的要求
    try:
        from core.scenario_scorer import score_scenario, _STRENGTH_THRESHOLD_MAP
        scen = score_scenario(
            account={"id": 0, "tier": tier},  # 单纯参考 tier+source
            drama_name="", task_source=source,
        )
        required_threshold = _STRENGTH_THRESHOLD_MAP.get(scen["min_strength"], 2.0)
        actual = r["strength_overall"]
        if actual < required_threshold - 0.3:  # 0.3 容差
            log.warning(
                "[pipeline][audit] recipe=%s strength=%.1f < required %.1f "
                "(tier=%s source=%s scenario=%s). 继续但可能被判重.",
                recipe, actual, required_threshold, tier, source,
                scen["scenario_tag"],
            )
        else:
            log.info(
                "[pipeline][audit] recipe=%s ks184=%.0f%% strength=%.1f OK for %s",
                recipe, r["ks184_alignment"] * 100, actual, scen["scenario_tag"],
            )
    except Exception as e:
        log.debug("[pipeline][audit] scenario check failed: %s", e)

    return recipe


def _update_task(task_id: str, **fields) -> None:
    """通用 update, 自动加 updated-at."""
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    vals = list(fields.values()) + [task_id]
    with _connect() as c:
        c.execute(f"UPDATE task_queue SET {cols} WHERE id = ?", vals)
        c.commit()


def _stage_start(task_id: str, stage: str) -> None:
    """进入某 stage. 更新 status + stage_updates_json."""
    with _connect() as c:
        row = c.execute(
            "SELECT stage_updates_json FROM task_queue WHERE id=?", (task_id,)
        ).fetchone()
        history = json.loads(row[0]) if row and row[0] else []
        history.append({"stage": stage, "started_at": time.time()})
        c.execute(
            """UPDATE task_queue SET status=?, stage_updates_json=?,
                 started_at=COALESCE(started_at, datetime('now','localtime'))
               WHERE id=?""",
            (stage, json.dumps(history, ensure_ascii=False), task_id),
        )
        c.commit()


def _stage_end(task_id: str, stage: str, ok: bool, details: dict | None = None) -> None:
    with _connect() as c:
        row = c.execute(
            "SELECT stage_updates_json FROM task_queue WHERE id=?", (task_id,)
        ).fetchone()
        history = json.loads(row[0]) if row and row[0] else []
        if history and history[-1].get("stage") == stage and "ended_at" not in history[-1]:
            history[-1]["ended_at"] = time.time()
            history[-1]["duration_sec"] = round(
                history[-1]["ended_at"] - history[-1].get("started_at", 0), 2)
            history[-1]["ok"] = ok
            if details:
                history[-1]["details"] = details
        c.execute(
            "UPDATE task_queue SET stage_updates_json=? WHERE id=?",
            (json.dumps(history, ensure_ascii=False), task_id),
        )
        c.commit()


# ─────────────────────────────────────────────────────────────────
# Pipeline 主函数
# ─────────────────────────────────────────────────────────────────

def run_publish_pipeline(task: dict) -> dict[str, Any]:
    """跑一个 PUBLISH 任务的完整流水线.

    Args:
        task: task_queue 行 (dict), 至少含:
              id, account_id, drama_name, banner_task_id (可选),
              priority, params (JSON)
              params 可包含:
                process_recipe / image_mode / recipe_config / input_asset_path
                (★ E-2 硬断修复: 以前这些全从 config 读, 现在优先 task)

    Returns:
        {ok, final_status, photo_id?, share_url?, error?}
    """
    task_id = task["id"]
    account_id = int(task["account_id"])
    drama_name = task["drama_name"]

    # ★ E-2: 解 params 一次, 给后续所有 stage 用
    try:
        task_params = json.loads(task.get("params") or "{}")
    except Exception:
        task_params = {}
        log.warning("[pipeline] task.params JSON 解析失败, fallback {}")

    # task 优先字段 (E-2 硬断修复核心)
    task_recipe     = (task.get("process_recipe") or task_params.get("process_recipe")
                        or task_params.get("recipe"))
    task_image_mode = task_params.get("image_mode")
    task_recipe_cfg = task_params.get("recipe_config")

    log.info("[pipeline] start task=%s account=%s drama=%s "
             "recipe=%s image_mode=%s (from task)",
             task_id, account_id, drama_name,
             task_recipe or "(fallback)", task_image_mode or "(fallback)")

    # ── Stage 0 (2026-04-20 用户要求): MCN 状态预检 ──
    # 账号在 MCN 被封/移除/违规暴增/剧在黑名单 → 立即拒 + 冻结 + 写记忆
    # 下次 planner 不排该账号 (看 device_accounts.tier='frozen'),
    # 除非 admin 手动解冻 (`python -m core.agents.maintenance_agent
    # unfreeze_account --id X`).
    if cfg_get("ai.preflight.mcn_enabled", True):
        _stage_start(task_id, "mcn_preflight")
        try:
            from core.mcn_preflight import preflight_check
            pre = preflight_check(account_id, drama_name=drama_name)
        except Exception as e:
            log.exception(f"[pipeline] mcn_preflight 异常 (放行): {e}")
            pre = {"ok": True, "reason": "preflight_error_bypass", "error": str(e),
                   "detail": {}}
        _stage_end(task_id, "mcn_preflight", pre["ok"], pre)
        if not pre["ok"]:
            reason = pre.get("reason", "mcn_preflight_fail")
            err = pre.get("error", "mcn preflight failed")
            log.warning(f"[pipeline] MCN preflight 拒绝 task={task_id} "
                        f"account={account_id}: {reason} — {err}")
            # 风控通知
            try:
                notify(
                    title=f"MCN Preflight 拒绝 账号 {account_id}",
                    body=f"{err}\n详情: {pre.get('detail')}",
                    level="warning",
                    category="风控",
                )
            except Exception:
                pass
            _update_task(
                task_id, status="failed",
                error_message=f"mcn_preflight:{reason}",
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return {"ok": False, "final_status": "blocked",
                    "error": err, "reason": reason, "blocked_by": "mcn_preflight"}

    # ── Stage 1: download (加文件锁防同剧多 worker 重复下) ──
    drama_cover_url = None   # 从 downloader 回传, 给 Stage 3.5 用
    drama_url_used = None
    if cfg_get("executor.pipeline.download_enabled", True):
        _stage_start(task_id, "downloading")
        from core.downloader import download_drama
        from core.file_lock import FileLock
        # 用 drama_name 作 lock key (同剧不并发下)
        with FileLock("download", drama_name, timeout=600, stale_sec=1800) as got_lock:
            if not got_lock:
                _update_task(task_id, status="failed",
                              error_message="download_lock_timeout")
                return {"ok": False, "final_status": "failed",
                        "error": "download_lock_timeout"}
            dl = download_drama(drama_name)
        _stage_end(task_id, "downloading", dl["ok"], dl)
        if not dl["ok"]:
            _update_task(task_id, status="failed",
                          error_message=f"download: {dl.get('error')}",
                          finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            return {"ok": False, "final_status": "failed",
                    "error": f"download: {dl.get('error')}"}
        input_asset_path = dl["file_path"]
        drama_cover_url = dl.get("cover_url")
        drama_url_used = dl.get("drama_url")
        _update_task(task_id, input_asset_path=input_asset_path)
    else:
        # download disabled → task.params 里应预置 input_asset_path
        params = json.loads(task.get("params") or "{}")
        input_asset_path = params.get("input_asset_path")
        if not input_asset_path:
            _update_task(task_id, status="failed",
                          error_message="no input_asset_path (download disabled)")
            return {"ok": False, "final_status": "failed", "error": "no_input"}

    # ── Stage 1.5: MD5 修改 (防查重) ──
    # 对齐 KS184 `_copy_and_modify_md5`: 往 mp4 末尾追加随机字节改 MD5
    if cfg_get("video.process.modify_md5", True):
        _stage_start(task_id, "md5_modifying")
        from core.md5_modifier import modify_if_enabled
        md5_r = modify_if_enabled(input_asset_path)
        _stage_end(task_id, "md5_modifying", md5_r.get("ok", False), md5_r)
        # MD5 改失败不致命, 继续 (只是失去一层防查重)
        if not md5_r.get("ok") and not md5_r.get("skipped"):
            log.warning("[pipeline] md5 modify failed: %s", md5_r.get("error"))

    # ── Stage 2: process (加锁: 同源视频不并发处理) ──
    if cfg_get("executor.pipeline.process_enabled", True):
        _stage_start(task_id, "processing")
        from core.processor import process_video
        from core.file_lock import FileLock
        out_dir = cfg_get("processor.output_dir", "short_drama_videos/processed")

        # ★ E-2: recipe 优先从 task 读, fallback config
        if task_recipe:
            recipe = task_recipe
        else:
            recipe = cfg_get("video.process.mode", "mvp_trim_wipe_metadata")
            log.warning("[pipeline] task 无 recipe, fallback config=%s", recipe)

        # ★ S-5 (2026-04-20): recipe knowledge 降级校验
        # 防 config 意外覆盖 AI 选的 recipe 导致强度不够 (如 planner 选了 kirin
        # 但 config 改了 mvp → 需要降级/提示)
        recipe = _validate_recipe_strength(
            recipe, task_params=task_params, task_id=task_id,
        )

        # 账号名 (给水印用, 也给 qitian frame_based 抽帧用)
        try:
            with _connect() as _c:
                _r = _c.execute(
                    "SELECT account_name FROM device_accounts WHERE id=?",
                    (account_id,),
                ).fetchone()
                account_name = (_r["account_name"] if _r else "") or f"acc_{account_id}"
        except Exception:
            account_name = f"acc_{account_id}"

        # 锁 key = 源 video path (同一输入文件不并发处理)
        with FileLock("process", input_asset_path, timeout=1200, stale_sec=3600) as pl:
            if not pl:
                _update_task(task_id, status="failed",
                              error_message="process_lock_timeout")
                return {"ok": False, "final_status": "failed",
                        "error": "process_lock_timeout"}
            # ★ E-2: 把 AI 决策的参数真传到 processor
            proc = process_video(
                input_asset_path,
                output_dir=out_dir,
                recipe=recipe,
                image_mode=task_image_mode,       # ← AI 选的素材风格
                drama_name=drama_name,
                account_name=account_name,
                recipe_config=task_recipe_cfg,    # ← AI 按 tier 调的参数 (blend_alpha 等)
            )

            # ★ 2026-04-24 v6 C1: kirin_mode6 step6 偶 fail → 自动 fallback mode5_pipeline
            # 保留原 recipe 标记以便分析, 但输出走备用 recipe
            if (not proc.get("ok")) and recipe == "kirin_mode6" \
                    and "step6" in str(proc.get("error") or "").lower() \
                    and cfg_get("video.process.fallback_on_mode6_fail", True):
                log.warning("[pipeline] kirin_mode6 step6 failed, fallback to zhizun_mode5_pipeline")
                proc = process_video(
                    input_asset_path,
                    output_dir=out_dir,
                    recipe="zhizun_mode5_pipeline",
                    image_mode=task_image_mode,
                    drama_name=drama_name,
                    account_name=account_name,
                    recipe_config=task_recipe_cfg,
                )
                if proc.get("ok"):
                    proc["fallback_from"] = "kirin_mode6"
                    proc["recipe"] = "zhizun_mode5_pipeline"

        _stage_end(task_id, "processing", proc["ok"], proc)
        if not proc["ok"]:
            _update_task(task_id, status="failed",
                          error_message=f"process: {proc.get('error')}",
                          finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            # ★ S-8: 记 failure
            _record_recipe_performance(
                task_id=task_id, recipe=recipe, task_params=task_params,
                account_id=account_id, verdict="failed",
            )
            return {"ok": False, "final_status": "failed",
                    "error": f"process: {proc.get('error')}"}
        processed_path = proc["output_path"]
        _update_task(task_id, processed_asset_path=processed_path,
                     process_recipe=proc["recipe"])

        # ★ 2026-04-23 P2-1: 异步回测去重质量 (不阻塞 publish)
        if cfg_get("dedup.quality_check.enabled", True):
            try:
                import threading as _t
                from core.dedup_quality import report as _dq_report
                _t.Thread(
                    target=lambda: _dq_report(
                        original_path=input_asset_path,
                        processed_path=processed_path,
                        task_id=task_id,
                        recipe=proc["recipe"],
                        image_mode=task_params.get("image_mode", ""),
                        drama_name=task.get("drama_name", ""),
                    ),
                    daemon=True,
                    name=f"dq-{task_id[-8:]}",
                ).start()
            except Exception:
                pass  # 回测失败不影响 publish
    else:
        processed_path = input_asset_path

    # ── Stage 3.5: 封面准备 (cover_service) + 烧水印 ──
    # 新版: 优先下快手原 cover + 缓存 + 尺寸/压缩 + 折行 textfile 水印.
    cover_override_path = None
    if cfg_get("cover.watermark.enabled", True):
        _stage_start(task_id, "cover_watermark")
        try:
            import secrets as _sec
            from core.cover_service import prepare_cover
            from core.watermark import burn_cover

            work_dir = Path(processed_path).parent

            # ① 用 cover_service 准备封面 (下载/抽帧/缓存/尺寸/压缩)
            prep = prepare_cover(
                video_path=processed_path,
                drama_url=drama_url_used,
                cover_url=drama_cover_url,
                output_dir=str(work_dir / ".cover_work"),
            )
            if not prep.get("ok"):
                log.warning("[pipeline] cover_service 失败: %s", prep.get("error"))
                _stage_end(task_id, "cover_watermark", False, prep)
            else:
                # ② 账号名
                import sqlite3 as _sqlite3
                with _connect() as _c:
                    _c.row_factory = _sqlite3.Row
                    _r = _c.execute(
                        "SELECT account_name FROM device_accounts WHERE id=?",
                        (account_id,)).fetchone()
                    acc_name = _r["account_name"] if _r else ""

                # ③ 烧水印 (输出新路径, 不覆盖缓存)
                rand = _sec.token_hex(4)
                burned = work_dir / f"cover_wm_{rand}.png"
                wm = burn_cover(prep["cover_path"], drama_name=drama_name,
                                  account_name=acc_name, out_cover=str(burned))
                _stage_end(task_id, "cover_watermark", wm.get("ok", False),
                            {**prep, "watermark": wm})
                if wm.get("ok"):
                    cover_override_path = str(burned)
                else:
                    # 水印失败 → fallback 用未烧水印的 prep.cover_path
                    cover_override_path = prep["cover_path"]
                    log.warning("[pipeline] watermark 失败, 用未烧水印的封面")
        except Exception as e:
            log.exception("[pipeline] cover_watermark 异常")
            _stage_end(task_id, "cover_watermark", False, {"error": str(e)})

    # ── Stage 3.7: 可选动态水印 (视频上的 sin 波动 +顶/底文字) ──
    # 对齐 KS184 scale34 的 sin 动态水印, 但可配独立于 scale34 使用
    dyn_wm_enabled = cfg_get("video.dynamic_watermark.enabled", False)
    if isinstance(dyn_wm_enabled, str):
        dyn_wm_enabled = dyn_wm_enabled.lower() in ("true", "1", "yes", "on")
    if dyn_wm_enabled and processed_path and os.path.isfile(processed_path):
        _stage_start(task_id, "dynamic_watermark")
        try:
            from core.dynamic_watermark import apply_dynamic_watermark_auto
            wm_out = str(Path(processed_path).with_suffix("")) + "_dynwm.mp4"
            acc_name = ""
            try:
                from core.db_manager import DBManager
                _db = DBManager()
                try:
                    _accs = _db.get_all_accounts()
                finally:
                    _db.close()
                acc_row = next((a for a in _accs if a["id"] == account_id), None)
                acc_name = (acc_row or {}).get("account_name", "") if acc_row else ""
            except Exception:
                acc_name = ""

            dwm = apply_dynamic_watermark_auto(
                input_video=processed_path, output_video=wm_out,
                drama_name=drama_name, account_name=acc_name,
            )
            if dwm.get("ok") and os.path.isfile(wm_out) and not dwm.get("skipped"):
                # 替换 processed_path → 下一步 publish 用带水印的
                processed_path = wm_out
                _stage_end(task_id, "dynamic_watermark", True,
                           {"output": wm_out,
                            "layers": dwm.get("layers"),
                            "elapsed_sec": dwm.get("elapsed_sec")})
            else:
                _stage_end(task_id, "dynamic_watermark",
                           True, {"skipped": dwm.get("skipped", False),
                                  "reason": dwm.get("reason", "")})
        except Exception as e:
            log.exception("[pipeline] dynamic_watermark 异常")
            _stage_end(task_id, "dynamic_watermark", False, {"error": str(e)})

    # ── Stage 3: publish ──
    if not cfg_get("executor.pipeline.publish_enabled", True):
        # dry-run 模式: publish 阶段 skip, 只算 processed
        _update_task(task_id, status="success",
                     finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                     result=json.dumps({"dry_run": True,
                                        "processed_path": processed_path},
                                       ensure_ascii=False))
        return {"ok": True, "final_status": "success_dry_run",
                "processed_path": processed_path}

    _stage_start(task_id, "publishing")
    try:
        from core.db_manager import DBManager
        from core.cookie_manager import CookieManager
        from core.sig_service import SigService
        from core.mcn_client import MCNClient
        from core.publisher import KuaishouPublisher

        db = DBManager()
        cm = CookieManager(db)
        sig = SigService()
        mcn = MCNClient()
        pub = KuaishouPublisher(cookie_manager=cm, sig_service=sig,
                                  mcn_client=mcn, db_manager=db)

        caption_tpl = cfg_get("publish.caption_template", "{drama} #快来看短剧")
        caption = caption_tpl.format(drama=drama_name, account="")
        pub_result = pub.publish_video(
            account_id=account_id,
            video_path=processed_path,
            drama_name=drama_name,
            caption=caption,
            task_queue_id=task_id,
            batch_id=task.get("batch_id") or "",
            input_asset_id=input_asset_path,
            cover_path_override=cover_override_path,
        )
        db.close()
    except Exception as e:
        pub_result = {"success": False, "message": f"publish exception: {e}"}

    _stage_end(task_id, "publishing", bool(pub_result.get("success")),
                {k: v for k, v in pub_result.items()
                 if k in ("success", "photo_id", "message")})

    if not pub_result.get("success"):
        err = pub_result.get("message", "")[:300]
        _update_task(task_id, status="failed",
                      error_message=f"publish: {err}",
                      finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                      photo_id=pub_result.get("photo_id") or "")
        notify(f"发布失败: {drama_name}",
               f"account_id={account_id}\nreason={err}",
               level="error", source="pipeline",
               extra={"task_id": task_id, "drama": drama_name,
                      "account_id": account_id})
        return {"ok": False, "final_status": "failed", "error": err}

    # Success
    photo_id = pub_result.get("photo_id")
    share_url = pub_result.get("share_url", "")
    _update_task(task_id, status="success",
                  photo_id=photo_id,
                  finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                  result=json.dumps({
                      "photo_id": photo_id, "share_url": share_url,
                  }, ensure_ascii=False))

    # ★ S-8 (2026-04-20): 记 recipe_performance (analyzer 反推 knowledge 用)
    _record_recipe_performance(
        task_id=task_id, recipe=recipe, task_params=task_params,
        account_id=account_id, verdict="success",
    )

    # ★ 2026-04-24 v6 Day 8: 发布成功 → 写 publish_outcome (学习根基)
    # 完整记录决策时的信号 snapshot + 结果 (24h/48h/7d 后由 outcome_collector 回采)
    try:
        from core.publish_outcome import record_publish_success
        record_publish_success(
            task_id=task_id,
            our_photo_id=str(photo_id) if photo_id else "",
            drama_name=drama_name,
            account_id=account_id,
            recipe=recipe,
            image_mode=task_image_mode,
            task_params=task_params,
        )
    except Exception as _e:
        log.warning("[pipeline] publish_outcome 记录失败 (non-fatal): %s", _e)

    notify(f"发布成功: {drama_name}",
           f"account_id={account_id}\nphoto_id={photo_id}\nurl={share_url}",
           level="info", source="pipeline",
           extra={"task_id": task_id, "photo_id": photo_id})
    return {"ok": True, "final_status": "success",
            "photo_id": photo_id, "share_url": share_url}
