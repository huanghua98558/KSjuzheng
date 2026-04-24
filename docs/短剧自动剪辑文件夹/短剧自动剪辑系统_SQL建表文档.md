# 短剧自动剪辑系统 SQL 建表文档

## 1. 文档说明

本文档用于定义“短剧自动剪辑系统”的数据库建模方案，服务于以下目标：

- 一部完整短剧母版只做一次重分析
- 产出可复用的剧情资产库
- 基于剧情资产库，反复生成主力素材与辅助测试素材
- 支持失败恢复、人工审核、多版本导出

本文档只定义数据库层，不涉及代码实现。

适用数据库：

- SQLite（当前项目现状）
- 后续可平滑迁移到 PostgreSQL

字段设计原则：

- 时间尽量使用 `TEXT` 保存 ISO 时间
- JSON 类型在 SQLite 中统一用 `TEXT`
- 布尔值使用 `INTEGER`，约定 `0/1`
- 状态字段使用 `TEXT`
- 所有表尽量带 `created_at` / `updated_at`

---

## 2. 建模总览

本系统建议新增 11 张核心表：

1. `longform_videos`
2. `highlight_jobs`
3. `video_shots`
4. `video_utterances`
5. `story_segments`
6. `theme_lines`
7. `highlight_points`
8. `segment_scores`
9. `asset_plans`
10. `highlight_timelines`
11. `render_outputs`

推荐关系如下：

```text
longform_videos
  └─ highlight_jobs
       ├─ video_shots
       ├─ video_utterances
       ├─ story_segments
       ├─ theme_lines
       ├─ highlight_points
       ├─ segment_scores
       ├─ asset_plans
       ├─ highlight_timelines
       └─ render_outputs
```

设计原则：

- `longform_videos` 代表原始整剧资产
- `highlight_jobs` 代表某次针对该整剧的精剪任务
- 其余表都围绕某次 job 产出中间结果和导出结果

这样做的好处是：

- 一部剧可被多次分析或重跑
- 每次任务的中间结果互不污染
- 支持版本对比和失败恢复

---

## 3. 表设计与 SQL

### 3.1 `longform_videos`

用途：

- 存储完整短剧母版视频资产
- 记录源文件、标准化文件和基础元数据

```sql
CREATE TABLE IF NOT EXISTS longform_videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  source_path TEXT NOT NULL,
  normalized_path TEXT,
  source_hash TEXT,
  duration_sec REAL,
  fps REAL,
  resolution TEXT,
  width INTEGER,
  height INTEGER,
  audio_tracks INTEGER DEFAULT 1,
  subtitle_status TEXT DEFAULT 'unknown',
  source_type TEXT DEFAULT 'manual',
  source_note TEXT,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_longform_videos_title
ON longform_videos(title);

CREATE INDEX IF NOT EXISTS idx_longform_videos_source_hash
ON longform_videos(source_hash);
```

设计要点：

- `source_hash` 可用于母版去重
- `normalized_path` 支持后续标准化缓存
- `meta_json` 可保存 ffprobe 原始信息

---

### 3.2 `highlight_jobs`

用途：

- 存储精剪任务
- 记录当前执行阶段、状态、错误信息

```sql
CREATE TABLE IF NOT EXISTS highlight_jobs (
  id TEXT PRIMARY KEY,
  video_id INTEGER NOT NULL,
  job_name TEXT,
  target_duration_sec INTEGER DEFAULT 480,
  target_template TEXT DEFAULT 'main_family',
  status TEXT NOT NULL DEFAULT 'queued',
  current_stage TEXT DEFAULT 'queued',
  progress INTEGER DEFAULT 0,
  retry_count INTEGER DEFAULT 0,
  recover_from_stage TEXT,
  source_subtitle_path TEXT,
  operator_name TEXT,
  error_message TEXT,
  config_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  started_at TEXT,
  finished_at TEXT,
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_highlight_jobs_video_id
ON highlight_jobs(video_id);

CREATE INDEX IF NOT EXISTS idx_highlight_jobs_status
ON highlight_jobs(status);

CREATE INDEX IF NOT EXISTS idx_highlight_jobs_current_stage
ON highlight_jobs(current_stage);
```

建议状态枚举：

- `queued`
- `ingesting`
- `normalizing`
- `parsing`
- `understanding`
- `scoring`
- `assembling`
- `rendering`
- `review_pending`
- `success`
- `partial_failed`
- `failed`
- `canceled`

---

### 3.3 `video_shots`

用途：

- 存储镜头切分结果
- 作为后续剧情段切分的底层参考

