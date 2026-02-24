from app.api_client import SessionManager
from app.captcha_solver import CaptchaSolver
from app.login_manager import LoginManager
from app.course_enroller import CourseEnroller


class UserAgent:
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

        # 每個使用者擁有獨立會話
        self.session = SessionManager()
        self.login_mgr = LoginManager(self.session, captcha_solver)
        self.enroller = CourseEnroller(self.session, captcha_solver)

    def ensure_logged_in(self) -> bool:
        if self.login_mgr.is_logged_in():
            return True
        return self.login_mgr.login(self.account, self.password)
