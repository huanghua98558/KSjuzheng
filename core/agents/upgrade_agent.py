# -*- coding: utf-8 -*-
"""UpgradeAgent — AI 升级提议.

职责:
  1. 扫 healing_playbook: 成功率低的规则 → 提议改写 remedy 或淘汰
  2. 扫 task_queue failed: 不被任何 playbook 匹配的错误类 → 提议新增规则
  3. 扫 task_queue error_message: 出现 Traceback 的 → 提议代码修复
  4. 所有提议落 upgrade_proposals 表
     (需人工 approve / 或高 confidence 自动 apply)

不会直接改代码, 只写提议. 真正的 "apply patch" 需要上升到 dev 复核.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK
from core.config import DB_PATH


def _wal_conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=120.0,
                        isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=120000")
    return c


# 常见 error_message → 关键词签名 (去掉动态变量后剩下的 "骨架")
ERR_SIG_NORMALIZERS = [
    (re.compile(r"https?://\S+"), "<URL>"),
    (re.compile(r"[A-Z]:[\\/][\w./\\_-]+\.(mp4|m3u8|ts|py|json|db)"), "<PATH>"),
    (re.compile(r"/[\w./_-]+\.(mp4|m3u8|ts|py|json|db)"), "<PATH>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
    (re.compile(r"(?:line|Line)\s+\d+"), "line <N>"),
    (re.compile(r"\b\d+\s*(?:MB|KB|GB|TB|B|ms|s|min)\b", re.IGNORECASE), "<SIZE>"),
    (re.compile(r"\b\d+\b"), "<NUM>"),   # 所有数字
    (re.compile(r"'[^']{8,}'"), "<STR>"),
    (re.compile(r'"[^"]{8,}"'), "<STR>"),
]


def _sig_of_err(msg: str) -> str:
    s = msg or ""
    for pat, repl in ERR_SIG_NORMALIZERS:
        s = pat.sub(repl, s)
    return s[:180]


class UpgradeAgent(BaseAgent):
    name = "upgrade"
    llm_mode = "rules"

    def _compute(self, payload: dict) -> dict:
        days = int(payload.get("days", 7))
        min_occurrences = int(payload.get("min_occurrences", 3))

        wc = _wal_conn()
        findings: list = []
        proposals: list = []

        # ----------------------------------------------------------
        # 1. 低成功率 playbook → 提议 rewrite / retire
        # ----------------------------------------------------------
        pb = wc.execute(
            """SELECT id, code, remedy_action, success_count, fail_count,
                      confidence, is_active
               FROM healing_playbook WHERE is_active=1"""
        ).fetchall()
        for (pb_id, code, remedy, sc, fc, conf, active) in pb:
            sc = sc or 0
            fc = fc or 0
            total = sc + fc
            if total < 5:
                continue
            rate = sc / total
            if rate < 0.5:
                p = {
                    "type": "playbook_rewrite",
                    "target_code": code,
                    "target_id": pb_id,
                    "reason": f"成功率 {rate*100:.0f}% ({sc}/{total}) — 建议改写 remedy 或降权",
                    "suggested_change": {
                        "action": "demote_or_retire",
                        "current_remedy": remedy,
                        "proposed": f"要么重写 {remedy} 的实现, 要么 is_active=0",
                    },
                    "confidence": min(0.9, 1 - rate + 0.3),
                    "evidence": {"success": sc, "fail": fc, "rate": rate},
                }
                proposals.append(p)
                findings.append({
                    "type": "low_success_rule",
                    "source": "playbook",
                    "playbook_code": code,
                    "success_rate": rate,
                    "message": p["reason"],
                    "confidence": p["confidence"],
                })

        # ----------------------------------------------------------
        # 2. 未匹配的失败 → 提议新增 playbook rule
        # ----------------------------------------------------------
        failed = wc.execute(
            """SELECT task_type, error_message, account_id, drama_name
               FROM task_queue
               WHERE status IN ('failed','dead_letter')
                 AND datetime(finished_at) >= datetime('now', ?)
                 AND (error_message IS NOT NULL AND error_message != '')""",
            (f"-{days} days",),
        ).fetchall()

        # 拉现有 patterns — (pattern, task_type) 二元组
        pb_rules = wc.execute(
            """SELECT symptom_pattern, task_type FROM healing_playbook
               WHERE is_active=1"""
        ).fetchall()

        def _matched_any(tt: str, err: str) -> bool:
            for (pat, pb_tt) in pb_rules:
                if pb_tt not in ("*", tt):
                    continue
                try:
                    if re.search(pat, err, re.IGNORECASE):
                        return True
                except re.error:
                    continue
            return False

        unmatched = [(tt, err) for (tt, err, _, _) in failed
                     if not _matched_any(tt, err or "")]
        sig_counter: Counter = Counter()
        sig_sample: dict[str, str] = {}
        sig_task_type: dict[str, Counter] = defaultdict(Counter)
        for tt, err in unmatched:
            sig = _sig_of_err(err)
            sig_counter[sig] += 1
            if sig not in sig_sample:
                sig_sample[sig] = err[:500]
            sig_task_type[sig][tt] += 1

        for sig, n in sig_counter.most_common(5):
            if n < min_occurrences:
                break
            dominant_tt, _ = sig_task_type[sig].most_common(1)[0]
            # 把错误 signature 变成一个 regex skeleton
            proposed_pattern = re.escape(sig)[:120].replace(r"\<URL\>", ".*") \
                                                  .replace(r"\<PATH\>", ".*") \
                                                  .replace(r"\<NUM\>", r"\d+") \
                                                  .replace(r"\<HEX\>", "0x[0-9a-f]+") \
                                                  .replace(r"\<STR\>", ".*") \
                                                  .replace(r"line \<N\>", r"line\s+\d+")
            proposed_code = f"auto_{dominant_tt.lower()}_{abs(hash(sig)) % 100000}"
            p = {
                "type": "playbook_new_rule",
                "target_code": proposed_code,
                "reason": f"{n} 个失败 ({dominant_tt}) 未被任何规则匹配 — 建议新增",
                "suggested_change": {
                    "action": "insert_playbook",
                    "proposed_row": {
                        "code": proposed_code,
                        "symptom_pattern": proposed_pattern,
                        "task_type": dominant_tt,
                        "min_occurrences": 2,
                        "diagnosis": f"auto-detected: {sig[:80]}",
                        "remedy_action": "TODO_NEED_HUMAN_REVIEW",
                        "confidence": 0.5,
                    },
                },
                "confidence": 0.5 + min(0.3, n * 0.03),
                "evidence": {"occurrences": n, "sample": sig_sample[sig][:200]},
            }
            proposals.append(p)
            findings.append({
                "type": "new_rule_candidate",
                "source": "unmatched",
                "message": p["reason"],
                "count": n,
                "sample": sig_sample[sig][:120],
                "confidence": p["confidence"],
            })

        # ----------------------------------------------------------
        # 3. Traceback → 代码级提议
        # ----------------------------------------------------------
        tb_frames: Counter = Counter()
        tb_sample: dict[str, str] = {}
        for tt, err, _, _ in failed:
            if not err or "Traceback" not in err:
                continue
            # 抓 File "xxx", line N 的最顶一行
            m = re.search(r'File\s+"([^"]+)",\s*line\s+(\d+)', err)
            if not m:
                continue
            key = f"{m.group(1)}:{m.group(2)}"
            tb_frames[key] += 1
            if key not in tb_sample:
                tb_sample[key] = err[-400:]
        for frame, n in tb_frames.most_common(5):
            if n < min_occurrences:
                break
            p = {
                "type": "code_fix",
                "target_code": frame,
                "reason": f"{n} 次 Traceback 命中同一帧 — 建议修代码",
                "suggested_change": {
                    "action": "human_review_file",
                    "file_line": frame,
                    "note": "推荐查 Exception handling / null guard / retry decorator",
                },
                "confidence": 0.6 + min(0.3, n * 0.02),
                "evidence": {"occurrences": n, "trace_tail": tb_sample[frame]},
            }
            proposals.append(p)
            findings.append({
                "type": "repeated_traceback",
                "source": "exception",
                "frame": frame,
                "count": n,
                "message": p["reason"],
                "confidence": p["confidence"],
            })

        # ----------------------------------------------------------
        # 4. 落 upgrade_proposals
        # ----------------------------------------------------------
        self._ensure_table(wc)
        for p in proposals:
            self._persist_proposal(wc, p)

        recommendations = [{
            "action": "review_proposals",
            "count": len(proposals),
            "message": f"共提议 {len(proposals)} 条升级, 请到 /autopilot 审核" if proposals
                       else "近期无升级需求",
        }]

        return AgentResponse.make(
            self.name, run_id="",
            status=RESPONSE_STATUS_OK,
            confidence=0.85,
            findings=findings,
            recommendations=recommendations,
            meta={
                "days_scanned": days,
                "proposals_written": len(proposals),
                "failed_tasks_seen": len(failed),
                "unmatched_failures": len(unmatched),
            },
        )

    # ------------------------------------------------------------------

    def _ensure_table(self, wc: sqlite3.Connection) -> None:
        # upgrade_proposals 在 migrate_v15 已建, 此处 idempotent fallback
        # 实际 schema: upgrade_type / target_file / current_state / proposed_state
        #   / reason / evidence_json / confidence / status / proposer / ...
        wc.execute("""
            CREATE TABLE IF NOT EXISTS upgrade_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upgrade_type   TEXT NOT NULL,
                target_file    TEXT,
                current_state  TEXT,
                proposed_state TEXT,
                reason         TEXT,
                evidence_json  TEXT,
                confidence     REAL,
                status         TEXT DEFAULT 'pending',
                proposer       TEXT DEFAULT 'UpgradeAgent',
                created_at     TEXT DEFAULT (datetime('now','localtime')),
                decided_at     TEXT,
                decision_note  TEXT
            )
        """)

    def _persist_proposal(self, wc: sqlite3.Connection, p: dict) -> None:
        upgrade_type = p["type"]
        target_file = p.get("target_code", "")
        change = p.get("suggested_change", {}) or {}
        current_state = json.dumps(
            {"remedy": change.get("current_remedy", "")} if upgrade_type == "playbook_rewrite"
            else ({"missing": True} if upgrade_type == "playbook_new_rule"
                  else {"frame": target_file}),
            ensure_ascii=False,
        )
        proposed_state = json.dumps(change, ensure_ascii=False)[:8000]

        # 去重: 同 upgrade_type + target_file + pending 只保留一条
        dup = wc.execute(
            """SELECT id FROM upgrade_proposals
               WHERE upgrade_type=? AND target_file=? AND status='pending'""",
            (upgrade_type, target_file),
        ).fetchone()
        if dup:
            wc.execute(
                """UPDATE upgrade_proposals SET
                     reason=?, current_state=?, proposed_state=?,
                     evidence_json=?, confidence=?,
                     created_at=datetime('now','localtime')
                   WHERE id=?""",
                (p["reason"], current_state, proposed_state,
                 json.dumps(p.get("evidence", {}), ensure_ascii=False, default=str)[:8000],
                 float(p["confidence"]), dup[0]),
            )
        else:
            wc.execute(
                """INSERT INTO upgrade_proposals
                     (upgrade_type, target_file, current_state, proposed_state,
                      reason, evidence_json, confidence, status, proposer)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'UpgradeAgent')""",
                (upgrade_type, target_file, current_state, proposed_state,
                 p["reason"],
                 json.dumps(p.get("evidence", {}), ensure_ascii=False, default=str)[:8000],
                 float(p["confidence"])),
            )
