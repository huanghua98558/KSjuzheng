# AI 种子学习: 去重技术知识库 (v2 — 基于代码实测)

> **目的**: 把"快手查重机制 + 我们 11 recipe 真实抗查重能力 + KS184 对标差距"
> 三份准确知识喂给 AI 种子板块, 让 planner/executor 知道
> "什么场景该用什么 recipe", 让 AI 决策在实际执行中不再凭感觉.
>
> **生成日期**: 2026-04-20
> **数据源**:
>   - `core/processor.py` 1803 行逐行读 (11 recipe + 2 pipeline 函数)
>   - `core/pattern_animator.py` 325 行 (7 动画 filter)
>   - `core/scale34.py` 316 行 (3:4 前置)
>   - `core/md5_modifier.py` 125 行 (MD5 追加字节)
>   - `KS184_下载剪辑去重_Canonical参考v3.md` 557 行 (Frida/dump 真实 argv)
>   - 3 个并行 Agent 外部调研 (web 15 篇)
>
> **重要**: 本版**推翻上一版报告的对齐度数字**. 上一版是 Agent 估计,
> 本版是代码逐 filter 对 canonical argv 核过的真实情况.

---

## §1 快手查重 5 层防御矩阵 (行业共识)

| 层 | 名称 | 算法 | 判定信号 | 绕过成本 |
|---|---|---|---|---|
| **L1** | 字节 hash | MD5 / SHA1 / xxHash | 文件哈希完全一致 | 极低 (改 1 字节即可) |
| **L2** | 容器/元数据指纹 | encoder / creation_time / container / GOP / bitrate 组合 | 组合指纹相似 | 低 (re-encode) |
| **L3** | 感知哈希 | pHash (DCT) / dHash / aHash / HashNet | 抽帧 → 64-bit hash → Hamming ≤ 10 | 中 (像素级叠加 / 颜色微调) |
| **L4** | 音频指纹 | Chromaprint / ACRCloud / 快手 2022 国家优秀奖专利 | 11025Hz → 色度特征 → 片段匹配 | 中高 (需覆盖频移/变速) |
| **L5** | CNN embedding | 3D ResNet / Quadruplet CNN / Keye-VL / KuaiMod-7B (2025-05) | 语义向量 + Hamming/余弦相似度 | 极高 (改内容/台词/叙事) |

**2025 新武器**:
- KuaiMod-7B (2025-05): 多模态 VLM, 看封面+标题+OCR+ASR+评论综合判别, 15 类细粒度劣质分类
- Keye-VL 1.5 (2025-11 开源): 128K 上下文 + 0.1 秒时序定位
- 短剧专项 (2026-02 广电): 单账号单日上传 ≤ 30 部, AI 仿真人剧分账 60%

**审核**: 异步为主, 爆款后二审 (秋后算账). 关联: 设备指纹 + IP + 同 MCN + 同分钟同剧 → 高危.

---

## §2 我们 11 recipe 真实实现分析 (代码逐 filter 核过)

**每项**: 代码文件+行号 / 关键 filter 摘要 / 核心反查重手段 / 对齐 canonical 的**真实**百分比 / 明确缺口.

### 2.1 `mvp_trim_wipe_metadata` (processor.py:134)

| 项 | 值 |
|---|---|
| 核心 | `-c copy + -map_metadata -1 + -movflags +faststart` |
| 反查重机制 | 截片段 + 抹 global metadata (不重编码) |
| 对齐 KS184 | **N/A** (KS184 canonical 没单独列 mvp — 这是我们自创的**初筛级**) |
| 5 层打穿 | L1:⭐ L2:⭐⭐⭐⭐⭐ L3:⭐ L4:⭐ L5:⭐ |

**现实用途**: 速度极快 (< 1s), 适合"走个过场"的初筛或测试账号冷启动. **绝不用于真流量场景**.

### 2.2 `light_noise_recode` (processor.py:156)

