# 快手短剧 AI 矩阵运营系统 — 授权架构蓝图

> **目的**: 把 KS184 反编译学到的授权设计模式, **抽象成可复用的企业级架构**, 给未来 APP 做技术文档储备.
>
> **写给未来的你**: 不是抄 KS184, 是**挑出好的丢掉差的**, 用现代标准重新设计.
>
> **生成**: 2026-04-19
> **版本**: v1.0
> **前置阅读**:
> - `KS184_REGISTRATION_KEYGEN_ANALYSIS.md` (KS184 注册码机制详解)
> - `KS184_ZUFN_DECOMPILE.md` + `KS184_Q_X64_DECOMPILE.md`
> - 本项目现有 `core/auth.py`, `core/app_config.py`, `core/switches.py`

---

# Part I — 从 KS184 学到的 5 个核心设计模式

## 模式 1: 壳层 + 业务层分离 ⭐⭐⭐⭐⭐

**KS184 做法**:
```
ZUFN.exe (壳)          ──→  校验许可证 + 反调试 + 反 VM
     │
     └── 派生 ──→  Q_x64.dll (业务)  ──→  服务器二次验证 + 业务逻辑
```

**核心思想**: **授权验证 ≠ 业务执行**. 两者应该分离到 **不同的进程/模块**, 用 **IPC/HTTP** 连接.

**为什么好**:
- 攻击面分散: 攻击者必须同时攻破两个进程
- 业务代码和授权代码独立迭代
- 可以把授权代码做得非常小, 集中加保护
- 业务代码体积大, 只用轻量保护即可

**反面教材**: 授权代码混在业务里, 攻击者 patch 一个 `if is_licensed():` 就破了.

**我们应该学**: ✅ **保留这个模式**. 未来 APP 做成 client + license-service 两端架构.

---

## 模式 2: 双密钥 HMAC 防篡改 ⭐⭐⭐⭐⭐

**KS184 做法**:
```python
_HMAC_SECRET         = b"REPLACE_WITH_HMAC_SECRET"   # 请求签名
_MCN_RESPONSE_SECRET = b"REPLACE_WITH_MCN_RESP_SECRET"    # 响应签名
```

**两把钥匙**:
1. 请求密钥: 客户端 → 服务端, 防重放 + 防伪造
2. 响应密钥: 服务端 → 客户端, 防中间人伪造 "已激活" 响应

**为什么好**: 中间人攻击 (MITM) 必须同时拿到两把钥匙. 拿一把只能伪造一个方向.

**我们应该学**: ✅ **全盘保留**. 但是升级到非对称签名 (Ed25519) 更强.

---

## 模式 3: 服务端唯一真源 ⭐⭐⭐⭐⭐

**KS184 做法**: 本地只存一个短 token (`YK40AFF617...`), 真正的授权状态在 `m.zhongxiangbao.com` 数据库.

**为什么好**:
- 远程吊销: 任何时候作者可把 card_no 拉黑
- 审计: 谁在用、几台机器、什么时间, 服务器全知道
- 动态限额: 服务器说"你这个月最多发 100 条", 客户端无权反驳
- 防共享: 两人用同一 key, 服务器看到两个 HWID, 可以拒绝

**代价**:
- 必须联网 (KS184 也是必须联网)
- 服务器挂了全部客户端瘫

**我们应该学**: ✅ **加强**: 服务端必须高可用 (双区域 + CDN + Redis 缓存).

---

## 模式 4: 硬件指纹容错 ⭐⭐⭐⭐

**KS184 做法**: 5 因子 HWID (SMBIOS + CPUID + Disk + MAC + MachineGuid), 5 级容差 (`HARDWARE_ID_OUT_OF_TOLERANCE`).

**为什么好**: 死绑 HWID 会导致客户换个网卡就要找你解绑, 售后成本高. 容错让硬件小改动不触发重绑.

**我们应该学**: ⚠️ **改良**. 
- 不用 SMBIOS (太依赖厂商填值, 云主机/虚拟机经常相同)
- 核心 3 因子: `MachineGuid` (Windows 注册表 UUID) + `DiskSerial` (C 盘) + `CPUID`
- 容差 1/3 (允许 1 个变)
- 新增: **加一个 user-scope 因子** (Windows 账号 SID), 防"同机多人用"

---

## 模式 5: 代码保护三层次 ⭐⭐⭐

**KS184 做法**:
1. 外壳: Oreans WinLicense ($299 商业) — 反调试 + 反 VM + 代码虚拟化
2. 业务: PyArmor — Python bytecode 保护 + co_consts 清空
3. 数据: 加密存储 (WLTrialStringWrite 等)

**我们应该学**:
- **Tier 1 (入门, 免费)**: PyArmor 基础版, 足够挡住 90% 业余逆向
- **Tier 2 (进阶, 低成本)**: Nuitka 编译到 C (完全丢掉 Python 源码痕迹), 免费
- **Tier 3 (商业级, 贵)**: WinLicense / VMProtect ($300-$800), 只在 $1000+ 客单价产品上用

**选型建议**: 我们 **一开始用 Tier 2 (Nuitka)** — 性价比最高.

---

# Part II — 未来 APP 授权架构蓝图

## 0. 总览架构图

