"""AI decision engine for KS184 automation -- LangGraph + DeepSeek.

Orchestrates a multi-step decision pipeline that determines, for each
account, which drama to publish, which dedup strategy to use, how many
videos to publish, and which channel (API vs. Selenium) to use.

Modes:
    "ai"      -- every node calls DeepSeek for reasoning
    "rules"   -- pure rule-based (no API calls)
    "hybrid"  -- AI for complex decisions (drama selection), rules for the rest

Self-learning:
    Every decision is persisted to SQLite.  When outcomes (views, CPM,
    approval) are recorded later, the engine feeds them back into future
    prompts so DeepSeek can learn from past performance.

Usage:
    from core.db_manager import DBManager
    from strategies.tracker import StrategyTracker
    from core.decision_engine import DecisionEngine

    db = DBManager()
    tracker = StrategyTracker(db)
    engine = DecisionEngine(db, tracker)
    result = engine.decide_for_account("some_account_id")
"""

from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypedDict

from core.logger import get_logger

logger = get_logger("decision_engine")

# ---------------------------------------------------------------------------
# Conditional imports -- graceful degradation when LangGraph is absent
# ---------------------------------------------------------------------------

try:
    from langgraph.graph import END, StateGraph
    from langgraph.checkpoint.memory import MemorySaver

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning(
        "langgraph not installed -- falling back to sequential pipeline. "
        "Install with: pip install langgraph"
    )

try:
    from openai import OpenAI

    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OPENAI_SDK_AVAILABLE = False
    logger.warning(
        "openai SDK not installed -- AI mode disabled. "
        "Install with: pip install openai"
    )


# ===================================================================
# Data Structures
# ===================================================================


class DecisionState(TypedDict, total=False):
    """State schema flowing through the LangGraph pipeline."""

    # --- Inputs (populated before graph execution) ---
    account_id: str
    account_name: str
    account_level: str  # V1 / V2 / V3 / V4+
    account_age_days: int
    today_published: int
    available_dramas: list[dict]  # [{name, url, score, times_used, avg_cpm}]
    available_strategies: list[dict]  # [{name, approval_rate, avg_views, weight}]
    historical_data: dict  # past performance context

    # --- Outputs (populated by graph nodes) ---
    selected_drama: Optional[dict]
    selected_strategy: str
    publish_count: int
    publish_channel: str  # "api" or "selenium"
    reasoning: str  # AI / rule explanation


@dataclass
class DecisionResult:
    """Immutable result returned by the engine to callers."""

    account_id: str
    account_name: str
    selected_drama: dict | None
    selected_strategy: str
    publish_count: int
    publish_channel: str
    reasoning: str
    decision_id: int | None = None  # set after DB persistence

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "selected_drama": self.selected_drama,
            "selected_strategy": self.selected_strategy,
            "publish_count": self.publish_count,
            "publish_channel": self.publish_channel,
            "reasoning": self.reasoning,
            "decision_id": self.decision_id,
        }


# ===================================================================
# Multi-Provider LLM Client
# ===================================================================

# Provider presets: try in order until one works
LLM_PROVIDERS = {
    "codex": {
        "base_url": "http://127.0.0.1:8642/v1",
        "api_key_env": None,
        "api_key_file": r"D:\AIbot\swarmclaw-stack\config\hermes\api-server.key",
        "model": "gpt-5.4",
        "description": "Codex GPT-5.4 via Hermes (复杂任务, free)",
    },
    "codex-mini": {
        "base_url": "http://127.0.0.1:8642/v1",
        "api_key_env": None,
        "api_key_file": r"D:\AIbot\swarmclaw-stack\config\hermes\api-server.key",
        "model": "gpt-5.4-mini",
        "description": "Codex GPT-5.4 mini via Hermes (快速批量, free)",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key_file": None,
        "api_key": "sk-69b28d14b0374362ab110a99b3164098",
        "model": "deepseek-chat",
        "description": "DeepSeek V3.2 ($0.14/M tokens)",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "api_key_file": None,
        "api_key": "sk-yhntnkjkpfyebhlgknhkbzkmlojihgxhmuplsjdxvppwhynm",
        "model": "deepseek-ai/DeepSeek-V3",
        "description": "SiliconFlow DeepSeek-V3",
    },
    "aliyun": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "api_key_file": None,
        "api_key": "sk-92b0cec5b87c4c739794c2b767685cc1",
        "model": "qwen-plus-latest",   # ★ 2026-04-20 用户要求 Qwen 3.6 Plus
        "description": "Aliyun Qwen 3.6 Plus (百炼, 主决策模型)",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "api_key_file": None,
        "model": "gpt-4.1-nano",
        "description": "OpenAI direct ($0.10/M tokens)",
    },
}