```sql
CREATE TABLE IF NOT EXISTS video_shots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  shot_key TEXT NOT NULL,
  start_sec REAL NOT NULL,
  end_sec REAL NOT NULL,
  duration_sec REAL NOT NULL,
  visual_change_score REAL,
  motion_score REAL,
  face_closeup INTEGER DEFAULT 0,
  multi_person INTEGER DEFAULT 0,
  tags_json TEXT,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, shot_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_video_shots_job_id
ON video_shots(job_id);

CREATE INDEX IF NOT EXISTS idx_video_shots_start_sec
ON video_shots(job_id, start_sec);
```

---

### 3.4 `video_utterances`

用途：

- 存储 ASR 或字幕提取结果
- 支撑摘要、冲突识别、情绪线索分析

```sql
CREATE TABLE IF NOT EXISTS video_utterances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  utterance_key TEXT NOT NULL,
  start_sec REAL NOT NULL,
  end_sec REAL NOT NULL,
  duration_sec REAL NOT NULL,
  speaker TEXT,
  text TEXT NOT NULL,
  confidence REAL,
  speech_rate REAL,
  volume_peak REAL,
  emotion_score REAL,
  source_type TEXT DEFAULT 'asr',
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, utterance_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_video_utterances_job_id
ON video_utterances(job_id);

CREATE INDEX IF NOT EXISTS idx_video_utterances_start_sec
ON video_utterances(job_id, start_sec);
```

---

### 3.5 `story_segments`

用途：

- 存储剧情段
- 是整个系统最核心的业务表

```sql
CREATE TABLE IF NOT EXISTS story_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  segment_key TEXT NOT NULL,
  start_sec REAL NOT NULL,
  end_sec REAL NOT NULL,
  duration_sec REAL NOT NULL,
  summary TEXT,
  characters_json TEXT,
  tags_json TEXT,
  story_role TEXT,
  emotion_type TEXT,
  theme_line TEXT,
  plot_importance REAL DEFAULT 0,
  emotion_peak REAL DEFAULT 0,
  continuity_score REAL DEFAULT 0,
  hook_score REAL DEFAULT 0,
  climax_score REAL DEFAULT 0,
  suspense_exit_score REAL DEFAULT 0,
  independent_watch_score REAL DEFAULT 0,
  source_utterance_keys_json TEXT,
  source_shot_keys_json TEXT,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, segment_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_story_segments_job_id
ON story_segments(job_id);

CREATE INDEX IF NOT EXISTS idx_story_segments_theme_line
ON story_segments(job_id, theme_line);

CREATE INDEX IF NOT EXISTS idx_story_segments_story_role
ON story_segments(job_id, story_role);

CREATE INDEX IF NOT EXISTS idx_story_segments_start_sec
ON story_segments(job_id, start_sec);
```

建议 `story_role` 枚举：

- `hook`
- `background`
- `conflict`
- `reversal`
- `climax`
- `suspense`
- `bridge`

---

### 3.6 `theme_lines`

用途：

- 存储主题线、冲突线、人物线
- 支撑一剧多剪和主力 B 差异化

```sql
CREATE TABLE IF NOT EXISTS theme_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  theme_key TEXT NOT NULL,
  theme_name TEXT NOT NULL,
  theme_type TEXT,
  summary TEXT,
  segment_keys_json TEXT NOT NULL,
  main_characters_json TEXT,
  tension_score REAL DEFAULT 0,
  conversion_score REAL DEFAULT 0,
  coverage_score REAL DEFAULT 0,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, theme_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_theme_lines_job_id
ON theme_lines(job_id);

CREATE INDEX IF NOT EXISTS idx_theme_lines_theme_type
ON theme_lines(job_id, theme_type);
```

建议 `theme_type` 示例：

- `main_line`
- `female_growth`
- `marriage_conflict`
- `identity_reveal`
- `revenge_line`
- `mother_in_law_conflict`

---

### 3.7 `highlight_points`

用途：

- 存储高光点
- 支撑辅助素材模板生成

```sql
CREATE TABLE IF NOT EXISTS highlight_points (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  point_key TEXT NOT NULL,
  segment_key TEXT,
  start_sec REAL NOT NULL,
  end_sec REAL NOT NULL,
  point_type TEXT NOT NULL,
  summary TEXT,
  score REAL DEFAULT 0,
  quote_text TEXT,
  emotion_type TEXT,
  theme_line TEXT,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, point_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_highlight_points_job_id
ON highlight_points(job_id);

CREATE INDEX IF NOT EXISTS idx_highlight_points_point_type
ON highlight_points(job_id, point_type);

CREATE INDEX IF NOT EXISTS idx_highlight_points_theme_line
ON highlight_points(job_id, theme_line);
```