| 项 | 值 |
|---|---|
| 核心 | `noise=c0s=5:c0f=t+u:allf=t+u + libx264 or h264_nvenc + VBR 2500k` |
| 反查重机制 | 轻噪点 (c0s=5, 肉眼不可察) + 重编码改指纹 |
| 对齐 KS184 | **N/A** (canonical 里没有, 我们自创中档) |
| 5 层打穿 | L1:⭐⭐ L2:⭐⭐⭐⭐ L3:⭐⭐ L4:⭐ L5:⭐⭐ |

**缺口**: 无单独对应, 但比 mvp 强. **L4 音频层**和所有 recipe 一样弱.

### 2.3 `zhizun` / `zhizun_overlay` (processor.py:333)

| 项 | 值 |
|---|---|
| 核心 filter | `[0:v]noise=alls=14:allf=t+u,eq=brightness=0.02:contrast=1.06:saturation=1.08:gamma=1.02[bg]; [1:v]format=rgba,scale=1080:1920,colorchannelmixer=aa=0.3[overlay]; [bg][overlay]overlay=0:0` |
| 关键编码 | `libx264 -preset medium -b:v 2500k -maxrate 5000k -bufsize 10000k` |
| 对齐 canonical §2.4 变体 A | **85%** — filter 主体完全一致, **但**: <br>• canonical 用 `-crf 18` (无码率上限), 我们用 VBR 2.5M (有意改, 防 371MB 爆体积) <br>• canonical 无 matroska 伪装 (对齐, 正确) |
| 5 层打穿 | L1:⭐⭐ L2:⭐⭐⭐⭐ L3:⭐⭐⭐ L4:⭐⭐ L5:⭐⭐⭐ |

**明确缺口**: 无关键缺口 — VBR 替换是有意工程修复. 可视为 "95% 对齐 + 1 个有意偏差".

### 2.4 `zhizun_mode5_pipeline` (processor.py:1600) — 5 步流水线

| 项 | 值 |
|---|---|
| 尺寸 | 716×954 (要求 scale34 前置) |
| 核心 | Step 4 zoompan_concat (`[0:v]trim=0:30 + [1:v]zoompan+tpad=140 + concat=n=2`) → imgvideo <br>Step 5 `interleave + matroska 伪装` |
| 两个 Step 5 路径 | <br>• **interleave_ks184** (严格对齐, 默认): `setsar,fps=30,tpad+interleave+select≠n=1` <br>• **overlay_compat** (fallback): `overlay=0:0:shortest=1` |
| 对齐 canonical §2.4 变体 B | **interleave 路径 80%**, **overlay 路径 60%** |
| 关键差异 (interleave) | <br>• canonical 用 **libx264 + yuv444p + x264-params "keyint=250:ref=2:bframes=2:aud=1:repeat-headers=0:level=9.9"** <br>• 我们用 **h264_nvenc + yuv420p + preset=p4 + vbr_hq -cq 25 -b:v 2.5M** <br>• → NVENC 硬编速度快, 但**失去了 canonical 的 x264-params 反查重特征** (keyint=250 强关键帧 / ref=2 / aud=1 等) |
| 5 层打穿 | L1:⭐⭐⭐⭐ L2:⭐⭐⭐⭐⭐ L3:⭐⭐⭐⭐⭐ L4:⭐⭐⭐ L5:⭐⭐⭐⭐⭐ |

**明确缺口**:
1. **没走 canonical libx264 + x264-params 路径** (速度 vs 反查重权衡, 快 5-10 倍但少 1 个反查重维度)
2. overlay fallback 路径失去逐帧交织, L5 降到 ⭐⭐⭐

### 2.5 `kirin_mode6` (processor.py:1221) — 7 步流水线

