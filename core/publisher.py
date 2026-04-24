# -*- coding: utf-8 -*-
"""Kuaishou video publisher via HTTP API.

Implements the full publish flow captured from real HTTP requests:
MCN verify -> sig3 -> upload_pre -> fragments -> complete -> finish -> relation -> submit
"""

import json
import logging
import os
import time
from typing import Optional

import requests
# 关键: curl-cffi 用 Chrome 120 TLS 指纹 + 自己序列化 body (ensure_ascii=False)
# 2026-04-18 反向确认: cp.kuaishou.com 端点做 JA3 指纹检测, 且 sig3 严格按
# base64(ensure_ascii=False) 生成 — 必须两头都 match 才能过 500002/10001.
from curl_cffi import requests as cr_requests
try:
    from curl_cffi import CurlMime
except ImportError:
    CurlMime = None

from core.cookie_manager import CookieManager
from core.mcn_client import MCNClient
from core.sig_service import SigService

log = logging.getLogger(__name__)

# Upload constants
FRAGMENT_SIZE = 4 * 1024 * 1024  # 4 MB per fragment
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Kuaishou CP base
CP_BASE = "https://cp.kuaishou.com/rest/cp/works/v2/video/pc"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://cp.kuaishou.com",
    "Referer": "https://cp.kuaishou.com/",
    "Content-Type": "application/json",
}


