# AI Matrix 反破解机制 — 完整防御体系

> **目的**: 授权系统的另一半. 蓝图 (`APP_LICENSE_ARCHITECTURE_BLUEPRINT.md`) 讲"怎么发卡/验证", 本文讲"怎么防破解".
>
> **核心思想**: **不是要让软件不可破解 (数学上不可能), 而是让破解成本 > 收益**. 业余逆向 1 周搞不定就放弃, 职业逆向要权衡 $X 成本 vs $Y 收入是否划算.
>
> **生成**: 2026-04-19
> **版本**: v1.0
> **关联**: `APP_LICENSE_ARCHITECTURE_BLUEPRINT.md` (Part VIII 威胁建模的具体展开)

---

# Part 0 — 反破解的核心哲学

## 0.1 五条设计原则

1. **深度防御 (Defense in Depth)**: 每层独立工作, 破一层不致命
2. **被动防御 (Passive Defense)**: 不要和攻击者"正面刚", 让 TA 觉得"不值得"
3. **延迟失效 (Delayed Failure)**: 攻击者 debug 时间越长, 越容易放弃
4. **可观测性 (Observability)**: 每次可疑行为都记录, 数据驱动
5. **经济学杠杆 (Economics)**: 提高攻击成本 + 降低攻击收益 → 理性攻击者放弃

## 0.2 不要做的事 (反模式)

| 反模式 | 为什么不好 | 正确做法 |
|---|---|---|
| 发现 debugger 立刻崩溃 | 攻击者立刻知道触发点, 定位 patch | 延迟 5-30 秒, 非确定性行为 |
| 破解后立刻显示"LICENSE INVALID" | 成功提示 = 破解成功信号 | 悄悄降级业务能力 |
| 把密钥硬编码在字符串里 | `strings` 命令秒扫 | 运行时派生 + 分段拼接 |
| 关键校验用 `if license_valid:` | 单行 patch 就破 | 校验结果渗透到每个业务路径 |
| 每次启动重新下载 full license | 服务器压力 + 攻击者能分析流量 | 本地离线验签 + 短签 |
| 反破解代码写得"性能最优" | 代码模式明显, 易被静态分析 | 冗余 + 混淆路径 |

## 0.3 攻击者分级

| 级别 | 画像 | 成本 | 时间 | 举例 |
|---|---|---|---|---|
| **L1 业余** | 下载 x32dbg, 看教程 | $0 | 数小时-1 周 | 大学生, 贴吧用户 |
| **L2 熟练** | 会用 IDA/Ghidra, 写 keygen | $0-$1000 | 1-4 周 | 破解组 FFF, CORE |
| **L3 职业** | 有自动化工具链, 卖破解版赚钱 | $1-10K | 1-3 月 | 国内破解网站主 |
| **L4 团伙** | 目标性逆向特定高价商业软件 | $10K+ | 3-12 月 | 针对 $1K+ 单价软件 |
| **L5 国家级** | APT/NSA 级对手 | 无限 | 无限 | 不针对商业软件 |

**我们的目标**: **挡住 L1-L3, 让 L4 觉得不值得, L5 不是我们要对付的**.

---

# Part I — 威胁建模 (完整攻击面)

## 1.1 16 种典型攻击路径

| # | 攻击路径 | 目标 | 防御层 |
|---|---|---|---|
| A1 | 静态反编译 .exe | 读业务逻辑 / 找密钥 | Layer 3: 代码混淆 |
| A2 | 动态调试 (x32dbg/IDA) | 断点在验证函数 | Layer 4: anti-debug |
| A3 | Frida hook | 替换验证函数返回值 | Layer 4: anti-hook |
| A4 | Memory dump + 分析 | 找 Token/密钥/解密后代码 | Layer 4: anti-dump |
| A5 | 二进制 patch | 改 `jne` 成 `jmp` 跳过校验 | Layer 3: integrity check |
| A6 | Keygen | 逆向算法自己生成 Token | Layer 2: 非对称签名 |
| A7 | License 共享 | 买一份多人用 | Layer 1: 多机检测 |
| A8 | Token 泄露 | 网上发 valid token 给别人 | Layer 2: HWID 绑定 |
| A9 | MITM (中间人) | 拦截并伪造服务器响应 | Layer 0: TLS + pinning |
| A10 | DNS 劫持 | 指向假服务器 | Layer 0: cert pinning + DoH |
| A11 | 回放攻击 | 重放旧的 "valid" 响应 | nonce + timestamp |
| A12 | VM 批量跑 | 用 VMware/Docker 造无数 HWID | anti-VM + VM 指纹 |
| A13 | 时间回拨 | 系统时间改回激活期 | 服务器时间权威 |
| A14 | 离线环境破 | 不联网状态下 patch | 联网 + 宽限期短 |
| A15 | DLL 替换 | 用自己编译的 DLL 替换掉 | 模块签名验证 |
| A16 | 配置篡改 | 改 SQLite / INI 绕过 | SQLCipher + HMAC |

## 1.2 攻击成本 vs 收益矩阵 (目标: 右上角进入"不划算"区)

```
攻击收益 (高 →)
  ↑
  │                                    X我们要到的位置
  │  A6 keygen                            ↓
  │  ($5K 卖破解版)           ←━━━━━━━━━ 提高攻击成本
  │                           ←━━━━━━━━━ 降低攻击收益
  │  A2 单机 patch
  │  (自己用)
  │  A11 replay
  │  (偶发)
  │
  │  A3 frida
  │  (临时绕)
  │________________________→
    0     $100  $1K   $10K  $100K   攻击成本
```

---

