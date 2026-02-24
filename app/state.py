import datetime
from typing import Set, Tuple

class State:
    def __init__(self, silence_duration_hours: int = 3):
        self.error_count = 0
        self.silence_until = None
        self.notified_courses: Set[Tuple[str, str]] = set() # (course_id, user_id)
        self.silence_duration_hours = silence_duration_hours

    def increment_error(self):
        self.error_count += 1

    def reset_error(self):
        self.error_count = 0
        self.silence_until = None

    def set_silence(self):
        self.silence_until = datetime.datetime.now() + datetime.timedelta(hours=self.silence_duration_hours)
        self.error_count = 0

    def is_silenced(self) -> bool:
        if self.silence_until is None:
            return False
        if datetime.datetime.now() < self.silence_until:
            return True
        # Silence period passed
        self.silence_until = None
        return False

    def is_already_notified(self, course_id: str, user_id: str) -> bool:
        return (course_id, user_id) in self.notified_courses

    def mark_notified(self, course_id: str, user_id: str):
        self.notified_courses.add((course_id, user_id))

    def unmark_notified(self, course_id: str, user_id: str):
        if (course_id, user_id) in self.notified_courses:
            self.notified_courses.remove((course_id, user_id))