class LLMClient:
    """Multi-provider LLM client with automatic fallback.

    Resolution order:
        1. Explicit ``provider`` parameter
        2. Codex/Hermes local proxy (free GPT-5.4 via ChatGPT Pro)
        3. OpenClaw gateway (free GPT-5.4)
        4. DeepSeek API (cheap)
        5. OpenAI API (expensive fallback)
        6. None (caller falls back to rules)

    After training is done with GPT-5.4, switch to DeepSeek:
        engine = DecisionEngine(db, tracker, llm_provider="deepseek")
    """

    TIMEOUT = 120
    TEMPERATURE = 0.3
    MAX_TOKENS = 1024

    def __init__(self, provider: str | None = None, api_key: str | None = None) -> None:
        self.provider_name: str = "none"
        self.model: str = ""
        self.available: bool = False
        self._client: Any = None

        if not OPENAI_SDK_AVAILABLE:
            logger.info("openai SDK missing -- AI mode disabled")
            return

        # If provider explicitly specified, try only that one
        if provider and provider in LLM_PROVIDERS:
            candidates = [provider]
        elif provider:
            logger.warning("Unknown provider '%s', trying auto-detect", provider)
            candidates = list(LLM_PROVIDERS.keys())
        else:
            # Auto-detect: try all in order
            candidates = list(LLM_PROVIDERS.keys())

        for name in candidates:
            cfg = LLM_PROVIDERS[name]
            key = api_key  # explicit key takes precedence

            # Try hardcoded key in provider config
            if not key and cfg.get("api_key"):
                key = cfg["api_key"]

            # Try to read key from file
            if not key and cfg.get("api_key_file"):
                try:
                    with open(cfg["api_key_file"], "r") as f:
                        key = f.read().strip()
                except (FileNotFoundError, PermissionError):
                    key = None

            # Try environment variable
            if not key and cfg.get("api_key_env"):
                key = os.getenv(cfg["api_key_env"], "")

            if not key:
                continue

            # For local proxies, test connectivity
            if "127.0.0.1" in cfg["base_url"]:
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        cfg["base_url"].replace("/v1", "/health"),
                        method="GET",
                    )
                    urllib.request.urlopen(req, timeout=1)
                except Exception:
                    # Try the /v1/models endpoint instead
                    try:
                        import urllib.request
                        req = urllib.request.Request(cfg["base_url"] + "/models")
                        req.add_header("Authorization", f"Bearer {key}")
                        urllib.request.urlopen(req, timeout=1)
                    except Exception:
                        logger.debug("Provider '%s' not reachable, skipping", name)
                        continue

            # Create client
            try:
                self._client = OpenAI(
                    api_key=key,
                    base_url=cfg["base_url"],
                    timeout=self.TIMEOUT,
                )
                self.provider_name = name
                self.model = cfg["model"]
                self.available = True
                logger.info(
                    "LLM provider: %s (%s, model=%s)",
                    name, cfg["description"], self.model,
                )
                break
            except Exception as exc:
                logger.debug("Failed to init provider '%s': %s", name, exc)

        if not self.available:
            logger.info("No LLM provider available -- rules-only mode")

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> str | None:
        """Send a chat completion request and return the assistant reply.

        Returns None on any error (caller should fall back to rules).
        """
        if not self.available or self._client is None:
            return None

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature or self.TEMPERATURE,
                max_tokens=self.MAX_TOKENS,
            )
            content = response.choices[0].message.content
            logger.debug("LLM response (first 200 chars): %s", content[:200] if content else "")
            return content
        except Exception as exc:
            logger.warning("LLM API call failed: %s", exc)
            return None

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> dict | None:
        """Like chat() but attempts to parse the response as JSON.

        Extracts JSON from markdown code fences if present.
        """
        raw = self.chat(system_prompt, user_prompt, temperature)
        if raw is None:
            return None

        # Strip markdown code fence if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse DeepSeek JSON response: %s", text[:300])
            return None


# ===================================================================
# Decision Memory (Self-Learning)
# ===================================================================