| 项 | 值 |
|---|---|
| 尺寸 | 1080×1920 (原尺寸) |
| 步骤 | <br>Step 2 `-vframes 1 -q:v 1` 抽帧 <br>Step 3 `[1]scale=3240:5760[video];[0][video]blend=all_expr='A*(1-0.5)+B*0.5'` <br>Step 4 `zoompan=z='(1+0.001*on)':d=30 ...` aux.mp4 <br>Step 5 `concat=n=2:v=1` (src 前 30 帧 + aux loop) <br>Step 6 `[v0f][v1d]interleave,select='not(eq(n,0))'` + `h264_nvenc -preset p1 -rc vbr -cq 20 -b:v 3000k -maxrate 4000k -bufsize 8000k` + `-f matroska -write_crc32 0` <br>Step 7 抽第 1 帧封面 |
| 对齐 canonical §2.6 | **95%** — 所有 7 步 argv 都对上. 唯一差异: canonical 提 "interleave,select='not(eq(n,0))'" 我们用 "select='not(eq(n,0))'" (一致) |
| 5 层打穿 | L1:⭐⭐⭐ L2:⭐⭐⭐⭐ L3:⭐⭐⭐⭐ L4:⭐⭐⭐ L5:⭐⭐⭐⭐ |

**结论**: 这是对齐度最高的. **实战主力** ✅

### 2.6 `wuxianliandui` (processor.py:404) — 🔴 明确缺 Step 2

| 项 | 值 |
|---|---|
| 我们实现 | Step 1 的 cach1: `libx264 + force_key_frames expr:eq(n,20) + fps=30 + x264-params "keyint=65535:ref=16:bframes=16:b-adapt=2"` (注: **我们没加 x264-params**! 让我再查…) |

让我回查一下…

```python
return [
    _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
    "-ss", f"{start_sec:.2f}",
    "-i", src,
    "-t", f"{target_dur:.2f}",
    "-c:v", "libx264", "-preset", str(preset),
    "-profile:v", "high", "-level:v", "4",
    "-force_key_frames", f"expr:eq(n,{force_keyframe_n})",
    "-pix_fmt", "yuv420p",
    "-vf", "fps=30",
    *_libx264_vbr_args(),
    "-c:a", "aac",
    # ...没 x264-params
]
```

确认: **没 x264-params**.

| 对齐 canonical §2.2 | **45%** (比 Agent 说的 60% 还低) |
|---|---|
| 关键缺口 | <br>1. **没 x264-params** — canonical Step 1 有 `keyint=65535:ref=16:bframes=16:b-adapt=2` <br>2. **完全没 Step 2** — canonical 有后续 `concat=n=2` 拼接 src 前 30 帧 + pattern zoompan, 我们只有 Step 1 cach1 |
| 5 层打穿 | L1:⭐⭐ L2:⭐⭐⭐ L3:⭐⭐ L4:⭐⭐ L5:⭐⭐ |

**结论**: **真实对齐 45%**, 不是 60%. 缺 Step 2 是硬伤, 需要补抓或补码.

### 2.7 `yemao` (processor.py:455) — 🔴 有关键缺口

| 项 | 值 |
|---|---|
| 我们实现 | `split=12 + 12 个 trim+loop+crop+rotate 分支 + xstack=12:layout=3×4` + 末尾 `noise=alls=6 + eq` |
| 对齐 canonical §2.7 | **60%** |
| 关键差异 | <br>1. **帧挑选机制**: canonical 用 `select='eq(n,<rand_frame>)'`, 我们用 `trim=start={pct*dur}:duration=0.5 + loop` (语义近似但生成帧不同) <br>2. **完全没走融图**: canonical config 有 `yemao_blend_enabled / yemao_blend_opacity / yemao_image_mode`, UI 允许夜猫选图片模式 + 融图. 我们`_recipe_yemao` **压根没读这几个 config** <br>3. **没走 image_mode 分发**: canonical 支持 6 图片模式叠加, 我们纯 12 格马赛克不叠任何 pattern |
| 5 层打穿 | L1:⭐⭐⭐ L2:⭐⭐⭐⭐ L3:⭐⭐⭐⭐⭐ L4:⭐⭐ L5:⭐⭐⭐ |

**结论**: L3 很强 (12 格空间打乱是真实的), 但**缺融图 + 图片模式集成**. 对齐度从 80% 砍到 60%.

### 2.8 `bushen` (processor.py:548) — 🔴 机制根本不同

