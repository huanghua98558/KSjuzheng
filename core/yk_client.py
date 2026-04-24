# -*- coding: utf-8 -*-
"""Standalone YK verification client (custom TCP protocol).

After 4 days of Frida + memory analysis, we reverse-engineered the YK
authentication handshake to ZUFN's verification server (210.16.171.50:8003).

Protocol structure (custom binary, NOT HTTPS):
    magic(6) + length(4 LE) + opcode(4) + body

Discovered properties:
    - Each round is its own TCP connection
    - Server is STATELESS per-connection (verified via Round 3 standalone test)
    - Server validates packet structure but not content cryptographically tightly
      (Round 4 accepts any of 3 different memory-extracted tails)
    - Response is non-deterministic (server generates fresh data each call)

Reconstructed packets (from trace + memory scan):
    R1: 149B → returns 655/656B  opcode 776cd553
    R2: 205B → returns 834B      opcode 01000000
    R3: 80B  → returns 14B ack   opcode 01000000
    R4: 99B  → returns 13B ack   opcode 97a932xx

USE CASE: Bypass need for live ZUFN.exe to "speak" to verification server.
We don't need the YK encryption key — server accepts replayed handshake.

Limitations:
    - Cannot verify NEW accounts (would need fresh nonce + valid HMAC)
    - But can confirm "verification succeeded" status to allow further API
"""
from __future__ import annotations

import json
import socket
import struct
import time
from binascii import unhexlify
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TARGET = ("210.16.171.50", 8003)
MAGIC = b"\x01\x02\x04\x02\x05\x04"
DEFAULT_TIMEOUT = 5.0


# ============================================================================
# Reconstructed packet bytes
# ============================================================================
# Round 1: 149B (from trace head_64 + memory body)
R1_PACKET = unhexlify(
    # magic + length(149)
    "010204020504950000005ef9df2f"
    # body bytes 0-49 (from trace)
    "21ec48be298aed98e32cd38e83920f9c768774ac6aa07777"
    "77d9e50b01f0ddcc91f579ad03f273f63b4cb762a259a216"
    "5cde"
    # body bytes 50-134 (from memory @ 0x6a005c8)
    "dd1b944428e94a984c2d1ff0911dc04ceffafde522d4ddc4"
    "3565169c93dfc88734e9ec8d0e5d0466595ea5f9e42d4126"
    "4292803bd979c23aa3b744f92a2199a40012ec86e37c899b"
    "7dc704eaab165c076e21d28051"
)
assert len(R1_PACKET) == 149, f"R1 length wrong: {len(R1_PACKET)}"

# Round 2: 205B (full trace capture, ASCII-hex body)
# Loaded lazily from req_205.bin to avoid string bloat
R2_BIN_PATH = Path(__file__).parent.parent / "tools" / "trace_publish" / "zufn_replay_1776633209" / "req_205.bin"

# Round 3: 80B (full memory capture)
R3_PACKET = unhexlify(
    "010204020504"
    "50000000"
    "45d7be7a"
    "22e92bc2af7e5317da4cd9fe81e308a619fd77ad1fd57578"
    "76dde50973f5a1c8e1857faf77f101843900d966dd29a763"
    "18d8991f980fa433fc77b9d1e42e6c873795"
)
assert len(R3_PACKET) == 80, f"R3 length wrong: {len(R3_PACKET)}"

# Round 4: 99B (trace head_64 + memory tail @ 0x690b278)
R4_PACKET = unhexlify(
    # magic + length(99)
    "010204020504630000005ef9df2f"
    # body bytes 0-49 (from trace)
    "36b05cd0668aa4999624a1fe84de7ca5168d04ae1ba74d18"
    "0ddae47e74f2d2cd95f57bdf068e77864b4ab516a12bd014"
    "10ad"
    # body bytes 50-84 (from memory)
    "946feb4258a306dd3a5b188ae36ec244effcf2e0249e9443"
    "eb9ebc1367506a09af0057"
)
assert len(R4_PACKET) == 99, f"R4 length wrong: {len(R4_PACKET)}"


# ============================================================================
# Round result structure
# ============================================================================
@dataclass
class RoundResult:
    round_num: int
    sent: int
    received: int
    response: bytes
    opcode: str
    declared_len: int
    duration_ms: float
    success: bool
    error: Optional[str] = None

    def to_dict(self):
        return {
            "round": self.round_num,
            "sent_bytes": self.sent,
            "received_bytes": self.received,
            "response_head": self.response[:32].hex() if self.response else "",
            "opcode": self.opcode,
            "declared_len": self.declared_len,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "error": self.error,
        }