```
┌──────────────────────────────────────────────────────────────┐
│                     客户端 (用户电脑)                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  AI Matrix Client (Nuitka 编译后 .exe)                 │ │
│  │                                                        │ │
│  │  启动 → LicenseAgent → HMAC 签名请求                  │ │
│  │         ↓ (HTTPS + cert pinning)                      │ │
│  └────────────────────────────────────────────────────────┘ │
│                        ↓                                     │
└────────────────────────┼─────────────────────────────────────┘
                         │ TLS 1.3
                         │
┌────────────────────────┼─────────────────────────────────────┐
│                  License Service (我们的云)                   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Cloudflare WAF / DDoS 前置                            │ │
│  │             ↓                                           │ │
│  │  FastAPI License Server (单独部署)                      │ │
│  │    ├── /v1/activate    (激活)                          │ │
│  │    ├── /v1/verify      (验证)                          │ │
│  │    ├── /v1/renew       (续签)                          │ │
│  │    ├── /v1/revoke      (吊销)                          │ │
│  │    └── /v1/heartbeat   (心跳统计)                      │ │
│  │             ↓                                           │ │
│  │  PostgreSQL (主库) + Redis (速率限制/缓存)              │ │
│  │             ↓                                           │ │
│  │  Secrets: AWS KMS / HashiCorp Vault / Age             │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## 1. 核心架构决策表

| 决策点 | 选择 | 原因 | 代替方案 |
|---|---|---|---|
| 客户端打包 | **Nuitka → .exe** | 编译到 C, 无 .py 源码; 免费; 启动快 | PyInstaller (被反编译烂了), PyArmor only |
| 外壳保护 | **不加商业壳** (前期); 后期可选 VMProtect | WinLicense $299 太贵, 首版没必要 | WinLicense, Themida |
| 授权 Token 格式 | **PASETO v4 (public)** | 比 JWT 安全, 默认 Ed25519 签名 | JWT + RS256, 自定义 TLV |
| 数字签名算法 | **Ed25519** | 小 (32B 公钥), 快, 抗 side-channel | RSA-2048, ECDSA P-256 |
| 对称加密 | **ChaCha20-Poly1305** | AEAD, 性能好, 无时序攻击 | AES-256-GCM |
| 密钥派生 | **Argon2id** (凭证) + **HKDF-SHA256** (派生) | 现代标准 | PBKDF2, bcrypt |
| 硬件指纹 | **3 因子 + 1/3 容差** | 平衡安全 vs 用户体验 | WinLicense 5 因子 |
| 服务端语言 | **Python + FastAPI** | 和客户端同栈, 复用代码 | Go, Node |
| 服务端数据库 | **PostgreSQL** | 多租户 RLS 原生支持; JSONB | SQLite (首版可以) |
| 缓存 | **Redis** | 速率限制 + session + 心跳聚合 | 内存 |
| TLS | **TLS 1.3 + cert pinning** | 防 MITM | 单纯 HTTPS |
| 本地存储 | **SQLCipher** (加密 SQLite) | 本地状态防篡改 | 明文 |
| License 颁发 | **试用 7 天 + 付费 30/90/365 天** | 行业标准 | 永久授权 |
| 吊销方式 | **服务端黑名单 + 客户端 TTL 短签** | 无需本地同步黑名单 | CRL, OCSP |

## 2. 四大核心模块设计

### 2.1 License Token — 用 PASETO v4 取代 JWT

**为什么不用 JWT**:
- JWT 有 `alg=none` 和 `HS256 vs RS256` 混淆漏洞
- JWT 默认不加密 payload
- JWT 头信息标准混乱 (kid/alg/typ 各家实现不一)

**为什么用 PASETO**:
- 固定版本号, 无算法协商 (防降级攻击)
- v4.public = Ed25519 签名 + 不加密 payload (license 场景, 内容不需要保密)
- v4.local = XChaCha20-Poly1305 + PRK (加密场景)
- 失败路径少: 实现不出错

**License Token 结构 (PASETO v4.public)**:

```python
# Payload (JSON, 签名但不加密)
{
  "iss": "license.our-domain.com",        # 签发方
  "sub": "user:12345",                     # 用户 UUID
  "aud": "ai-matrix-client",               # 受众
  "jti": "lic_abc123",                     # Token 唯一 ID (可吊销)
  "iat": 1735689600,                       # 签发时间
  "nbf": 1735689600,                       # 生效时间
  "exp": 1735776000,                       # 过期时间 (24h 短签)
  "license_id": "LIC-2026-00042",          # 人类可读 license 编号
  "tenant_id": "ten_xyz",                  # 租户 UUID
  "plan": "pro",                           # 订阅套餐 (free/pro/enterprise)
  "hwid": "hash_of_hardware",              # HWID 绑定 (可选)
  "features": ["matrix", "ai-planner"],   # 功能开关
  "quotas": {
    "max_accounts": 20,                    # 最多 20 个快手号
    "max_publishes_per_day": 200,          # 每日最多 200 条
    "max_storage_gb": 100
  },
  "commission_rate": 0.80,                 # 分成比例
  "metadata": {
    "issued_to": "黄老板",
    "phone": "+86REPLACE_WITH_YOUR_PHONE",
    "original_plan_ts": 1700000000         # 初次激活时间
  }
}

# 最终 token 形态:
# v4.public.eyJ...base64url_payload...eyJ....base64url_sig
# 总长度 ~ 600-800 字符
```

**关键设计**:
- **exp = 24h**: 短签. 破解也只能用 24h
- **jti**: 每次续签换 jti, 服务端维护黑名单 (Redis SET, TTL=48h 即可, 因为超 24h 过期自动失效)
- **hwid**: 可选. 服务端首次激活记录 HWID, 续签时比对, 超容差拒绝
- **features + quotas**: 颗粒度细, 服务端一处改全局生效

### 2.2 硬件指纹 — 3 因子平衡方案

```python
# core/license/hwid.py
import hashlib, subprocess, winreg

def compute_hwid() -> dict:
    """返回 3 个独立因子 + 合成 hash"""
    factors = {}
    
    # 因子 1: Windows MachineGuid (注册表 UUID, 重装系统才变)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                            r"SOFTWARE\Microsoft\Cryptography") as key:
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        factors["machine_guid"] = hashlib.sha256(machine_guid.encode()).hexdigest()[:16]
    except Exception:
        factors["machine_guid"] = None
    
    # 因子 2: C 盘 VolumeSerial (格式化才变)
    try:
        out = subprocess.check_output("vol C:", shell=True, text=True)
        # "卷 C: 的序列号是 A1B2-C3D4"
        serial = out.strip().split()[-1].replace("-", "")
        factors["disk_serial"] = hashlib.sha256(serial.encode()).hexdigest()[:16]
    except Exception:
        factors["disk_serial"] = None
    
    # 因子 3: CPU ID (vendor + family/model/stepping, 换 CPU 才变)
    try:
        out = subprocess.check_output(
            'wmic cpu get ProcessorId /value', shell=True, text=True)
        cpu_id = out.strip().split("=")[-1]
        factors["cpu_id"] = hashlib.sha256(cpu_id.encode()).hexdigest()[:16]
    except Exception:
        factors["cpu_id"] = None
    
    # 合成: 3 个因子拼接 → SHA-256
    concat = "|".join([factors.get(k, "MISSING") for k in 
                       ["machine_guid", "disk_serial", "cpu_id"]])
    factors["combined"] = hashlib.sha256(concat.encode()).hexdigest()
    
    return factors

def hwid_matches(stored: dict, current: dict, tolerance: int = 1) -> bool:
    """容差比对: 3 个因子中允许 `tolerance` 个变动"""
    changed = sum(
        1 for k in ["machine_guid", "disk_serial", "cpu_id"]
        if stored.get(k) != current.get(k)
    )
    return changed <= tolerance
