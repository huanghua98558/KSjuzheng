# 运营策略种子 v1.0

> **来源**: 用户思维导图 (2026-04-23)
> **固化**: `ai.policy.operation.seed_json` in app_config + research_notes
> **原则**: 所有 agent 决策都以此为准, 不再硬编码

## 结构化 JSON

```json
{
  "version": "1.0",
  "source": "user_mindmap_20260423",
  "updated_at": "2026-04-23",
  "tracks": {
    "female": {
      "name": "女频",
      "subtracks": {
        "modern_emotion": {
          "name": "现代情感",
          "tags": [
            "甜宠剧",
            "虐渣打脸",
            "先婚后爱",
            "带球跑",
            "真假千金",
            "职场大女主",
            "豪门"
          ]
        },
        "ancient_romance": {
          "name": "古风言情",
          "tags": [
            "宫斗宅斗",
            "重生逆袭",
            "替嫁",
            "穿书",
            "江湖恩怨",
            "古代言情",
            "古风"
          ]
        },
        "imaginative": {
          "name": "脑洞爽剧",
          "tags": [
            "快穿",
            "系统",
            "末世",
            "星际",
            "无限流",
            "脑洞"
          ]
        }
      }
    },
    "male": {
      "name": "男频",
      "subtracks": {
        "workplace_war": {
          "name": "职场商战",
          "tags": [
            "职场",
            "商战",
            "逆袭",
            "创业",
            "金融"
          ]
        },
        "fantasy_cultivation": {
          "name": "玄幻修仙",
          "tags": [
            "玄幻",
            "修仙",
            "修真",
            "仙尊",
            "战神"
          ]
        },
        "system_flow": {
          "name": "系统流",
          "tags": [
            "系统流",
            "签到",
            "充值",
            "氪金"
          ]
        },
        "historical_travel": {
          "name": "历史穿越",
          "tags": [
            "历史",
            "穿越",
            "穿越古代",
            "皇帝",
            "王爷"
          ]
        }
      }
    }
  },
  "publishing_rules": {
    "first_3_days": {
      "count_per_day": 4,
      "description": "新号前 3 天每天 4 条, 垂直发布, 不跨赛道",
      "enforce_vertical_lock": true
    },
    "day_4_onwards": {
      "creator_level_v1_v2": {
        "count": 4,
        "desc": "未涨等级也保持新号节奏"
      },
      "creator_level_v3_v4": {
        "count": 5,
        "desc": "V3-V4 每天 5 条"
      },
      "creator_level_v5_plus": {
        "count": 15,
        "desc": "V5+ 接近无上限, 保底 15"
      }
    },
    "level_priority": "一定要涨创作者等级到 V3-V4 才进入正常节奏"
  },
  "key_principles": [
    "作品一定要垂直发布 (不跨赛道)",
    "选赛道 = 新号第一件事",
    "一定要涨创作者等级到 V3 以上",
    "前 3 天是起号期 — 数量少但精准垂直",
    "V3-V4 是正常运营期 — 每天 5 条稳定产出",
    "V5+ 是起量期 — 可以无上限跑"
  ],
  "tier_mapping": {
    "_comment": "内部 tier 映射到用户玩法",
    "new": {
      "days": "0-3d",
      "target_quota": 4,
      "user_term": "前 3 天新号"
    },
    "testing": {
      "days": "3-7d",
      "target_quota": 5,
      "user_term": "类 V3 试号期"
    },
    "warming_up": {
      "days": "7-30d",
      "target_quota": 5,
      "user_term": "类 V3-V4 起量期"
    },
    "established": {
      "days": "30d+",
      "target_quota": 8,
      "user_term": "类 V4-V5 成长期"
    },
    "viral": {
      "days": ">60d",
      "target_quota": 15,
      "user_term": "V5+ 无上限"
    }
  }
}
```

## AI 读取入口

```python
from core.operation_policy import OperationPolicy
pol = OperationPolicy.load()
pol.quota_for_account(account)   # 按年龄 + tier 决定
pol.subtrack_for_drama(name)     # drama → 7 赛道之一
pol.is_vertical_match(account, drama)
```