class DecisionMemory:
    """Persists decisions and their outcomes to SQLite for self-learning.

    Table: decision_history
    """

    def __init__(self, db_manager: Any) -> None:
        self.db = db_manager
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the decision_history table if it does not exist."""
        try:
            self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS decision_history (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id          TEXT NOT NULL,
                    drama_name          TEXT,
                    strategy_name       TEXT,
                    channel             TEXT,
                    publish_count       INTEGER DEFAULT 0,
                    decision_reasoning  TEXT,
                    outcome_views       INTEGER DEFAULT 0,
                    outcome_cpm         REAL DEFAULT 0,
                    outcome_approved    INTEGER DEFAULT -1,
                    created_at          TEXT NOT NULL,
                    outcome_updated_at  TEXT
                )
            """)
            self.db.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dh_account
                ON decision_history(account_id)
            """)
            self.db.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dh_created
                ON decision_history(created_at)
            """)
            self.db.conn.commit()
            logger.debug("decision_history table ensured")
        except sqlite3.Error as exc:
            logger.error("Failed to create decision_history table: %s", exc)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_decision(
        self,
        account_id: str,
        drama_name: str | None,
        strategy_name: str,
        channel: str,
        publish_count: int,
        reasoning: str,
    ) -> int | None:
        """Persist a new decision.  Returns the row id or None on failure."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = self.db.conn.execute(
                """
                INSERT INTO decision_history
                    (account_id, drama_name, strategy_name, channel,
                     publish_count, decision_reasoning, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, drama_name, strategy_name, channel,
                 publish_count, reasoning, now),
            )
            self.db.conn.commit()
            row_id = cursor.lastrowid
            logger.info(
                "Recorded decision #%d: account=%s drama=%s strategy=%s",
                row_id, account_id, drama_name, strategy_name,
            )
            return row_id
        except sqlite3.Error as exc:
            logger.error("record_decision failed: %s", exc)
            self.db.conn.rollback()
            return None

    def update_outcome(
        self,
        decision_id: int,
        views: int = 0,
        cpm: float = 0.0,
        approved: int = -1,
    ) -> bool:
        """Update the outcome for a previously recorded decision.

        Args:
            decision_id: Primary key from record_decision.
            views: Total views observed.
            cpm: Revenue per mille (CPM).
            approved: 1=approved, 0=rejected, -1=pending.

        Returns:
            True if the row was updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = self.db.conn.execute(
                """
                UPDATE decision_history
                SET outcome_views = ?, outcome_cpm = ?, outcome_approved = ?,
                    outcome_updated_at = ?
                WHERE id = ?
                """,
                (views, cpm, approved, now, decision_id),
            )
            self.db.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            logger.error("update_outcome(%d) failed: %s", decision_id, exc)
            self.db.conn.rollback()
            return False

    # ------------------------------------------------------------------
    # Read -- context for AI prompts
    # ------------------------------------------------------------------

    def get_account_history(
        self,
        account_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return recent decisions + outcomes for an account."""
        try:
            rows = self.db.conn.execute(
                """
                SELECT drama_name, strategy_name, channel, publish_count,
                       outcome_views, outcome_cpm, outcome_approved, created_at
                FROM decision_history
                WHERE account_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (account_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("get_account_history(%s) failed: %s", account_id, exc)
            return []

    def get_drama_usage_counts(self) -> dict[str, int]:
        """Return {drama_name: total_times_used} across all accounts."""
        try:
            rows = self.db.conn.execute(
                """
                SELECT drama_name, COUNT(*) AS cnt
                FROM decision_history
                WHERE drama_name IS NOT NULL
                GROUP BY drama_name
                """
            ).fetchall()
            return {r["drama_name"]: r["cnt"] for r in rows}
        except sqlite3.Error as exc:
            logger.error("get_drama_usage_counts failed: %s", exc)
            return {}

    def get_overall_stats(self) -> dict[str, Any]:
        """Aggregate performance metrics across all decisions."""
        try:
            row = self.db.conn.execute(
                """
                SELECT
                    COUNT(*) AS total_decisions,
                    SUM(CASE WHEN outcome_approved = 1 THEN 1 ELSE 0 END) AS total_approved,
                    SUM(CASE WHEN outcome_approved = 0 THEN 1 ELSE 0 END) AS total_rejected,
                    AVG(CASE WHEN outcome_views > 0 THEN outcome_views END) AS avg_views,
                    AVG(CASE WHEN outcome_cpm > 0 THEN outcome_cpm END) AS avg_cpm
                FROM decision_history
                WHERE outcome_approved != -1
                """
            ).fetchone()
            if row:
                return dict(row)
            return {}
        except sqlite3.Error as exc:
            logger.error("get_overall_stats failed: %s", exc)
            return {}

    def get_channel_failure_rates(self, days: int = 7) -> dict[str, float]:
        """Return failure rate (0.0-1.0) per channel over recent days.

        A decision is counted as a failure if outcome_approved == 0.
        """
        try:
            rows = self.db.conn.execute(
                """
                SELECT
                    channel,
                    COUNT(*) AS total,
                    SUM(CASE WHEN outcome_approved = 0 THEN 1 ELSE 0 END) AS failed
                FROM decision_history
                WHERE created_at >= datetime('now', ? || ' days')
                  AND outcome_approved != -1
                GROUP BY channel
                """,
                (f"-{days}",),
            ).fetchall()
            result: dict[str, float] = {}
            for r in rows:
                total = r["total"] or 0
                failed = r["failed"] or 0
                result[r["channel"]] = round(failed / total, 4) if total > 0 else 0.0
            return result
        except sqlite3.Error as exc:
            logger.error("get_channel_failure_rates failed: %s", exc)
            return {}


# ===================================================================
# Rule-Based Decider (Fallback)
# ===================================================================


class RuleBasedDecider:
    """Deterministic decision logic -- no external API calls.

    Used as fallback when AI is unavailable, or for nodes that are
    simple enough to not need AI (e.g. publish count, channel selection).
    """

    # Publish quotas by account level
    QUOTAS: dict[str, dict[str, int]] = {
        "V1_new": {"daily_max": 7},   # days 1-3
        "V1":     {"daily_max": 3},   # days 4+
        "V2":     {"daily_max": 5},
        "V3":     {"daily_max": 5},
        "V4+":    {"daily_max": 20},
    }

    def select_drama(
        self,
        available_dramas: list[dict],
        account_history: list[dict],
        account_level: str,
    ) -> dict | None:
        """Pick the highest-score drama not yet published by this account.

        For new accounts (V1), prefer hot dramas (high score).
        For mature accounts (V3+), prefer high-CPM dramas.
        """
        if not available_dramas:
            return None

        # Dramas already used by this account
        used_names = {h.get("drama_name") for h in account_history if h.get("drama_name")}

        # Filter to unused dramas
        candidates = [d for d in available_dramas if d.get("name") not in used_names]

        # If all used, allow repeats but prefer least-used
        if not candidates:
            candidates = sorted(available_dramas, key=lambda d: d.get("times_used", 0))

        if not candidates:
            return None

        # Sorting key depends on account maturity
        if account_level in ("V3", "V4+"):
            # Mature accounts: prioritize CPM
            candidates.sort(key=lambda d: d.get("avg_cpm", 0), reverse=True)
        else:
            # New / growing accounts: prioritize hot score
            candidates.sort(key=lambda d: d.get("score", 0), reverse=True)

        return candidates[0]

    def select_strategy(
        self,
        available_strategies: list[dict],
        account_id: str,
        drama_name: str | None,
    ) -> str:
        """Pick strategy with highest approval rate, or random if no data.

        Different accounts publishing the same drama should use different
        strategies, but without global state here we just pick the best.
        """
        if not available_strategies:
            return "mode6"

        # Sort by approval rate descending, then by weight
        ranked = sorted(
            available_strategies,
            key=lambda s: (s.get("approval_rate", 0), s.get("weight", 0)),
            reverse=True,
        )

        # If top strategies are close in rate, add randomness
        top_rate = ranked[0].get("approval_rate", 0)
        close_candidates = [
            s for s in ranked
            if abs(s.get("approval_rate", 0) - top_rate) < 0.05
        ]

        if len(close_candidates) > 1:
            chosen = random.choice(close_candidates)
        else:
            chosen = ranked[0]

        return chosen.get("name", "mode6")

    def decide_publish_count(
        self,
        account_level: str,
        account_age_days: int,
        today_published: int,
    ) -> int:
        """Compute how many more videos to publish today."""
        # Determine effective level key
        if account_level == "V1" and account_age_days <= 3:
            key = "V1_new"
        elif account_level in self.QUOTAS:
            key = account_level
        else:
            key = "V1"

        daily_max = self.QUOTAS[key]["daily_max"]
        remaining = max(0, daily_max - today_published)
        return remaining

    def decide_channel(self, channel_failure_rates: dict[str, float]) -> str:
        """Choose publish channel based on recent failure rates.

        If API failure rate exceeds 30%, switch to Selenium.
        """
        api_fail = channel_failure_rates.get("api", 0.0)
        if api_fail > 0.30:
            logger.info(
                "API failure rate %.1f%% > 30%% -- switching to selenium",
                api_fail * 100,
            )
            return "selenium"
        return "api"


# ===================================================================
# LangGraph Node Functions
# ===================================================================

# These are module-level functions that the StateGraph calls.
# Each receives and returns a DecisionState dict.

_llm: LLMClient | None = None
_rules: RuleBasedDecider = RuleBasedDecider()
_memory: DecisionMemory | None = None
_mode: str = "hybrid"


def _build_history_context(state: DecisionState) -> str:
    """Format historical data into a readable string for AI prompts."""
    hist = state.get("historical_data", {})
    if not hist:
        return "No historical data available."

    parts: list[str] = []
    for key, val in hist.items():
        if isinstance(val, list):
            parts.append(f"{key}: {json.dumps(val, ensure_ascii=False)[:500]}")
        elif isinstance(val, dict):
            parts.append(f"{key}: {json.dumps(val, ensure_ascii=False)[:500]}")
        else:
            parts.append(f"{key}: {val}")
    return "\n".join(parts)


def select_drama_node(state: DecisionState) -> dict:
    """Node 1: Select which drama to publish for this account."""
    account_id = state.get("account_id", "unknown")
    account_level = state.get("account_level", "V1")
    dramas = state.get("available_dramas", [])
    history = state.get("historical_data", {})
    account_history = history.get("recent_decisions", [])

    reasoning_parts: list[str] = []
    selected: dict | None = None

    # Try AI if mode allows
    if _mode in ("ai", "hybrid") and _llm and _llm.available and dramas:
        system_prompt = (
            "You are a decision engine for a video publishing platform. "
            "You select which drama a specific account should publish next. "
            "Respond with ONLY a JSON object: {\"drama_name\": \"...\", \"reason\": \"...\"}"
        )
        user_prompt = (
            f"Account: {state.get('account_name', account_id)} "
            f"(level={account_level}, age={state.get('account_age_days', 0)} days)\n"
            f"Already published today: {state.get('today_published', 0)}\n"
            f"Available dramas: {json.dumps(dramas, ensure_ascii=False)[:2000]}\n"
            f"Account history: {json.dumps(account_history, ensure_ascii=False)[:1000]}\n\n"
            "Rules:\n"
            "- Hot dramas (high score) for new accounts\n"
            "- High-CPM dramas for mature accounts (V3+)\n"
            "- Avoid dramas this account already published\n"
            "- Avoid oversaturated dramas (high times_used across all accounts)\n"
            "Which drama should this account publish? Respond JSON only."
        )

        ai_result = _llm.chat_json(system_prompt, user_prompt)
        if ai_result and "drama_name" in ai_result:
            chosen_name = ai_result["drama_name"]
            # Find matching drama in available list
            for d in dramas:
                if d.get("name") == chosen_name:
                    selected = d
                    break
            if selected:
                reasoning_parts.append(f"[AI] {ai_result.get('reason', 'AI selected')}")
            else:
                reasoning_parts.append(
                    f"[AI] Suggested '{chosen_name}' but not found in available list -- falling back to rules"
                )

    # Fallback to rules
    if selected is None:
        selected = _rules.select_drama(dramas, account_history, account_level)
        if selected:
            reasoning_parts.append(
                f"[RULES] Selected '{selected.get('name')}' "
                f"(score={selected.get('score', 0)}, cpm={selected.get('avg_cpm', 0)})"
            )
        else:
            reasoning_parts.append("[RULES] No drama available for selection")

    return {
        "selected_drama": selected,
        "reasoning": "; ".join(reasoning_parts),
    }


def select_strategy_node(state: DecisionState) -> dict:
    """Node 2: Select dedup strategy for the chosen drama."""
    strategies = state.get("available_strategies", [])
    account_id = state.get("account_id", "unknown")
    drama = state.get("selected_drama")
    drama_name = drama.get("name", "unknown") if drama else "unknown"

    reasoning_parts: list[str] = []
    selected_strategy: str = "mode6"

    # Try AI in full AI mode
    if _mode == "ai" and _llm and _llm.available and strategies:
        system_prompt = (
            "You are a dedup strategy selector. Different accounts publishing "
            "the same drama MUST use different strategies to avoid detection. "
            "Respond with ONLY a JSON object: {\"strategy\": \"...\", \"reason\": \"...\"}"
        )
        user_prompt = (
            f"Account: {account_id}\n"
            f"Drama: {drama_name}\n"
            f"Available strategies: {json.dumps(strategies, ensure_ascii=False)[:1500]}\n"
            "Pick the best strategy. Respond JSON only."
        )
        ai_result = _llm.chat_json(system_prompt, user_prompt)
        if ai_result and "strategy" in ai_result:
            selected_strategy = ai_result["strategy"]
            reasoning_parts.append(f"[AI] {ai_result.get('reason', 'AI selected')}")
        else:
            selected_strategy = _rules.select_strategy(strategies, account_id, drama_name)
            reasoning_parts.append(f"[RULES] Fallback -- selected '{selected_strategy}'")
    else:
        selected_strategy = _rules.select_strategy(strategies, account_id, drama_name)
        reasoning_parts.append(f"[RULES] Selected strategy '{selected_strategy}'")

    # Append to existing reasoning
    prev_reasoning = state.get("reasoning", "")
    combined = prev_reasoning + "; " + "; ".join(reasoning_parts) if prev_reasoning else "; ".join(reasoning_parts)

    return {
        "selected_strategy": selected_strategy,
        "reasoning": combined,
    }


def decide_publish_node(state: DecisionState) -> dict:
    """Node 3: Decide how many videos to publish."""
    account_level = state.get("account_level", "V1")
    age_days = state.get("account_age_days", 0)
    today_pub = state.get("today_published", 0)

    reasoning_parts: list[str] = []

    # Try AI in full AI mode
    count: int | None = None
    if _mode == "ai" and _llm and _llm.available:
        now_str = datetime.now().strftime("%H:%M")
        system_prompt = (
            "You decide how many videos an account should publish. "
            "Respond with ONLY a JSON object: {\"count\": N, \"reason\": \"...\"}"
        )
        user_prompt = (
            f"Account level: {account_level}, age: {age_days} days\n"
            f"Already published today: {today_pub}\n"
            f"Current time: {now_str}\n"
            "Quotas: V1(d1-3)=7/day, V1(d4+)=3/day, V2=5, V3=5, V4+=20\n"
            "How many more should we publish? Respond JSON only."
        )
        ai_result = _llm.chat_json(system_prompt, user_prompt)
        if ai_result and "count" in ai_result:
            try:
                count = int(ai_result["count"])
                reasoning_parts.append(f"[AI] {ai_result.get('reason', 'AI decided')}")
            except (ValueError, TypeError):
                count = None

    if count is None:
        count = _rules.decide_publish_count(account_level, age_days, today_pub)
        reasoning_parts.append(
            f"[RULES] level={account_level} age={age_days}d "
            f"published={today_pub} -> {count} remaining"
        )

    prev_reasoning = state.get("reasoning", "")
    combined = prev_reasoning + "; " + "; ".join(reasoning_parts) if prev_reasoning else "; ".join(reasoning_parts)

    return {
        "publish_count": max(0, count),
        "reasoning": combined,
    }


def decide_channel_node(state: DecisionState) -> dict:
    """Node 4: Choose publish channel (API vs. Selenium).

    This is always rule-based -- no AI needed for a simple threshold check.
    """
    history = state.get("historical_data", {})
    failure_rates = history.get("channel_failure_rates", {})

    channel = _rules.decide_channel(failure_rates)

    prev_reasoning = state.get("reasoning", "")
    api_rate = failure_rates.get("api", 0)
    sel_rate = failure_rates.get("selenium", 0)
    note = f"[RULES] channel={channel} (api_fail={api_rate:.0%}, sel_fail={sel_rate:.0%})"
    combined = prev_reasoning + "; " + note if prev_reasoning else note

    return {
        "publish_channel": channel,
        "reasoning": combined,
    }


# ===================================================================
# Graph Builder
# ===================================================================


def _build_graph() -> Any:
    """Construct the LangGraph StateGraph for the decision pipeline.

    Returns the compiled graph, or None if LangGraph is not available.
    """
    if not LANGGRAPH_AVAILABLE:
        return None

    graph = StateGraph(DecisionState)

    graph.add_node("select_drama", select_drama_node)
    graph.add_node("select_strategy", select_strategy_node)
    graph.add_node("decide_publish", decide_publish_node)
    graph.add_node("decide_channel", decide_channel_node)

    graph.set_entry_point("select_drama")
    graph.add_edge("select_drama", "select_strategy")
    graph.add_edge("select_strategy", "decide_publish")
    graph.add_edge("decide_publish", "decide_channel")
    graph.add_edge("decide_channel", END)

    memory = MemorySaver()
    compiled = graph.compile(checkpointer=memory)
    logger.info("LangGraph decision pipeline compiled successfully")
    return compiled


# ===================================================================
# Main Engine
# ===================================================================


class DecisionEngine:
    """Production-grade AI decision engine for the KS184 publish workflow.

    Orchestrates drama selection, strategy picking, publish count, and
    channel routing using a LangGraph state graph with DeepSeek AI and
    rule-based fallbacks.

    Args:
        db_manager: An instance of core.db_manager.DBManager.
        strategy_tracker: An instance of strategies.tracker.StrategyTracker.
        llm_provider: Which LLM provider to use. None = auto-detect.
            "codex"    -- GPT-5.4 via SwarmClaw/Hermes (free, local)
            "openclaw" -- GPT-5.4 via OpenClaw gateway (free, local)
            "deepseek" -- DeepSeek V3.2 ($0.14/M tokens)
            "openai"   -- OpenAI direct API
        api_key: Optional explicit API key (overrides auto-detection).
        mode: One of "ai", "rules", or "hybrid" (default).
            - "ai":     all nodes attempt LLM first
            - "rules":  pure rule-based, no API calls
            - "hybrid": AI for drama selection, rules for everything else
    """

    def __init__(
        self,
        db_manager: Any,
        strategy_tracker: Any,
        llm_provider: str | None = None,
        api_key: str | None = None,
        mode: Literal["ai", "rules", "hybrid"] = "hybrid",
    ) -> None:
        global _llm, _rules, _memory, _mode

        self.db = db_manager
        self.tracker = strategy_tracker
        self.mode = mode
        _mode = mode

        # Decision memory (self-learning storage)
        self.memory = DecisionMemory(db_manager)
        _memory = self.memory

        # AI client -- auto-detects: Codex → OpenClaw → DeepSeek → OpenAI
        if mode != "rules":
            self.llm = LLMClient(provider=llm_provider, api_key=api_key)
        else:
            self.llm = LLMClient(provider="__none__")  # won't connect
        _llm = self.llm

        # Rule-based fallback
        self.rules = RuleBasedDecider()
        _rules = self.rules

        # LangGraph pipeline
        self.graph = _build_graph()
        if self.graph is None:
            logger.info("Running in sequential mode (no LangGraph)")

        logger.info(
            "DecisionEngine initialized: mode=%s, ai=%s, langgraph=%s",
            mode,
            self.llm.available,
            self.graph is not None,
        )

    # ------------------------------------------------------------------
    # State Preparation
    # ------------------------------------------------------------------

    def _build_initial_state(self, account_id: str) -> DecisionState:
        """Gather all inputs needed for the decision pipeline.

        Pulls account info from the DB, available dramas, strategies,
        and historical performance data.
        """
        # Account info
        accounts = self.db.get_all_accounts()
        account = next((a for a in accounts if a.get("account_id") == account_id), None)

        account_name = account.get("account_name", account_id) if account else account_id

        # TODO: account_level and account_age_days should come from DB
        # For now, default to V1 / 0 -- caller can override
        account_level = "V1"
        account_age_days = 0

        # Available dramas from drama_links
        drama_rows = self.db.get_drama_links(status="pending")
        available_dramas: list[dict] = []
        drama_usage = self.memory.get_drama_usage_counts()

        for row in drama_rows:
            name = row.get("drama_name", "")
            available_dramas.append({
                "name": name,
                "url": row.get("drama_url", ""),
                "score": row.get("score", 50),
                "times_used": drama_usage.get(name, 0),
                "avg_cpm": row.get("avg_cpm", 0),
            })

        # Available strategies from tracker
        strat_stats = self.tracker.get_strategy_stats()
        strat_weights = self.tracker.get_strategy_weights()
        available_strategies: list[dict] = []
        for name, stats in strat_stats.items():
            available_strategies.append({
                "name": name,
                "approval_rate": stats.get("approval_rate", 0),
                "avg_views": stats.get("avg_views", 0),
                "weight": strat_weights.get(name, 0.5),
            })
        # Ensure at least mode6 exists
        if not available_strategies:
            available_strategies.append({
                "name": "mode6",
                "approval_rate": 0.5,
                "avg_views": 0,
                "weight": 1.0,
            })

        # Today's publish count from execution logs
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_published = 0
        try:
            row = self.db.conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM account_drama_execution_logs
                WHERE kuaishou_uid = ?
                  AND created_at LIKE ?
                  AND status = 'success'
                """,
                (account_id, f"{today_str}%"),
            ).fetchone()
            if row:
                today_published = row["cnt"] or 0
        except Exception as exc:
            logger.warning("Failed to count today's publishes: %s", exc)

        # Historical data for AI context
        recent_decisions = self.memory.get_account_history(account_id)
        channel_failure_rates = self.memory.get_channel_failure_rates()

        historical_data: dict[str, Any] = {
            "recent_decisions": recent_decisions,
            "channel_failure_rates": channel_failure_rates,
            "overall_stats": self.memory.get_overall_stats(),
        }

        state: DecisionState = {
            "account_id": account_id,
            "account_name": account_name,
            "account_level": account_level,
            "account_age_days": account_age_days,
            "today_published": today_published,
            "available_dramas": available_dramas,
            "available_strategies": available_strategies,
            "historical_data": historical_data,
            # Outputs will be filled by nodes
            "selected_drama": None,
            "selected_strategy": "mode6",
            "publish_count": 0,
            "publish_channel": "api",
            "reasoning": "",
        }

        return state

    # ------------------------------------------------------------------
    # Pipeline Execution
    # ------------------------------------------------------------------

    def _run_sequential(self, state: DecisionState) -> DecisionState:
        """Execute the decision pipeline sequentially (no LangGraph)."""
        result = dict(state)

        for node_fn in [
            select_drama_node,
            select_strategy_node,
            decide_publish_node,
            decide_channel_node,
        ]:
            try:
                updates = node_fn(result)  # type: ignore[arg-type]
                result.update(updates)
            except Exception as exc:
                logger.error("Node %s failed: %s", node_fn.__name__, exc)
                # Continue with defaults rather than crashing

        return result  # type: ignore[return-value]

    def _run_graph(self, state: DecisionState) -> DecisionState:
        """Execute the decision pipeline via LangGraph."""
        config = {
            "configurable": {
                "thread_id": f"decision_{state['account_id']}_{int(time.time())}",
            }
        }
        try:
            final_state = self.graph.invoke(state, config=config)
            return final_state
        except Exception as exc:
            logger.error("LangGraph execution failed: %s -- falling back to sequential", exc)
            return self._run_sequential(state)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide_for_account(
        self,
        account_id: str,
        account_level: str | None = None,
        account_age_days: int | None = None,
    ) -> DecisionResult:
        """Get a full publish plan for one account.

        Args:
            account_id: The account to decide for.
            account_level: Override the auto-detected level (V1/V2/V3/V4+).
            account_age_days: Override the auto-detected age.

        Returns:
            A DecisionResult with all decisions and reasoning.
        """
        logger.info("--- Deciding for account: %s ---", account_id)
        t0 = time.time()

        # Build state
        state = self._build_initial_state(account_id)

        # Allow caller overrides
        if account_level is not None:
            state["account_level"] = account_level
        if account_age_days is not None:
            state["account_age_days"] = account_age_days

        # Execute pipeline
        if self.graph is not None:
            final = self._run_graph(state)
        else:
            final = self._run_sequential(state)

        elapsed = time.time() - t0

        # Build result
        result = DecisionResult(
            account_id=account_id,
            account_name=final.get("account_name", account_id),
            selected_drama=final.get("selected_drama"),
            selected_strategy=final.get("selected_strategy", "mode6"),
            publish_count=final.get("publish_count", 0),
            publish_channel=final.get("publish_channel", "api"),
            reasoning=final.get("reasoning", ""),
        )

        # Persist decision
        drama_name = result.selected_drama.get("name") if result.selected_drama else None
        decision_id = self.memory.record_decision(
            account_id=account_id,
            drama_name=drama_name,
            strategy_name=result.selected_strategy,
            channel=result.publish_channel,
            publish_count=result.publish_count,
            reasoning=result.reasoning,
        )
        result.decision_id = decision_id

        logger.info(
            "Decision for %s completed in %.2fs: drama=%s strategy=%s count=%d channel=%s",
            account_id,
            elapsed,
            drama_name,
            result.selected_strategy,
            result.publish_count,
            result.publish_channel,
        )

        return result

    def decide_batch(
        self,
        account_ids: list[str] | None = None,
    ) -> list[DecisionResult]:
        """Decide for multiple accounts (or all logged-in accounts).

        Args:
            account_ids: Specific accounts to decide for.
                If None, decides for all logged-in accounts.

        Returns:
            A list of DecisionResult objects.
        """
        if account_ids is None:
            accounts = self.db.get_logged_in_accounts()
            account_ids = [a["account_id"] for a in accounts]

        logger.info("Batch decision for %d accounts", len(account_ids))

        results: list[DecisionResult] = []
        for aid in account_ids:
            try:
                result = self.decide_for_account(aid)
                results.append(result)
            except Exception as exc:
                logger.error("Failed to decide for account %s: %s", aid, exc)

        approved = sum(1 for r in results if r.publish_count > 0)
        logger.info(
            "Batch complete: %d/%d accounts have videos to publish",
            approved, len(results),
        )
        return results

    def record_outcome(
        self,
        decision_id: int,
        views: int = 0,
        cpm: float = 0.0,
        approved: int = -1,
    ) -> bool:
        """Record the outcome of a previous decision (called after data collection).

        Args:
            decision_id: The ID returned by decide_for_account.
            views: Total views observed.
            cpm: Revenue per mille.
            approved: 1=approved, 0=rejected, -1=pending.

        Returns:
            True if the outcome was recorded.
        """
        success = self.memory.update_outcome(decision_id, views, cpm, approved)
        if success:
            logger.info(
                "Outcome recorded for decision #%d: views=%d cpm=%.2f approved=%d",
                decision_id, views, cpm, approved,
            )
        return success

    def get_performance_report(self) -> dict[str, Any]:
        """Generate an overall decision quality report.

        Returns:
            Dict with aggregate metrics: total decisions, approval rate,
            average views, average CPM, per-strategy breakdown, and
            per-channel failure rates.
        """
        overall = self.memory.get_overall_stats()
        strat_stats = self.tracker.get_strategy_stats()
        channel_rates = self.memory.get_channel_failure_rates()

        total = overall.get("total_decisions", 0)
        approved = overall.get("total_approved", 0)
        rejected = overall.get("total_rejected", 0)

        report = {
            "total_decisions": total,
            "total_approved": approved,
            "total_rejected": rejected,
            "approval_rate": round(approved / total, 4) if total > 0 else 0.0,
            "avg_views": round(overall.get("avg_views", 0) or 0, 1),
            "avg_cpm": round(overall.get("avg_cpm", 0) or 0, 2),
            "strategy_breakdown": strat_stats,
            "channel_failure_rates": channel_rates,
            "engine_mode": self.mode,
            "ai_available": self.llm.available,
            "langgraph_available": LANGGRAPH_AVAILABLE,
        }

        logger.info(
            "Performance report: %d decisions, %.1f%% approval rate",
            total,
            report["approval_rate"] * 100,
        )
        return report