```

**用户换硬盘会怎样?**
- 重装系统 + 换硬盘 = 2 个因子变了 → 超容差 → 需要联系客服重新激活
- 只换硬盘 (不重装) = disk_serial 变但 machine_guid 不变 = 1 个因子变 → 通过
- 只换 CPU = cpu_id 变 = 1 个因子变 → 通过

### 2.3 激活/验证 API 契约

#### `POST /v1/activate` — 首次激活

```http
POST /v1/activate HTTP/1.1
Host: license.our-domain.com
Content-Type: application/json
X-Client-Version: 1.0.0
X-Request-Id: <uuidv4>

{
  "activation_code": "AMX-2026-ABCDEF123456",
  "hwid": {
    "machine_guid": "a1b2c3d4e5f6...",
    "disk_serial": "...",
    "cpu_id": "...",
    "combined": "..."
  },
  "client_info": {
    "os": "Windows 10 22H2",
    "python_version": "3.12.3",
    "app_version": "1.0.0",
    "hostname_hash": "sha256_of_hostname"
  },
  "timestamp": 1735689600000,
  "nonce": "<32 hex chars>",
  "sig": "<HMAC-SHA256 of above fields with PRE_SHARED_KEY>"
}
```

**PRE_SHARED_KEY**: 烧在客户端二进制里 (打包时注入), 用于请求阶段的 HMAC. 每个大版本轮换. 作用: 防止非我们客户端的工具刷 API.

**响应 (成功)**:

```json
{
  "status": "ok",
  "license_token": "v4.public.eyJpc3MiOiJsaWNlbnNlLi4u...",
  "refresh_token": "v4.local.abcdef...",
  "expires_at": 1735776000,
  "license_info": {
    "license_id": "LIC-2026-00042",
    "plan": "pro",
    "features": ["matrix", "ai-planner"],
    "quotas": {"max_accounts": 20, "max_publishes_per_day": 200}
  },
  "server_timestamp": 1735689600123,
  "server_sig": "<Ed25519 signature of response with SERVER_PRIVATE_KEY>"
}
```

**响应失败码** (HTTP 状态 + 机器码):

| HTTP | code | 含义 |
|---|---|---|
| 400 | `INVALID_FORMAT` | 激活码格式错 |
| 401 | `SIG_INVALID` | HMAC 签名错 |
| 403 | `CODE_NOT_FOUND` | 激活码不存在 |
| 403 | `CODE_EXPIRED` | 激活码过期 (未激活的) |
| 403 | `HWID_MISMATCH` | 已绑定不同机器 |
| 409 | `ALREADY_ACTIVATED` | 已在别的机器激活 |
| 429 | `RATE_LIMITED` | 频率限制 |
| 500 | `SERVER_ERROR` | 服务器故障 |

#### `POST /v1/verify` — 验证已有 token (每次启动)

```http
POST /v1/verify HTTP/1.1
Content-Type: application/json

{
  "license_token": "v4.public.eyJ...",
  "hwid_combined": "<sha256>",
  "timestamp": 1735689600000,
  "nonce": "...",
  "sig": "<HMAC>"
}
```

**响应 (成功)**:
```json
{
  "status": "ok",
  "remaining_seconds": 2345678,
  "should_renew": false,
  "server_timestamp": 1735689600123,
  "server_sig": "..."
}
```

**响应 (吊销)**:
```json
{
  "status": "revoked",
  "reason": "manual_admin_action",
  "revoked_at": 1735689500,
  "server_timestamp": 1735689600123,
  "server_sig": "..."
}
```

#### `POST /v1/renew` — 续签

```json
{
  "refresh_token": "v4.local.abcdef...",
  "timestamp": ...,
  "nonce": ...,
  "sig": ...
}
```

**核心逻辑**:
- license_token 过期前 6 小时, 客户端主动用 refresh_token 续
- refresh_token 7 天过期 (长于 24h 但比激活码短)
- 服务端续签时重新颁发新 jti (老 jti 加入黑名单)

#### `POST /v1/heartbeat` — 心跳 (可选)

```json
{
  "license_token": "...",
  "usage_stats": {
    "active_accounts": 12,
    "publishes_today": 45,
    "agent_decisions_today": 89
  },
  "timestamp": ..., "nonce": ..., "sig": ...
}
```

**频率**: 1 小时 1 次. 服务端用来:
- 验证实际用量 vs. quota
- 发现单 license 多机共享 (多 IP 同时心跳)
- 计费基础

### 2.4 客户端 LicenseAgent 实现蓝图

```python
# core/license/agent.py
"""
LicenseAgent: 客户端授权代理.

生命周期:
  启动 → load_local() → verify_remote() → watch_expiry()
                              ↓
                       (过期) renew() OR (无效) raise
"""
import asyncio, time, httpx
from pathlib import Path
from typing import Optional

from core.license.crypto import (
    verify_paseto_v4_public, verify_hmac, sign_hmac,
    SERVER_PUBLIC_KEY, CLIENT_HMAC_KEY,
)
from core.license.hwid import compute_hwid, hwid_matches
from core.license.storage import EncryptedLicenseStore
from core.logger import get_logger

log = get_logger(__name__)

class LicenseState:
    NOT_ACTIVATED = "not_activated"
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    REVOKED = "revoked"
    NETWORK_ERROR = "network_error"