| 项 | 值 |
|---|---|
| 我们实现 | 两路: blend_enabled=True 走 `noise+eq+pattern blend`; blend_enabled=False 走 `纯 vf noise+eq + -c:a copy` |
| cfg64.exe | ✅ 优先用 (`_get_bushen_ffmpeg`) |
| 对齐 canonical §2.3 | **30%** |
| 关键差异 | canonical 说 bushen 是 `AlgorithmTest` Python 类内部调用, 最终**走 `interleave_videos` 方法** (即 interleave 逐帧交织). 我们是**单 pass vf 滤镜**, 根本不做 interleave |
| 5 层打穿 | L1:⭐⭐ L2:⭐⭐⭐⭐ L3:⭐⭐⭐ L4:⭐ (或 copy → ⭐) L5:⭐⭐⭐ |

**结论**: 我们的 bushen 是"轻量 CPU 模式"定位, 名字叫 bushen 但机制和 KS184 真实 bushen 差得远. 真实对齐 30%.

### 2.9 `touming_9gong` (processor.py:669)

| 项 | 值 |
|---|---|
| 我们实现 | `[0:v]split=2[base][src]; [src]fps=9/dur,scale,crop,tile=3x3,{animation_filter}[grid]; [base][grid]blend=all_expr='A*(1-op)+B*op'` + `-f matroska -metadata encoder=kuaishou_mode3_processor -write_crc32 0` |
| 动画 | ✅ 7 种全实现 (zoom_in/zoom_out/zoom_pulse/pan_left/pan_right/rotate_cw/rotate_ccw, 见 pattern_animator.py) |
| 对齐 canonical §2.1 + §1 | **85%** |
| 小差异 | <br>1. canonical 的 pulse 用 `t` (秒) 不是 `on` (帧号), 我们 pattern_animator.py 已修 `on/(4*fps)` 等效但实现不同 <br>2. canonical 是 2 个 input (原 + pre-made pattern), 我们是 1 input split 后内嵌生成 (结果等价) <br>3. **只用 1 个动画** (代码 `anim = animations[0]` 注释说"多动画需要多阶段 concat"), canonical 是"7 选 N 多选" |
| 5 层打穿 | L1:⭐⭐⭐ L2:⭐⭐⭐⭐⭐ L3:⭐⭐⭐⭐ L4:⭐⭐ L5:⭐⭐⭐⭐ |

**结论**: 对齐 85%. 多动画叠加是小缺口.

### 2.10 `rongyu` (processor.py:777) — 🔴 缺 concat=n=2

| 项 | 值 |
|---|---|
| 我们实现 | 纯 overlay blend: `noise=8,eq,unsharp + format=rgba,scale,colorchannelmixer + blend` |
| 关键编码 | `libx264 -preset faster + x264-params "keyint=65535:ref=16:bframes=16:b-adapt=2"` ✅ |
| 对齐 canonical §2.5 | **65%** (Agent 说 90% 偏乐观) |
| 关键缺口 | canonical 的核心 filter 是 **`concat=n=2`**: <br>`[0:v]trim=start_frame=0:end_frame=30,setpts,scale=720:1280[first]; [1:v]scale,crop,zoompan=z='min(zoom+0.001,1.5)':d=70[..zoompan]; [first][..zoompan]concat=n=2:v=1:a=0` <br>我们是**纯 blend**, 没 concat 拼接. 这是实质差异 — canonical 用"原视频前 30 帧 + pattern zoompan"接起来, 我们是"原视频全程 blend pattern" |
| x264-params | ✅ 有 (`keyint=65535:ref=16:bframes=16:b-adapt=2`) 这个对齐度高 |
| 5 层打穿 | L1:⭐⭐⭐ L2:⭐⭐⭐⭐ L3:⭐⭐⭐⭐ L4:⭐⭐ L5:⭐⭐⭐ |

**结论**: x264 激进参数对齐了, 但核心的 `concat=n=2` 缺. 真实 65%.

### 2.11 `qitian` 图片模式 6 种 (qitian.py)

