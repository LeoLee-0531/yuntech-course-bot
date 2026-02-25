import json
import os
import time
import schedule
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import requests.exceptions
from app.scraper import CourseScraper
from app.notifier import NotificationManager
from app.state import State, SILENCE_THRESHOLD, TIMEOUT_SILENCE_THRESHOLD
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
_last_users_json_mtime: float = 0.0


def load_config():
    """重新載入 users.json 並更新全域狀態"""
    global user_agents, all_target_courses, _last_users_json_mtime
    
    USERS_JSON_PATH = os.getenv("USERS_JSON", "users.json")
    
    try:
        mtime = os.path.getmtime(USERS_JSON_PATH)
        changed = mtime != _last_users_json_mtime

        with open(USERS_JSON_PATH, encoding="utf-8") as f:
            users_config = json.load(f)
            
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
        _last_users_json_mtime = mtime

        if changed:
            accounts = [u["account"] for u in users_config]
            logger.info(f"🔄 {USERS_JSON_PATH} 已更新，載入 {len(accounts)} 位使用者：{accounts}，監控課程：{new_all_target_courses}")
        
    except Exception as e:
        logger.error(f"❌ Failed to reload {USERS_JSON_PATH}: {e}")


notifier = NotificationManager()
state = State()

# 每個課程設定一個 CourseScraper（持久化 Session，支援 keep-alive）
_course_scrapers: dict[str, CourseScraper] = {}

def _get_scraper(course_id: str) -> CourseScraper:
    if course_id not in _course_scrapers:
        _course_scrapers[course_id] = CourseScraper()
    return _course_scrapers[course_id]

# 初始載入
load_config()


def _scrape_course(course_id: str):
    # 使用該課程的持久化 Session 抓取資料（keep-alive，避免每次重新握手）
    scraper = _get_scraper(course_id)
    t0 = time.monotonic()

    # 若請求失敗，自動丟棄損壞的 Session，下次將重建。
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

    # 過濾掉靜默期的課程
    courses_to_check = [
        cid for cid in all_target_courses
        if not state.is_course_silenced(cid)
    ]
    silenced = set(all_target_courses) - set(courses_to_check)
    for cid in silenced:
        logger.debug(f"[{cid}] 仍在靜默期，略過")

    # 並行抓取所有課程名額
    available_courses: dict[str, tuple[int, int, str]] = {}
    with ThreadPoolExecutor(max_workers=len(courses_to_check) or 1) as executor:
        futures = {executor.submit(_scrape_course, cid): cid for cid in courses_to_check}
        for future in as_completed(futures):
            course_id = futures[future]
            try:
                _, (enrolled, limit, name) = future.result()
                state.reset_error(course_id)
                if enrolled < limit:
                    available_courses[course_id] = (enrolled, limit, name)
                else:
                    # 課程已滿 - 重設通知狀態
                    for ua in user_agents:
                        if course_id in ua.courses and state.is_already_notified(course_id, ua.account):
                            state.unmark_notified(course_id, ua.account)
            except Exception as e:
                is_timeout = isinstance(e, (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout))
                logger.error(f"Error scraping {course_id}: {e}")
                state.increment_error(course_id, is_timeout=is_timeout)
                error_count = state.get_error_count(course_id)
                threshold = TIMEOUT_SILENCE_THRESHOLD if is_timeout else SILENCE_THRESHOLD
                if error_count >= threshold:
                    silence_until = state.get_silence_until(course_id)
                    silence_info = (
                        f"\n靜默至：{silence_until.strftime('%H:%M:%S')}"
                        if silence_until else ""
                    )
                    kind = "Timeout" if is_timeout else "抓取失敗"
                    error_msg = (
                        f"⚠️ 課程 {course_id} 連續{kind} {error_count} 次，\n"
                        f"已進入退避靜默。{silence_info}\n錯誤訊息：{str(e)}"
                    )
                    try:
                        notifier.send_message(error_msg)
                    except Exception:
                        pass

    if not available_courses:
        return

    # 嘗試為每個使用者加選有餘額的課程
    for ua in user_agents:
        user_available = [
            cid for cid in ua.courses
            if cid in available_courses and not state.is_already_notified(cid, ua.account)
        ]
        if not user_available:
            continue

        # 登入使用者
        if not ua.ensure_logged_in():
            logger.warning(f"[{ua.account}] 登入失敗，略過加選")
            continue

        for course_id in user_available:
            enrolled, limit, name = available_courses[course_id]
            enroll_msg = ""

            logger.info(f"[{ua.account}] 正在嘗試加選 {course_id}...")
            success, reason = ua.enroller.enroll(course_id)

            if success:
                enrolled, limit, name = available_courses[course_id]
                logger.success(f"[{ua.account}] 成功加選 {course_id}")
                msg = (
                    f"🎉 選課成功！\n"
                    f"課程：{name} ({course_id})"
                )
                notifier.send_message(msg)
                state.mark_notified(course_id, ua.account)
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
    # 設定排程
    schedule.every(INTERVAL).seconds.do(job)
    logger.info(f"Course Bot started")

    # 啟動時執行一次
    job()

    while True:
        # 執行待處理的排程任務
        schedule.run_pending()
        time.sleep(1)