class LicenseAgent:
    SERVER_URL = "https://license.our-domain.com"
    STORE_PATH = Path.home() / ".ai-matrix" / "license.db"
    VERIFY_INTERVAL_SEC = 3600  # 1 小时验证一次
    RENEW_BUFFER_SEC = 6 * 3600  # 过期前 6 小时续
    
    def __init__(self):
        self.store = EncryptedLicenseStore(self.STORE_PATH)
        self.state: str = LicenseState.NOT_ACTIVATED
        self.token_payload: Optional[dict] = None
        self._client = httpx.AsyncClient(
            verify=True,  # 不要关 TLS 校验
            timeout=30.0,
            # TODO: 增加 pinned CA
        )

    async def initialize(self) -> str:
        """启动时调: 加载本地 + 远程验证. 返回最终状态."""
        # Step 1: 加载本地持久化 token
        local = self.store.load_license_token()
        if not local:
            self.state = LicenseState.NOT_ACTIVATED
            return self.state

        # Step 2: 本地验签 (Ed25519, 无需联网)
        try:
            payload = verify_paseto_v4_public(local, SERVER_PUBLIC_KEY)
        except Exception as e:
            log.error(f"Local token signature invalid: {e}")
            self.state = LicenseState.NOT_ACTIVATED
            return self.state

        self.token_payload = payload

        # Step 3: 本地过期检查
        now = int(time.time())
        if payload["exp"] < now:
            self.state = LicenseState.EXPIRED
            return self.state

        # Step 4: HWID 检查
        current_hwid = compute_hwid()
        if payload.get("hwid") and not hwid_matches_remote(payload["hwid"], current_hwid):
            log.warning("HWID mismatch, local token likely copied from another machine")
            # 不立即拒绝, 让服务端判断容差
        
        # Step 5: 远程验证 (有网就做, 没网用本地)
        try:
            ok = await self.verify_remote()
            self.state = LicenseState.ACTIVE if ok else LicenseState.REVOKED
        except (httpx.NetworkError, httpx.TimeoutException) as e:
            log.warning(f"Cannot verify remotely: {e}. Using local cache.")
            self.state = LicenseState.ACTIVE  # 宽限: 网络故障不拦
        
        # Step 6: 判断是否需要续签
        if self.state == LicenseState.ACTIVE and \
           payload["exp"] - now < self.RENEW_BUFFER_SEC:
            asyncio.create_task(self.renew())
        
        return self.state

    async def activate(self, activation_code: str) -> bool:
        """用激活码换 license_token + refresh_token."""
        hwid = compute_hwid()
        payload = {
            "activation_code": activation_code.upper().strip(),
            "hwid": hwid,
            "client_info": self._client_info(),
            "timestamp": int(time.time() * 1000),
            "nonce": self._gen_nonce(),
        }
        payload["sig"] = sign_hmac(CLIENT_HMAC_KEY, payload)
        
        resp = await self._client.post(
            f"{self.SERVER_URL}/v1/activate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        # 验证响应签名
        if not verify_hmac(SERVER_PUBLIC_KEY, data):
            raise ValueError("Server response signature invalid — MITM?")
        
        # 持久化 token
        self.store.save_license_token(data["license_token"])
        self.store.save_refresh_token(data["refresh_token"])
        self.state = LicenseState.ACTIVE
        self.token_payload = verify_paseto_v4_public(
            data["license_token"], SERVER_PUBLIC_KEY)
        return True

    async def verify_remote(self) -> bool:
        """远程验证 current token; 返回 True=有效, False=吊销."""
        token = self.store.load_license_token()
        hwid = compute_hwid()["combined"]
        payload = {
            "license_token": token,
            "hwid_combined": hwid,
            "timestamp": int(time.time() * 1000),
            "nonce": self._gen_nonce(),
        }
        payload["sig"] = sign_hmac(CLIENT_HMAC_KEY, payload)
        
        resp = await self._client.post(
            f"{self.SERVER_URL}/v1/verify", json=payload)
        data = resp.json()
        
        if not verify_hmac(SERVER_PUBLIC_KEY, data):
            return False
        
        return data.get("status") == "ok"

    async def renew(self) -> bool:
        """用 refresh_token 换新的 license_token."""
        # ... 同上结构
        pass

    def has_feature(self, feature: str) -> bool:
        if not self.token_payload:
            return False
        return feature in self.token_payload.get("features", [])

    def quota(self, key: str, default=0):
        if not self.token_payload:
            return default
        return self.token_payload.get("quotas", {}).get(key, default)

    def _client_info(self) -> dict:
        import platform, sys
        return {
            "os": f"{platform.system()} {platform.release()}",
            "python_version": sys.version.split()[0],
            "app_version": "1.0.0",
            "hostname_hash": hashlib.sha256(
                platform.node().encode()).hexdigest(),
        }

    def _gen_nonce(self) -> str:
        import secrets
        return secrets.token_hex(16)
```

---

# Part III — 服务端实现蓝图

## 3.1 数据库 Schema (PostgreSQL)

```sql
-- 租户 (企业客户)
CREATE TABLE tenants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    billing_email TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    status       TEXT NOT NULL DEFAULT 'active',  -- active/suspended/deleted
    metadata     JSONB DEFAULT '{}'::jsonb,
    CHECK (status IN ('active','suspended','deleted'))
);

-- 用户 (企业内的座位)
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    email           TEXT UNIQUE NOT NULL,
    phone           TEXT,
    password_hash   TEXT NOT NULL,  -- Argon2id
    is_admin        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    status          TEXT DEFAULT 'active'
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

-- 订阅套餐
CREATE TABLE plans (
    id              TEXT PRIMARY KEY,  -- 'free', 'pro', 'enterprise'
    name            TEXT NOT NULL,
    price_cny_monthly DECIMAL(10,2),
    features        JSONB NOT NULL DEFAULT '[]'::jsonb,
    quotas          JSONB NOT NULL DEFAULT '{}'::jsonb,
    commission_rate DECIMAL(3,2) DEFAULT 0.80,
    is_active       BOOLEAN DEFAULT TRUE
);

-- Licenses (具体签发记录)
CREATE TABLE licenses (
    id              TEXT PRIMARY KEY,  -- 'LIC-2026-00042'
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    user_id         UUID REFERENCES users(id),
    plan_id         TEXT NOT NULL REFERENCES plans(id),
    status          TEXT NOT NULL DEFAULT 'unused',
    -- unused → activated → active → expired / revoked
    activation_code TEXT UNIQUE,       -- 印在发票/卡片的码
    activated_at    TIMESTAMPTZ,
    activated_ip    INET,
    hwid            JSONB,             -- 激活时记录的 HWID 因子
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    created_by      UUID,              -- 哪个管理员发的
    price_paid_cny  DECIMAL(10,2),
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb,
    CHECK (status IN ('unused','activated','expired','revoked'))
);
CREATE INDEX idx_lic_tenant ON licenses(tenant_id);
CREATE INDEX idx_lic_status ON licenses(status) WHERE status='activated';

-- Token 记录 (jti 索引, 用于吊销)
CREATE TABLE license_tokens (
    jti             TEXT PRIMARY KEY,
    license_id      TEXT NOT NULL REFERENCES licenses(id),
    issued_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked         BOOLEAN DEFAULT FALSE,
    revoked_at      TIMESTAMPTZ,
    ip              INET,
    user_agent      TEXT
);
CREATE INDEX idx_tokens_license ON license_tokens(license_id);
CREATE INDEX idx_tokens_expires ON license_tokens(expires_at) 
  WHERE revoked = FALSE;