| 项 | 值 |
|---|---|
| 实现 | qitian_art / gradient_random / random_shapes / mosaic_rotate / frame_transform / random_chars 6 种 PIL 独立 |
| 集成 | ✅ processor 的 `_generate_pattern_by_mode` 分发器已调用 qitian.generate — 上一版报告错说是"孤岛", **实际已接入** mode5/mode6/zhizun_overlay/bushen/rongyu |
| 对齐 canonical §0 图片模式 (6 选 1) | **100%** (6 种全对应) |

**但有 1 个问题**: `yemao` 的 `_recipe_yemao` 里**没调 `_generate_pattern_by_mode`**, 所以夜猫没融合图片模式. 这是 §2.7 的缺口具体表现.

---

## §3 跨 recipe 共通短板 (AI 不可忽视)

这些是**全系** recipe 都有的问题, 不是单 recipe 问题:

### 3.1 L4 音频层全系弱
全 11 recipe 都只是 `aac 128k` (bushen 纯模式甚至 `-c:a copy`), **无一做音频 filter**. 快手有音频指纹国家优秀奖专利, L4 层是真实威胁. 改进方向:
- `asetrate + atempo` 音调微移 (±50 cent) + 变速复位
- `anoise` 叠微弱白噪 (< -40dB)
- 多声道 downmix 或声道互换
- **这些 filter 加到所有 recipe 的 ffmpeg 命令尾部即可**, 不改算法

### 3.2 调色链单一 (canonical §5 有但我们没)
Canonical 说 KS184 真实用的是组合链:
```
hue=s=0 → colorbalance=rs=0.3:gs=-0.3:bs=0.3 → eq=brightness=0.1:contrast=1.2 → curves=vintage
```
我们只用 `eq=brightness:contrast:saturation:gamma`. 缺 hue/colorbalance/curves.

### 3.3 MD5 修改 ✅ 已有 (md5_modifier.py 125 行)
追加 8-32 随机字节到 mp4 末尾, 改 L1 字节 hash 但不破坏播放. 对齐 canonical §0 "视频下载后修改 MD5" ✅.

### 3.4 scale34 前置 ✅ 已有 (scale34.py 316 行)
带 sin 动态水印公式 (T ∈ [45, 86] 随机). 实现和 canonical §3 略有差异 (我们是 3 层 scale+overlay+pad, canonical 是 decrease+scale+overlay), 但都合理. 对齐 90%.

---

## §4 重新评估的综合打穿能力 (代码实测 × 真实对齐)

| # | recipe | KS184 对齐 | L1 | L2 | L3 | L4 | L5 | 综合星 | 核心问题 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `mvp_trim_wipe_metadata` | N/A (自创) | ⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐ | 1.8 | 只抹 metadata |
| 2 | `light_noise_recode` | N/A (自创) | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | 2.2 | L4 弱 |
| 3 | `zhizun_overlay` | **85%** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 2.8 | VBR 替代 crf 有意 |
| 4 | `zhizun_mode5_pipeline` (interleave) | **80%** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **4.4** | NVENC 替代 libx264+x264-params |
| 5 | `zhizun_mode5_pipeline` (overlay fallback) | **60%** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 3.4 | 失去逐帧交织 |
| 6 | `kirin_mode6` | **95%** ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | **3.6** | (无明显缺口) |
| 7 | `wuxianliandui` | 🔴 **45%** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ | 2.2 | 缺 Step 2 concat + 缺 x264-params |
| 8 | `yemao` | 🔴 **60%** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 3.4 | 缺融图 + 缺 image_mode 集成 |
| 9 | `bushen` | 🔴 **30%** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | 2.6 | 缺 interleave (机制根本不同) |
| 10 | `touming_9gong` | **85%** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | 3.6 | 只用 1 动画 |
| 11 | `rongyu` | 🔴 **65%** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 3.2 | 缺 concat=n=2 |

**主力 2 种 (viral / established 账号专用)**:
- `kirin_mode6` — 95% 对齐 + 3.6 综合星 ✅
- `zhizun_mode5_pipeline` (interleave) — 80% 对齐 + 4.4 综合星 ⭐⭐⭐ (最强但差 x264-params)