# Part II — 五层防御纵深 (总体架构)

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 0: 网络层        TLS 1.3 + Cert Pinning + DoH          │
│    防御: A9 A10                                                │
├────────────────────────────────────────────────────────────────┤
│  Layer 1: 认证层        双密钥 HMAC + Ed25519 + 短签 + nonce  │
│    防御: A6 A7 A8 A11 A13                                      │
├────────────────────────────────────────────────────────────────┤
│  Layer 2: 代码层        Nuitka + PyArmor + VMProtect (可选)   │
│    防御: A1 A5 A15                                             │
├────────────────────────────────────────────────────────────────┤
│  Layer 3: 运行时层      Anti-Debug + Anti-Hook + Anti-Dump    │
│    防御: A2 A3 A4 A14                                          │
├────────────────────────────────────────────────────────────────┤
│  Layer 4: 数据层        SQLCipher + HWID 派生密钥 + HMAC 封存 │
│    防御: A8 A16                                                │
├────────────────────────────────────────────────────────────────┤
│  Layer 5: 行为层        心跳 + 多机检测 + ML 异常 + Canary    │
│    防御: A7 A12 (服务端兜底)                                   │
├────────────────────────────────────────────────────────────────┤
│  Layer ∞: 法律层        EULA + 水印 + DMCA + 索赔             │
│    防御: 规模化商业破解                                        │
└────────────────────────────────────────────────────────────────┘
```

**核心**: **任何单层被破 ≠ 系统被破**. 攻击者必须穿透 6 层.

---

# Part III — Layer 2: 代码层保护 (静态防御)

## 3.1 Nuitka vs PyArmor vs VMProtect 深度对比

| 维度 | Nuitka | PyArmor Pro | VMProtect |
|---|---|---|---|
| **价格** | 免费 | $99/年 | $500/年 |
| **原理** | Python → C → 编译到 .exe | bytecode 加密 + 运行时解密 | x86 指令虚拟化 |
| **对抗静态分析** | 强 (C 代码无 Python 源痕迹) | 中 (有 bytecode 残留) | 极强 (虚拟化指令) |
| **对抗动态分析** | 弱 (正常 .exe 可 debug) | 中 (有 anti-debug) | 极强 (反调试 + 反 VM) |
| **启动速度** | 快 (原生代码) | 中 (解密开销) | 慢 (VM 解释) |
| **运行速度** | 快 | 与原生 Python 相当 | **慢 5-50 倍** |
| **二进制大小** | 大 (+ Python runtime) | 小 | 中 |
| **学习曲线** | 低 | 低 | 高 |
| **调试难度** | 中 | 中 | 极高 |
| **Best for** | 全量编译防反编译 | 快速给 Python 加锁 | 保护核心算法 10-20 行 |

## 3.2 推荐组合 (分阶段)

### Phase 0 — 免费版

```
整个 core/ 用 Nuitka 编译到 .exe
  ↓
敏感函数 (license/crypto/hwid) 用 PyArmor 额外加密
  ↓
字符串常量 (API URL, 密钥前缀) 运行时派生
```

### Phase 1 — 中级

```
+ 对 license/crypto.py 的 3 个核心函数用 VMProtect 虚拟化
+ 编译时注入 build_id (每次打包 hash 不同, 防模板 patch)
+ 字符串加密工具: 自研简单 XOR + base85 编码
```

### Phase 2 — 高级

```
+ 控制流平坦化 (LLVM ollvm)
+ 代码自校验 (self-checksum)
+ 关键路径多版本冗余 (3 份不同实现, 结果投票)
```

## 3.3 Nuitka 打包脚本

```bash
# build.sh
python -m nuitka \
    --standalone \
    --onefile \
    --windows-console-mode=disable \
    --windows-icon-from-ico=assets/icon.ico \
    --include-package=core \
    --include-package=core.license \
    --include-package=core.agents \
    --include-data-dir=tools/ffmpeg=tools/ffmpeg \
    --enable-plugin=tk-inter \
    --python-flag=no_site \
    --python-flag=no_docstrings \
    --lto=yes \
    --remove-output \
    --output-dir=dist \
    --output-filename=AIMatrix_v${VERSION}_${BUILD_ID}.exe \
    main.py

# 注入 build_id (每次构建唯一, 用于溯源破解版本)
BUILD_ID=$(openssl rand -hex 8)
sed -i "s/BUILD_ID_PLACEHOLDER/${BUILD_ID}/g" dist/main.py
```

## 3.4 字符串加密工具

```python
# core/license/_strings.py
"""
字符串运行时解密. 防静态扫描.

使用:
    from core.license._strings import S
    url = S("AQIDBAU...")  # 编译时被替换成加密串
"""
import base64
import hashlib
import functools

# 密钥从多处派生 (防单点攻击)
_SEED = (
    b"\x41\x49\x4d\x61\x74"     # "AIMat"
    b"\x72\x69\x78\x00\x76"     # "rix\0v"
    b"\x31"                      # "1"
)

@functools.lru_cache(maxsize=None)
def _derive_key(salt: bytes) -> bytes:
    return hashlib.sha256(_SEED + salt).digest()

def S(enc: str) -> str:
    """解密运行时字符串."""
    data = base64.b85decode(enc.encode())
    salt, ct = data[:8], data[8:]
    key = _derive_key(salt)
    pt = bytes(c ^ key[i % 32] for i, c in enumerate(ct))
    return pt.decode('utf-8')

def E(plain: str) -> str:
    """编译时用: 把明文变成 S() 里的参数."""
    import os
    salt = os.urandom(8)
    key = _derive_key(salt)
    ct = bytes(ord(c) ^ key[i % 32] for i, c in enumerate(plain))
    return base64.b85encode(salt + ct).decode()

# 预编译工具: python -m core.license._strings encode "https://license.my.com"
if __name__ == "__main__":
    import sys
    if sys.argv[1] == "encode":
        print(E(sys.argv[2]))
```

**使用前**:
```python
LICENSE_URL = "https://license.my-domain.com"  # ← grep 能找到
```

**使用后**:
```python
from core.license._strings import S
LICENSE_URL = S("N@Bx4@ABxZ_...")  # ← grep 找不到
```

## 3.5 编译时注入 Build ID (防模板 Patch)

```python
# core/license/build_info.py (编译前被 sed 替换)
BUILD_ID = "BUILD_ID_PLACEHOLDER"  # 16 hex chars, 每次打包唯一
BUILD_TIMESTAMP = 0                # 也会被替换

def build_fingerprint() -> str:
    """把 build_id 融入每次 license 验证."""
    import hashlib
    return hashlib.sha256(
        f"{BUILD_ID}:{BUILD_TIMESTAMP}".encode()
    ).hexdigest()[:16]
```

**作用**: 破解者给 v1.0.0 写了 patch, v1.0.1 的 BUILD_ID 变了, patch 失效. 每次发版自动失效破解版.

**搭配**: license 响应里带 `expected_build_fingerprint`, 客户端比对不符合就拒绝 (防破解版冒充新版).

## 3.6 自校验 (Code Integrity Check)

```python
# core/license/integrity.py
"""
启动时验证关键模块未被篡改.
"""
import hashlib
import os
import sys
from pathlib import Path