-- Activation codes (独立表, 可以批量生成预发)
CREATE TABLE activation_codes (
    code            TEXT PRIMARY KEY,
    plan_id         TEXT NOT NULL REFERENCES plans(id),
    duration_days   INTEGER NOT NULL,  -- 如 30, 90, 365
    used            BOOLEAN DEFAULT FALSE,
    used_by_license TEXT REFERENCES licenses(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,       -- 未激活也会过期
    created_by      UUID,
    batch_id        UUID,              -- 批量号
    metadata        JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX idx_codes_batch ON activation_codes(batch_id);

-- 心跳 / 用量
CREATE TABLE usage_heartbeats (
    id              BIGSERIAL PRIMARY KEY,
    license_id      TEXT NOT NULL REFERENCES licenses(id),
    ts              TIMESTAMPTZ DEFAULT NOW(),
    ip              INET,
    active_accounts INT,
    publishes_today INT,
    agent_decisions_today INT,
    client_version  TEXT,
    raw             JSONB
);
CREATE INDEX idx_heartbeat_lic_ts ON usage_heartbeats(license_id, ts DESC);

-- 审计日志
CREATE TABLE audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ DEFAULT NOW(),
    actor_type      TEXT,  -- 'user'|'admin'|'system'
    actor_id        TEXT,
    action          TEXT NOT NULL,  -- 'activate'|'revoke'|'verify'|'renew'
    target_type     TEXT,
    target_id       TEXT,
    ip              INET,
    user_agent      TEXT,
    before_state    JSONB,
    after_state     JSONB,
    success         BOOLEAN,
    error_code      TEXT
);
CREATE INDEX idx_audit_target ON audit_logs(target_type, target_id, ts DESC);

-- 秘钥版本管理
CREATE TABLE signing_keys (
    key_id          TEXT PRIMARY KEY,  -- 'v1', 'v2', 'v3'
    algorithm       TEXT NOT NULL,     -- 'ed25519'
    public_key_b64  TEXT NOT NULL,
    private_key_encrypted TEXT NOT NULL,  -- envelope-encrypted
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    activated_at    TIMESTAMPTZ,
    deprecated_at   TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT FALSE
);

-- Row Level Security: 多租户隔离
ALTER TABLE licenses ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON licenses
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);
```

## 3.2 FastAPI 服务端骨架

```python
# server/license_api/main.py
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address

from server.license_api.routes import activate, verify, renew, heartbeat, admin
from server.license_api.middleware import verify_client_hmac, rate_limit

app = FastAPI(title="AI Matrix License Service", version="1.0")
limiter = Limiter(key_func=get_remote_address)

# 安全 headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp

# 全局 HMAC 验证 (除 /health)
app.include_router(
    activate.router, 
    prefix="/v1", 
    dependencies=[Depends(verify_client_hmac), Depends(rate_limit("10/minute"))])
app.include_router(
    verify.router, 
    prefix="/v1",
    dependencies=[Depends(verify_client_hmac), Depends(rate_limit("60/minute"))])
app.include_router(
    renew.router, 
    prefix="/v1",
    dependencies=[Depends(verify_client_hmac), Depends(rate_limit("20/minute"))])
app.include_router(heartbeat.router, prefix="/v1",
    dependencies=[Depends(verify_client_hmac), Depends(rate_limit("120/hour"))])

# Admin API (JWT 认证, 不用 HMAC)
app.include_router(admin.router, prefix="/admin",
    dependencies=[Depends(admin_jwt_required)])
```

```python
# server/license_api/routes/activate.py
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
import logging

from server.license_api.models import ActivateRequest, ActivateResponse
from server.license_api.db import get_db
from server.license_api.paseto_sign import issue_license_token, issue_refresh_token
from server.license_api.hwid import hwid_ok
from server.license_api.audit import audit

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/activate", response_model=ActivateResponse)
async def activate(req: ActivateRequest, db=Depends(get_db)):
    # 1. 查激活码
    code = await db.fetch_one(
        "SELECT * FROM activation_codes WHERE code=$1", req.activation_code)
    if not code:
        audit(action="activate", target_id=req.activation_code,
              success=False, error_code="CODE_NOT_FOUND")
        raise HTTPException(403, detail={"code": "CODE_NOT_FOUND"})
    
    if code["used"]:
        audit(action="activate", target_id=req.activation_code,
              success=False, error_code="ALREADY_ACTIVATED")
        raise HTTPException(409, detail={"code": "ALREADY_ACTIVATED"})
    
    if code["expires_at"] and code["expires_at"] < datetime.utcnow():
        audit(action="activate", target_id=req.activation_code,
              success=False, error_code="CODE_EXPIRED")
        raise HTTPException(403, detail={"code": "CODE_EXPIRED"})
    
    # 2. 发 license
    license_id = f"LIC-{datetime.now():%Y}-{await db.nextval('license_seq'):05}"
    expires_at = datetime.utcnow() + timedelta(days=code["duration_days"])
    
    async with db.transaction():
        await db.execute("""
            INSERT INTO licenses (id, tenant_id, user_id, plan_id,
                status, activation_code, activated_at, activated_ip,
                hwid, expires_at)
            VALUES ($1, $2, $3, $4, 'activated', $5, NOW(), $6::inet, $7, $8)
        """, license_id, code["tenant_id"], code.get("user_id"),
             code["plan_id"], req.activation_code, req.ip,
             json.dumps(req.hwid.dict()), expires_at)
        
        await db.execute(
            "UPDATE activation_codes SET used=TRUE, used_by_license=$1 WHERE code=$2",
            license_id, req.activation_code)
    
    # 3. 颁发 token
    plan = await db.fetch_one("SELECT * FROM plans WHERE id=$1", code["plan_id"])
    token_payload = {
        "license_id": license_id,
        "tenant_id": str(code["tenant_id"]),
        "user_id": str(code.get("user_id", "")),
        "plan": code["plan_id"],
        "hwid": req.hwid.combined,
        "features": plan["features"],
        "quotas": plan["quotas"],
        "commission_rate": float(plan["commission_rate"]),
    }
    license_token, jti = await issue_license_token(token_payload, expires_at)
    refresh_token = await issue_refresh_token(license_id, jti)
    
    # 4. 记录 token
    await db.execute("""
        INSERT INTO license_tokens (jti, license_id, expires_at, ip)
        VALUES ($1, $2, $3, $4::inet)
    """, jti, license_id, expires_at, req.ip)
    
    audit(action="activate", target_id=license_id, success=True,
          actor_type="user", actor_id=str(code.get("user_id")),
          after_state={"license_id": license_id, "plan": code["plan_id"]})
    
    return ActivateResponse(
        status="ok",
        license_token=license_token,
        refresh_token=refresh_token,
        expires_at=int(expires_at.timestamp()),
        license_info={
            "license_id": license_id,
            "plan": code["plan_id"],
            "features": plan["features"],
            "quotas": plan["quotas"],
        },
    )
