from app.api_client import SessionManager
from app.captcha_solver import CaptchaSolver
from app.login_manager import LoginManager
from app.course_enroller import CourseEnroller


class UserAgent:
    """
    One UserAgent per YunTech account.

    Each agent keeps its own HTTP session (cookies) so that multiple users can
    be logged in simultaneously without interfering with each other.
    A single shared CaptchaSolver is injected to avoid reloading the EasyOCR
    model multiple times (the model is large and expensive to initialise).
    """

    def __init__(
        self,
        account: str,
        password: str,
        line_user_id: str,
        courses: list[str],
        captcha_solver: CaptchaSolver,
    ):
        self.account = account
        self.password = password
        self.line_user_id = line_user_id
        self.courses = courses

        # Independent session per user
        self.session = SessionManager()
        self.login_mgr = LoginManager(self.session, captcha_solver)
        self.enroller = CourseEnroller(self.session, captcha_solver)

    def ensure_logged_in(self) -> bool:
        """Log in if not already logged in. Returns True on success."""
        if self.login_mgr.is_logged_in():
            return True
        return self.login_mgr.login(self.account, self.password)
