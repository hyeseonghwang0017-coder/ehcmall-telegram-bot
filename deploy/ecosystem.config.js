// PM2 프로세스 설정 — EHC Mall Bot
// 사용법: pm2 start deploy/ecosystem.config.js
const HOME = process.env.HOME;
const BOT_DIR = process.env.EHCMALL_BOT_DIR || `${HOME}/ehcmall-telegram-bot`;

module.exports = {
  apps: [
    {
      name: "ehcmall-api",
      cwd: BOT_DIR,
      script: "python3",
      args: "-m uvicorn api.main:app --host 0.0.0.0 --port 8000",
      interpreter: "none",
      env: {
        INDEX_PATH: `${BOT_DIR}/data/ehcmall_index.json`,
        EHCMALL_BOT_DIR: BOT_DIR,
      },
      autorestart: true,
      restart_delay: 3000,
      max_restarts: 10,
      watch: false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
    {
      name: "ehcmall-bot",
      cwd: BOT_DIR,
      script: "openclaw",
      args: "gateway start",
      interpreter: "none",
      env: {
        EHCMALL_BOT_DIR: BOT_DIR,
        INDEX_PATH: `${BOT_DIR}/data/ehcmall_index.json`,
      },
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
      watch: false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
  ],
};