# 编译时工具生成 (对每个打包的 .pyc / 数据文件算 hash)
EXPECTED_HASHES = {
    "core/license/agent.pyc": "a1b2c3...",
    "core/license/crypto.pyc": "d4e5f6...",
    "core/license/hwid.pyc": "...",
}

def verify_self(raise_on_fail: bool = True) -> bool:
    """验证本进程关键文件. 不通过则退出."""
    import importlib.util
    
    for module_path, expected in EXPECTED_HASHES.items():
        full_path = Path(sys._MEIPASS if hasattr(sys, '_MEIPASS') 
                         else sys.prefix) / module_path
        try:
            h = hashlib.sha256(full_path.read_bytes()).hexdigest()
        except FileNotFoundError:
            if raise_on_fail:
                _silent_sabotage()
            return False
        
        if h != expected:
            if raise_on_fail:
                _silent_sabotage()
            return False
    
    return True

def _silent_sabotage():
    """发现篡改不报错, 10 分钟后悄悄退出."""
    import threading, time, random
    def _die():
        time.sleep(300 + random.random() * 300)  # 5-10 分钟
        os._exit(1)
    threading.Thread(target=_die, daemon=True).start()
```

**要点**:
- **不要立即抛异常** — 攻击者能一下定位到检查函数
- **随机延迟** — 破解者难以关联触发点和崩溃点
- **使用 `os._exit(1)`** — 绕过 Python 清理逻辑, 比 `sys.exit()` 更难拦

---

# Part IV — Layer 3: 运行时保护 (动态防御)

## 4.1 Anti-Debug 技术 (Windows)

### 4.1.1 基础检测

```python
# core/license/anti_debug.py
import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

def is_debugger_present() -> bool:
    """最基本的 IsDebuggerPresent API. L1 攻击者都会绕."""
    return bool(kernel32.IsDebuggerPresent())

def check_remote_debugger() -> bool:
    """CheckRemoteDebuggerPresent — 稍难绕."""
    h = kernel32.GetCurrentProcess()
    is_debugged = wintypes.BOOL(False)
    kernel32.CheckRemoteDebuggerPresent(h, ctypes.byref(is_debugged))
    return bool(is_debugged.value)

def check_peb_being_debugged() -> bool:
    """
    直接读 PEB.BeingDebugged 字段.
    绕过 IsDebuggerPresent 的 hook 不一定绕这里.
    """
    # 32-bit: PEB at fs:[0x30] offset 0x02
    # 64-bit: PEB at gs:[0x60] offset 0x02
    # Python 读 PEB 比较麻烦, 用 NtQueryInformationProcess 替代
    ProcessBasicInformation = 0
    class PROCESS_BASIC_INFO(ctypes.Structure):
        _fields_ = [
            ("Reserved1", ctypes.c_void_p),
            ("PebBaseAddress", ctypes.c_void_p),
            ("Reserved2", ctypes.c_void_p * 2),
            ("UniqueProcessId", ctypes.c_void_p),
            ("Reserved3", ctypes.c_void_p),
        ]
    info = PROCESS_BASIC_INFO()
    ntdll.NtQueryInformationProcess(
        kernel32.GetCurrentProcess(),
        ProcessBasicInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    )
    peb_addr = info.PebBaseAddress
    being_debugged = ctypes.c_ubyte.from_address(peb_addr + 0x02).value
    return being_debugged != 0

def check_nt_global_flag() -> bool:
    """
    PEB.NtGlobalFlag — 被调试时有 FLG_HEAP_ENABLE_TAIL_CHECK (0x10) 等位.
    稍微 pro 一点的检测.
    """
    # 位置: PEB + 0x68 (32-bit) 或 0xBC (64-bit)
    # ...
    pass
```

### 4.1.2 时间差检测 (Anti-Timing)

```python
def detect_by_timing() -> bool:
    """
    在正常执行过程中插入时间测量.
    被调试时某些操作会超时.
    """
    import time
    
    t0 = time.perf_counter_ns()
    # 一个正常应该很快的操作
    x = 0
    for _ in range(1000):
        x += 1
    t1 = time.perf_counter_ns()
    
    # 正常: < 50 microsecond; 被 single-step debug: > 100 ms
    elapsed_us = (t1 - t0) / 1000
    return elapsed_us > 10000  # 10 ms 阈值
```

### 4.1.3 异常处理陷阱

```python
def debug_trap_via_exception():
    """
    触发一个异常, debugger 会先接管.
    """
    import ctypes
    try:
        # 故意 AV
        ctypes.c_int.from_address(0).value
    except Exception:
        # 正常情况 Python 会捕获
        # 如果被 debugger 拦, 流程会不同
        pass
```

### 4.1.4 Python 层检测

```python
def check_python_tracers() -> bool:
    """
    Python 有 sys.gettrace 和 sys.getprofile — 用于 debugger/profiler.
    """
    import sys
    if sys.gettrace() is not None:
        return True
    if sys.getprofile() is not None:
        return True
    # 检查是否有 pdb 已导入
    return 'pdb' in sys.modules or 'bdb' in sys.modules
```

### 4.1.5 组合使用 (权重投票)

```python
class AntiDebugGuard:
    """
    多重检测组合. 单一方法可能被 hook, 但所有方法都被 hook 的成本很高.
    
    关键设计:
    1. 不在一个函数里检测 (攻击者一个 return True 就过)
    2. 检测结果不是 boolean, 而是 "可疑度" 分数
    3. 不立即反应, 延迟触发
    """
    def __init__(self):
        self.suspicion_score = 0
        self._checks = []
    
    def tick(self):
        """每次业务调用附带 1 次检测 (分散)."""
        import random
        checks = [
            check_peb_being_debugged,
            check_remote_debugger,
            check_python_tracers,
            detect_by_timing,
            self._check_nt_global_flag,
        ]
        fn = random.choice(checks)
        if fn():
            self.suspicion_score += 1
        
        if self.suspicion_score > 5:
            self._sabotage_async()
    
    def _sabotage_async(self):
        """延迟破坏."""
        import threading, random, time, os
        def _die():
            time.sleep(random.randint(180, 600))  # 3-10 分钟后
            # 不打印任何东西
            os._exit(0xDEAD)
        threading.Thread(target=_die, daemon=True).start()