**4 个有明确缺口的 recipe** (按优先级):
- 🔴 `wuxianliandui` 45% — 缺 Step 2 + x264-params
- 🔴 `bushen` 30% — 缺 interleave 机制
- 🔴 `rongyu` 65% — 缺 concat=n=2
- 🔴 `yemao` 60% — 缺融图 + image_mode 集成

---

## §5 AI 种子学习注入方案 (落地设计)

### 5.1 目标
让 planner/executor 基于以下 4 类**准确知识**自动选 recipe + 调参数:
1. 账号 tier (高 tier → 主力王炸 kirin_mode6 / zhizun_mode5_pipeline)
2. 风险信号 (爆款 / 同剧 / 同 IP → 升级强度)
3. recipe 真实 5 层打穿能力 (§4 矩阵, 机器可读版)
4. recipe 当前已知缺口 (避免 AI 在不该用时选了 wuxianliandui 却发现缺 Step 2)

### 5.2 数据层 — 3 张新表

**表 1**: `recipe_knowledge` — 每 recipe 的打穿能力 (从 §4 来)
```sql
CREATE TABLE recipe_knowledge (
  id INTEGER PRIMARY KEY,
  recipe_name TEXT UNIQUE NOT NULL,
  strength_overall REAL,              -- 综合星 (1-5)
  beat_l1_bytes INTEGER,              -- 0-5
  beat_l2_metadata INTEGER,
  beat_l3_phash INTEGER,
  beat_l4_audio INTEGER,
  beat_l5_cnn INTEGER,
  ks184_alignment REAL,               -- 真实对齐度 0-1 (从 §4 来)
  alignment_status TEXT,              -- "aligned"/"partial"/"divergent"
  known_gaps_json TEXT,               -- ["缺 Step 2", "缺 x264-params"] 明确缺口
  best_for_scenarios_json TEXT,       -- ["viral","established","high_risk"]
  avoid_scenarios_json TEXT,          -- ["low_value","testing"]
  notes TEXT,
  updated_at TEXT
);
```

**表 2**: `dedup_layer_knowledge` — 5 层科普 (LLMResearcher 用)
```sql
CREATE TABLE dedup_layer_knowledge (
  layer_code TEXT PRIMARY KEY,       -- "L1"..."L5"
  layer_name TEXT,
  algorithm TEXT,
  detection_signal TEXT,
  bypass_cost TEXT,
  bypass_tactics_json TEXT,
  kuaishou_specific TEXT,
  updated_at TEXT
);
```

**表 3**: `recipe_performance` — **实战反馈反推**
```sql
CREATE TABLE recipe_performance (
  id INTEGER PRIMARY KEY,
  recipe_name TEXT,
  scenario_tag TEXT,       -- "burst"/"high_tier"/"new_account"
  verdict TEXT,            -- correct/wrong/over_optimistic
  income_delta REAL,
  task_id TEXT,
  recorded_at TEXT
);
```

seed 脚本 `scripts/seed_dedup_knowledge.py` 从本报告 §2 + §4 写入前两表.
Analyzer 每日从表 3 反推调整表 1 的 `beat_l*` 星数.

### 5.3 决策层 — `_pick_recipe()` 加 scenario 感知

新模块 `core/scenario_scorer.py`:
```python
def compute_min_strength(account, drama, task_source) -> tuple[int, list[str]]:
    """返回 (min_strength 1-5, 触发原因 list).

    信号 1: 账号 tier  (new/testing=2, warming_up=3, established=4, viral=5)
    信号 2: 同剧 72h 多账号 ≥5  → 上 4
    信号 3: task_source=='burst'  → 直上 5
    信号 4: 近 6h 失败 ≥2       → 上 4
    信号 5: 同 MCN 同剧 24h ≥3  → 上 5
    """
```