```

## 3.3 密钥管理

### 签名密钥轮换

```python
# server/license_api/key_rotation.py
"""
Ed25519 密钥分阶段轮换:
  t0: 生成 v2, 不启用 (只存数据库, is_active=FALSE)
  t0+1d: 启用 v2 (is_active=TRUE), v1 仍可验证 (但新签全用 v2)
  t0+30d: 废弃 v1 (deprecated_at), 服务端拒绝用 v1 验签
  t0+90d: 删除 v1

客户端兼容:
  PASETO v4 header 里的 `kid` 字段带密钥版本
  客户端存多个公钥, 按 kid 选对应公钥验签
"""
from nacl.signing import SigningKey, VerifyKey
import secrets

def rotate_signing_key(db):
    new_key_id = f"v{db.next_key_version()}"
    sk = SigningKey.generate()
    pk = sk.verify_key
    
    # 私钥用 KMS 加密存储
    encrypted_sk = kms_encrypt(bytes(sk))
    
    db.execute("""
        INSERT INTO signing_keys (key_id, algorithm, public_key_b64,
            private_key_encrypted, is_active)
        VALUES ($1, 'ed25519', $2, $3, FALSE)
    """, new_key_id, base64.b64encode(bytes(pk)).decode(), encrypted_sk)
    
    return new_key_id
```

### 使用 Envelope Encryption

```
DEK (data encryption key) = 每个私钥随机生成
KEK (key encryption key) = 云 KMS (AWS/Aliyun) 或离线 hw token

存储: DEK_encrypted_by_KEK + private_key_encrypted_by_DEK
```

**开发机/低成本场景**: 用 `age` 工具 + 本机 private key 加密.

**生产**: AWS KMS 或 HashiCorp Vault.

---

# Part IV — 实施路线图

## Phase 0 — 基础 (MVP, 2 周)

**目标**: 能发卡 + 能激活 + 能验证.

```
Week 1:
  □ 搭建 FastAPI server 骨架 (复用现有 core/auth.py 作参考)
  □ PostgreSQL schema (上述 licenses/plans/activation_codes)
  □ Ed25519 密钥生成 + envelope encryption (age)
  □ PASETO v4.public 签发/验证 (pyseto 库)
  □ /v1/activate + /v1/verify 两个端点
  □ 简单 admin CLI: `python -m license_admin issue --plan pro --days 30`

Week 2:
  □ 客户端 LicenseAgent (core/license/agent.py)
  □ HWID 3 因子 (core/license/hwid.py)  
  □ EncryptedLicenseStore (SQLCipher 或 cryptography.Fernet)
  □ 启动流程集成 (在 main.py 里 await LicenseAgent().initialize())
  □ 付款跳转: 用户点击 → 生成 activation_code → 发邮件/短信
```

**交付**: 能在自己开发环境跑通"买卡 → 激活 → 用 → 过期" 完整流程.

## Phase 1 — 加固 (3-4 周)

```
Week 3:
  □ 密钥轮换 (签名密钥 v1 → v2)
  □ Token 吊销 (Redis 黑名单 + admin /v1/revoke 端点)
  □ 心跳统计 (/v1/heartbeat + usage_heartbeats 表)
  □ Rate limiting (slowapi + Redis)

Week 4:
  □ 客户端 Nuitka 打包 + PyArmor obfuscate
  □ TLS cert pinning (客户端固定服务端公钥 hash)
  □ 防止篡改本地 license.db (SQLCipher + HMAC 校验文件头)
  □ 多机检测 (同 license_id 从 2 个不同 IP 心跳, 告警)

Week 5:
  □ 续签自动化 (客户端过期前 6h 触发)
  □ 离线宽限期 (联不上服务器, 允许 72h 继续用)
  □ HWID 自动升级 (用户换硬盘, 容差内自动更新)

Week 6:
  □ 审计日志 + 管理后台 (复用现有 dashboard/)
  □ 用量仪表盘 (active licenses, MRR, top features)
  □ 邮件提醒 (到期前 7 天)
```

**交付**: 可以把系统卖给第一批付费用户.

## Phase 2 — 企业级 (6+ 周)

```
  □ 多租户 RLS 隔离
  □ 座位管理 (一个 license 支持 N 个 user)
  □ OAuth2/OIDC 集成 (企业 SSO)
  □ API key (供客户端外的集成)
  □ 配额精细化 (按功能/按时间窗口)
  □ 计费集成 (Stripe / 支付宝商户)
  □ 灾备: 多区域 + 异地备份
  □ 公钥固定更新机制 (不发补丁就能轮换)