# 全局实例
_guard = AntiDebugGuard()

def protected(fn):
    """装饰器: 给关键函数加保护."""
    def wrapper(*args, **kwargs):
        _guard.tick()
        return fn(*args, **kwargs)
    return wrapper
```

**使用**:
```python
@protected
def verify_license(token):
    # ...
```

## 4.2 Anti-Hook 技术 (对抗 Frida / EasyHook)

### 4.2.1 检测 Frida 特征

```python
# core/license/anti_frida.py
"""
Frida 工作原理: 把 frida-agent.dll 注入到目标进程.
检测思路: 扫描进程空间找 frida 特征字符串.
"""
import ctypes
from ctypes import wintypes

def detect_frida_in_process() -> bool:
    """
    扫描本进程内存找 "frida" / "gum-js-loop" 等字符串.
    """
    import re
    
    FRIDA_SIGNATURES = [
        b"frida:rpc",
        b"gum-js-loop",
        b"gmain",
        b"frida-gadget",
        b"LIBFRIDA",
    ]
    
    # 枚举 loaded modules
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    
    h_process = kernel32.GetCurrentProcess()
    modules = (wintypes.HMODULE * 1024)()
    cb_needed = wintypes.DWORD()
    
    if not psapi.EnumProcessModules(h_process, ctypes.byref(modules), 
                                     ctypes.sizeof(modules), 
                                     ctypes.byref(cb_needed)):
        return False
    
    n_modules = cb_needed.value // ctypes.sizeof(wintypes.HMODULE)
    for i in range(n_modules):
        module_name = (ctypes.c_wchar * 512)()
        psapi.GetModuleFileNameExW(h_process, modules[i], 
                                    module_name, 512)
        name = module_name.value.lower()
        if 'frida' in name or 'gadget' in name:
            return True
    
    return False

def detect_frida_via_tcp() -> bool:
    """
    Frida 默认监听 localhost:27042.
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.1)
        s.connect(('127.0.0.1', 27042))
        s.close()
        return True
    except (socket.error, socket.timeout):
        return False

def detect_frida_threads() -> bool:
    """
    Frida 注入会创建特征线程名.
    """
    import threading
    for t in threading.enumerate():
        if t.name and ('frida' in t.name.lower() or 
                       'gum' in t.name.lower() or
                       'gdbus' in t.name.lower()):
            return True
    return False
```

### 4.2.2 检测函数被 Hook

```python
def check_api_integrity() -> bool:
    """
    关键 Win32 API 的前几字节应该是标准 prologue.
    被 hook 则首字节通常是 0xE9 (jmp) 或 0xFF 0x25 (iat hook).
    """
    import ctypes
    
    kernel32 = ctypes.WinDLL("kernel32")
    # 取 CreateFileW 地址
    addr = ctypes.cast(kernel32.CreateFileW, ctypes.c_void_p).value
    
    # 读前 5 字节
    first_bytes = (ctypes.c_ubyte * 5).from_address(addr)
    data = bytes(first_bytes)
    
    # 正常开头: 0x4C 0x8B 0xDC (mov r11, rsp) 或类似
    # 被 hook: 0xE9 XX XX XX XX (jmp rel32)
    return data[0] == 0xE9 or (data[0] == 0xFF and data[1] == 0x25)
```

### 4.2.3 启动前 Frida 排查

```python
# 在 main() 最早的地方调用
def pre_flight_check():
    if (detect_frida_in_process() or 
        detect_frida_via_tcp() or 
        detect_frida_threads()):
        # 不抛异常, 不打印任何信息
        # 静默进入"降级模式": 业务逻辑返回假数据
        import os
        os.environ["_DEGRADED"] = "1"
```

**KS184 有同样的 trick**: Q_x64.dll 启动时探测 Frida, 所以我们之前 `child-gating inject` 总是 `access violation 0x60`.

## 4.3 Anti-VM 技术

### 4.3.1 CPU Hypervisor Bit

```python
def check_cpuid_hypervisor() -> bool:
    """
    CPUID leaf 1, ECX bit 31 = hypervisor present.
    """
    import ctypes
    # 需要 assembly, 用 ctypes 不容易
    # 方案 1: 调 wmic / systeminfo
    import subprocess
    try:
        out = subprocess.check_output(
            'wmic cpu get manufacturer /value', 
            shell=True, text=True, timeout=3)
        return 'KVM' in out or 'VMware' in out or 'VirtualBox' in out
    except Exception:
        return False

def check_registry_vm() -> bool:
    """
    注册表查虚拟机特征.
    """
    import winreg
    vm_indicators = [
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System", "SystemBiosVersion"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System", "VideoBiosVersion"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\Disk\Enum", "0"),
    ]
    
    vm_strings = ['VMWARE', 'VIRTUAL', 'VBOX', 'QEMU', 'XEN']
    
    for root, key, value in vm_indicators:
        try:
            with winreg.OpenKey(root, key) as k:
                data = str(winreg.QueryValueEx(k, value)[0]).upper()
                if any(s in data for s in vm_strings):
                    return True
        except Exception:
            continue
    return False

def check_vm_processes() -> bool:
    """
    VM 的 guest tools 进程特征.
    """
    import psutil
    vm_procs = {
        'vmtoolsd.exe',      # VMware Tools
        'vmwaretray.exe',
        'vmwareuser.exe',
        'vboxservice.exe',   # VirtualBox
        'vboxtray.exe',
        'xenservice.exe',    # Xen
    }
    for p in psutil.process_iter(['name']):
        if p.info['name'] and p.info['name'].lower() in vm_procs:
            return True
    return False
```

### 4.3.2 VM 策略

**不要禁止 VM**. 理由: 很多合法用户在 VM 里跑 (比如云桌面). 

**策略**: 允许 VM 但**降级 + 标记**:
- 同 license 多 VM 检测: 服务端心跳 IP 聚类
- VM 环境下限制某些功能 (例如不允许批量激活)
- VM 运行的账号数 * 2 计入 quota

## 4.4 Anti-Dump 技术

```python
def mark_no_dump_pages():
    """
    Windows: 用 SetProcessWorkingSetSize + VirtualProtect 标记关键内存页
    为 PAGE_NOACCESS 或 PAGE_GUARD.
    Dump 工具读到时会失败.
    """
    import ctypes
    from ctypes import wintypes
    
    # 找到 license 模块的内存区域
    # 对其应用保护 — 技术细节较多, Phase 2 实施
    pass

def clear_sensitive_memory():
    """
    敏感操作结束后立即清 0.
    """
    secret = bytearray(b"private_key_bytes")
    # ... 使用
    # 清零
    for i in range(len(secret)):
        secret[i] = 0
```

---

# Part V — Layer 5: 行为层检测 (服务端兜底)

这是**最重要的防线** — 即使客户端全破, 服务端行为分析仍能发现.

## 5.1 多机检测算法

### 5.1.1 IP 聚类 (DBSCAN)

```python
# server/license_api/detection/multi_machine.py
"""
同一 license 从多个 IP 心跳 = 多人使用.
但真实场景可能有: 家 + 公司 + 移动网络 → 3 个 IP 不一定是共享.