然后 planner `_pick_recipe()` 改为:
```python
min_strength, reasons = compute_min_strength(account, drama, task_source)
# 从 recipe_knowledge 表选 strength_overall >= min_strength 且 ks184_alignment >= 0.70
pool = query("""SELECT recipe_name, strength_overall FROM recipe_knowledge
                 WHERE strength_overall >= ? AND ks184_alignment >= 0.70
                 ORDER BY strength_overall DESC""", (min_strength,))
# 在满足的 pool 里按 weighted_random + Thompson Sampling 选
```

**关键**: 低对齐度 recipe (wuxianliandui 45% / bushen 30%) **默认不进池**, 除非 config 显式打开.

### 5.4 执行层 — pipeline 加校验

`pipeline.py` 在 `process_video` 前加:
```python
# AI 选的 recipe 必须 ≥ scenario 要求的 min_strength
recipe_info = get_recipe_knowledge(recipe_name)
min_required = scenario.min_strength
if recipe_info["strength_overall"] < min_required:
    log.warning("[pipeline] recipe %s strength %.1f < min %d, 降级并告警",
                recipe_name, recipe_info["strength_overall"], min_required)
    recipe_name = "kirin_mode6"   # 安全 fallback
```

防止 Phase 1 E-2 bug 重演 (config 意外覆盖 AI 选择).

### 5.5 LLM 知识注入

`llm_researcher_agent.py::propose_new_rules` 的 prompt 头部加:
```
你有这些准确知识可用 (从 recipe_knowledge 表):

主力 recipe:
- kirin_mode6: 综合 3.6 星, L1★★★ L2★★★★ L3★★★★ L4★★★ L5★★★★, KS184 对齐 95%, 无明显缺口
- zhizun_mode5_pipeline: 综合 4.4 星 (王炸), L1★★★★ L2★★★★★ L3★★★★★ L4★★★ L5★★★★★, KS184 对齐 80%, 缺 canonical x264-params

缺陷 recipe (慎用):
- wuxianliandui: KS184 对齐只 45%, 缺 Step 2 concat, 只适合"走过场"场景
- bushen: 对齐 30%, 机制和 KS184 真实 bushen 根本不同 (缺 interleave)
- rongyu: 对齐 65%, 缺 canonical concat=n=2
- yemao: 对齐 60%, 缺融图 + image_mode 集成

通用短板 (所有 recipe):
- L4 音频层全系 ⭐-⭐⭐ (缺 asetrate/atempo/anoise)
- 调色链单一 (缺 hue+colorbalance+curves=vintage)

你分析失败时请引用这些事实. 不要推荐有已知缺口的 recipe 用于高风险场景.
```

### 5.6 Dashboard 可视化
`🎯 去重武器库` 页 (dashboard/streamlit_app.py):
- §4 矩阵热图 (11 recipe × 5 layer)
- 每 recipe 点开看: 已知缺口 + 建议场景 + 近 7 天使用次数 + 平均 income_delta
- 对齐度进度条 (从 recipe_knowledge.ks184_alignment)
- 实战反馈图 (recipe_performance 按 scenario 聚合)

### 5.7 闭环 (AI 不断推翻更新)

```
task 完 → 记 recipe_performance (recipe + scenario + verdict + income)
        ↓
analyzer 每日聚合: 每 recipe × scenario 的 success_rate + avg_income
        ↓
如果某 recipe 在某 scenario 下 success_rate < baseline - 0.1 → 自动下调
  beat_l* 星数 或 strength_overall (推翻 seed 数据)
        ↓
下次 planner 决策读最新 knowledge → 自动避开该组合
```

这就是用户要的"**AI 不断调整, 追求效益最大化, 推翻之前经验**"闭环.

---

## §6 落地分拆 (更新后的估时)