```

## 成本估算

### 技术栈成本 (月度)

| 项目 | 估算 | 选型 |
|---|---|---|
| 服务器 (API) | $20-50 | DigitalOcean / Vultr 4GB |
| PostgreSQL (托管) | $15-30 | Supabase / Neon 免费额度 → $25 付费 |
| Redis (托管) | $10 | Upstash / Redis Cloud |
| CDN / WAF | $0-20 | Cloudflare 免费层够用 |
| 域名 + TLS | $1 | Cloudflare 原生 TLS |
| 监控 | $0-10 | Uptime Kuma 自托管 / BetterStack |
| 邮件 | $0-10 | AWS SES (1000/月免费) |
| KMS | $0 | 自托管 age + backup key 冷存 |
| **合计** | **$50-130/月** | |

### 一次性成本

| 项目 | 估算 | 备注 |
|---|---|---|
| Nuitka 打包调试 | $0 | 免费 |
| PyArmor pro | $0 (社区版) 或 $99/年 | 商业版可选 |
| WinLicense (可选) | $299 | 等 MRR > $2000 再考虑 |
| VMProtect (可选) | $499 | 同上 |
| HashiCorp Vault (托管) | $0 (免费 tier) | 生产可切到 HCP Vault $5-20/月 |

---

# Part V — 实施前的关键问答

## Q1: 要不要一开始就上商业壳 (WinLicense/VMProtect)?

**不要**. 理由:
- 付费用户 < 100 前, 破解者不会盯你
- 破解你的 Python 代码, 不如偷你的服务器业务逻辑 — 而这不依赖客户端壳
- 商业壳每年 $299-500 成本, 不如先花在 **服务端可靠性** 上
- Nuitka + PyArmor 已经挡住 95% 业余逆向

**MRR 达到 $5000/月后** 再考虑. 那时候再花 $500 买 WinLicense, 只影响小成本.

## Q2: Token 签名为什么不用 RSA?

| 算法 | 公钥大小 | 签名速度 | 签名大小 | 安全强度 | 抗量子 |
|---|---|---|---|---|---|
| RSA-2048 | 256 字节 | 慢 | 256 字节 | 112 bit | ❌ |
| ECDSA P-256 | 65 字节 | 中 | 64 字节 | 128 bit | ❌ |
| **Ed25519** | **32 字节** | **快** | **64 字节** | **128 bit** | ❌ |
| Ed448 | 57 字节 | 中 | 114 字节 | 224 bit | ❌ |
| Dilithium (PQC) | 1.3 KB | 中 | 2.4 KB | 128 bit | ✅ |

**Ed25519** 是当前最佳选择:
- 小 (节省客户端二进制体积)
- 快 (启动时验签 < 1ms)
- 简单 (无参数协商)
- 抗侧信道攻击

后量子时代再迁 Dilithium. 现在没必要.

## Q3: 为什么不用 JWT?

JWT 是 2015 的设计, 问题一堆:
1. `alg=none` 炸过好多系统
2. `HS256 vs RS256` 混淆: 攻击者把 RS256 token 用公钥当 HS256 secret
3. 头信息可以注入 `kid` 变成 path traversal
4. 默认没加密 (JWE 是可选)

PASETO (Platform-Agnostic Security Tokens):
- 固定版本号 (v4), 没有算法协商
- v4.public = Ed25519 签名
- v4.local = XChaCha20-Poly1305 加密+认证
- 实现库少, 不容易被自己写错

替代品: **biscuit** (支持可委派的授权), **Macaroons** (Google 设计, 可分级). Phase 2 可考虑.

## Q4: 怎么让卡号在邮件里没被截获也不是问题?

**激活码 ≠ License Token**.
- 激活码一次性使用, 用完就废
- 即使被截, 攻击者必须 **抢在买家之前激活** + **绑自己的 HWID**, 合法用户发现后可申请退款重发
- 服务端可以限制: 同一 activation_code 只能在下单后 72h 内激活, 超时作废

配合:
- 激活码短 (16-20 字符, 带校验位 - Luhn 算法)
- 给买家发 **私人一次性链接** 而不是激活码本身, 链接打开后出码

## Q5: 客户端怎么存储 license_token 防篡改?

**SQLCipher** (AES-256 加密 SQLite) + **HMAC 校验存储文件的哈希**.

```python
# core/license/storage.py
from sqlcipher3 import dbapi2 as sqlite
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

class EncryptedLicenseStore:
    def __init__(self, path: Path):
        self.path = path
        # 加密密钥: 从 HWID 派生 (让 token 绑定当前机器)
        from core.license.hwid import compute_hwid
        seed = compute_hwid()["combined"]
        self.encryption_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"ai-matrix-license-v1",
            info=b"local-store",
        ).derive(seed.encode())
    
    def _connect(self):
        conn = sqlite.connect(str(self.path))
        conn.execute(f"PRAGMA key = x'{self.encryption_key.hex()}'")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        return conn
    
    def save_license_token(self, token: str):
        with self._connect() as c:
            c.execute("INSERT OR REPLACE INTO kv VALUES ('license_token', ?)",
                      (token,))
    
    def load_license_token(self) -> Optional[str]:
        with self._connect() as c:
            row = c.execute("SELECT v FROM kv WHERE k='license_token'").fetchone()
            return row[0] if row else None
```

**关键**: 加密密钥是 HWID 派生的. 把 `license.db` 复制到别的机器, HWID 不同 → 解密失败. 简单有效.

## Q6: 如何支持 "离线激活"?

用户机器不能联网:
1. 客户端生成 `activation_request`: HWID + nonce + 时间戳, 签名
2. 用户用手机拍照或拷到 U 盘, 访问我们网站
3. 网站验证 request, 签发一个 `offline_license_bundle` (PASETO v4.public + HWID 绑定 + 7 天有效)
4. 用户拷回机器, 客户端验证签名并载入

离线 license 不能续签, 过期只能重来一次. 作为 **高安全环境/边境用户** 的兜底.

---

# Part VI — 对照清单 (学 KS184 的 vs 改进的)

| KS184 做法 | 我们抄 | 我们改 | 理由 |
|---|---|---|---|
| WinLicense 商业壳 | ❌ | Nuitka + PyArmor | 节省 $300/年, 够用 |
| PyArmor 保护业务 | ✅ | 继续用 | 好用 |
| 短 token (YK...) | ❌ | PASETO v4 (长 token) | 短 token 必须每次查服务器, 开销大 |
| 服务端二次验证 | ✅ | 保留 | 真源在服务端 |
| HMAC-SHA256 防篡改 | ✅ | 升级到 Ed25519 签名 | 非对称更强 |
| 5 因子 HWID | ⚠️ | 改 3 因子 + 容差 | SMBIOS 云主机不稳 |
| 每次启动联网 | ⚠️ | 本地验 + 每日 1 次联网 | 降低服务器成本 |
| 响应 HMAC 双签 | ✅ | 保留 | 防 MITM |
| 本地 INI 明文存卡号 | ❌ | SQLCipher + HWID 派生密钥 | 明文太弱 |
| 单密钥永远不换 | ❌ | 版本化密钥 + 90 天轮换 | 密钥泄露可控 |
| 无心跳 | ❌ | 小时级心跳 | 用量审计 + 多机检测 |
| 无审计日志 | ❌ | audit_logs 全量 | 合规 + 调试 |
| 手动发卡 (客服) | ❌ | 自动化 + Stripe 集成 | 规模化 |
| 无试用 | ❌ | 7 天全功能试用 | 标准套路 |
| 无租户隔离 | ❌ | PostgreSQL RLS | 多租户 SaaS |

---

# Part VII — 关键工具链 & 依赖

## 客户端依赖

```toml
# pyproject.toml
[project]
dependencies = [
    "pyseto >= 1.7.0",          # PASETO v4 支持
    "pynacl >= 1.5.0",          # libsodium 绑定 (Ed25519)
    "cryptography >= 42.0",     # HKDF, Fernet
    "sqlcipher3 >= 0.5.0",      # 加密 SQLite
    "httpx >= 0.27",            # 异步 HTTP
    "pywin32 >= 306; sys_platform == 'win32'",  # registry 访问
]