建议 `point_type` 枚举：

- `hook`
- `conflict`
- `reversal`
- `emotion`
- `climax`
- `suspense_exit`

---

### 3.8 `segment_scores`

用途：

- 存储剧情段的多维评分
- 支撑编排器按模板选段

```sql
CREATE TABLE IF NOT EXISTS segment_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  segment_key TEXT NOT NULL,
  plot_score REAL DEFAULT 0,
  emotion_score REAL DEFAULT 0,
  info_density_score REAL DEFAULT 0,
  visual_score REAL DEFAULT 0,
  relation_shift_score REAL DEFAULT 0,
  independent_watch_score REAL DEFAULT 0,
  hook_score REAL DEFAULT 0,
  background_score REAL DEFAULT 0,
  climax_score REAL DEFAULT 0,
  suspense_exit_score REAL DEFAULT 0,
  diversity_penalty REAL DEFAULT 0,
  final_score REAL DEFAULT 0,
  score_version TEXT DEFAULT 'v1',
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, segment_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_segment_scores_job_id
ON segment_scores(job_id);

CREATE INDEX IF NOT EXISTS idx_segment_scores_final_score
ON segment_scores(job_id, final_score DESC);
```

---

### 3.9 `asset_plans`

用途：

- 存储自动编排后的素材方案
- 代表“尚未导出的素材计划”

```sql
CREATE TABLE IF NOT EXISTS asset_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  plan_key TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  template_type TEXT NOT NULL,
  theme_focus TEXT,
  target_duration_sec INTEGER NOT NULL,
  actual_duration_sec REAL,
  selected_segment_keys_json TEXT NOT NULL,
  overlap_score REAL DEFAULT 0,
  generation_reason TEXT,
  plan_status TEXT DEFAULT 'draft',
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, plan_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_asset_plans_job_id
ON asset_plans(job_id);

CREATE INDEX IF NOT EXISTS idx_asset_plans_asset_type
ON asset_plans(job_id, asset_type);

CREATE INDEX IF NOT EXISTS idx_asset_plans_template_type
ON asset_plans(job_id, template_type);
```

建议 `asset_type`：

- `main`
- `aux`
- `hook`

建议 `template_type`：

- `main_a`
- `main_b`
- `aux_hook`
- `aux_conflict`
- `aux_reversal`
- `aux_emotion`
- `aux_satisfy`
- `aux_suspense`

建议 `plan_status`：

- `draft`
- `reviewed`
- `locked`
- `discarded`

---

### 3.10 `highlight_timelines`

用途：

- 存储可导出的时间轴和桥接文案
- 实现“计划”和“导出”的解耦

```sql
CREATE TABLE IF NOT EXISTS highlight_timelines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  plan_key TEXT NOT NULL,
  timeline_key TEXT NOT NULL,
  target_duration_sec INTEGER NOT NULL,
  actual_duration_sec REAL,
  timeline_json TEXT NOT NULL,
  bridge_text_json TEXT,
  subtitle_policy TEXT DEFAULT 'auto',
  cta_text TEXT,
  version INTEGER DEFAULT 1,
  is_final INTEGER DEFAULT 0,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, timeline_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_highlight_timelines_job_id
ON highlight_timelines(job_id);

CREATE INDEX IF NOT EXISTS idx_highlight_timelines_plan_key
ON highlight_timelines(job_id, plan_key);

CREATE INDEX IF NOT EXISTS idx_highlight_timelines_is_final
ON highlight_timelines(job_id, is_final);
```

---

### 3.11 `render_outputs`

用途：

- 存储导出结果
- 支撑多尺寸、多标题、多 CTA 版本

```sql
CREATE TABLE IF NOT EXISTS render_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  video_id INTEGER NOT NULL,
  plan_key TEXT NOT NULL,
  timeline_key TEXT NOT NULL,
  output_key TEXT NOT NULL,
  output_type TEXT NOT NULL,
  aspect_ratio TEXT DEFAULT '9:16',
  title_variant TEXT,
  cover_variant TEXT,
  cta_variant TEXT,
  file_path TEXT,
  subtitle_path TEXT,
  cover_path TEXT,
  duration_sec REAL,
  render_status TEXT DEFAULT 'queued',
  error_message TEXT,
  meta_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(job_id, output_key),
  FOREIGN KEY (job_id) REFERENCES highlight_jobs(id),
  FOREIGN KEY (video_id) REFERENCES longform_videos(id)
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_render_outputs_job_id
ON render_outputs(job_id);

CREATE INDEX IF NOT EXISTS idx_render_outputs_plan_key
ON render_outputs(job_id, plan_key);

CREATE INDEX IF NOT EXISTS idx_render_outputs_render_status
ON render_outputs(job_id, render_status);
```