| 步骤 | 工作 | 估时 | 文件 |
|---|---|---|---|
| **S-1** | migrate_v25: 3 表 (recipe_knowledge / dedup_layer_knowledge / recipe_performance) | 0.5h | `scripts/migrate_v25.py` |
| **S-2** | seed 脚本: 把本报告 §4 数据 (11 recipe 真实对齐度+5 层星+gap) 写入 knowledge 表 | 1.5h (真实填要细致) | `scripts/seed_dedup_knowledge.py` |
| **S-3** | `core/scenario_scorer.py`: 5 个信号 → min_strength + reasons | 1h | 新文件 |
| **S-4** | 改 `_pick_recipe` 叠加 scenario 约束 + 读 recipe_knowledge 池 | 1h | 已有文件 |
| **S-5** | `pipeline.py` 加 recipe 降级校验 (min_strength 校验) | 0.5h | 已有文件 |
| **S-6** | LLMResearcher prompt 注入 knowledge | 1h | 已有文件 |
| **S-7** | Dashboard "🎯 去重武器库" 页 | 2h (5 层热图 + 缺口展示 + 实战反馈图) | `dashboard/streamlit_app.py` |
| **S-8** | `recipe_performance` 埋点 (pipeline + analyzer 双端) + analyzer 自动调 beat_l* | 1.5h | 多个文件 |
| **S-9** | E2E smoke test | 0.5h | `scripts/test_dedup_knowledge.py` |
| **合计** | 9 步 | **~9.5h** | **~1000 行新代码** |

---

## §7 本次报告 vs 上一版关键修正

上一版 (Agent 估计) vs 本版 (代码实测):

| Recipe | 上一版对齐度 | 本版真实对齐度 | 差值 |
|---|---|---|---|
| zhizun_mode5_pipeline (interleave) | 100% | **80%** | **-20** (缺 canonical libx264+x264-params 走 NVENC 了) |
| kirin_mode6 | 100% | **95%** | -5 (基本一致) |
| wuxianliandui | 60% | **45%** | **-15** (缺 Step 2 + 缺 x264-params, 两个坑) |
| yemao | 80% | **60%** | **-20** (缺融图 + 缺 image_mode 集成) |
| bushen | 85% | **30%** | **-55** (机制根本不同, 上版完全错) |
| rongyu | 90% | **65%** | **-25** (缺 concat=n=2) |
| touming_9gong | 85% | **85%** | 0 (一致) |
| zhizun_overlay | 95% | **85%** | -10 (VBR 替换 crf 18 是有意) |

**教训**:
- AI 自评经常偏乐观 (+15-55 点)
- 以后核对"代码是否用 filter X" 必须实打开 processor.py 查, 不能靠 Agent 总结
- canonical v3 是**基准事实**, 任何 Agent 说"对齐 100%" 都要对着 canonical argv 逐字段核

---

## §8 不在本次落地范围 (P2 延后)

- **L4 音频层 filter 补全** (独立小子项目 ~2h, 加 asetrate/atempo 到 3-4 个主力 recipe)
- **调色链升级** (hue+colorbalance+curves=vintage, ~1.5h, 改所有 libx264 recipe)
- **rongyu / wuxianliandui 缺失 filter 补码** (~3h, 需要参考 canonical §2.5/§2.2 的 concat filter 复刻)
- **bushen AlgorithmTest 机制重写** (~4h, 需要完全换架构到 interleave 模式)
- IP 池 / 设备指纹 (不在 dedup 范围)
- Keye-VL / KuaiMod-7B 本地对抗 (需要 16GB GPU)

---

## §9 引用资料

**内部**:
- `core/processor.py` (1803 行, 11 recipe + 2 pipeline)
- `core/pattern_animator.py` (325 行)
- `core/scale34.py` (316 行)
- `core/md5_modifier.py` (125 行)
- `core/qitian.py` (587 行)
- `KS184_下载剪辑去重_Canonical参考v3.md` (557 行, Frida/dump 基准)
- `docs/KS184_Q_X64_DECOMPILE.md` (1117 行, 静态反编译)

**外部** (Agent 调研):
- CSDN/掘金视频去重机制 (2022)
- 凌创派 2025 短剧去重白皮书
- 快手音频指纹 2022 国家优秀奖专利
- KuaiMod-7B / Keye-VL 1.5 (2025 开源)
- Chromaprint / ACRCloud 音频指纹
- 短剧专项治理 (2026-02 广电)

---

**报告结束. 等用户批准后按 §6 九步执行.**
