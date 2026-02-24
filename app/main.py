import json
import os
import time
import schedule
from dotenv import load_dotenv
from app.scraper import CourseScraper
from app.notifier import LineNotifier
from app.state import State
from app.api_client import SessionManager
from app.captcha_solver import CaptchaSolver
from app.user_agent import UserAgent

load_dotenv()

# ---------------------------------------------------------------------------
# Load user configs from users.json
# Format: [{ "account": "...", "password": "...", "line_user_id": "...", "courses": [...] }]
# ---------------------------------------------------------------------------
USERS_JSON_PATH = os.getenv("USERS_JSON", "users.json")

with open(USERS_JSON_PATH, encoding="utf-8") as f:
    users_config = json.load(f)

if not users_config:
    raise ValueError(f"{USERS_JSON_PATH} 不能為空，請至少填入一位使用者")

INTERVAL = int(os.getenv("CRON_INTERVAL_SECONDS", "30"))

# Shared across all users — avoids reloading the EasyOCR model multiple times
captcha_solver = CaptchaSolver()

# Build one UserAgent per configured user
user_agents: list[UserAgent] = [
    UserAgent(
        account=u["account"],
        password=u["password"],
        line_user_id=u["line_user_id"],
        courses=u["courses"],
        captcha_solver=captcha_solver,
    )
    for u in users_config
]

# Deduplicated list of all courses to check availability for
all_target_courses = list({c for ua in user_agents for c in ua.courses})

# One scraper using a shared (non-auth) session for course availability checks
scraper_session = SessionManager()
scraper = CourseScraper(scraper_session)
notifier = LineNotifier()
state = State()


def job():
    if state.is_silenced():
        return

    # -----------------------------------------------------------------------
    # Step 1: Check course availability (shared, no auth required)
    # -----------------------------------------------------------------------
    available_courses: dict[str, tuple[int, int, str]] = {}  # course_id → (enrolled, limit, name)

    for course_id in all_target_courses:
        try:
            enrolled, limit, name = scraper.get_course_info(course_id)
            state.reset_error()
            if enrolled < limit:
                available_courses[course_id] = (enrolled, limit, name)
            else:
                # Course is full again — reset per-user notification state
                for ua in user_agents:
                    if course_id in ua.courses and state.is_already_notified(course_id, ua.line_user_id):
                        state.unmark_notified(course_id, ua.line_user_id)
        except Exception as e:
            print(f"Error scraping {course_id}: {e}")
            state.increment_error()
            if state.error_count >= 3:
                error_msg = f"⚠️ 系統異常通知\n連續抓取失敗 3 次，系統將靜默 3 小時。\n錯誤訊息：{str(e)}"
                try:
                    notifier.send_message(error_msg)
                except Exception:
                    pass
                state.set_silence()
            return

    if not available_courses:
        return

    # -----------------------------------------------------------------------
    # Step 2: For each user, try to enroll in their available target courses
    # -----------------------------------------------------------------------
    for ua in user_agents:
        user_available = [
            cid for cid in ua.courses
            if cid in available_courses and not state.is_already_notified(cid, ua.line_user_id)
        ]
        if not user_available:
            continue

        # Log in with this user's credentials
        if not ua.ensure_logged_in():
            print(f"[{ua.account}] 登入失敗，略過加選")
            continue

        for course_id in user_available:
            enrolled, limit, name = available_courses[course_id]
            enroll_msg = ""

            print(f"[{ua.account}] Attempting to auto-enroll into {course_id}...")
            success, reason = ua.enroller.enroll(course_id)

            if success:
                enrolled, limit, name = available_courses[course_id]
                msg = (
                    f"🎉 選課成功！\n\n"
                    f"課程：{name} ({course_id})"
                )
                notifier.send_message(msg, mention_user_ids=[ua.line_user_id])
                state.mark_notified(course_id, ua.line_user_id)
            else:
                print(f"[{ua.account}] Enrollment failed for {course_id}: {reason}")


if __name__ == "__main__":
    accounts = [ua.account for ua in user_agents]
    print(f"Starting Yuntech Course Bot")
    print(f"Users: {accounts}")
    print(f"Courses: {all_target_courses}")
    schedule.every(INTERVAL).seconds.do(job)

    # Run once at start
    job()

    while True:
        schedule.run_pending()
        time.sleep(1)
