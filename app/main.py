import hashlib
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import requests.exceptions
from app.scraper import CourseScraper
from app.notifier import NotificationManager
from app.captcha_solver import CaptchaSolver
from app.user_agent import UserAgent

import logging

# 設定日誌
SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")

def log_success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS):
        self._log(SUCCESS, message, args, **kwargs)

logging.Logger.success = log_success

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

INTERVAL = int(os.getenv("CRON_INTERVAL_SECONDS", "30"))

# 全域共享，避免重複載入模型
captcha_solver = CaptchaSolver()

# 動態更新的設定
user_agents: list[UserAgent] = []
all_target_courses: list[str] = []
_last_users_json_hash: str = ""

USERS_JSON_PATH = os.getenv("USERS_JSON", "users.json")


def load_config():
    # 重新載入 users.json 並更新全域狀態
    global user_agents, all_target_courses, _last_users_json_hash

    try:
        with open(USERS_JSON_PATH, "rb") as f:
            raw = f.read()

        current_hash = hashlib.md5(raw).hexdigest()
        changed = current_hash != _last_users_json_hash

        users_config = json.loads(raw.decode("utf-8"))

        if not users_config:
            logger.warning(f"⚠️ {USERS_JSON_PATH} 為空，略過更新")
            return

        # 建立每個使用者的 UserAgent
        new_user_agents = [
            UserAgent(
                account=u["account"],
                password=u["password"],
                courses=u["courses"],
                captcha_solver=captcha_solver,
            )
            for u in users_config
        ]

        # 整理所有要檢查的課程清單
        new_all_target_courses = list({c for ua in new_user_agents for c in ua.courses})

        # 更新全域變數
        user_agents = new_user_agents
        all_target_courses = new_all_target_courses
        _last_users_json_hash = current_hash

        if changed:
            accounts = [u["account"] for u in users_config]
            logger.info(f"🔄 {USERS_JSON_PATH} 已更新，載入 {len(accounts)} 位使用者：{accounts}，監控課程：{new_all_target_courses}")

    except Exception as e:
        logger.error(f"❌ Failed to reload {USERS_JSON_PATH}: {e}")


def remove_course_from_config(account: str, course_id: str):
    # 加選成功後，從 users.json 移除該帳號對應的課程
    try:
        with open(USERS_JSON_PATH, encoding="utf-8") as f:
            users_config = json.load(f)

        changed = False
        for user in users_config:
            if user["account"] == account and course_id in user["courses"]:
                user["courses"].remove(course_id)
                changed = True
                logger.info(f"[{account}] 已從 {USERS_JSON_PATH} 移除課程 {course_id}")

        if changed:
            with open(USERS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(users_config, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"❌ 無法更新 {USERS_JSON_PATH}: {e}")


notifier = NotificationManager()

# 每個課程設定一個 CourseScraper（持久化 Session，支援 keep-alive）
_course_scrapers: dict[str, CourseScraper] = {}

def _get_scraper(course_id: str) -> CourseScraper:
    if course_id not in _course_scrapers:
        _course_scrapers[course_id] = CourseScraper()
    return _course_scrapers[course_id]

# 初始載入
load_config()


def _scrape_course(course_id: str):
    scraper = _get_scraper(course_id)
    t0 = time.monotonic()

    try:
        result = scraper.get_course_info(course_id)
        elapsed = time.monotonic() - t0
        logger.debug(f"[{course_id}] 抓取完成，耗時 {elapsed:.1f}s")
        return course_id, result
    except Exception:
        elapsed = time.monotonic() - t0
        logger.debug(f"[{course_id}] 抓取失敗，耗時 {elapsed:.1f}s")
        _course_scrapers.pop(course_id, None)
        raise


def job():
    # 重新載入設定
    load_config()

    if not all_target_courses:
        return

    # 並行抓取所有課程名額
    available_courses: dict[str, tuple[int, int, str]] = {}
    with ThreadPoolExecutor(max_workers=len(all_target_courses) or 1) as executor:
        futures = {executor.submit(_scrape_course, cid): cid for cid in all_target_courses}
        for future in as_completed(futures):
            course_id = futures[future]
            try:
                _, (enrolled, limit, name) = future.result()
                if enrolled < limit:
                    available_courses[course_id] = (enrolled, limit, name)
            except Exception as e:
                logger.error(f"Error scraping {course_id}: {e}")

    if not available_courses:
        return

    # 嘗試為每個使用者加選有餘額的課程
    for ua in user_agents:
        user_available = [
            cid for cid in ua.courses
            if cid in available_courses
        ]
        if not user_available:
            continue

        # 登入使用者
        if not ua.ensure_logged_in():
            logger.warning(f"[{ua.account}] 登入失敗，略過加選")
            continue

        for course_id in user_available:
            enrolled, limit, name = available_courses[course_id]

            logger.info(f"[{ua.account}] 正在嘗試加選 {course_id}...")
            success, reason = ua.enroller.enroll(course_id)

            if success:
                logger.success(f"[{ua.account}] 成功加選 {course_id}")
                msg = (
                    f"🎉 選課成功！\n"
                    f"課程：{name} ({course_id})"
                )
                notifier.send_message(msg)
                # 成功後從 users.json 移除
                remove_course_from_config(ua.account, course_id)
            else:
                logger.error(f"[{ua.account}] {course_id} 加選失敗: {reason}")
                fail_msg = (
                    f"❌ 加選失敗！\n"
                    f"帳號：{ua.account}\n"
                    f"課程：{name} ({course_id})\n"
                    f"原因：{reason}"
                )
                try:
                    notifier.send_message(fail_msg)
                except Exception:
                    pass


if __name__ == "__main__":
    logger.info(f"Course Bot started")

    # 啟動時執行一次（同步）
    job()

    # 最長容許 job() 執行的時間（防止卡住）
    JOB_TIMEOUT = INTERVAL * 4

    while True:
        time.sleep(INTERVAL)

        # 在 daemon thread 中執行 job，避免卡住主迴圈
        t = threading.Thread(target=job, daemon=True)
        t.start()
        t.join(timeout=JOB_TIMEOUT)
        if t.is_alive():
            logger.warning(f"⚠️ job() 執行超過 {JOB_TIMEOUT}s，已放棄本次執行，下次繼續")