[tool.nuitka]
standalone = true
onefile = true
python-flag = "no_site"
lto = "yes"
include-package = ["core.license"]
```

## 服务端依赖

```toml
# pyproject.toml
[project]
dependencies = [
    "fastapi >= 0.110",
    "uvicorn[standard]",
    "asyncpg >= 0.29",          # PostgreSQL async
    "pyseto >= 1.7.0",
    "pynacl >= 1.5.0",
    "redis >= 5.0",
    "slowapi >= 0.1.9",         # rate limiting
    "pydantic >= 2.6",
    "pydantic-settings",
    "python-jose[cryptography]",# admin JWT (不用于 license)
    "passlib[argon2]",          # Argon2id 密码 hash
    "prometheus-fastapi-instrumentator", # 指标
]
```

## 运维工具

```
docker-compose.yml    # 本地开发
k8s/                  # Kubernetes 部署
terraform/            # AWS/Aliyun 基础设施
scripts/
  ├── issue_batch.py      # 批量发卡
  ├── revoke.py           # 吊销
  ├── rotate_key.py       # 密钥轮换
  ├── backup_db.sh        # 数据库备份
  └── audit_report.py     # 审计月报
```

---

# Part VIII — 关键威胁建模 (STRIDE)

| 威胁 | 描述 | 对策 |
|---|---|---|
| **Spoofing** | 攻击者伪造客户端身份 | 客户端 HMAC + 服务端 IP 速率限制 + HTTPS mTLS (Phase 2) |
| **Tampering** | 篡改 token | Ed25519 签名, 客户端每次启动验 |
| **Repudiation** | 用户否认使用 | 全量 audit_logs + 用户签名确认 |
| **Info Disclosure** | 数据泄露 | TLS + PostgreSQL encrypted_at_rest + KMS 管理私钥 |
| **DoS** | 打爆服务器 | Cloudflare WAF + Redis 限流 + 离线宽限期 72h (降低用户依赖) |
| **Elevation** | 普通用户变管理员 | 双因素认证 + 管理员 JWT 短时效 + IP 白名单 |
| **HWID Copy** | 复制 VM 让多人用 | 多机并发检测 + HWID 容差 + 用量心跳 |
| **Reverse Engineering** | 逆向客户端 | Nuitka + PyArmor + 控制流混淆 (后期) |
| **MITM** | 中间人攻击 | TLS 1.3 + cert pinning (Phase 1) |
| **Replay** | 重放旧请求 | nonce + timestamp (5 分钟窗口) + jti 黑名单 |
| **Side Channel** | 时序攻击盗密钥 | Ed25519 天然抗 + `hmac.compare_digest` |
| **Binary Patching** | Patch 本地二进制绕过检查 | 服务端为真源 + 定期心跳 + 短签 |

---

# Part IX — 立即可执行的第一步

**不要**一上来就写完整服务器. 用 **增量式** 方案:

## Week 1 MVP (本周就能做)

```bash
# 1. 在现有 core/ 里加一个 core/license/ 子包
mkdir core/license
touch core/license/__init__.py
touch core/license/agent.py
touch core/license/hwid.py
touch core/license/crypto.py
touch core/license/storage.py

# 2. 加依赖
pip install pyseto pynacl sqlcipher3 cryptography

# 3. 生成第一对 Ed25519 密钥 (自签)
python -c "
from nacl.signing import SigningKey
import base64
sk = SigningKey.generate()
print('PRIVATE:', base64.b64encode(bytes(sk)).decode())
print('PUBLIC:', base64.b64encode(bytes(sk.verify_key)).decode())
"
# 私钥放 .env (或 age 加密), 公钥硬编码到客户端

# 4. 写 hwid.py 先跑通本机 HWID 计算
python -m core.license.hwid

# 5. 写一个 admin CLI 生成 license
python -m core.license.admin issue \
  --plan pro \
  --days 30 \
  --phone REPLACE_WITH_YOUR_PHONE
# 输出: 激活码 + 签发的 PASETO token (用于测试)

# 6. 写 LicenseAgent.initialize() 在 main 启动时调用
```

完成这 6 步 = 有最小可用授权系统 (无服务器, 纯自签). 

**下一步**: 当想上线给外部用户时, 才把 admin CLI 扩展成 FastAPI 服务.

---

# Part X — 后续可以追加的文档

本蓝图故意留白的话题, 以后补充:

1. `APP_LICENSE_IMPL_GUIDE.md` — Phase 0 的逐步实现 (拷贝即用)
2. `APP_BILLING_INTEGRATION.md` — Stripe/支付宝 集成
3. `APP_OFFLINE_ACTIVATION_WORKFLOW.md` — 离线激活详细流程
4. `APP_LICENSE_KEY_ROTATION_RUNBOOK.md` — 密钥轮换的 runbook
5. `APP_LICENSE_INCIDENT_RESPONSE.md` — 密钥泄露应急预案
6. `APP_ANTI_CRACK_ADVANCED.md` — 高级反破解 (代码完整性, 自校验)

---

# 总结

**从 KS184 学到, 可以直接搬的**:
✅ 双层架构 (客户端壳 + 业务层 + 服务端)
✅ 双密钥 HMAC 签名
✅ 服务端唯一真源
✅ HWID + 容差
✅ 短签 + 续签

**该改良的**:
❌ WinLicense → Nuitka (省 $300/年)
❌ HMAC-SHA256 → Ed25519 签名 (更强)
❌ 短 token → PASETO v4 (本地离线可验)
❌ 每次联网 → 每日 1 次 + 离线 72h 宽限
❌ 无版本 → 密钥 90 天轮换
❌ 单租户 → PostgreSQL RLS 多租户

**不要过度工程**:
✅ Phase 0 先跑通 (MVP 2 周)
✅ MRR < $5000 不用商业壳
✅ 先 SQLite + 单机, 再迁 PostgreSQL + 多区域

**长期投资的技术栈**:
- Ed25519 / PASETO / SQLCipher / Nuitka / PyArmor / FastAPI / PostgreSQL / Redis
- 这些都是 **2026 年起码再用 10 年** 的技术, 学了不亏

**总结一句话**: **不复制 KS184, 而是站在它肩膀上设计一套更现代的系统**. KS184 是 2024 年的作品, 我们要做 2030 年还不过时的架构.

---

*(蓝图 v1.0 完结, 2026-04-19)*
