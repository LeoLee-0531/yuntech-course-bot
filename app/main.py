import json
import os
import time
import schedule
from dotenv import load_dotenv
from app.scraper import CourseScraper
from app.notifier import NotificationManager
from app.state import State
from app.api_client import SessionManager
from app.captcha_solver import CaptchaSolver
from app.user_agent import UserAgent

import logging

# 設定日誌
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


def load_config():
    """重新載入 users.json 並更新全域狀態"""
    global user_agents, all_target_courses
    
    USERS_JSON_PATH = os.getenv("USERS_JSON", "users.json")
    
    try:
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
        
    except Exception as e:
        logger.error(f"❌ Failed to reload {USERS_JSON_PATH}: {e}")


# 使用共享會話的抓取器（不需登入）
scraper_session = SessionManager()
scraper = CourseScraper(scraper_session)
notifier = NotificationManager()
state = State()

# 初始載入
load_config()


def job():
    # 重新載入設定
    load_config()

    # 檢查課程名額（共享會話，不需登入）
    available_courses: dict[str, tuple[int, int, str]] = {}

    for course_id in all_target_courses:
        # 若該課程仍在退避靜默期就跳過
        if state.is_course_silenced(course_id):
            logger.debug(f"[{course_id}] 仍在靜默期，略過")
            continue

        try:
            enrolled, limit, name = scraper.get_course_info(course_id)
            state.reset_error(course_id)
            if enrolled < limit:
                available_courses[course_id] = (enrolled, limit, name)
            else:
                # 課程已滿 - 重設通知狀態
                for ua in user_agents:
                    if course_id in ua.courses and state.is_already_notified(course_id, ua.account):
                        state.unmark_notified(course_id, ua.account)
        except Exception as e:
            logger.error(f"Error scraping {course_id}: {e}")
            state.increment_error(course_id)
            error_count = state.get_error_count(course_id)
            if error_count >= 3:
                error_msg = (
                    f"⚠️ 課程 {course_id} 連續抓取失敗 {error_count} 次，\n"
                    f"已進入退避靜默。\n錯誤訊息：{str(e)}"
                )
                try:
                    notifier.send_message(error_msg)
                except Exception:
                    pass
            continue  # 其他課程繼續正常檢查

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
                logger.info(f"[{ua.account}] 成功加選 {course_id}")
                msg = (
                    f"🎉 選課成功！\n"
                    f"課程：{name} ({course_id})"
                )
                notifier.send_message(msg)
                state.mark_notified(course_id, ua.account)
            else:
                logger.error(f"[{ua.account}] {course_id} 加選失敗: {reason}")


if __name__ == "__main__":
    # 設定排程
    schedule.every(INTERVAL).seconds.do(job)
    logger.info(f"Course Bot started, target courses: {all_target_courses}")

    # 啟動時執行一次
    job()

    while True:
        # 執行待處理的排程任務
        schedule.run_pending()
        time.sleep(1)
