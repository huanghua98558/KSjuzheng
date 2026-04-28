# KSjuzheng — 火视界后台 (后端 + 前端) 备份

> 本仓库存的是 **ksjuzheng 后台系统的源代码**, 由本机自动同步.
> ksjuzheng = 火视界 MCN 矩阵管理后台 (FastAPI + Vue3)
> 服务器部署: 43.161.249.108 (xhy-app), /opt/ksjuzheng + /var/www/ksjuzheng

## 目录结构

```
KSjuzheng/
├── backend/          # 后端 FastAPI 源代码 (从 ubuntu:/opt/ksjuzheng 备份)
│   ├── app/          # FastAPI 主应用
│   ├── docs/         # 设计文档
│   ├── migrations/   # DB schema migrations
│   ├── scripts/      # 工具脚本
│   ├── tests/        # 测试
│   ├── requirements.txt
│   └── pyproject.toml
│
└── frontend/         # 前端 Vue3 源代码 (从 D:\KS184\ks-admin-vue 备份)
    ├── src/
    │   ├── views/    # 页面组件
    │   ├── api/
    │   ├── config/   # pageConfigs.ts (列定义)
    │   ├── router/
    │   └── ...
    ├── package.json
    └── vite.config.ts
```

## 数据库

部署在腾讯云 CynosDB:
- Host: 10.5.0.12:3306 (内网) / hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com:27666 (公网)
- DB: huoshijie
- User: xhy_app

数据库结构: 102 张表 (51 老 + 51 mcn_xxx 镜像), 详见 backend/docs/AI_README.md

## 部署

详见 backend/docs/AI_README.md