# ============================================================================
# TCP transport
# ============================================================================
def _send_one_round(packet: bytes,
                    target: tuple = DEFAULT_TARGET,
                    timeout: float = DEFAULT_TIMEOUT) -> tuple[bytes, str]:
    """Open TCP, send packet, drain response, return (resp, error).

    Server framing: magic(6) + length(4 LE) tells us the response size.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(target)
        s.sendall(packet)
        chunks = []
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                full = b"".join(chunks)
                if len(full) >= 10 and full[:6] == MAGIC:
                    declared = struct.unpack("<I", full[6:10])[0]
                    if len(full) >= declared:
                        break
        except socket.timeout:
            pass
        return b"".join(chunks), ""
    except Exception as e:
        return b"", str(e)
    finally:
        try:
            s.close()
        except Exception:
            pass


def _send_round(round_num: int, packet: bytes,
                target: tuple = DEFAULT_TARGET,
                timeout: float = DEFAULT_TIMEOUT) -> RoundResult:
    """Wrap _send_one_round with parsing into RoundResult."""
    t0 = time.time()
    resp, err = _send_one_round(packet, target, timeout)
    dur_ms = (time.time() - t0) * 1000

    if err or not resp:
        return RoundResult(
            round_num=round_num,
            sent=len(packet),
            received=len(resp),
            response=resp,
            opcode="",
            declared_len=0,
            duration_ms=dur_ms,
            success=False,
            error=err or "no response",
        )

    declared = struct.unpack("<I", resp[6:10])[0] if len(resp) >= 10 else 0
    opcode = resp[10:14].hex() if len(resp) >= 14 else ""
    valid_magic = resp[:6] == MAGIC

    return RoundResult(
        round_num=round_num,
        sent=len(packet),
        received=len(resp),
        response=resp,
        opcode=opcode,
        declared_len=declared,
        duration_ms=dur_ms,
        success=valid_magic and len(resp) >= 10,
    )


# ============================================================================
# Public API
# ============================================================================
def load_r2() -> bytes:
    """Load R2 packet from binary file (full ASCII-hex captured trace)."""
    if not R2_BIN_PATH.exists():
        raise FileNotFoundError(f"R2 binary not found: {R2_BIN_PATH}")
    return R2_BIN_PATH.read_bytes()


def perform_yk_handshake(target: tuple = DEFAULT_TARGET,
                         timeout: float = DEFAULT_TIMEOUT,
                         verbose: bool = False) -> dict:
    """Perform full 4-round YK verification handshake.

    Returns:
        {
            "ok": bool,                 # all 4 rounds succeeded
            "rounds": [4 dicts],
            "duration_ms": float,
            "summary": str,
        }
    """
    t0 = time.time()
    results: list[RoundResult] = []

    r2_bytes = load_r2()

    rounds = [
        (1, R1_PACKET),
        (2, r2_bytes),
        (3, R3_PACKET),
        (4, R4_PACKET),
    ]

    for round_num, packet in rounds:
        if verbose:
            print(f"[R{round_num}] sending {len(packet)}B...")
        result = _send_round(round_num, packet, target, timeout)
        results.append(result)
        if verbose:
            print(f"  ← {result.received}B  opcode={result.opcode}  "
                  f"success={result.success}  ({result.duration_ms:.0f}ms)")
        # Tiny pause between rounds (server may be sensitive)
        time.sleep(0.1)

    total_ms = (time.time() - t0) * 1000
    all_ok = all(r.success for r in results)

    return {
        "ok": all_ok,
        "rounds": [r.to_dict() for r in results],
        "duration_ms": round(total_ms, 2),
        "summary": (
            f"4-round YK handshake {'✓ SUCCESS' if all_ok else '✗ FAILED'} "
            f"({total_ms:.0f}ms): "
            + " ".join(f"R{r.round_num}={r.received}B" for r in results)
        ),
    }


def is_yk_server_online(target: tuple = DEFAULT_TARGET,
                       timeout: float = 3.0) -> bool:
    """Quick connectivity check: send R3 (smallest, stateless) and verify ack."""
    result = _send_round(3, R3_PACKET, target, timeout)
    # R3 expected response: 14B with valid magic
    return result.success and result.received >= 13


# ============================================================================
# CLI
# ============================================================================
if __name__ == "__main__":
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="210.16.171.50:8003")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--ping", action="store_true",
                    help="Quick connectivity check only (R3)")
    ap.add_argument("--json", action="store_true",
                    help="Output JSON only")
    args = ap.parse_args()

    host, port = args.target.split(":")
    target = (host, int(port))

    if args.ping:
        ok = is_yk_server_online(target, args.timeout)
        if args.json:
            print(json.dumps({"online": ok, "target": args.target}))
        else:
            print(f"YK server {args.target}: {'✓ ONLINE' if ok else '✗ OFFLINE'}")
        sys.exit(0 if ok else 1)

    result = perform_yk_handshake(target, args.timeout, verbose=not args.json)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print()
        print("=" * 60)
        print(result["summary"])
        print("=" * 60)
        for r in result["rounds"]:
            mark = "✓" if r["success"] else "✗"
            print(f"  {mark} R{r['round']}: sent={r['sent_bytes']:>3}B  "
                  f"recv={r['received_bytes']:>3}B  "
                  f"opcode={r['opcode']}  "
                  f"({r['duration_ms']:.0f}ms)")
            if r["error"]:
                print(f"      error: {r['error']}")

    sys.exit(0 if result["ok"] else 1)
