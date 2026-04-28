// PM2 ecosystem for ksjuzheng FastAPI/uvicorn backend.
// 用法:
//   pm2 start /opt/ksjuzheng/ecosystem.config.cjs --env production
//   pm2 save
//
// 注意:
//   - PM2 用 fork 模式直接 spawn uvicorn (uvicorn 自身已内置多 worker)
//   - 不用 PM2 cluster 模式 (那是给纯 Node.js 用的)
//   - .env 通过 dotenv-style 由 uvicorn / app/core/config.py 自加载;
//     PM2 这里只把 PATH / PYTHONPATH 传过去
'use strict'
const path = require('path')
const APP_ROOT = '/opt/ksjuzheng'

module.exports = {
  apps: [
    {
      name: 'ksjuzheng',
      cwd: APP_ROOT,
      script: path.join(APP_ROOT, '.venv/bin/uvicorn'),
      args: 'app.main:app --host 0.0.0.0 --port 8800 --workers 2 --log-level info',
      interpreter: 'none',          // 用 uvicorn 自身可执行,不再套 python/node
      exec_mode: 'fork',            // 不要 cluster
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 15000,           // 跟原 systemd TimeoutStopSec=15 对齐
      max_memory_restart: '1G',
      out_file: path.join(APP_ROOT, 'logs/pm2-out.log'),
      error_file: path.join(APP_ROOT, 'logs/pm2-err.log'),
      merge_logs: true,
      time: true,                    // 行首加时间戳
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: APP_ROOT,
      },
    },
  ],
}
