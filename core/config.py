"""Central configuration management for KS184 automation project.

Loads tool paths from PATHS.json and provides all API URLs, browser settings,
MCN credentials, and operational parameters used across the automation pipeline.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool paths from PATHS.json
# ---------------------------------------------------------------------------

_PATHS_JSON = Path(r"D:\ks_automation\tools\PATHS.json")

try:
    with open(_PATHS_JSON, "r", encoding="utf-8") as _f:
        PATHS: dict[str, str] = json.load(_f)
except FileNotFoundError:
    logger.warning("PATHS.json not found at %s, using empty defaults", _PATHS_JSON)
    PATHS = {}
except json.JSONDecodeError as exc:
    logger.error("Failed to parse PATHS.json: %s", exc)
    PATHS = {}

# Convenience aliases
KS184_ROOT: str = PATHS.get("KS184_ROOT", r"C:\Program Files\kuaishou2\KS184.7z\184-1")
CHROME_EXE: str = PATHS.get("chrome_exe", "")
CHROMEDRIVER_EXE: str = PATHS.get("chromedriver_exe", "")
FFMPEG_EXE: str = PATHS.get("ffmpeg_exe", "")
FFPROBE_EXE: str = PATHS.get("ffprobe_exe", "")
N_M3U8DL_EXE: str = PATHS.get("n_m3u8dl_exe", "")
MKV_EXE: str = PATHS.get("mkv_exe", "")
DB_PATH: str = PATHS.get("db_path", r"C:\Users\Administrator\AppData\Local\KuaishouControl\data\kuaishou_control.db")
CHROME_USER_DATA: str = PATHS.get("chrome_user_data", "")
VIDEO_DOWNLOAD_DIR: str = PATHS.get("video_download_dir", "")
VIDEO_PROCESSED_DIR: str = PATHS.get("video_processed_dir", "")
CLOUD_SERVER: str = PATHS.get("cloud_server", "43.161.249.108")
CLOUD_USER: str = PATHS.get("cloud_user", "ubuntu")
BASE_PORT: int = int(PATHS.get("base_port", 9520))

# ---------------------------------------------------------------------------
# Kuaishou API URLs
# ---------------------------------------------------------------------------

KUAISHOU_API_URLS: dict[str, str] = {
    # Creator platform
    "cp_base": "https://cp.kuaishou.com",
    "cp_article_publish": "https://cp.kuaishou.com/article/publish/video",
    "cp_rest_wd_works": "https://cp.kuaishou.com/rest/wd/works",
    "cp_rest_wd_account": "https://cp.kuaishou.com/rest/wd/account",
    "cp_rest_wd_data": "https://cp.kuaishou.com/rest/wd/data",
    # MCN / zhongxiangbao
    "mcn_base": "http://im.zhongxiangbao.com:8000",
    "mcn_sig": "http://im.zhongxiangbao.com:50002",
    "mcn_login": "http://im.zhongxiangbao.com:8000/api/login",
    "mcn_account_list": "http://im.zhongxiangbao.com:8000/api/account/list",
    "mcn_drama_list": "http://im.zhongxiangbao.com:8000/api/drama/list",
    # Upload
    "upload_base": "https://upload.kuaishouzt.com",
    "upload_video": "https://upload.kuaishouzt.com/api/upload/video",
    # External API
    "az1_api_base": "https://az1-api.ksapisrv.com",
    "az1_api_feed": "https://az1-api.ksapisrv.com/rest/wd/feed",
}

# ---------------------------------------------------------------------------
# Kuaishou Web URLs (browser automation targets)
# ---------------------------------------------------------------------------

KUAISHOU_WEB_URLS: dict[str, str] = {
    "login_url": "https://cp.kuaishou.com/article/publish/video",
    "passport_login_url": "https://passport.kuaishou.com/pc/account/login",
    "publish_url": "https://cp.kuaishou.com/article/publish/video",
    "my_works_url": "https://cp.kuaishou.com/profile/my-works",
}

# ---------------------------------------------------------------------------
# Web element selectors for publish page automation
# ---------------------------------------------------------------------------

WEB_SELECTORS: dict[str, str] = {
    "upload_input": 'input[type="file"]',
    "title_input": 'input[placeholder*="标题"], input.title-input',
    "description_textarea": 'textarea[placeholder*="描述"], textarea.desc-textarea',
    "tag_input": 'input[placeholder*="标签"], input.tag-input',
    "publish_button": 'button.publish-btn, button:has-text("发布")',
    "success_message": '.publish-success, .success-tip',
    "cover_upload": 'div.cover-upload, input.cover-input[type="file"]',
    "category_select": 'select.category-select, div.category-dropdown',
    "draft_button": 'button.draft-btn, button:has-text("存草稿")',
}

# ---------------------------------------------------------------------------
# Publish workflow configuration
# ---------------------------------------------------------------------------

PUBLISH_CONFIG: dict[str, int] = {
    "upload_timeout": 300,       # seconds - wait for video upload
    "process_timeout": 600,      # seconds - wait for server-side processing
    "publish_timeout": 30,       # seconds - wait for publish confirmation
    "verify_timeout": 30,        # seconds - wait for post-publish verification
    "error_retry_count": 1,      # retries on transient publish errors
}

# ---------------------------------------------------------------------------
# Chrome / WebDriver configuration
# ---------------------------------------------------------------------------

CHROME_CONFIG: dict[str, str | int] = {
    "chrome_path": CHROME_EXE,
    "driver_path": CHROMEDRIVER_EXE,
    "user_data_base": CHROME_USER_DATA,
    "base_port": BASE_PORT,
}

BROWSER_OPTIONS: dict[str, bool | str] = {
    "headless": False,
    "disable_gpu": True,
    "no_sandbox": True,
    "disable_dev_shm": True,
    "window_size": "1920,1080",
}

# ---------------------------------------------------------------------------
# MCN platform credentials — ★ 2026-04-24 v6 Day 6: 迁到 core/secrets.py
# 老调用 `from core.config import MCN_CONFIG` 仍工作 (lazy load).
# 新代码建议直接用 `from core.secrets import get_captain_login`.
# ---------------------------------------------------------------------------

def _load_mcn_config():
    try:
        from core.secrets import get
        return {
            "base_url":   get("KS_MCN_API_BASE"),
            "sig_url":    get("KS_MCN_SIG3_URL"),
            "phone":      get("KS_CAPTAIN_PHONE"),
            "password":   get("KS_CAPTAIN_PASSWORD"),
            "owner_code": get("KS_CAPTAIN_OWNER_CODE"),
        }
    except Exception:
        # secrets 模块不可用 → fallback 硬编码 (保老路径)
        return {
            "base_url":   "http://im.zhongxiangbao.com:8000",
            "sig_url":    "http://im.zhongxiangbao.com:50002",
            "phone":      "REPLACE_WITH_YOUR_PHONE",
            "password":   "REPLACE_WITH_YOUR_PASSWORD",
            "owner_code": "黄华",
        }

MCN_CONFIG: dict[str, str] = _load_mcn_config()

# ---------------------------------------------------------------------------
# Cookie management
# ---------------------------------------------------------------------------

COOKIE_CONFIG: dict[str, int] = {
    "expire_days": 30,
    "check_interval": 3600,      # seconds between freshness checks
}

# ---------------------------------------------------------------------------
# Retry / resilience
# ---------------------------------------------------------------------------

RETRY_CONFIG: dict[str, int | bool] = {
    "max_retry": 3,
    "retry_delay": 10,           # seconds (base delay)
    "exponential_backoff": True,
}

# ---------------------------------------------------------------------------
# HTTP headers template for cp.kuaishou.com requests
# ---------------------------------------------------------------------------

CP_HTTP_HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://cp.kuaishou.com",
    "Referer": "https://cp.kuaishou.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