用 DBSCAN 聚类: 如果心跳时间重叠 + 地理位置相隔 > 500km, 则判定共享.
"""
from collections import defaultdict
from datetime import datetime, timedelta
import ipaddress

class MultiMachineDetector:
    """检测单 license 被多人共享."""
    
    CONCURRENT_WINDOW_SEC = 300       # 5 分钟内
    GEO_DISTANCE_THRESHOLD_KM = 500   # 地理距离阈值
    UNIQUE_IP_THRESHOLD = 3           # 30 天独立 IP 数
    
    def check(self, license_id: str, db) -> dict:
        # 过去 30 天心跳
        heartbeats = db.query("""
            SELECT ip, ts, active_accounts
            FROM usage_heartbeats
            WHERE license_id = %s AND ts > NOW() - INTERVAL '30 days'
            ORDER BY ts
        """, license_id).fetchall()
        
        if len(heartbeats) < 10:
            return {"verdict": "insufficient_data"}
        
        # Signal 1: 唯一 IP 数
        unique_ips = set(h['ip'] for h in heartbeats)
        if len(unique_ips) >= self.UNIQUE_IP_THRESHOLD:
            # 进一步验证: 是否真的并发
            concurrent_ips = self._find_concurrent_ips(heartbeats)
            if len(concurrent_ips) >= 2:
                return {
                    "verdict": "multi_machine_detected",
                    "confidence": "high",
                    "concurrent_ips": list(concurrent_ips),
                    "unique_ip_count": len(unique_ips),
                }
        
        # Signal 2: 地理跳跃 (1 小时内 IP 跨 500km+)
        geo_jumps = self._detect_geo_jumps(heartbeats)
        if geo_jumps:
            return {
                "verdict": "impossible_travel",
                "confidence": "high",
                "jumps": geo_jumps,
            }
        
        return {"verdict": "single_machine"}
    
    def _find_concurrent_ips(self, heartbeats) -> set:
        """找时间重叠的 IP."""
        from itertools import combinations
        
        ip_windows = defaultdict(list)
        for h in heartbeats:
            ip_windows[h['ip']].append(h['ts'])
        
        concurrent = set()
        for ip_a, ip_b in combinations(ip_windows.keys(), 2):
            for ta in ip_windows[ip_a]:
                for tb in ip_windows[ip_b]:
                    if abs((ta - tb).total_seconds()) < self.CONCURRENT_WINDOW_SEC:
                        concurrent.add(ip_a)
                        concurrent.add(ip_b)
                        break
        return concurrent
    
    def _detect_geo_jumps(self, heartbeats) -> list:
        """检测 1 小时内不可能的地理位置跳跃."""
        import geoip2.database
        reader = geoip2.database.Reader('GeoLite2-City.mmdb')
        
        prev = None
        jumps = []
        for h in heartbeats:
            try:
                r = reader.city(h['ip'])
                loc = (r.location.latitude, r.location.longitude)
            except:
                continue
            
            if prev and (h['ts'] - prev['ts']).total_seconds() < 3600:
                dist_km = self._haversine(prev['loc'], loc)
                if dist_km > self.GEO_DISTANCE_THRESHOLD_KM:
                    jumps.append({
                        "from": prev['loc'],
                        "to": loc,
                        "distance_km": dist_km,
                        "time_diff_min": (h['ts'] - prev['ts']).total_seconds() / 60,
                    })
            prev = {'ts': h['ts'], 'loc': loc}
        
        return jumps
    
    @staticmethod
    def _haversine(p1, p2):
        from math import radians, cos, sin, sqrt, atan2
        lat1, lon1 = radians(p1[0]), radians(p1[1])
        lat2, lon2 = radians(p2[0]), radians(p2[1])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
        return 2 * 6371 * atan2(sqrt(a), sqrt(1-a))
```

### 5.1.2 HWID 指纹聚类

```python
def detect_fake_hwids(license_id: str, db) -> bool:
    """
    检测"人为生成的假 HWID".
    特征:
      - HWID 完全相同但来自不同 IP
      - HWID 序列递增 (批量造)
      - HWID 某因子在短时间内大量变动
    """
    hwids = db.query("""
        SELECT DISTINCT ON (ip) hwid, ip, MIN(ts) as first_seen
        FROM usage_heartbeats
        WHERE license_id = %s
        GROUP BY ip, hwid
    """, license_id).fetchall()
    
    # 特征 1: 完全相同 HWID 跨 IP
    hwid_to_ips = defaultdict(set)
    for h in hwids:
        hwid_to_ips[h['hwid']].add(h['ip'])
    
    for hwid, ips in hwid_to_ips.items():
        if len(ips) >= 3:
            return True  # 3+ IP 用同一 HWID → 可疑
    
    return False
```

### 5.1.3 异常行为 ML 模型 (Phase 3)

```python
# Isolation Forest 异常检测
from sklearn.ensemble import IsolationForest

class UsageAnomalyDetector:
    """
    训练 baseline: 正常 license 的心跳特征分布.
    特征向量:
      [hourly_heartbeats, unique_ips_30d, active_accounts_mean,
       publishes_per_day_mean, session_duration_mean, ...]
    """
    def __init__(self):
        self.model = IsolationForest(contamination=0.05)
    
    def train(self, historical_data):
        X = self._extract_features(historical_data)
        self.model.fit(X)
    
    def score(self, license_id, recent_data):
        X = self._extract_features([recent_data])
        return self.model.score_samples(X)[0]  # 负数越小越异常
```

## 5.2 Canary 蜜罐 (高阶)

### 5.2.1 假激活码陷阱

```
生成 10 个"蜜罐激活码":
  HONEYPOT-XXX-001 ~ HONEYPOT-XXX-010

这些码绑定到一个 Telegram 群的公开消息 / 破解论坛发布.
任何人用这些码激活 = 100% 确认是破解者.
```

```python
# server: activate.py 加 hook
KNOWN_HONEYPOTS = set(db.query("SELECT code FROM honeypot_codes"))

@router.post("/activate")
async def activate(req):
    if req.activation_code in KNOWN_HONEYPOTS:
        # 激活成功! 但标记该机器
        await db.execute("""
            INSERT INTO flagged_machines (hwid, ip, detected_at, reason)
            VALUES (%s, %s, NOW(), 'honeypot_activation')
        """, req.hwid.combined, req.ip)
        
        # 依然发一个"看起来有效"的 token, 但它绑到一个特殊分组
        # 这个分组的所有请求会被记录 + 将来审计
        return issue_tainted_license(req)
    # ... 正常流程
```

### 5.2.2 假功能诱饵

```python
# 业务代码里加一些"诱饵功能"
# 它们只在 license_status == "tainted" 时被激活

@router.post("/api/draft/export_all")
async def export_all(license: License = Depends(get_license)):
    if license.is_tainted:
        # 破解版用户调这个接口 → 返回大量无效数据, 浪费他们的带宽
        return generate_fake_data(size_mb=500)
    # 正常用户调 → 正常流程
    return do_real_export()
```

### 5.2.3 水印 (Watermark)

每个发出去的 license token, payload 里嵌入 `steganography_marker`:

```python
def embed_watermark(payload: dict, license_id: str):
    """
    在 payload 里隐藏 license_id 的哈希, 用于破解版溯源.
    
    位置: 利用 JSON 序列化中 field 顺序的微小变化
    """
    # 方案 1: 添加一个看似无害但值可识别的字段
    marker = hashlib.sha256(f"{license_id}:canary:v1".encode()).hexdigest()[:8]
    payload["_internal_check"] = marker
    # 客户端验 token 时若 _internal_check != expected → 篡改
    return payload
```

**破解流程**: 用户 A 买 license → 分享到论坛 → 我们抓取论坛 token → 解 `_internal_check` → 反查到用户 A → 吊销 + 发律师函.

---

# Part VI — Layer 0/1: 网络 + 认证层加固

## 6.1 Cert Pinning

```python
# core/license/network.py
import ssl
import hashlib
import httpx

# 编译时硬编码 (服务端证书公钥 hash)
EXPECTED_CERT_SHA256 = b"\x12\x34\x56..."  # 32 bytes

class PinnedHTTPSTransport(httpx.HTTPTransport):
    def handle_request(self, request):
        # 自定义 SSL 上下文, 拒绝任何不匹配 pinning 的证书
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        
        # 用 pyOpenSSL 取证书 pub key hash
        # (httpx 原生不支持, 需要自定义)
        # ...
        return super().handle_request(request)

def make_pinned_client() -> httpx.AsyncClient:
    transport = PinnedHTTPSTransport(retries=2)
    return httpx.AsyncClient(
        transport=transport,
        timeout=30.0,
    )
```

## 6.2 请求签名 (防重放)

```python
def sign_request(secret: bytes, body: dict) -> dict:
    """
    标准化 + HMAC-SHA256 签名.
    加 timestamp + nonce 防重放.
    """
    import time, secrets, hmac, hashlib, json
    
    body["timestamp"] = int(time.time() * 1000)
    body["nonce"] = secrets.token_hex(16)
    
    # 标准化: keys 排序后 JSON
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'))
    
    sig = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    body["sig"] = sig
    return body

# 服务端
def verify_request(secret: bytes, body: dict) -> bool:
    sig = body.pop("sig", None)
    if not sig:
        return False
    
    # 时间窗口 5 分钟
    now_ms = int(time.time() * 1000)
    if abs(now_ms - body["timestamp"]) > 300_000:
        return False
    
    # nonce 查 Redis (防重放)
    if redis.exists(f"nonce:{body['nonce']}"):
        return False
    redis.setex(f"nonce:{body['nonce']}", 600, "1")  # 10 分钟
    
    # 验签
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'))
    expected = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
```

## 6.3 服务端时间权威

```python
# 客户端不信任本地时间!
# 每次 license 验证都带 server_timestamp, 客户端用它做过期判断.

# 客户端:
def check_expired(token_payload, server_time_ms):
    # 不用 time.time() — 用户可以改系统时间
    return token_payload["exp"] * 1000 < server_time_ms

# 如果多次验证失败 (网络断), 允许用本地时间 + 72h 宽限
# 但记录 offset: 本地时间 vs 服务器时间差 > 1 小时 → 告警
```

---

# Part VII — 失败处理策略 (发现破解后该怎么办)

## 7.1 四种反应模式

| 模式 | 描述 | 优点 | 缺点 | 适用 |
|---|---|---|---|---|
| **FAIL_FAST** | 立即弹"License Invalid" 退出 | 简单 | 攻击者一眼定位触发点 | ❌ 不推荐 |
| **FAIL_SILENT** | 悄悄退出, 无错误提示 | 攻击者难定位 | 用户懵 | 可疑但不确定时 |
| **DEGRADE** | 业务能力悄悄降级 (50% 成功率) | 迷惑性强 | 实现复杂 | ⭐ 推荐默认 |
| **POISON** | 返回假数据 + 记录行为 | 收集情报 + 浪费对方时间 | 误伤正常用户 | 高置信度时 |

## 7.2 延迟失效 + 不确定性

```python
class FailureOrchestrator:
    """
    发现破解证据后, 不立即反应.
    用随机延迟 + 分散触发点 让攻击者无法 debug 定位.
    """
    def __init__(self):
        self.poison_level = 0  # 0-10
    
    def report_evidence(self, evidence_type: str, weight: int = 1):
        self.poison_level = min(10, self.poison_level + weight)
    
    def maybe_sabotage(self):
        """每次业务调用都可能触发 (概率性)."""
        import random
        if self.poison_level == 0:
            return
        
        # 概率 = poison_level / 10 的 1/10
        if random.random() < self.poison_level * 0.01:
            self._trigger_random_sabotage()
    
    def _trigger_random_sabotage(self):
        """随机破坏 (看起来像 bug)."""
        import random, os, time, threading
        
        choices = [
            lambda: time.sleep(random.randint(10, 60)),  # 卡顿
            lambda: (_ for _ in ()).throw(IOError("disk err")),  # 假 IO 错
            lambda: os._exit(random.choice([0, 1, 0xDEAD])),  # 随机退出码
            lambda: os.environ.update({"_CORRUPTED": "1"}),  # 污染环境变量
        ]
        
        # 非立即触发 — 延迟 0-30 秒
        def _delayed():
            time.sleep(random.uniform(0, 30))
            random.choice(choices)()
        threading.Thread(target=_delayed, daemon=True).start()
```

## 7.3 业务降级 (最优雅)

```python
# 不是"拒绝服务", 而是"服务变差"
# 攻击者体验: 发布成功率 50%, 以为是网络问题
#             图像处理有几率崩溃, 以为是 FFmpeg 问题
#             Agent 决策随机, 以为是 bug

@protected
def publish_video(account, drama):
    if license_status == "tainted":
        # 50% 概率"失败"
        if random.random() < 0.5:
            raise Exception("Network timeout")  # 假错误
        # 另外 50% 正常 — 让攻击者以为偶发
    
    # 正常流程
    return do_publish(account, drama)
```

**攻击者角度**: "我破解成功了, 但软件不太稳定, 可能是 bug". 继续用一段时间后发现"这软件质量不行", 放弃.

**真实用户**: 没有问题, 一切正常.

---

# Part VIII — 法律层 (最后一道防线)

## 8.1 EULA 必需条款

```markdown
END USER LICENSE AGREEMENT (EULA)

4. PROHIBITED ACTIONS
You agree NOT to:
(a) Reverse engineer, disassemble, decompile the Software
(b) Remove or alter any proprietary notices
(c) Share, distribute, or publish activation codes, license tokens, 
    or any authentication material
(d) Use the Software on more machines than licensed
(e) Attempt to bypass, circumvent, or disable any license 
    enforcement mechanism

5. LEGAL REMEDIES
Violations may result in:
- Immediate license termination without refund
- Liquidated damages of $10,000 per violation (pre-agreed amount)
- Injunctive relief
- Criminal referral under applicable computer fraud statutes 
  (CFAA, DMCA §1201 in US; 刑法第 285 条 in China)
```

## 8.2 水印溯源 (技术 + 法律 结合)

- 每个 license token 带用户 ID 水印
- 客户端日志每 100 条带一次隐藏水印 (用户 ID 哈希)
- 生成的视频元数据 EXIF 里带 license_id (隐形)
- 破解版流通到论坛 → 分析水印 → 反查用户 → 发律师函

## 8.3 DMCA / 通知-删除

| 平台 | 措施 | 成本 |
|---|---|---|
| GitHub | DMCA takedown | 免费, 邮件 |
| 百度网盘 | 举报侵权 | 免费 |
| 迅雷 | 举报 | 免费 |
| 淘宝/闲鱼 | 知识产权投诉 | 免费 |
| 破解论坛 | 通过国内 ICP 备案投诉 | 免费, 3-7 天 |
| 海外论坛 | DMCA → Cloudflare → 源站 | 免费, 7-30 天 |

## 8.4 民事索赔模板

**中国**: 发律师函 → 起诉 → 取证 (公证处见证下载破解版 + 水印分析)
**诉讼金额**: 按 "每个破解 license 的市场价 × 下载数" 算. 通常一个破解版涉及 1000+ 下载 × $100 = $100K 索赔.

---

# Part IX — 实施优先级路线图

## Phase 0 — 免费基础 (2 周, $0)

```
□ Nuitka 编译整个 core/ 为 .exe (移除 .py 源)
□ 字符串加密工具 core/license/_strings.py
□ 基础 anti-debug: IsDebuggerPresent + sys.gettrace (5 行代码)
□ 基础 anti-VM: 注册表扫描 (10 行代码)
□ Build ID 注入 (每次打包唯一)
□ EULA + 水印
```

**能挡住**: L1 业余逆向 90%.

## Phase 1 — 低成本加固 (1 个月, ~$150)

```
□ PyArmor Pro 许可 ($99/年)
□ Cert Pinning (客户端 + 服务端)
□ 代码自校验 (self-hash)
□ 延迟失效 + 分散触发点
□ 服务端多机检测 (IP 聚类算法)
□ 地理跳跃检测
□ Token 水印 + 溯源系统
□ Redis nonce 防重放
```

**能挡住**: L2 熟练 70%, L3 职业 30%.

## Phase 2 — 中等加固 (3 个月, ~$600)

```
□ VMProtect ($500 买永久) 包 core/license/crypto.py 的 3 个关键函数
□ 高级 anti-hook (PEB.NtGlobalFlag + API 完整性扫描)
□ Frida 多维检测 (进程 + TCP + 线程名)
□ 蜜罐激活码 + 业务诱饵
□ ML 异常检测 (Isolation Forest)
□ Build-specific canary (每版独立水印)
□ 法律模板库 (EULA + 律师函 + DMCA 模板)
```

**能挡住**: L3 职业 80%, L4 团伙开始动摇.

## Phase 3 — 企业级 (6+ 月, $2K+)

```
□ 代码控制流混淆 (LLVM ollvm)
□ 多版本冗余实现 (3 份验证函数投票)
□ 行为分析 ML 模型 (训练 + 调参)
□ 威胁情报订阅 (监控破解论坛)
□ 法律团队合作 (知识产权律师 retainer)
□ 红蓝对抗演练 (雇人来破)
```

**能挡住**: L4 团伙 95%.

---

# Part X — 成本 vs 收益经济学

## 10.1 破解成本估算 (单个破解者)

| 阶段 | 我们投入 | 破解者需要的时间 | 破解者成本 (按$50/hr) |
|---|---|---|---|
| 无防护 | 0 | 1 hour | $50 |
| Phase 0 | $0 | 1 week | $2,000 |
| Phase 1 | $150 | 1 month | $8,000 |
| Phase 2 | $600 | 3-6 months | $30,000-$60,000 |
| Phase 3 | $2,000+ | 6-12 months | $60,000-$120,000 |

## 10.2 合理投资点

**假设**:
- 软件单价 $100/月
- 破解版流通会损失 30% 市场 → $30/破解用户/月
- 1000 个潜在用户 → 破解损失 $30K/月

**投资建议**:
- **MRR < $5K**: Phase 0 (免费, 足够)
- **MRR $5K - $20K**: Phase 1 (每年 $150, 挡住业余+熟练)
- **MRR $20K - $100K**: Phase 2 (每年 $500-$1K, 挡住职业)
- **MRR > $100K**: Phase 3 + 法律团队

## 10.3 不该投资的情况

- 软件已经免费/开源: 没必要防
- 用户群 < 100: 破解者不感兴趣
- 软件依赖必联网服务: 服务端防线够用

---

# Part XI — 对照 KS184 + 改进清单

| 维度 | KS184 | 我们 | 效果对比 |
|---|---|---|---|
| 代码保护 | WinLicense ($299) + PyArmor | Nuitka + PyArmor | 节省 $300, 同等强度 |
| Anti-Debug | WL 内置 8 种 | 手写 5 种 + Python 层 | 差不多, 我们更透明 |
| Anti-VM | WLCheckVirtualPC | 注册表 + 进程 + CPUID | 我们更全面 |
| Anti-Hook | (没有明显实现) | 显式检测 Frida | ✅ 超越 KS184 |
| 代码自校验 | WLProtectCheckCodeIntegrity | 自写 hash check | 平 |
| 多机检测 | (服务端未知) | DBSCAN + 地理跳跃 | ✅ 算法更清晰 |
| 蜜罐 | (无) | 激活码 + 功能诱饵 | ✅ 创新 |
| 水印溯源 | (无明显) | Token + 日志 + 视频 EXIF | ✅ 超越 |
| 失败处理 | 崩溃 (粗暴) | 降级 + 延迟 + 概率 | ✅ 更高级 |
| 法律条款 | 民间软件 (不规范) | 正式 EULA + 水印法律案 | ✅ 专业 |

**总结**: KS184 是**技术防御强 (WinLicense 壳) + 法律弱**, 我们是**技术防御中等 + 行为分析强 + 法律完整**. 前者挡业余后者全链条.

---

# Part XII — 关键文件清单

落地时需要创建的文件:

```
core/license/
├── agent.py                  # LicenseAgent 主入口 (已在蓝图)
├── crypto.py                 # PASETO + HMAC
├── hwid.py                   # HWID 计算
├── storage.py                # SQLCipher 本地存储
├── _strings.py               # 字符串加密 (NEW)
├── build_info.py             # Build ID 注入 (NEW)
├── integrity.py              # 自校验 (NEW)
├── anti_debug.py             # Anti-Debug (NEW)
├── anti_frida.py             # Anti-Frida (NEW)
├── anti_vm.py                # Anti-VM (NEW)
├── failure.py                # Failure orchestrator (NEW)
└── honeypot.py               # 客户端诱饵 hook (NEW)

server/license_api/
├── detection/
│   ├── multi_machine.py      # 多机检测 (NEW)
│   ├── anomaly_ml.py         # ML 异常检测 (NEW)
│   └── watermark.py          # 水印溯源 (NEW)
├── honeypot/
│   ├── activation_codes.py   # 蜜罐激活码 (NEW)
│   └── tainted_license.py    # 污染 license 处理 (NEW)
└── legal/
    ├── eula_templates.py     # EULA 生成器 (NEW)
    └── audit_trail.py        # 法律证据链 (NEW)

docs/
├── APP_LICENSE_ARCHITECTURE_BLUEPRINT.md    # 已有
├── APP_ANTI_CRACK_FULL_DEFENSE.md           # 本文 (NEW)
├── APP_ANTI_CRACK_IMPL_PHASE0.md            # 待写: Phase 0 实施 runbook
├── APP_ANTI_CRACK_IMPL_PHASE1.md            # 待写
├── APP_ANTI_CRACK_LEGAL_PLAYBOOK.md         # 待写: 法律应对手册
└── APP_ANTI_CRACK_INCIDENT_RESPONSE.md      # 待写: 破解事件响应流程
```

---

# Part XIII — 立即能做的第一步

**不用等整套蓝图实现, 今天就能做的** (按优先级):

## Step 1: EULA + 用户同意记录 (1 小时)

```python
# 所有用户首次启动前必须点击 "I Agree"
# 同意时间 + IP + HWID 写入服务端
# 这是法律追责的基础
```

## Step 2: 字符串加密 (2 小时)

```python
# 把所有 API URL / 密钥前缀用 _strings.S() 包起来
# 编译后 `strings output.exe | grep license` 找不到
```

## Step 3: 基础 Anti-Debug (30 分钟)

```python
# main() 第一行:
if check_python_tracers() or is_debugger_present():
    import os; os._exit(0)
# 虽然 L2 能绕, 但挡住所有 L1 入门者
```

## Step 4: Build ID (15 分钟)

```bash
# 构建脚本里:
BUILD_ID=$(openssl rand -hex 8)
sed -i "s/BUILD_ID_PLACEHOLDER/${BUILD_ID}/g" core/license/build_info.py
# 每次发版自动失效老的破解 patch
```

这 4 步加起来不到 4 小时, 能挡住 80% 业余破解.

---

# 总结 — 反破解 10 条心法

1. **不求绝对安全, 求不值得**
2. **深度防御, 每层独立**
3. **延迟失效, 隐藏触发点**
4. **降级而非拒绝**
5. **服务端是最后真源**
6. **水印随处可见**
7. **心跳 + 行为分析**
8. **蜜罐陷阱网**
9. **法律做兜底**
10. **每次发版刷新防线 (Build ID)**

**核心一句话**: **技术挡业余 + 数据识别职业 + 法律对付规模化**. 三者缺一不可.

---

*(本文档 v1.0, 2026-04-19 完结. 与 APP_LICENSE_ARCHITECTURE_BLUEPRINT.md 配套使用.)*
