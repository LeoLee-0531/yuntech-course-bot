import logging
import os
from bs4 import BeautifulSoup
from typing import Optional
from app.api_client import SessionManager
from app.captcha_solver import CaptchaSolver

logger = logging.getLogger(__name__)

class LoginManager:
    LOGIN_URL = "https://webapp.yuntech.edu.tw/YunTechSSO/Account/Login"
    CAPTCHA_URL = "https://webapp.yuntech.edu.tw/YunTechSSO/Captcha/Number"
    VERIFY_URL = "https://webapp.yuntech.edu.tw/YunTechSSO/Account/IsLogined"
    
    def __init__(self, session_manager: SessionManager, captcha_solver: CaptchaSolver):
        self.session_manager = session_manager
        self.captcha_solver = captcha_solver

        if self.is_logged_in():
            # 已經登入
            logger.info("Already logged in.")
            return True

        for attempt in range(max_retries):
            try:
                # 取得登入頁面
                resp = self.session_manager.get(self.LOGIN_URL, timeout=10)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # 提取 token
                token_input = soup.find('input', {'name': '__RequestVerificationToken'})
                if not token_input:
                    logger.error("Could not find __RequestVerificationToken on login page.")
                    continue
                token = token_input['value']

                # 取得驗證碼
                captcha_text, captcha_b64 = self._get_and_solve_captcha_with_retries(retries=5)
                

                if not captcha_text:
                    logger.warning("Failed to get a clear 4-character captcha, retrying full login flow...")
                    continue

                logger.debug(f"Attempting login with token: {token[:10]}... and captcha: {captcha_text}")

                # 登入
                payload = {
                    '__RequestVerificationToken': token,
                    'pLoginName': username,
                    'pLoginPassword': password,
                    'pRememberMe': 'true',
                    'pSecretString': captcha_text,
                }
                
                post_resp = self.session_manager.post(self.LOGIN_URL, data=payload, timeout=10)
                post_resp.raise_for_status()
                
                # 驗證登入狀態
                if self.is_logged_in():
                    logger.info("Successfully logged in.")
                    return True
                else:
                    logger.warning("Log in failed (possibly wrong captcha or credentials), retrying...")
                    
            except Exception as e:
                logger.error(f"Login error on attempt {attempt+1}: {e}")
                
        return False

    def _get_and_solve_captcha_with_retries(self, retries=5) -> tuple[Optional[str], Optional[str]]:
        for _ in range(retries):
            try:
                resp = self.session_manager.get(self.CAPTCHA_URL, timeout=5)
                resp.raise_for_status()
                # 回應內容直接就是 base64 字串
                b64 = resp.text.strip().strip('"') 
                
                text = self.captcha_solver.solve_base64(b64)
                
                if len(text) == 4:
                    return text, b64
                else:
                    logger.debug(f"Captcha length not 4 (got '{text}'), re-fetching...")
            except Exception as e:
                logger.error(f"Error getting captcha: {e}")
        return None, None

    def is_logged_in(self) -> bool:
        try:
            resp = self.session_manager.get(self.VERIFY_URL, timeout=5)
            resp.raise_for_status()
            return resp.text.strip().lower() == "true"
        except Exception as e:
            logger.debug(f"Failed to check login status: {e}")
            return False
