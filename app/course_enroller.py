import logging
import re
import base64
from bs4 import BeautifulSoup
from typing import Tuple, Dict, Optional
from app.api_client import SessionManager
from app.captcha_solver import CaptchaSolver

logger = logging.getLogger(__name__)

class CourseEnroller:
    BASE_URL = "https://webapp.yuntech.edu.tw/AAXCCS/CourseSelectionRegister.aspx"

    def __init__(self, session_manager: SessionManager, captcha_solver: CaptchaSolver = None):
        self.session_manager = session_manager
        self.captcha_solver = captcha_solver or CaptchaSolver()

    def _extract_asp_state(self, soup: BeautifulSoup) -> Dict[str, str]:
        state = {}
        for name in ['__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION', '__VIEWSTATEENCRYPTED']:
            elem = soup.find('input', {'name': name})
            state[name] = elem['value'] if elem else ""
        return state

    def _get_enrollment_page(self) -> Optional[BeautifulSoup]:
        resp = self.session_manager.get(self.BASE_URL, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 檢查是否在 SSO 的 JS 跳轉頁面
        if soup.title and 'Redirect' in (soup.title.string or ''):
            logger.debug("Got SSO redirect page, extracting JS redirect URL...")
            script_tag = soup.find('script', string=re.compile(r'redirectUrl\s*='))
            if not script_tag:
                logger.error("Could not find JS redirect URL on SSO page.")
                return None

            # 提取完整的跳轉 URL: var redirectUrl = 'https://...';
            match = re.search(r"redirectUrl\s*=\s*'(https://[^']+)'", script_tag.string)
            if not match:
                logger.error("Could not parse JS redirect URL.")
                return None

            endpoint_url = match.group(1)
            logger.debug(f"Following OAuth endpoint: {endpoint_url}")
            resp2 = self.session_manager.get(endpoint_url, timeout=10)
            resp2.raise_for_status()

            # 再次嘗試取得加選頁面
            resp3 = self.session_manager.get(self.BASE_URL, timeout=10)
            resp3.raise_for_status()
            soup3 = BeautifulSoup(resp3.text, 'html.parser')
            return soup3

        return soup  # 已在加選頁面

    def _prepare_course_enrollment(self, course_id: str) -> Optional[BeautifulSoup]:
        """執行查詢→登記→下一步，回傳驗證碼頁面的 soup，失敗時回傳 None。"""
        soup = self._get_enrollment_page()
        if not soup:
            logger.error("Unable to fetch enrollment page")
            return None

        if not soup.find('input', {'name': '__VIEWSTATE'}):
            logger.error("Enrollment page missing VIEWSTATE — OAuth may have failed")
            return None

        # 搜尋課程
        state = self._extract_asp_state(soup)
        payload_search = state.copy()
        payload_search.update({
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$ContentPlaceHolder1$CurrentSubjTextBox": course_id,
            "ctl00$ContentPlaceHolder1$QueryButton": "查詢",
        })
        resp_search = self.session_manager.post(self.BASE_URL, data=payload_search, timeout=10)
        resp_search.raise_for_status()
        soup_search = BeautifulSoup(resp_search.text, 'html.parser')

        # 找到課程勾選框
        checkbox_search = soup_search.find('input', {'type': 'checkbox',
                                             'id': re.compile(r'QueryCourseGridView_SelectCheckBox')})
        if not checkbox_search:
            logger.error(f"Course {course_id} not found in search results")
            return None
        course_checkbox_name = checkbox_search['name']

        # 登記課程
        state = self._extract_asp_state(soup_search)
        payload_register = state.copy()
        payload_register.update({
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$RegisterButton",
            "__EVENTARGUMENT": "",
            course_checkbox_name: "on",
        })
        resp_register = self.session_manager.post(self.BASE_URL, data=payload_register, timeout=10)
        resp_register.raise_for_status()
        soup_register = BeautifulSoup(resp_register.text, 'html.parser')

        # 下一步
        state = self._extract_asp_state(soup_register)
        payload_next = state.copy()
        payload_next.update({
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$NextStepButton",
            "__EVENTARGUMENT": "",
        })
        resp_next = self.session_manager.post(self.BASE_URL, data=payload_next, timeout=10)
        resp_next.raise_for_status()
        soup_next = BeautifulSoup(resp_next.text, 'html.parser')
        return soup_next

    def enroll(self, course_id: str) -> Tuple[bool, str]:
        try:
            max_flow_retries = 3
            msg = "未知結果"
            success = False

            for flow_attempt in range(max_flow_retries):
                if flow_attempt > 0:
                    logger.warning(f"Retrying full enrollment flow (attempt {flow_attempt + 1}/{max_flow_retries})...")

                # 取得驗證碼頁面
                current_soup = self._prepare_course_enrollment(course_id)
                if not current_soup:
                    return False, "無法取得選課頁面"

                # 重試迴圈：辨識驗證碼（最多 5 次，空字串不計入次數）
                max_captcha_retries = 5
                captcha_attempt = 0

                while captcha_attempt < max_captcha_retries:
                    captcha_text = ""
                    captcha_img = current_soup.find('img', id=re.compile(r'Captcha', re.I))
                    if captcha_img:
                        src = captcha_img.get('src', '')
                        if src.startswith('data:image'):
                            captcha_text = self.captcha_solver.solve_base64(src)
                        elif src:
                            full_url = "https://webapp.yuntech.edu.tw" + src if src.startswith('/') else src
                            c_resp = self.session_manager.get(full_url)
                            b64 = base64.b64encode(c_resp.content).decode('ascii')
                            captcha_text = self.captcha_solver.solve_base64(b64)
                        logger.debug(f"Enrollment captcha read (attempt {captcha_attempt + 1}): '{captcha_text}'")
                    else:
                        # 頁面上沒有驗證碼，重試整個流程
                        logger.warning("No captcha image on confirmation page, retrying full flow...")
                        break

                    if not captcha_text:
                        logger.warning("OCR returned empty, retrying captcha read...")
                        continue  # 不計入次數

                    # 建立送出 payload
                    state = self._extract_asp_state(current_soup)
                    payload_submit = state.copy()

                    captcha_input = current_soup.find('input', id=re.compile(r'CaptchaTextBox', re.I))
                    captcha_name = captcha_input['name'] if captcha_input else "ctl00$ContentPlaceHolder1$CaptchaTextBox"

                    submit_link = current_soup.find('a', id=re.compile(r'SaveButton|SubmitButton|SendButton', re.I))
                    if submit_link:
                        href = submit_link.get('href', '')
                        target_match = re.search(r"__doPostBack\('([^']+)'", href)
                        submit_eventtarget = target_match.group(1) if target_match else "ctl00$ContentPlaceHolder1$SaveButton"
                    else:
                        submit_eventtarget = "ctl00$ContentPlaceHolder1$SaveButton"

                    payload_submit.update({
                        "__EVENTTARGET": submit_eventtarget,
                        "__EVENTARGUMENT": "",
                        captcha_name: captcha_text,
                    })

                    resp_submit = self.session_manager.post(self.BASE_URL, data=payload_submit, timeout=10)
                    resp_submit.raise_for_status()
                    soup_submit = BeautifulSoup(resp_submit.text, 'html.parser')
                    captcha_attempt += 1
                    logger.debug(f"POSTed 送出 button (attempt {captcha_attempt})")

                    # 檢查結果
                    msg_label = soup_submit.find('span', id=re.compile(r'ProcessMsg'))
                    msg = msg_label.text.strip() if msg_label else ""

                    if "成功" in msg or "完成選課" in msg:
                        logger.info(f"Enrollment SUCCESS for {course_id}")
                        success = True
                        break

                    # 如果返回頁面仍有驗證碼輸入框，表示驗證碼錯誤 -> 重試
                    if soup_submit.find('input', id=re.compile(r'CaptchaTextBox', re.I)):
                        logger.warning(f"Captcha attempt {captcha_attempt} wrong, retrying with new captcha...")
                        current_soup = soup_submit
                        continue

                    # 沒有驗證碼輸入框 -> 最終結果頁面
                    logger.info(f"Enrollment result for {course_id}")
                    success = "成功" in msg or "完成選課" in msg or "預定加選" in msg
                    break

                if success:
                    break
                if captcha_attempt >= max_captcha_retries:
                    logger.error(f"Failed to solve enrollment captcha after {max_captcha_retries} attempts")
                    break

            return success, msg

        except Exception as e:
            logger.error(f"Enrollment error for {course_id}: {e}")
            return False, str(e)