建议 `render_status`：

- `queued`
- `rendering`
- `success`
- `failed`
- `canceled`

---

## 4. 推荐的建表顺序

为了避免外键关系混乱，建议按以下顺序建表：

1. `longform_videos`
2. `highlight_jobs`
3. `video_shots`
4. `video_utterances`
5. `story_segments`
6. `theme_lines`
7. `highlight_points`
8. `segment_scores`
9. `asset_plans`
10. `highlight_timelines`
11. `render_outputs`

---

## 5. 推荐的迁移策略

### 5.1 当前项目建议

当前项目是 SQLite + 多个 `migrate_v*.py` 形式，建议保持一致，新增一个后续迁移版本，比如：

- `scripts/migrate_v39.py`

该迁移只做：

- 新表创建
- 必要索引创建

第一版不建议：

- 一上来加太多 seed 数据
- 一上来加触发器
- 一上来和现有任务队列做强耦合

### 5.2 第一版迁移原则

- 幂等
- 可重复执行
- 不改现有业务表
- 不影响当前发布流水线

---

## 6. 关键查询场景

### 6.1 查询某个 job 的剧情段

```sql
SELECT segment_key, start_sec, end_sec, summary, story_role, emotion_type, theme_line
FROM story_segments
WHERE job_id = ?
ORDER BY start_sec ASC;
```

### 6.2 查询某个 job 的主题线

```sql
SELECT theme_key, theme_name, theme_type, summary, tension_score, conversion_score
FROM theme_lines
WHERE job_id = ?
ORDER BY conversion_score DESC, tension_score DESC;
```

### 6.3 查询主力素材方案

```sql
SELECT plan_key, asset_type, template_type, theme_focus, target_duration_sec, actual_duration_sec
FROM asset_plans
WHERE job_id = ?
  AND asset_type = 'main'
ORDER BY created_at ASC;
```

### 6.4 查询辅助素材方案

```sql
SELECT plan_key, template_type, theme_focus, selected_segment_keys_json
FROM asset_plans
WHERE job_id = ?
  AND asset_type = 'aux'
ORDER BY created_at ASC;
```

### 6.5 查询最终导出结果

```sql
SELECT output_key, output_type, aspect_ratio, file_path, render_status
FROM render_outputs
WHERE job_id = ?
ORDER BY created_at ASC;
```

---

## 7. V1 建模边界建议

为了避免第一版过重，建议 V1 严格控制：

### 7.1 V1 必做

- `longform_videos`
- `highlight_jobs`
- `video_shots`
- `video_utterances`
- `story_segments`
- `theme_lines`
- `highlight_points`
- `segment_scores`
- `asset_plans`
- `highlight_timelines`
- `render_outputs`

### 7.2 V1 暂不单独拆表

这些数据先放进 `meta_json` 即可，不必现在拆表：

- OCR 事件明细
- 音频细粒度特征
- 视觉细粒度特征
- 人工审核操作日志
- 标题文案候选
- 封面文案候选

如果后期验证确实需要，再新增：

- `ocr_events`
- `audio_feature_windows`
- `review_actions`
- `copy_variants`

---

## 8. 可扩展预留

后续如要扩展到更完整的生产系统，建议预留以下方向：

### 8.1 人工审核体系

未来可新增：

- `review_tasks`
- `review_actions`
- `review_comments`

### 8.2 多版本实验体系

未来可新增：

- `asset_experiments`
- `asset_experiment_assignments`
- `asset_performance_daily`

### 8.3 素材投放反馈体系

未来可新增：

- `mount_click_feedback`
- `watch_performance_feedback`
- `conversion_feedback`

---

## 9. 最终建议

如果只看数据库层，第一版最重要的不是把表做得多花哨，而是确保下面三件事成立：

1. 一部整剧只做一次重分析也能复用
2. 一次 job 能稳定沉淀完整中间结果
3. 同一份剧情资产库可以支撑多条主力和辅助素材生成

换句话说，SQL 建模最核心的设计思想就是：

**把“整剧资产”“分析任务”“剧情资产”“素材方案”“导出结果”五层分开。**

这样后面无论你是继续做人工快审、模板升级、A/B 测试，还是多版本导出，都不会推翻当前模型。