# ===================================================================
# Self-Test
# ===================================================================


def _self_test() -> None:
    """Run a basic smoke test with an in-memory SQLite database."""
    import sqlite3 as _sqlite3

    print("=" * 60)
    print("DecisionEngine Self-Test")
    print("=" * 60)

    # Create in-memory DB with required tables
    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")

    conn.execute("""
        CREATE TABLE device_accounts (
            id INTEGER PRIMARY KEY,
            device_serial TEXT,
            account_id TEXT,
            account_name TEXT,
            browser_port INTEGER,
            cookies TEXT,
            login_status TEXT DEFAULT 'logged_in',
            kuaishou_uid TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE drama_links (
            id INTEGER PRIMARY KEY,
            drama_name TEXT,
            drama_url TEXT,
            source_file TEXT,
            link_mode TEXT,
            status TEXT,
            score INTEGER DEFAULT 80,
            avg_cpm REAL DEFAULT 0,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE account_drama_execution_logs (
            id INTEGER PRIMARY KEY,
            kuaishou_uid TEXT,
            kuaishou_name TEXT,
            device_serial TEXT,
            drama_name TEXT,
            drama_url TEXT,
            status TEXT,
            video_path TEXT,
            created_at TEXT
        )
    """)

    # Insert test data
    conn.execute(
        "INSERT INTO device_accounts (account_id, account_name, login_status, kuaishou_uid) "
        "VALUES ('test_001', 'TestAccount', 'logged_in', 'test_001')"
    )
    conn.execute(
        "INSERT INTO drama_links (drama_name, drama_url, status, score, avg_cpm) "
        "VALUES ('HotDrama1', 'https://example.com/1', 'completed', 95, 12.5)"
    )
    conn.execute(
        "INSERT INTO drama_links (drama_name, drama_url, status, score, avg_cpm) "
        "VALUES ('MidDrama2', 'https://example.com/2', 'completed', 70, 8.0)"
    )
    conn.execute(
        "INSERT INTO drama_links (drama_name, drama_url, status, score, avg_cpm) "
        "VALUES ('LowDrama3', 'https://example.com/3', 'completed', 40, 3.0)"
    )
    conn.commit()

    # Build a minimal db_manager-like object
    class _MockDB:
        def __init__(self, connection):
            self.conn = connection

        def get_all_accounts(self):
            rows = self.conn.execute("SELECT * FROM device_accounts").fetchall()
            return [dict(r) for r in rows]

        def get_logged_in_accounts(self):
            rows = self.conn.execute(
                "SELECT * FROM device_accounts WHERE login_status = 'logged_in'"
            ).fetchall()
            return [dict(r) for r in rows]

        def get_drama_links(self, status="completed"):
            rows = self.conn.execute(
                "SELECT * FROM drama_links WHERE status = ?", (status,)
            ).fetchall()
            return [dict(r) for r in rows]

    mock_db = _MockDB(conn)

    # Create tracker (it needs the DB for its own tables)
    from strategies.tracker import StrategyTracker
    tracker = StrategyTracker(mock_db)

    # Build engine in rules mode (no API key needed)
    engine = DecisionEngine(
        db_manager=mock_db,
        strategy_tracker=tracker,
        mode="rules",
    )

    print("\n[1] Single account decision:")
    result = engine.decide_for_account("test_001", account_level="V1", account_age_days=2)
    print(f"  Drama:    {result.selected_drama}")
    print(f"  Strategy: {result.selected_strategy}")
    print(f"  Count:    {result.publish_count}")
    print(f"  Channel:  {result.publish_channel}")
    print(f"  Reason:   {result.reasoning}")
    print(f"  ID:       {result.decision_id}")

    print("\n[2] Record outcome:")
    if result.decision_id:
        ok = engine.record_outcome(result.decision_id, views=1500, cpm=10.5, approved=1)
        print(f"  Outcome recorded: {ok}")

    print("\n[3] Batch decision:")
    batch = engine.decide_batch()
    print(f"  Accounts processed: {len(batch)}")

    print("\n[4] Performance report:")
    report = engine.get_performance_report()
    for k, v in report.items():
        print(f"  {k}: {v}")

    print("\n[5] V4+ mature account decision:")
    result2 = engine.decide_for_account("test_001", account_level="V4+", account_age_days=60)
    print(f"  Drama:    {result2.selected_drama}")
    print(f"  Count:    {result2.publish_count}")
    print(f"  Channel:  {result2.publish_channel}")

    conn.close()
    print("\n" + "=" * 60)
    print("Self-test PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
