import datetime
import logging
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 錯誤次數：靜默分鐘（從第 3 次才開始靜默）
SILENCE_THRESHOLD = 3
BACKOFF_SCHEDULE = {
    3: 1,
    4: 3,
    5: 5,
    6: 10,
    7: 15,
    8: 30,
}
BACKOFF_MAX_MINUTES = 60  # 最大靜默 1 小時


class State:
    def __init__(self):
        # 每門課的錯誤記錄
        self._course_errors: Dict[str, int] = {}
        # 每門課的靜默狀態
        self._course_silence: Dict[str, Optional[datetime.datetime]] = {}
        # 已通知的名單
        self.notified_courses: Set[Tuple[str, str]] = set()

    def increment_error(self, course_id: str):
        # 增加錯誤次數
        self._course_errors[course_id] = self._course_errors.get(course_id, 0) + 1
        count = self._course_errors[course_id]

        if count < SILENCE_THRESHOLD:
            logger.warning(
                f"[{course_id}] 連續錯誤 {count} 次（還需 {SILENCE_THRESHOLD - count} 次才靜默）"
            )
        else:
            minutes = BACKOFF_SCHEDULE.get(count, BACKOFF_MAX_MINUTES)
            silence_until = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
            self._course_silence[course_id] = silence_until
            logger.warning(
                f"[{course_id}] 連續錯誤 {count} 次，將靜默 {minutes} 分鐘（至 {silence_until.strftime('%H:%M:%S')}）"
            )

    def reset_error(self, course_id: str):
        # 重置該課程的錯誤次數與靜默狀態
        self._course_errors.pop(course_id, None)
        self._course_silence.pop(course_id, None)

    def is_course_silenced(self, course_id: str) -> bool:
        # 檢查該課程是否處於靜默期
        silence_until = self._course_silence.get(course_id)
        if silence_until is None:
            return False
        if datetime.datetime.now() < silence_until:
            return True
        # 靜默期已過 — 只清除靜默，保留錯誤次數繼續累積
        self._course_silence.pop(course_id, None)
        return False

    def get_error_count(self, course_id: str) -> int:
        # 取得該課程的連續錯誤次數
        return self._course_errors.get(course_id, 0)

    def is_already_notified(self, course_id: str, user_id: str) -> bool:
        # 檢查是否已對該使用者通知過該課程
        return (course_id, user_id) in self.notified_courses

    def mark_notified(self, course_id: str, user_id: str):
        # 標記已通知
        self.notified_courses.add((course_id, user_id))

    def unmark_notified(self, course_id: str, user_id: str):
        # 移除通知標記（用於課程已滿時重置）
        self.notified_courses.discard((course_id, user_id))