class KuaishouPublisher:
    """Publish videos to Kuaishou via the CP HTTP API.

    Uses captured HTTP request patterns to replicate the browser-based
    publish workflow end-to-end.
    """

    def __init__(
        self,
        cookie_manager: CookieManager,
        sig_service: SigService,
        mcn_client: MCNClient,
        db_manager,
    ):
        """
        Parameters
        ----------
        cookie_manager : CookieManager
            Manages cookie retrieval and validation for accounts.
        sig_service : SigService
            Generates ``__NS_sig3`` signatures for API requests.
        mcn_client : MCNClient
            MCN verification and account management.
        db_manager : DBManager
            Database access for account data and publish records.
        """
        self.cookie_mgr = cookie_manager
        self.sig_svc = sig_service
        self.mcn = mcn_client
        self.db = db_manager
        # curl-cffi Chrome 120 TLS 指纹 — 绕过快手 cp.kuaishou.com JA3 检测
        self._sess = cr_requests.Session(impersonate="chrome120")

    def _post_signed(self, url: str, payload: dict, *,
                     extra_headers: dict | None = None,
                     cookie_str: str = "", timeout: int = 30):
        """统一的 sig3 POST:
         - sig 签 payload (ensure_ascii=False)
         - body 也用 ensure_ascii=False 序列化, 字节级跟 sig 输入一致.
         - 自动带 Cookie + Content-Type + curl-cffi Chrome TLS.
        """
        sig = self.sig_svc.sign_payload(payload)
        sep = "&" if "?" in url else "?"
        full_url = f"{url}{sep}__NS_sig3={sig}"
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "User-Agent": _DEFAULT_HEADERS["User-Agent"],
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://cp.kuaishou.com",
            "Referer": "https://cp.kuaishou.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if cookie_str:
            headers["Cookie"] = cookie_str
        if extra_headers:
            headers.update(extra_headers)
        return self._sess.post(full_url, data=body_bytes,
                               headers=headers, timeout=timeout)

    # ==================================================================
    # Public API
    # ==================================================================

    def publish_video(
        self,
        account_id: int,
        video_path: str,
        drama_name: str,
        caption: Optional[str] = None,
        is_private: bool = False,
        chapters: list | None = None,
        *,
        task_queue_id: str = "",
        batch_id: str = "",
        input_asset_id: str = "",
        cover_path_override: Optional[str] = None,
    ) -> dict:
        """Execute the full video publish flow for one account.

        Parameters
        ----------
        account_id : int
            Database ID (device_accounts.id) of the target account.
        video_path : str
            Local path to the video file to upload.
        drama_name : str
            Drama/series name for banner task association.
        caption : str, optional
            Post caption. Defaults to ``"{drama_name} #快来看短剧"``.
        is_private : bool
            If ``True``, set ``photoStatus=1`` (private). Default public.
        chapters : list, optional
            multi_segment chapters payload.  Empty = single-segment post.
        task_queue_id, batch_id, input_asset_id : str
            Trace fields — joined back to task_queue / media_assets from
            the publish_results row so Analysis/Threshold agents can
            reconstruct the full pipeline lineage.

        Returns
        -------
        dict
            ``{success: bool, photo_id: str|None, message: str}``
        """
        # UI "使用短剧名称+话题标签模式" + "话题标签" — 默认 caption 构造
        from core.app_config import get as _cfg_get

        def _b_cfg(key: str, default: bool) -> bool:
            """bool-coerced app_config read (避免 str '0'/'false' 被 bool() 当真)."""
            v = _cfg_get(key, default)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "on")
            return bool(v)

        if caption is None:
            tag_mode = _cfg_get("publisher.use_drama_hashtag_mode", True)
            default_tag = str(_cfg_get("publisher.default_hashtag", "#快来看短剧") or "").strip()
            tpl = str(_cfg_get("publisher.description_template", "") or "").strip()
            if tpl:
                caption = tpl.replace("{drama}", drama_name).replace("{tag}", default_tag)
            elif tag_mode:
                caption = f"{drama_name} {default_tag}".strip()
            else:
                caption = drama_name

        # UI "禁用时间段" 守门 (quiet_hours)
        try:
            if _cfg_get("publisher.quiet_hours.enabled", False):
                from datetime import datetime as _dt
                h0 = int(_cfg_get("publisher.quiet_hours.start_hour", 0))
                h1 = int(_cfg_get("publisher.quiet_hours.end_hour", 6))
                now_h = _dt.now().hour
                # 支持跨零点 (如 22→6)
                in_quiet = (h0 <= now_h < h1) if h0 <= h1 else (now_h >= h0 or now_h < h1)
                if in_quiet:
                    msg = f"publisher quiet_hours active ({h0}-{h1}, now={now_h})"
                    log.warning("[Publisher] 禁用时间段内 拒绝发布: %s", msg)
                    return {"success": False, "photo_id": None, "message": msg,
                             "deferred": True}
        except Exception as _e:
            log.warning("[Publisher] quiet_hours check 异常 忽略: %s", _e)

        log.info(
            "[Publisher] Starting publish: account=%s video=%s drama=%s",
            account_id, os.path.basename(video_path), drama_name,
        )

        # trace 字段统一打包, 任何路径都带着它
        trace = {
            "task_queue_id": task_queue_id, "batch_id": batch_id,
            "input_asset_id": input_asset_id, "caption": caption,
        }
        # Step 6 会根据 CXT 分支决策覆盖为 "chengxing"; 早期 except 仍记 "api"
        channel_type = "api"

        # Validate video file
        if not os.path.isfile(video_path):
            msg = f"Video not found: {video_path}"
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type="api", publish_status="failed",
                failure_reason=msg, **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}

        file_size = os.path.getsize(video_path)
        file_name = os.path.basename(video_path)

        if file_size == 0:
            msg = "Video file is empty"
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type="api", publish_status="failed",
                failure_reason=msg, **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}

        # cp.kuaishou.com cookies live under ``creator_cookie``, not ``cookies[]``.
        cookie_str = self.cookie_mgr.get_cookie_string(account_id, domain="cp")
        if not cookie_str:
            msg = "No cp cookie for account"
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type="api", publish_status="failed",
                failure_reason=msg, **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}

        api_ph = self.cookie_mgr.get_api_ph(account_id)
        if not api_ph:
            msg = "No api_ph in cookies"
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type="api", publish_status="failed",
                failure_reason=msg, **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}

        try:
            # Step 1: upload/pre — sig3 over {uploadType, api_ph}
            log.info("[Publisher] Step 1/8: upload/pre")
            pre_sig = self.sig_svc.sign_payload({
                "uploadType": 1,
                "kuaishou.web.cp.api_ph": api_ph,
            })
            pre_result = self._upload_pre(api_ph, pre_sig, cookie_str)
            token = pre_result["token"]
            file_id = pre_result["fileId"]
            endpoint = pre_result["endpoints"][0]

            # Step 2: upload fragments (no sig3 needed; goes to upload.kuaishouzt.com)
            log.info("[Publisher] Step 2/8: upload fragments (%d bytes)", file_size)
            fragment_count = self._upload_fragments(
                video_path, token, endpoint, cookie_str=cookie_str,
            )
            log.info("[Publisher] Uploaded %d fragments", fragment_count)

            # Step 3: upload/complete
            log.info("[Publisher] Step 3/8: upload/complete")
            if not self._upload_complete(token, fragment_count, endpoint):
                msg = "Upload complete failed"
                self._record_publish_result(
                    account_id=account_id, drama_name=drama_name,
                    channel_type="api", publish_status="failed",
                    failure_reason=msg, **trace,
                )
                return {"success": False, "photo_id": None, "message": msg}

            # Step 4: upload/finish — sig3 over **全 5 字段** body
            # Frida 2026-04-18 确认: sig 跟 POST body 必须一致, 否则 500002.
            # KS184 log 显示 complete 后 "等待服务器处理分片合并 (5秒)"; 服务端 upload
            # 集群到 cp 集群同步有时超过 5s, 延长到 12s 避免 10001 "文件不存在".
            log.info("[Publisher] Waiting 12s for upload cluster → cp cluster sync...")
            time.sleep(12)
            log.info("[Publisher] Step 4/8: upload/finish")
            # Normalize fileName to ASCII-safe KS184 format (non-ASCII → 500002)
            import re as _re, secrets as _sc
            safe_file_name = file_name
            if not _re.match(r'^[A-Za-z0-9_.\-]+$', file_name):
                safe_file_name = (f"video_{_sc.token_hex(4)}_"
                                  f"{time.strftime('%Y%m%d_%H%M%S')}_processed.mp4")
            finish_body = {
                "token": token,
                "fileName": safe_file_name,
                "fileType": "video/mp4",
                "fileLength": file_size,
                "kuaishou.web.cp.api_ph": api_ph,
            }
            finish_sig = self.sig_svc.sign_payload(finish_body)
            finish_info = self._upload_finish(
                api_ph, finish_sig, cookie_str, token,
                safe_file_name, file_size, body_override=finish_body,
            )

            # Step 5: 上传封面 (优先用 pipeline 烧好水印的; 无则从视频抽帧) -> 拿新 coverKey
            # Frida 2026-04-18 验证: 必须独立 POST cover/edit/cover/upload (multipart),
            # 用返回的新 coverKey 提交, 不能用 finish 返回的 auto-gen coverKey.
            log.info("[Publisher] Step 5/8: upload cover%s",
                     " (with watermark)" if cover_path_override else "")
            custom_cover_key = self._upload_cover(
                api_ph, cookie_str, video_path,
                cover_override=cover_path_override,
            )
            if custom_cover_key:
                finish_info["coverKey"] = custom_cover_key

            # Step 6: banner/list OR CXT mount — sig3 over appropriate payload
            # ────────────────────────────────────────────────────────────
            # 分叉决策 (2026-04-21 C-6):
            #   publisher.chengxing.enabled=true + 账号已授权 → CXT 分支
            #   否则 → 默认 firefly/yingguang 分支 (历史行为)
            # ────────────────────────────────────────────────────────────
            cxt_enabled = _b_cfg("publisher.chengxing.enabled", False)
            channel_type = "api"            # 默认 firefly 渠道标签
            cxt_mount = None                 # CXT 挂载数据 (非空=走 CXT)

            if cxt_enabled:
                numeric_uid = self._get_numeric_uid_for_account(account_id)
                if not numeric_uid:
                    log.info(
                        "[Publisher] CXT enabled 但 account=%s 无 numeric_uid, "
                        "回退 firefly", account_id,
                    )
                else:
                    can_cxt, auth_code, reason = self._check_chengxing_permission(numeric_uid)
                    if can_cxt:
                        log.info(
                            "[Publisher] Step 6/8: CXT mount (auth_code=%s reason=%s)",
                            auth_code, reason or "ok",
                        )
                        cxt_mount = self._get_chengxing_mount(drama_name, auth_code)
                        channel_type = "chengxing"
                    else:
                        log.info(
                            "[Publisher] CXT rejected for account=%s uid=%s: %s — "
                            "回退 firefly", account_id, numeric_uid, reason,
                        )

            if cxt_mount:
                # CXT 分支: 不调 /relation/banner/list (这个是 yingguang 端点)
                # 构造 xinghuo shape bannerTask (bindId+taskId 代替 bannerTaskId)
                banner_task = {
                    "bindId": cxt_mount.get("cxt_bind_id", ""),
                    "taskId": cxt_mount.get("cxt_task_id", ""),
                    "entranceType": int(cxt_mount.get("entranceType", 4)),
                    "bindType": int(cxt_mount.get("bindType", 4)),
                    "taskType": cxt_mount.get("taskType", "PLC"),
                    "title": drama_name,
                    "authCode": cxt_mount.get("authCode", ""),
                    "chengxingCode": cxt_mount.get("chengxing_code", ""),
                }
            else:
                # ★ 2026-04-22 §26.16-20: 我们业务只做**萤光 CPS** (§2 铁证: TOP 1000 earning
                # tasks 全是 promotion_type=None 老萤光). 所以默认 drama_type='firefly',
                # 直接走 /relation/banner/list → mcn_drama_lookup → DEFAULT 170767 fallback,
                # **不调** /relation/list (xinghuo 是代码储备, 当前业务不需要).
                #
                # 若未来切星火, 只改 config publisher.default_drama_type='xinghuo' 即可.
                from core.app_config import get as _cfg_get
                drama_type = str(_cfg_get("publisher.default_drama_type", "firefly") or "firefly").lower()
                log.info("[Publisher] Step 6/8: get_drama_task(drama_type=%s) for '%s'",
                          drama_type, drama_name)
                banner_task = self.get_drama_task(
                    drama_name, api_ph, cookie_str, drama_type=drama_type,
                )
                if not banner_task:
                    log.warning("[Publisher] no drama_task for '%s' "
                                "→ DEFAULT_FIREFLY_BANNER fallback", drama_name)
                    banner_task = dict(self.DEFAULT_FIREFLY_BANNER)

            # Step 7/8: submit — sig3 over **全 42 字段 body**
            # Frida 2026-04-18 确认: submit sig 签的是完整 body, 不是 {fileId, coverKey}.
            log.info("[Publisher] Step 7/8: submit (channel=%s)", channel_type)
            submit_body = self._build_submit_payload(
                api_ph, finish_info, caption, banner_task, is_private, chapters,
            )
            submit_sig = self.sig_svc.sign_payload(submit_body)
            submit_result = self._submit(
                api_ph, submit_sig, cookie_str, finish_info, caption, banner_task,
                is_private, chapters, body_override=submit_body,
            )

            # ─── Canonical (Frida 2026-04-19): ───────────────────────────
            # photoIdStr 来自 /upload/finish 的响应 data, 不是 submit.
            # KS184 发布成功时 submit 响应是: {result:1, data:{}, message:"成功"}
            # data={} 是**正常的**, 不代表失败. 之前把 "无 photo_id" 当 fake success
            # 判失败是误判 — 真正的 success 应该:
            #   1. finish_info 里有 photoIdStr (视频真被快手收录)
            #   2. submit result == 1 (作品提交被接受)
            # ─────────────────────────────────────────────────────────────
            photo_id = finish_info.get("photoIdStr") or finish_info.get("photoId")
            submit_ok = submit_result.get("result") == 1

            if not photo_id:
                # finish 阶段没拿到 photoIdStr = 视频根本没进快手
                msg = (f"upload/finish 没返回 photoIdStr — 视频未被快手收录. "
                       f"finish_info keys={list(finish_info.keys())} "
                       f"finish_info={str(finish_info)[:300]}")
                log.error("[Publisher] FINISH_NO_PHOTO_ID: %s", msg)
                self._record_publish_result(
                    account_id=account_id, drama_name=drama_name,
                    banner_task=banner_task, file_name=file_name,
                    finish_info=finish_info,
                    channel_type=channel_type,
                    publish_status="failed",
                    failure_reason=f"finish_no_photo_id: {msg[:200]}",
                    **trace,
                )
                return {"success": False, "photo_id": None,
                        "message": msg, "finish_info": finish_info}

            if not submit_ok:
                # finish 拿到了 photo_id 但 submit 被拒
                result_code = submit_result.get("result")
                msg = (f"submit result={result_code} "
                       f"message={submit_result.get('message', '')} — "
                       f"视频已上传但提交被拒. submit_raw={str(submit_result)[:300]}")
                log.error("[Publisher] SUBMIT_REJECTED: %s", msg)

                # ★ 2026-04-24 v6 Day 7: 80004 "无作者变现权限" → 加入 (account, drama) blacklist
                # 避免 planner 下次重排同组合导致 5-15 min pipeline 浪费
                # 必须在 record_publish_result 之前 (blacklist 是业务事实, 记录是流水)
                try:
                    raw_str = str(submit_result)
                    is_80004 = (
                        result_code == 80004
                        or "80004" in raw_str
                        or "无作者变现" in raw_str
                        or "变现权限" in raw_str
                    )
                    if is_80004:
                        from core.account_drama_blacklist import add_to_blacklist
                        r = add_to_blacklist(
                            account_id=account_id, drama_name=drama_name,
                            reason="auth_80004", source="publisher",
                            metadata={
                                "photo_id": str(photo_id),
                                "result_code": result_code,
                                "message": submit_result.get("message", "")[:200],
                            },
                        )
                        log.warning("[Publisher] 80004 → blacklist: acct=%s drama=%s action=%s cd=%dh",
                                    account_id, drama_name, r.get("action"),
                                    r.get("cooldown_hours", 72))
                except Exception as _e:
                    log.exception("[Publisher] blacklist write failed: %s", _e)

                self._record_publish_result(
                    account_id=account_id, drama_name=drama_name,
                    photo_id=str(photo_id),
                    banner_task=banner_task, file_name=file_name,
                    finish_info=finish_info,
                    channel_type=channel_type,
                    publish_status="failed",
                    failure_reason=f"submit_rejected: {msg[:200]}",
                    **trace,
                )
                return {"success": False, "photo_id": str(photo_id),
                        "message": msg, "submit_raw": submit_result}

            log.info(
                "[Publisher] Publish complete: account=%s photo_id=%s submit_ok=True",
                account_id, photo_id,
            )
            result = {
                "success": True,
                "photo_id": str(photo_id),
                "message": "Published successfully",
            }
            # Write publish_results row (Phase 1 requirement)
            share_url = self._build_share_url(result["photo_id"])
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                photo_id=result["photo_id"],
                share_url=share_url,
                banner_task=banner_task, file_name=file_name,
                finish_info=finish_info,
                channel_type=channel_type,
                publish_status="success",
                failure_reason="",
                **trace,
            )
            result["share_url"] = share_url
            return result

        except requests.RequestException as exc:
            msg = f"Network error: {exc}"
            log.error("[Publisher] %s", msg)
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type=channel_type, publish_status="failed", failure_reason=msg,
                **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}
        except (KeyError, ValueError, TypeError) as exc:
            msg = f"Data error: {exc}"
            log.error("[Publisher] %s", msg)
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type=channel_type, publish_status="failed", failure_reason=msg,
                **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}
        except Exception as exc:
            msg = f"Unexpected error: {exc}"
            log.error("[Publisher] %s", msg, exc_info=True)
            self._record_publish_result(
                account_id=account_id, drama_name=drama_name,
                channel_type=channel_type, publish_status="failed", failure_reason=msg,
                **trace,
            )
            return {"success": False, "photo_id": None, "message": msg}

    @staticmethod
    def _build_share_url(photo_id: str | None) -> str:
        """从 photo_id 拼分享 URL. VerifyAgent 后续查 CP API 可以覆盖为
        Kuaishou 真实返回的 short link, 这里只做 best-effort."""
        if not photo_id:
            return ""
        return f"https://v.kuaishou.com/{photo_id}"

    # ------------------------------------------------------------------
    # publish_results writer
    # ------------------------------------------------------------------

    def _record_publish_result(
        self, *,
        account_id: int,
        drama_name: str,
        caption: str = "",
        channel_type: str = "api",
        publish_status: str = "pending",
        failure_reason: str = "",
        photo_id: str | None = None,
        share_url: str = "",
        banner_task: dict | None = None,
        file_name: str = "",
        finish_info: dict | None = None,
        # 可追溯性
        task_queue_id: str = "",
        batch_id: str = "",
        input_asset_id: str = "",
    ) -> int | None:
        """Persist every publish attempt outcome to ``publish_results`` table.

        Non-fatal: errors here never break the actual publish flow.
        Returns the new row id on success, None on error.
        """
        if self.db is None:
            return None
        try:
            banner_id = (banner_task or {}).get("bannerTaskId", "")
            # verify_status: 成功后 pending 等 VerifyAgent 去 CP API 查实
            #                失败直接 unverified, 没东西可查
            verify_status = "pending" if publish_status == "success" else "unverified"

            cur = self.db.conn.execute(
                """INSERT INTO publish_results
                     (task_queue_id, batch_id, account_id, device_serial,
                      channel_type, drama_name,
                      input_asset_id, output_asset_id,
                      caption, photo_id, share_url, banner_task_id,
                      publish_status, verify_status, failure_reason,
                      published_at, created_at, updated_at)
                   VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           CASE WHEN ?='success' THEN datetime('now','localtime') ELSE NULL END,
                           datetime('now','localtime'),
                           datetime('now','localtime'))""",
                (
                    task_queue_id, batch_id,
                    str(account_id),
                    channel_type, drama_name,
                    input_asset_id, file_name or "",
                    caption, photo_id or "", share_url, str(banner_id),
                    publish_status, verify_status, failure_reason,
                    publish_status,
                ),
            )
            self.db.conn.commit()
            row_id = cur.lastrowid
            log.info(
                "[Publisher] publish_results #%s: acct=%s drama=%s status=%s photo_id=%s",
                row_id, account_id, drama_name, publish_status, photo_id or "-",
            )
            # system_events 埋点
            try:
                from core.event_bus import emit_event
                et = "publish.success" if publish_status == "success" else "publish.failed"
                emit_event(
                    et,
                    entity_type="account", entity_id=str(account_id),
                    payload={
                        "drama": drama_name, "photo_id": photo_id or "",
                        "channel": channel_type,
                        "failure_reason": failure_reason if publish_status != "success" else "",
                        "task_queue_id": task_queue_id,
                    },
                    level="info" if publish_status == "success" else "warn",
                    source_module="publisher",
                )
            except Exception:
                pass
            return row_id
        except Exception as exc:
            log.warning("[Publisher] _record_publish_result failed: %s", exc)
            return None

    # ==================================================================
    # Internal steps
    # ==================================================================

    def _make_headers(self, cookie_str: str) -> dict:
        """Build HTTP headers with the given cookie string.

        Returns
        -------
        dict
            Headers dict suitable for Kuaishou CP API requests.
        """
        headers = dict(_DEFAULT_HEADERS)
        headers["Cookie"] = cookie_str
        return headers

    def _upload_pre(self, api_ph: str, sig3: str, cookie_str: str) -> dict:
        """Request upload credentials from Kuaishou.

        sig3 is ignored here — we use _post_signed which signs+posts atomically
        to guarantee sig and body are byte-identical.
        """
        payload = {"uploadType": 1, "kuaishou.web.cp.api_ph": api_ph}
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_signed(f"{CP_BASE}/upload/pre",
                                         payload, cookie_str=cookie_str, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if data.get("result") != 1:
                    raise RuntimeError(f"upload_pre result={data.get('result')}: {data}")
                inner = data["data"]
                log.debug("[Publisher] upload_pre OK: fileId=%s endpoints=%s",
                          inner["fileId"], inner["endPoints"])
                return {"token": inner["token"], "fileId": inner["fileId"],
                        "endpoints": inner["endPoints"]}
            except Exception as exc:
                log.warning("[Publisher] upload_pre attempt %d/%d failed: %s",
                            attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_DELAY * attempt)

    def _upload_fragments(self, video_path: str, token: str, endpoint: str,
                          cookie_str: str = "",
                          threads: int | None = None) -> int:
        """Upload the video file in ~4 MB fragments — 8-thread concurrent.

        ★ 2026-04-22 §26.16 (ks184 source): KS184 源码证实
          `UPLOAD_THREADS = 8` + `_upload_video` 用 ThreadPoolExecutor 并发.
          我们原版单线程顺序上传, 对 65-片 (260MB) 视频需 6-10 分钟.
          8 线程并发后 ~50-80 秒完成 → 发布总时长 12:51 → ~6 分钟.

        POST ``https://{endpoint}/api/upload/fragment``

        Returns total fragment count, raises on failure.
        """
        # 并发度 — config 可调, 默认 8 对齐 KS184
        if threads is None:
            from core.app_config import get as _cfg_get
            threads = int(_cfg_get("publisher.upload_threads", 8))
        threads = max(1, min(threads, 16))  # 夹到 [1, 16]

        frag_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/octet-stream",
            "Origin": "https://cp.kuaishou.com",
            "Referer": "https://cp.kuaishou.com/",
        }
        if cookie_str:
            frag_headers["Cookie"] = cookie_str

        # 1. 先读全部分片到内存 (对 260MB 视频 OK, 内存开销 <300MB)
        chunks: list[tuple[int, bytes]] = []
        idx = 0
        with open(video_path, "rb") as fh:
            while True:
                chunk = fh.read(FRAGMENT_SIZE)
                if not chunk: break
                chunks.append((idx, chunk))
                idx += 1
        total = len(chunks)
        log.info("[Publisher] prepared %d fragments, uploading with %d threads",
                  total, threads)

        def _upload_one(chunk_idx: int, chunk_data: bytes) -> tuple[int, bool, str]:
            """单片上传, 带重试. 返回 (idx, ok, err_msg)."""
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    frag_url = (
                        f"https://{endpoint}/api/upload/fragment"
                        f"?upload_token={token}&fragment_id={chunk_idx}"
                    )
                    resp = self._sess.post(
                        frag_url, data=chunk_data, headers=frag_headers,
                        timeout=120,
                    )
                    resp.raise_for_status()
                    if resp.content:
                        try:
                            result = resp.json()
                            if result.get("result") not in (1, None):
                                raise RuntimeError(
                                    f"Fragment {chunk_idx} upload error: {result}"
                                )
                        except ValueError:
                            pass  # 非 JSON 响应, 200 就认 OK
                    return (chunk_idx, True, "")
                except Exception as exc:
                    if attempt == MAX_RETRIES:
                        return (chunk_idx, False, str(exc))
                    time.sleep(RETRY_DELAY * attempt)
            return (chunk_idx, False, "max_retries")

        # 2. ThreadPoolExecutor 并发上传
        from concurrent.futures import ThreadPoolExecutor, as_completed
        succeeded: set[int] = set()
        failures: list[tuple[int, str]] = []
        with ThreadPoolExecutor(max_workers=threads,
                                 thread_name_prefix="ks-upload") as ex:
            futures = {ex.submit(_upload_one, ci, cd): ci
                       for ci, cd in chunks}
            done = 0
            for fut in as_completed(futures):
                done += 1
                ci, ok, err = fut.result()
                if ok:
                    succeeded.add(ci)
                else:
                    failures.append((ci, err))
                if done % 10 == 0 or done == total:
                    log.info("[Publisher] upload progress %d/%d ok",
                              len(succeeded), total)

        if failures:
            # 对齐 KS184: 失败就整个重申 token 从头来. 这里抛出让上层决定.
            first_err = failures[0]
            raise RuntimeError(
                f"Fragment upload failed {len(failures)}/{total}: "
                f"idx={first_err[0]} err={first_err[1][:120]}"
            )

        log.info("[Publisher] All %d fragments uploaded (concurrent x%d)",
                  total, threads)
        return total

    def _upload_complete(self, token: str, fragment_count: int, endpoint: str) -> bool:
        """Signal that all fragments have been uploaded.

        POST ``https://{endpoint}/api/upload/complete?fragment_count=N&upload_token=TOKEN``

        Returns
        -------
        bool
            ``True`` if server acknowledged the complete signal.
        """
        url = (
            f"https://{endpoint}/api/upload/complete"
            f"?fragment_count={fragment_count}&upload_token={token}"
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._sess.post(url, timeout=30)
                resp.raise_for_status()
                # 新行为兼容: 200 空 body = 成功
                if not resp.content:
                    log.debug("[Publisher] upload_complete OK (200 empty body)")
                    return True
                try:
                    data = resp.json()
                    if data.get("result") in (1, None):
                        log.debug("[Publisher] upload_complete OK")
                        return True
                    log.warning("[Publisher] upload_complete unexpected result: %s", data)
                    return False
                except requests.exceptions.JSONDecodeError:
                    # 非 JSON body — 200 就算成功
                    log.debug("[Publisher] upload_complete non-JSON body: %r",
                              resp.text[:80])
                    return True
            except Exception as exc:
                log.warning("[Publisher] upload_complete attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_DELAY * attempt)

        return False

    def _upload_finish(
        self,
        api_ph: str,
        sig3: str,
        cookie_str: str,
        token: str,
        filename: str,
        filesize: int,
        body_override: dict | None = None,
    ) -> dict:
        """Notify Kuaishou that the upload is finished and get media metadata.

        POST ``/upload/finish?__NS_sig3={sig3}``

        Returns
        -------
        dict
            Contains ``fileId``, ``duration``, ``coverKey``, ``width``,
            ``height``, ``mediaId``, ``photoIdStr``, ``videoDuration``.

        Raises
        ------
        RuntimeError
            If the API does not return ``result == 1``.
        """
        # body_override 优先 — 外部已构建好 body, 这里统一走 _post_signed 保证
        # sig+body 字节级一致 (ensure_ascii=False + Chrome TLS).
        if body_override is not None:
            payload = body_override
        else:
            payload = {
                "token": token, "fileName": filename, "fileType": "video/mp4",
                "fileLength": filesize, "kuaishou.web.cp.api_ph": api_ph,
            }

        RETRYABLE_BUSINESS_RESULTS = {500002, 500003, 500004, 500005}
        BUSINESS_BACKOFF = [3, 6, 10, 15, 25]

        for attempt in range(1, 1 + len(BUSINESS_BACKOFF) + 1):
            try:
                resp = self._post_signed(
                    f"{CP_BASE}/upload/finish", payload,
                    cookie_str=cookie_str, timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                result_code = data.get("result")
                if result_code == 1:
                    inner = data["data"]
                    log.info(
                        "[Publisher] upload_finish OK: mediaId=%s duration=%s",
                        inner.get("mediaId"), inner.get("videoDuration"),
                    )
                    return inner

                # 业务级可重试错误
                if result_code in RETRYABLE_BUSINESS_RESULTS and attempt <= len(BUSINESS_BACKOFF):
                    wait = BUSINESS_BACKOFF[attempt - 1]
                    log.warning(
                        "[Publisher] upload_finish result=%s (%s) — retry in %ds (attempt %d)",
                        result_code, data.get("message", ""), wait, attempt,
                    )
                    time.sleep(wait)
                    continue

                raise RuntimeError(f"upload_finish result={result_code}: {data}")
            except Exception as exc:
                log.warning("[Publisher] upload_finish net err attempt %d: %s", attempt, exc)
                if attempt >= MAX_RETRIES:
                    raise
                time.sleep(RETRY_DELAY * attempt)

    # Default firefly banner task used when the API returns no match.
    # KS184 captured behavior: when banner/list returns empty, the original
    # software **constructs** a banner task object rather than giving up.
    # The numeric id ``169570`` is the firefly-plan generic placeholder as
    # observed in the publish trace on 2026-04-17 (pid=31308 Frida session).
    # This is NOT looked up — it is synthesized to signal "intent to hook
    # a firefly CPS cover" even when the drama has no registered task.
    # 2026-04-19 update: 原来是 169570 (财源滚滚小厨神 老废弃任务, 近 30 天仅 ¥19).
    # 换成 170767 — 同剧名另一个 biz_id, 近 30 天 ¥332, 74 条分佣记录, 活跃中.
    # 只在极罕见"drama 找不到 taskId + banner/list API 没命中"时 fall 到这里.
    DEFAULT_FIREFLY_BANNER = {
        "bannerTaskId": "170767",
        "entranceType": 10,
        "bindTaskType": "1",
        "canParticipate": True,
        "startTime": "",
        "endTime": "",
    }

    def _lookup_cached_banner_task(self, drama_name: str) -> dict | None:
        """Try to find a cached bannerTaskId for this drama in ``drama_banner_tasks``.

        Returns a fully-shaped banner task dict or None.
        """
        if self.db is None:
            return None
        try:
            row = self.db.conn.execute(
                """SELECT banner_task_id, entrance_type, bind_task_type
                   FROM drama_banner_tasks WHERE drama_name = ?""",
                (drama_name,),
            ).fetchone()
        except Exception as exc:
            log.debug("[Publisher] banner-cache lookup failed: %s", exc)
            return None
        if not row:
            return None
        task_id, entrance_type, bind_task_type = row[0], row[1], row[2]
        log.info("[Publisher] banner-cache HIT: '%s' -> %s", drama_name, task_id)
        return {
            "bannerTaskId": str(task_id),
            "entranceType": int(entrance_type or 10),
            "bindTaskType": str(bind_task_type or "1"),
            "canParticipate": True,
            "startTime": "",
            "endTime": "",
        }

    def _remember_banner_task(self, drama_name: str, banner_task: dict) -> None:
        """Persist a (drama_name, bannerTaskId) pair into cache for next time."""
        if self.db is None or not banner_task.get("bannerTaskId"):
            return
        try:
            self.db.conn.execute(
                """INSERT INTO drama_banner_tasks
                    (drama_name, banner_task_id, entrance_type, bind_task_type,
                     source, first_seen_at, last_seen_at, hit_count)
                   VALUES (?, ?, ?, ?, 'publisher', datetime('now','localtime'),
                           datetime('now','localtime'), 1)
                   ON CONFLICT(drama_name) DO UPDATE SET
                     last_seen_at = datetime('now','localtime'),
                     hit_count = hit_count + 1,
                     banner_task_id = excluded.banner_task_id""",
                (
                    drama_name,
                    str(banner_task["bannerTaskId"]),
                    int(banner_task.get("entranceType", 10)),
                    str(banner_task.get("bindTaskType", "1")),
                ),
            )
            self.db.conn.commit()
        except Exception as exc:
            log.debug("[Publisher] banner-cache write failed: %s", exc)

    def _get_banner_task(
        self,
        api_ph: str,
        sig3: str,
        cookie_str: str,
        drama_name: str,
        plan_mode: str = "firefly",
    ) -> dict:
        """Look up (or synthesize) the banner/relation task for a drama.

        Resolution order (KS184-aligned, verified Frida 2026-04-21 §23):
          1. ⭐ MCN MySQL live (主路, spark_drama_info 实时, business_type=0 过滤)
          2. Local ``drama_banner_tasks`` cache (备份, MCN 宕机时用)
          3. Kuaishou CP banner/list API (礼节性调用, 对齐 KS184 — KS184 实测 12/12 返空)
          4. ``DEFAULT_FIREFLY_BANNER`` fallback (无 firefly 绑定时)

        KS184 7-Layer Frida 铁证 (§23.2 #3): banner/list 100% 返空,
        KS184 每条剧的 bannerTaskId 都来自本地 drama→biz_id 映射表.
        我们对齐: MCN live → local backup → API (仅对齐行为, 不依赖).

        Returns
        -------
        dict
            ``{bannerTaskId, entranceType, bindTaskType, canParticipate,
               startTime, endTime}`` ready to drop into submit payload.
        """
        # 1. ⭐ MCN live lookup (主路) + 2. local backup fallback (内嵌在 lookup 模块)
        try:
            from core.mcn_drama_lookup import get_banner_by_drama
            info = get_banner_by_drama(drama_name)
            if info and info.get("banner_task_id"):
                log.info(
                    "[Publisher] banner from %s: '%s' -> %s (commission=%s)",
                    info.get("_source","?"), drama_name,
                    info["banner_task_id"], info.get("commission_rate"),
                )
                result = {
                    "bannerTaskId": str(info["banner_task_id"]),
                    "entranceType": 10,
                    "bindTaskType": "1",
                    "canParticipate": True,
                    "startTime": "",
                    "endTime": "",
                }
                # Warm local cache for next call (from MCN live hits)
                if info.get("_source") == "mcn_mysql":
                    try: self._remember_banner_task(drama_name, result)
                    except Exception: pass
                return result
        except Exception as e:
            log.warning("[Publisher] mcn_drama_lookup failed (falling through): %r", e)

        # 2b. Legacy local cache (if mcn_drama_lookup module missing)
        cached = self._lookup_cached_banner_task(drama_name)
        if cached:
            return cached

        # 3. Live API lookup — 走 _post_signed (curl-cffi + ensure_ascii=False)
        payload = {
            "type": 10, "title": drama_name, "cursor": "",
            "kuaishou.web.cp.api_ph": api_ph,
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_signed(
                    f"{CP_BASE}/relation/banner/list", payload,
                    cookie_str=cookie_str, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("result") != 1:
                    log.warning("[Publisher] banner_list result=%s: %s", data.get("result"), data)
                    break

                items = data.get("data", {}).get("list", [])
                if not items:
                    log.info(
                        "[Publisher] banner_list: no API match for '%s' — using fallback",
                        drama_name,
                    )
                    break

                task = items[0]
                result = {
                    "bannerTaskId": str(task.get("bannerTaskId", "")),
                    "entranceType": task.get("entranceType", 10),
                    "bindTaskType": str(task.get("bindTaskType", "1")),
                    "canParticipate": task.get("canParticipate", True),
                    "startTime": task.get("startTime", ""),
                    "endTime": task.get("endTime", ""),
                }
                log.info("[Publisher] banner_list API hit: taskId=%s", result["bannerTaskId"])
                self._remember_banner_task(drama_name, result)  # cache for next time
                return result
            except Exception as exc:
                log.warning("[Publisher] banner_list attempt %d/%d failed: %s",
                            attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    log.warning("[Publisher] banner_list unreachable, using fallback")
                    break
                time.sleep(RETRY_DELAY * attempt)

        # 3. Fallback — generic firefly placeholder.
        return dict(self.DEFAULT_FIREFLY_BANNER)

    def search_xinghuo_task(self,
                              drama_name: str,
                              api_ph: str,
                              cookie_str: str,
                              max_pages: int = 10,
                              ) -> dict | None:
        """搜星火计划任务 (KS184 `search_drama_task(task_type='xinghuo')` 对齐).

        ★ 2026-04-22 §26.16 源码对齐:
          yingguang (萤光): POST /rest/cp/works/v2/video/pc/relation/banner/list  (type=10)
          xinghuo  (星火): POST /rest/cp/works/v2/video/pc/relation/list          ← 本函数!

        用于 C-8 80004 根因修复 (之前以为缺 auth, 真正缺的是 xinghuo /relation/list 搜剧).

        Returns
        -------
        dict | None
            成功: {"taskId", "bindId", "entranceType", "bindType", "taskType", "title"}
            未找到: None (调用方可 fallback firefly)
        """
        cursor = ""
        for page in range(1, max_pages + 1):
            # body 对齐 firefly 但字段不同 (type/title 仍在, 但 endpoint 不同)
            # 注意: relation/list 可能的字段 (从 ks_drama_api / kuaishou_creator_publisher
            #       search_drama_task 变量名推: data_str/sig3/response/tasks/task/title)
            payload = {
                "title": drama_name,
                "cursor": cursor,
                "count": 20,
                "kuaishou.web.cp.api_ph": api_ph,
            }
            try:
                resp = self._post_signed(
                    f"{CP_BASE}/relation/list", payload,
                    cookie_str=cookie_str, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("[Publisher/xinghuo] relation/list page=%d err: %s",
                             page, exc)
                return None

            if data.get("result") != 1:
                log.warning("[Publisher/xinghuo] relation/list result=%s: %s",
                             data.get("result"), str(data)[:200])
                return None

            tasks = (data.get("data") or {}).get("list", [])
            for task in tasks:
                # 匹配剧名 (title / drama_title / dramaName 都试)
                title = (task.get("title") or task.get("dramaName")
                         or task.get("drama_title") or "")
                if not title: continue
                if title == drama_name or drama_name in title or title in drama_name:
                    result = {
                        "taskId": str(task.get("taskId", "")),
                        "bindId": str(task.get("bindId", "")),
                        "entranceType": task.get("entranceType", 10),
                        "bindType": str(task.get("bindType", "1")),
                        "taskType": task.get("taskType", ""),
                        "title": title,
                    }
                    log.info("[Publisher/xinghuo] matched '%s' page=%d taskId=%s bindId=%s",
                              drama_name, page, result["taskId"], result["bindId"])
                    return result

            # 翻页
            cursor = (data.get("data") or {}).get("cursor", "")
            if not cursor or cursor == "no_more":
                break

        log.info("[Publisher/xinghuo] '%s' not found after %d pages",
                  drama_name, page)
        return None

    def get_drama_task(self,
                        drama_name: str,
                        api_ph: str,
                        cookie_str: str,
                        drama_type: str = "firefly",
                        ) -> dict | None:
        """统一剧任务查询 — 对齐 KS184 `search_drama_task(task_type=drama_type)`.

        ★ 2026-04-22 §26.20: 我们业务默认 drama_type='firefly' (萤光 CPS),
          因为 TOP 1000 earning tasks 全是 promotion_type=None 老萤光 (§2 铁证).
          xinghuo 作为代码储备, 需要时 config 切换.

        Args:
            drama_type: 'firefly'/'yingguang' (萤光, 默认) 或 'xinghuo' (星火, 储备).

        Returns:
            firefly shape: {bannerTaskId, entranceType, bindTaskType, canParticipate, startTime, endTime}
            xinghuo shape: {taskId, bindId, entranceType, bindType, taskType, title}
            找不到: None
        """
        dt = (drama_type or "firefly").lower()
        if dt in ("firefly", "yingguang", "ying"):
            # 萤光主路径: mcn_drama_lookup → banner/list → DEFAULT_FIREFLY_BANNER
            return self._get_banner_task(api_ph, "", cookie_str, drama_name,
                                           plan_mode="firefly")
        elif dt in ("xinghuo", "xh", "spark"):
            # 星火优先 → miss fallback firefly
            r = self.search_xinghuo_task(drama_name, api_ph, cookie_str)
            if r: return r
            log.info("[Publisher] xinghuo miss → fallback firefly for '%s'", drama_name)
            return self._get_banner_task(api_ph, "", cookie_str, drama_name,
                                           plan_mode="firefly")
        else:
            log.warning("[Publisher] unknown drama_type=%r → firefly", drama_type)
            return self._get_banner_task(api_ph, "", cookie_str, drama_name,
                                           plan_mode="firefly")

    # ────────────────────────────────────────────────────────────────
    # 橙星推 (CXT) — 独立分支 (对齐 KS184 _publish_chengxing @ 0x21c0e8a6840)
    # ────────────────────────────────────────────────────────────────

    def _get_numeric_uid_for_account(self, account_id: int) -> str:
        """读 device_accounts.numeric_uid (快手数字 uid, 关联 cxt_user / mcn_member_snapshots).

        Note: kuaishou_uid 是字符串 (3xmne9bjww75dt9), numeric_uid 是数字 (887329560).
        CXT auth 表 cxt_user.uid 存的是**数字**, 所以只认 numeric_uid.

        Returns ``""`` (空字符串) 如果 account_id 不存在或该列为 NULL.
        """
        if self.db is None:
            return ""
        try:
            row = self.db.conn.execute(
                "SELECT numeric_uid FROM device_accounts WHERE id = ? LIMIT 1",
                (int(account_id),),
            ).fetchone()
        except Exception as exc:
            log.warning("[Publisher/CXT] numeric_uid lookup failed for id=%s: %s",
                        account_id, exc)
            return ""
        if not row or row[0] in (None, "", 0):
            return ""
        return str(row[0])

    def _check_chengxing_permission(
        self,
        numeric_uid: int | str,
    ) -> tuple[bool, str, str]:
        """对齐 KS184 `_check_chengxing_permission @ 0x21c0e8a6740`.

        读 mirror_cxt_users 判断账号是否有橙星推发布资格.

        ★ Path A override (2026-04-21):
          如果配置了 `publisher.chengxing.owner_auth_code_override`,
          且账号不在 cxt_user 表 (account_not_in_cxt_user_table),
          则使用 override auth_code 作为共享身份凭证 (例如 'huanghuwei888').
          该 auth_code 在 cxt_user 里有 status=1 的关联条目 → 在快手侧 MCN
          中继转发时会被识别为同一工作室的挂载权证. 走这条只做 **发布侧**
          逻辑绕过, 不影响 MCN 上游的真实授权状态.

        Returns
        -------
        tuple
            (can_publish, auth_code, reason)
              can_publish=True 才能进入 _publish_chengxing 分支
              auth_code 是挂载参数之一 (必传)
              reason 失败时的人类可读原因; 如果 override 生效, 会返回
              ``"override:<auth_code>"`` 标识, 便于 Publisher 日志追踪.
        """
        if self.db is None:
            return (False, "", "db_unavailable")
        try:
            row = self.db.conn.execute(
                """SELECT status, auth_code FROM mirror_cxt_users
                   WHERE uid = ? LIMIT 1""",
                (str(numeric_uid),),
            ).fetchone()
        except Exception as exc:
            log.warning("[Publisher/CXT] permission check failed: %s", exc)
            return (False, "", f"db_error:{exc}")

        # ── Path A: override 解救 ──
        if not row:
            try:
                from core.app_config import get as cfg_get
                override = str(cfg_get(
                    "publisher.chengxing.owner_auth_code_override", ""
                ) or "").strip()
            except Exception:
                override = ""
            if override:
                # 校验 override 在 cxt_user 存在且有效 (status=1), 免得用错 code
                try:
                    vrow = self.db.conn.execute(
                        """SELECT COUNT(*) FROM mirror_cxt_users
                           WHERE auth_code = ? AND status = 1""",
                        (override,),
                    ).fetchone()
                    valid = bool(vrow and vrow[0] > 0)
                except Exception:
                    valid = False
                if valid:
                    log.info(
                        "[Publisher/CXT] override auth_code=%s (uid=%s 不在 cxt_user)",
                        override, numeric_uid,
                    )
                    return (True, override, f"override:{override}")
                else:
                    log.warning(
                        "[Publisher/CXT] override auth_code=%s 在 cxt_user 找不到 status=1 条目, 拒绝 override",
                        override,
                    )
            return (False, "", "account_not_in_cxt_user_table")

        status, auth_code = row[0], row[1]
        status = int(status or -1)
        # 对齐 MCN schema: 0=待审核, 1=通过, 2=禁用
        if status == 0:
            return (False, auth_code or "", "cxt_status=0 (待审核)")
        if status == 2:
            return (False, auth_code or "", "cxt_status=2 (禁用)")
        if status != 1:
            return (False, auth_code or "", f"cxt_status={status} (未知状态)")
        if not auth_code:
            return (False, "", "cxt_status=1 但 auth_code 为空")
        return (True, auth_code, "")

    def _get_chengxing_mount(
        self,
        drama_name: str,
        auth_code: str,
    ) -> dict:
        """橙星推挂载参数 (对齐 KS184, 完全不同于 firefly/spark 的 bannerTask).

        对齐 cxt_mount_links schema:
            bind_id / task_id / entrance_type=4 / bind_type=4 / task_type='PLC'

        Resolution order:
          1. Local cxt_mount_links (如已通过 UI 绑过, drama-level cache)
          2. Synthesize default (auth_code + 默认 entrance_type/bind_type)

        Returns
        -------
        dict
            ``{chengxing_code, cxt_bind_id, cxt_task_id, entranceType,
               bindType, taskType, authCode}`` ready for submit payload.
        """
        from core.app_config import get as cfg_get

        # 默认值 (from config, 对齐 v37)
        default_entrance_type = int(cfg_get("publisher.chengxing.default_entrance_type", 4))
        default_bind_type = int(cfg_get("publisher.chengxing.default_bind_type", 4))
        default_task_type = cfg_get("publisher.chengxing.default_task_type", "PLC")

        result = {
            "authCode": auth_code,
            "entranceType": default_entrance_type,
            "bindType": default_bind_type,
            "taskType": default_task_type,
            "cxt_bind_id": "",
            "cxt_task_id": "",
            "chengxing_code": "",
        }

        if self.db is None:
            return result

        # 1. cxt_mount_links 查缓存
        try:
            row = self.db.conn.execute(
                """SELECT bind_id, task_id, entrance_type, bind_type, task_type, share_link
                   FROM cxt_mount_links WHERE drama_name = ? LIMIT 1""",
                (drama_name,),
            ).fetchone()
        except Exception:
            row = None

        if row:
            bind_id, task_id, et, bt, tt, share_link = row
            result["cxt_bind_id"] = str(bind_id or "")
            result["cxt_task_id"] = str(task_id or "")
            result["entranceType"] = int(et or default_entrance_type)
            result["bindType"] = int(bt or default_bind_type)
            result["taskType"] = tt or default_task_type
            # 从 share_link 抽 code (play.html?code=XXX)
            if share_link:
                try:
                    from core.parsers.chengxing import extract_code
                    result["chengxing_code"] = extract_code(share_link) or ""
                except Exception:
                    pass
            log.info(
                "[Publisher/CXT] mount cache HIT: '%s' -> bind_id=%s",
                drama_name, bind_id,
            )
            return result

        # 2. 没缓存: 上游要么去 MCN 预绑 (_publish_chengxing 会报 "no bind_id")
        #    要么直接拿 auth_code 硬发 (PLC 默认入口)
        log.warning(
            "[Publisher/CXT] no cxt_mount_links row for '%s' - "
            "using auth_code-only fallback (no bind_id)",
            drama_name,
        )
        return result

    def _upload_cover(self, api_ph: str, cookie_str: str, video_path: str,
                       cover_override: str | None = None) -> str:
        """Step 5 (新增): 上传封面到快手 CP, 返回 coverKey.

        POST https://cp.kuaishou.com/rest/cp/works/v4/video/pc/cover/edit/cover/upload
        multipart/form-data:
          - kuaishou.web.cp.api_ph: <api_ph>
          - file: <jpeg bytes>

        Args:
            video_path: 源视频 (用于抽帧, 如果 cover_override 没给)
            cover_override: 外部提供的 cover 文件 (PNG/JPG). 给了 → 直接用 (跳过抽帧).
                            pipeline Stage 3.5 烧完水印后传进来.

        返回: 新 coverKey (如 "cp_video_upload_cover_xxxxxxxx.jpeg")
        失败时返回 "", 上游会 fallback 用 finish 的 coverKey.

        Frida trace 2026-04-18 103453 & 175537 确认此步骤必需.
        """
        import os
        import subprocess
        from core.config import FFMPEG_EXE

        # 优先用外部封面 (pipeline 烧好水印的)
        cleanup = False
        if cover_override and os.path.isfile(cover_override):
            cover_path = cover_override
            log.info("[Publisher] 使用外部封面 %s", os.path.basename(cover_path))
        else:
            # 抽第一帧
            cover_path = video_path + ".cover.jpg"
            cleanup = True
            try:
                result = subprocess.run(
                    [FFMPEG_EXE, "-y", "-loglevel", "error",
                     "-ss", "1.0", "-i", video_path,
                     "-vframes", "1", "-q:v", "3", cover_path],
                    capture_output=True, text=True, timeout=20,
                )
                if result.returncode != 0 or not os.path.isfile(cover_path):
                    log.warning("[Publisher] ffmpeg cover extract failed: %s",
                                result.stderr[:200])
                    return ""
            except Exception as exc:
                log.warning("[Publisher] cover extract exception: %s", exc)
                return ""

        try:
            with open(cover_path, "rb") as f:
                cover_bytes = f.read()
        except Exception as exc:
            log.warning("[Publisher] cover read failed: %s", exc)
            return ""

        url = "https://cp.kuaishou.com/rest/cp/works/v4/video/pc/cover/edit/cover/upload"
        headers = {
            "User-Agent": _DEFAULT_HEADERS["User-Agent"],
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://cp.kuaishou.com",
            "Referer": "https://cp.kuaishou.com/",
            "Cookie": cookie_str,
        }
        # curl-cffi 要求用 CurlMime (而不是 requests 的 files=)
        if CurlMime is None:
            log.error("[Publisher] CurlMime not available, cover upload skipped")
            return ""

        for attempt in range(1, MAX_RETRIES + 1):
            mp = CurlMime()
            mp.addpart(name="kuaishou.web.cp.api_ph", data=api_ph)
            mp.addpart(name="file", filename="cover.jpg",
                       content_type="image/jpeg", data=cover_bytes)
            try:
                resp = self._sess.post(url, multipart=mp, headers=headers, timeout=30)
                mp.close()
                resp.raise_for_status()
                body = resp.json()
                if body.get("result") == 1:
                    ck = body.get("data", {}).get("coverKey", "")
                    log.info("[Publisher] cover upload OK: %s", ck)
                    if cleanup:
                        try: os.remove(cover_path)
                        except Exception: pass
                    return ck
                log.warning("[Publisher] cover upload result=%s: %s",
                            body.get("result"), body)
                return ""
            except Exception as exc:
                try: mp.close()
                except Exception: pass
                log.warning("[Publisher] cover upload attempt %d/%d: %s",
                            attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    return ""
                time.sleep(RETRY_DELAY * attempt)
        return ""

    def _build_submit_payload(
        self,
        api_ph: str,
        file_info: dict,
        caption: str,
        banner_task: dict,
        is_private: bool = False,
        chapters: list | None = None,
    ) -> dict:
        """Build the 42-field submit payload — same dict used to sign AND POST.

        Frida 2026-04-18 关键发现: submit 的 sig3 是签**整个 body**, 不是签 {fileId,
        coverKey}. 所以必须把 body 抽出来供 sig + POST 共用.

        ★ UI 互动设置接入 (2026-04-20):
          allowSameFrame     ← publisher.interaction.allow_copy_shoot
          downloadType       ← publisher.interaction.allow_download  (true→1, false→0)
          disableNearbyShow  ← publisher.interaction.show_in_local  (inverted)
          photoStatus        ← publisher.visibility  (public→0, self/friends→1) | is_private arg override
          declareInfo.source ← publisher.author_statement 下拉  (空→不加)
        """
        from core.app_config import get as _cfg_get
        def _b(k, d):
            v = _cfg_get(k, d)
            if isinstance(v, bool): return v
            if isinstance(v, str):  return v.lower() in ("true", "1", "yes", "on")
            return bool(v)

        allow_copy_shoot = _b("publisher.interaction.allow_copy_shoot", True)
        allow_download   = _b("publisher.interaction.allow_download", True)
        show_in_local    = _b("publisher.interaction.show_in_local", True)
        visibility_str   = str(_cfg_get("publisher.visibility", "public") or "public").lower()
        author_statement = str(_cfg_get("publisher.author_statement", "") or "")

        # visibility → photoStatus (0=public, 1=private/self/friends)
        effective_private = is_private or (visibility_str in ("self", "friends", "private"))

        payload = {
            "fileId": file_info["fileId"],
            "coverKey": file_info.get("coverKey", ""),
            "coverTimeStamp": 0,
            "caption": caption,
            "photoStatus": 1 if effective_private else 0,
            "coverType": 1,
            "coverTitle": "",
            "photoType": 0,
            "collectionId": "",
            "publishTime": 0,
            "longitude": "",
            "latitude": "",
            "poiId": 0,
            "notifyResult": 0,
            "domain": "",
            "secondDomain": "",
            "coverCropped": False,
            "pkCoverKey": "",
            "profileCoverKey": "",
            "downloadType": 1 if allow_download else 0,
            "disableNearbyShow": not show_in_local,
            "allowSameFrame": allow_copy_shoot,
            "movieId": "",
            "openPrePreview": False,
            "declareInfo": {"source": 2} if author_statement else {},  # "演绎情节，仅供娱乐"
            "activityIds": [],
            "riseQuality": False,
            "chapters": chapters or [],
            "useAiCaptionCover": False,
            "useAiCaption": False,
            "projectId": "",
            "recTagIdList": [],
            "videoInfoMeta": "",
            "previewUrlErrorMessage": "",
            "coPublishUser": [],
            "triggerH265": False,
            "photoIdStr": file_info.get("photoIdStr", ""),
            "videoDuration": file_info.get("videoDuration", 0),
            "activity": [],
            "kuaishou.web.cp.api_ph": api_ph,
            "mediaId": file_info.get("mediaId", ""),
        }
        # Canonical (Frida 2026-04-19): KS184 submit 永远带 bannerTask (42 字段).
        # 即使没拿到 drama 对应的 taskId, 也要用 fallback 保证 body 有这个 key,
        # 否则字段数从 42 变 41, sig3 算出来不一样快手可能拒收.
        #
        # 2026-04-21 C-6: 支持 CXT xinghuo shape (bindId/taskId + authCode)
        # 和 firefly yingguang shape (bannerTaskId) 两种都认.
        if banner_task and (
            banner_task.get("bannerTaskId") or banner_task.get("bindId")
            or banner_task.get("authCode")
        ):
            payload["bannerTask"] = banner_task
        else:
            log.warning(
                "[Publisher] banner_task 为空或无 bannerTaskId/bindId/authCode, 用 DEFAULT fallback"
            )
            payload["bannerTask"] = dict(self.DEFAULT_FIREFLY_BANNER)
        return payload

    def _submit(
        self,
        api_ph: str,
        sig3: str,
        cookie_str: str,
        file_info: dict,
        caption: str,
        banner_task: dict,
        is_private: bool = False,
        chapters: list | None = None,
        body_override: dict | None = None,
    ) -> dict:
        """Submit the uploaded video as a new post.

        POST ``/submit?__NS_sig3={sig3}``

        If body_override is given (recommended), use it as payload — caller
        已经用同一份 dict 签了 sig3. 否则 fallback 到重新构建 (sig 可能不匹配 body,
        这只用于向后兼容).

        ★ Week 3 F-5 MCN 中继 fallback:
          sig3 失败时 (publisher.mcn_relay_on_sig3_error=true), 自动切 :50002/xh
          让 MCN 代签转发. 需开启 publisher.enable_mcn_relay_fallback.
        """
        from core.app_config import get as _cfg_get

        payload = body_override if body_override is not None else self._build_submit_payload(
            api_ph, file_info, caption, banner_task, is_private, chapters,
        )

        last_sig3_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_signed(
                    f"{CP_BASE}/submit", payload,
                    cookie_str=cookie_str, timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                result = data.get("result")
                # sig3 相关错误码 (109=auth_expired, 112=sig_invalid, 120=api_changed)
                if result in (109, 112, 120):
                    raise RuntimeError(f"sig3_like_error result={result}: {data}")
                if result != 1:
                    raise RuntimeError(f"submit result={result}: {data}")
                log.info("[Publisher] Submit OK: result=%s data=%s",
                         result, data.get("data", {}))
                return data
            except Exception as exc:
                last_sig3_err = exc
                log.warning("[Publisher] submit attempt %d/%d failed: %s",
                            attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    break
                time.sleep(RETRY_DELAY * attempt)

        # ★ 走到这里说明 MAX_RETRIES 次 sig3 路径都失败 → 尝试 MCN 中继 fallback
        def _to_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "on")
            return bool(v)

        enable_fallback = _to_bool(_cfg_get("publisher.enable_mcn_relay_fallback", False))
        on_sig3_error = _to_bool(_cfg_get("publisher.mcn_relay_on_sig3_error", True))
        err_str = str(last_sig3_err or "")
        is_sig3_error = ("sig3_like_error" in err_str
                          or "109" in err_str or "112" in err_str
                          or "120" in err_str or "__NS_sig3" in err_str)

        if enable_fallback and (on_sig3_error is False or is_sig3_error):
            log.warning("[Publisher] sig3 路径失败, 切 MCN 中继 fallback: %s", err_str[:120])
            try:
                from core.mcn_relay import submit_via_relay
                relay_result = submit_via_relay(payload, apdid=api_ph)
                if relay_result.get("ok"):
                    log.info("[Publisher] ✅ MCN 中继 fallback 成功 (status=%s)",
                             relay_result.get("status_code"))
                    # 构造兼容 sig3 路径的返回结构
                    # photoIdStr 在 payload 里, upload 阶段已拿到
                    return {
                        "result": 1,
                        "data": {"photoIdStr": payload.get("photoIdStr", ""),
                                  "fallback": "mcn_relay"},
                        "_via": "mcn_relay",
                        "_relay_response": relay_result,
                    }
                else:
                    log.error("[Publisher] MCN 中继也失败: %s", relay_result)
            except Exception as fb_exc:
                log.exception("[Publisher] MCN 中继异常: %s", fb_exc)

        # 两路都挂 → 抛原异常
        raise last_sig3_err  # type: ignore[misc]

    # ==================================================================
    # P0 补漏 (KS184 内存逆向 2026-04-19): 作品删除 + 关联列表
    # ==================================================================

    def delete_work(self, account_id: int, photo_id: str) -> dict:
        """删除已发布作品 (矩阵运营低表现剔除).

        端点: POST ``/rest/cp/works/v2/video/pc/delete?__NS_sig3=SIG``
        Body: ``{"photoId": <str>, "kuaishou.web.cp.api_ph": <str>}``

        来源: KS184 内存 dump grep 上下文还原 (2026-04-19).
        Frida trace 未直接捕获 (用户从未点过删除), 字段以 dump 还原为准.

        Parameters
        ----------
        account_id : int
            ``device_accounts.id`` 整数主键.
        photo_id : str
            待删除作品的 photoId (字符串, 不是 photoIdLong).

        Returns
        -------
        dict
            ``{"success": bool, "result": int|None, "message": str, "raw": dict}``
        """
        if not photo_id:
            return {"success": False, "result": None,
                    "message": "photo_id is empty", "raw": {}}

        cookie_str = self.cookie_mgr.get_cookie_string(account_id, domain="cp")
        if not cookie_str:
            return {"success": False, "result": None,
                    "message": "No cp cookie for account", "raw": {}}

        api_ph = self.cookie_mgr.get_api_ph(account_id)
        if not api_ph:
            return {"success": False, "result": None,
                    "message": "No api_ph in cookies", "raw": {}}

        payload = {
            "photoId": str(photo_id),
            "kuaishou.web.cp.api_ph": api_ph,
        }
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_signed(
                    f"{CP_BASE}/delete", payload,
                    cookie_str=cookie_str, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("result") == 1:
                    log.info("[Publisher] delete_work OK: account=%s photo=%s",
                             account_id, photo_id)
                    return {"success": True, "result": 1,
                            "message": "deleted", "raw": data}
                log.warning("[Publisher] delete_work non-1 result=%s: %s",
                            data.get("result"), data)
                return {"success": False, "result": data.get("result"),
                        "message": str(data.get("error_msg") or data),
                        "raw": data}
            except Exception as exc:
                last_exc = exc
                log.warning("[Publisher] delete_work attempt %d/%d failed: %s",
                            attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
        return {"success": False, "result": None,
                "message": f"delete_work exhausted retries: {last_exc}",
                "raw": {}}

    # ==================================================================
    # 2026-04-20: 账号清洗 — 查+批量删历史作品
    # (KS184 API_MASTER.md 指出的 home/photo/list 端点)
    # ==================================================================

    def list_account_works(self, account_id: int, pcursor: str = "",
                            page_size: int = 20) -> dict:
        """分页查账号已发作品.

        端点: POST /rest/cp/works/v2/video/pc/home/photo/list
        Body: {"pcursor": str, "count": int, "kuaishou.web.cp.api_ph": str}

        Returns:
          {ok, items: [{workId, title, playCount, likeCount, uploadTime,
                         publishCoverUrl, durationSecond, ...}],
           pcursor_next, has_more, raw}
        """
        cookie_str = self.cookie_mgr.get_cookie_string(account_id, domain="cp")
        if not cookie_str:
            return {"ok": False, "error": "no_cp_cookie", "items": []}
        api_ph = self.cookie_mgr.get_api_ph(account_id)
        if not api_ph:
            return {"ok": False, "error": "no_api_ph", "items": []}

        payload = {
            "pcursor": pcursor or "",
            "count": int(page_size),
            "kuaishou.web.cp.api_ph": api_ph,
        }
        try:
            resp = self._post_signed(
                f"{CP_BASE}/home/photo/list", payload,
                cookie_str=cookie_str, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") != 1:
                return {"ok": False, "error": f"result={data.get('result')}",
                        "items": [], "raw": data}
            d = data.get("data") or {}
            items = d.get("list") or []
            return {
                "ok": True,
                "items": [
                    {
                        "work_id": it.get("workId"),
                        "title": it.get("title", ""),
                        "play_count": it.get("playCount", 0),
                        "like_count": it.get("likeCount", 0),
                        "comment_count": it.get("commentCount", 0),
                        "upload_time": it.get("uploadTime"),
                        "duration_sec": it.get("durationSecond", 0),
                        "publish_cover_url": it.get("publishCoverUrl", ""),
                        "photo_status": it.get("photoStatus"),
                        "publish_status": it.get("publishStatus"),
                        "judgement_status": it.get("judgementStatus"),
                        "user_id": it.get("userId"),
                        "user_name": it.get("userName", ""),
                    }
                    for it in items
                ],
                "pcursor_next": d.get("pcursor", "no_more"),
                "has_more": (d.get("pcursor") and d.get("pcursor") != "no_more"),
                "raw_count": len(items),
            }
        except Exception as e:
            log.exception("[Publisher] list_account_works failed: %s", e)
            return {"ok": False, "error": str(e), "items": []}

    def list_all_works(self, account_id: int, max_pages: int = 10) -> list[dict]:
        """翻页拉完所有作品. max_pages 防止账号作品过多打爆."""
        all_items = []
        cursor = ""
        for page in range(max_pages):
            r = self.list_account_works(account_id, pcursor=cursor, page_size=20)
            if not r.get("ok"):
                log.warning("[Publisher] list_all_works page %d failed: %s",
                            page, r.get("error"))
                break
            all_items.extend(r["items"])
            if not r.get("has_more"):
                break
            cursor = r.get("pcursor_next", "")
            if not cursor or cursor == "no_more":
                break
            time.sleep(0.3)  # 防限流
        return all_items

    def batch_cleanup_non_drama(self, account_id: int,
                                  keep_drama_names: list[str] | None = None,
                                  keep_photo_ids: list[str] | None = None,
                                  delete_interval_sec: float = 8.0,
                                  max_deletes: int = 50,
                                  dry_run: bool = False) -> dict:
        """批量删除非短剧作品 (账号品牌统一化).

        保留规则 (任一匹配即保留):
          1. photo_id ∈ keep_photo_ids (我们 publish_results 的已发作品)
          2. title 含 keep_drama_names 里任一剧名
          3. title 含 "短剧" 或 "#短剧" tag

        其他视为"非短剧废作品", 逐条 delete_work(...).

        Args:
            account_id: device_accounts.id
            keep_drama_names: 要保留的剧名列表 (命中就保)
            keep_photo_ids: 要保留的 photo_id 列表
            delete_interval_sec: 删 1 条后等 N 秒 (防风控)
            max_deletes: 单次最多删 N 条
            dry_run: True = 只列不删

        Returns:
            {ok, total, kept, deleted, failed, details: [...]}
        """
        keep_drama_names = keep_drama_names or []
        keep_photo_ids = set(keep_photo_ids or [])

        # 1. 拉所有作品
        works = self.list_all_works(account_id)
        if not works:
            return {"ok": True, "total": 0, "kept": 0, "deleted": 0,
                    "failed": 0, "details": [], "note": "no_works"}

        # 2. 分类 (保留 vs 删除)
        # 保留规则 (有一个匹配就保留):
        #   a. 是我们自己真发的作品 (publish_results.photo_id)
        #   b. title 含某个保留剧名 (keep_drama_names)
        #   c. title 含"短剧"关键字 tag: #短剧 / #快来看短剧 / #看短剧 / #短剧推荐
        # 只删 "纯生活/美食/搞笑/Vlog" 等不含任何短剧标签的
        drama_tag_kw = ["#短剧", "#快来看短剧", "#看短剧", "#短剧推荐", "#追剧",
                         "#霸总短剧", "#甜宠短剧", "#虐恋短剧", "#古装短剧"]
        to_delete: list[dict] = []
        kept: list[dict] = []
        for w in works:
            pid = str(w.get("work_id") or "")
            title = (w.get("title") or "").strip()
            # a. 我们发的
            if pid in keep_photo_ids:
                kept.append({**w, "_reason": "our_published"})
                continue
            # b. 命中保留剧名
            hit_drama = next((n for n in keep_drama_names if n and n in title), None)
            if hit_drama:
                kept.append({**w, "_reason": f"matches_drama:{hit_drama}"})
                continue
            # c. 含短剧标签 tag (任意)
            hit_tag = next((kw for kw in drama_tag_kw if kw in title), None)
            if hit_tag:
                kept.append({**w, "_reason": f"drama_tag:{hit_tag}"})
                continue
            # 其他 → 非短剧废作品, 删
            to_delete.append(w)

        to_delete = to_delete[:max_deletes]

        # 3. 真删
        deleted = 0
        failed = 0
        results = []
        for w in to_delete:
            pid = str(w.get("work_id") or "")
            if dry_run:
                results.append({"work_id": pid, "title": w.get("title"),
                                 "action": "would_delete"})
                deleted += 1
                continue
            r = self.delete_work(account_id, pid)
            if r.get("success"):
                deleted += 1
                results.append({"work_id": pid, "title": w.get("title",""),
                                 "action": "deleted"})
            else:
                failed += 1
                results.append({"work_id": pid, "title": w.get("title",""),
                                 "action": "failed", "error": r.get("message")})
            time.sleep(delete_interval_sec)

        return {
            "ok": True,
            "total": len(works),
            "kept": len(kept),
            "deleted": deleted,
            "failed": failed,
            "kept_details": kept[:5],
            "delete_details": results,
            "dry_run": dry_run,
        }


    def list_relations(self, account_id: int, drama_title: str,
                       relation_type: int = 10, cursor: str = "",
                       page_size: int = 20) -> dict:
        """查询账号当前关联的剧/任务列表 (非 banner 类).

        端点: POST ``/rest/cp/works/v2/video/pc/relation/list?__NS_sig3=SIG``
        Body: ``{"type", "title", "drama_title", "cursor",
                 "kuaishou.web.cp.api_ph"}``

        ``relation_type=10`` 为 firefly/萤光剧, 与 banner_list 同语义但范围更广 —
        banner_list 只返回正在挂载的 banner, list 返回所有可关联候选.

        Returns
        -------
        dict
            ``{"success": bool, "items": [...], "next_cursor": str,
               "result": int|None, "raw": dict}``
        """
        if not drama_title:
            return {"success": False, "items": [], "next_cursor": "",
                    "result": None, "raw": {}}

        cookie_str = self.cookie_mgr.get_cookie_string(account_id, domain="cp")
        if not cookie_str:
            return {"success": False, "items": [], "next_cursor": "",
                    "result": None, "raw": {"error": "no cp cookie"}}

        api_ph = self.cookie_mgr.get_api_ph(account_id)
        if not api_ph:
            return {"success": False, "items": [], "next_cursor": "",
                    "result": None, "raw": {"error": "no api_ph"}}

        payload = {
            "type": int(relation_type),
            "title": drama_title,
            "drama_title": drama_title,
            "cursor": cursor or "",
            "pageSize": int(page_size),
            "kuaishou.web.cp.api_ph": api_ph,
        }
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_signed(
                    f"{CP_BASE}/relation/list", payload,
                    cookie_str=cookie_str, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("result") != 1:
                    log.warning("[Publisher] list_relations result=%s: %s",
                                data.get("result"), data)
                    return {"success": False, "items": [], "next_cursor": "",
                            "result": data.get("result"), "raw": data}
                d = data.get("data") or {}
                items = d.get("list") or d.get("items") or []
                next_cursor = d.get("cursor") or d.get("nextCursor") or ""
                log.info("[Publisher] list_relations: %d items, drama='%s'",
                         len(items), drama_title)
                return {"success": True, "items": items,
                        "next_cursor": next_cursor, "result": 1, "raw": data}
            except Exception as exc:
                last_exc = exc
                log.warning("[Publisher] list_relations attempt %d/%d failed: %s",
                            attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
        return {"success": False, "items": [], "next_cursor": "",
                "result": None, "raw": {"error": str(last_exc)}}
