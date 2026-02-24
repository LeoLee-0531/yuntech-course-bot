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
        """
        Navigates to the enrollment page, handling the two-step OAuth redirect:
        1. GET enrollment page -> 302 -> AAXCCS/Login.aspx -> 302 -> YunTechSSO (JS redirect)
        2. Extract JS redirect URL -> GET LoginEndpoint.aspx (completes OAuth)
        3. GET enrollment page again -> should now have VIEWSTATE
        """
        resp = self.session_manager.get(self.BASE_URL, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Check if we ended up on the SSO "Redirecting" page (JS redirect)
        if soup.title and 'Redirect' in (soup.title.string or ''):
            logger.debug("Got SSO redirect page, extracting JS redirect URL...")
            script_tag = soup.find('script', string=re.compile(r'redirectUrl\s*='))
            if not script_tag:
                logger.error("Could not find JS redirect URL on SSO page.")
                return None

            # Extract the full URL from: var redirectUrl = 'https://...';
            match = re.search(r"redirectUrl\s*=\s*'(https://[^']+)'", script_tag.string)
            if not match:
                logger.error("Could not parse JS redirect URL.")
                return None

            endpoint_url = match.group(1)
            logger.debug(f"Following OAuth endpoint: {endpoint_url}")
            resp2 = self.session_manager.get(endpoint_url, timeout=10)
            resp2.raise_for_status()

            # Now try fetching the enrollment page again — session should be established
            resp3 = self.session_manager.get(self.BASE_URL, timeout=10)
            resp3.raise_for_status()
            soup3 = BeautifulSoup(resp3.text, 'html.parser')
            return soup3

        return soup  # Already on the enrollment page

    def enroll(self, course_id: str) -> Tuple[bool, str]:
        """
        Attempts to enroll in a course. Correct flow:
        1. GET enrollment page (with OAuth redirect handling)
        2. POST search course
        3. Check course checkbox + POST 登記/加進選課清單 (__EVENTTARGET = RegisterButton)
        4. POST 下一步 (__EVENTTARGET = CurrentSubjRegisterButton)
        5. Solve captcha + POST 送出 to complete enrollment
        Returns: (success_bool, message_str)
        """
        try:
            # 1. GET enrollment page (handling OAuth redirect if needed)
            soup = self._get_enrollment_page()
            if not soup:
                return False, "無法取得選課頁面"

            if not soup.find('input', {'name': '__VIEWSTATE'}):
                logger.error("Enrollment page missing VIEWSTATE — OAuth may have failed")
                return False, "選課頁面未正確載入（缺少 VIEWSTATE）"

            # 2. POST search course
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

            # Find the course row checkbox in the search results
            checkbox_search = soup_search.find('input', {'type': 'checkbox',
                                                 'id': re.compile(r'QueryCourseGridView_SelectCheckBox')})
            if not checkbox_search:
                return False, f"課程 {course_id} 未在搜尋結果中找到"
            course_checkbox_name = checkbox_search['name']
            logger.debug(f"Found course checkbox: {course_checkbox_name}")

            # 3. POST 登記/加進選課清單
            #    The 登記 button is a link triggered via __EVENTTARGET = 'ctl00$ContentPlaceHolder1$RegisterButton'
            state = self._extract_asp_state(soup_search)
            payload_register = state.copy()
            payload_register.update({
                "__EVENTTARGET": "ctl00$ContentPlaceHolder1$RegisterButton",
                "__EVENTARGUMENT": "",
                course_checkbox_name: "on",  # Check the course checkbox
            })
            resp_register = self.session_manager.post(self.BASE_URL, data=payload_register, timeout=10)
            resp_register.raise_for_status()
            soup_register = BeautifulSoup(resp_register.text, 'html.parser')
            logger.debug("POSTed 登記 button")

            # 4. POST 下一步(確認或刪除預選課程) — triggers NextStepButton
            state = self._extract_asp_state(soup_register)
            payload_next = state.copy()
            payload_next.update({
                "__EVENTTARGET": "ctl00$ContentPlaceHolder1$NextStepButton",
                "__EVENTARGUMENT": "",
            })
            resp_next = self.session_manager.post(self.BASE_URL, data=payload_next, timeout=10)
            resp_next.raise_for_status()
            soup_next = BeautifulSoup(resp_next.text, 'html.parser')
            logger.debug("POSTed 下一步 button")

            # 5. Retry loop: solve captcha and POST 送出 (max 5 attempts)
            #    If captcha is wrong, the server returns the same confirmation page
            #    with a new captcha image — just retry with the fresh image.
            current_soup = soup_next
            max_captcha_retries = 5
            msg = "未知結果"
            success = False

            for captcha_attempt in range(max_captcha_retries):
                # Solve captcha from current page
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
                    logger.debug(f"Enrollment captcha attempt {captcha_attempt + 1}: '{captcha_text}'")
                else:
                    logger.warning("No captcha image on confirmation page")

                if not captcha_text:
                    logger.warning(f"Captcha attempt {captcha_attempt + 1}: OCR returned empty, skipping")
                    continue

                # Build submit payload
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
                logger.debug(f"POSTed 送出 button (attempt {captcha_attempt + 1})")

                # Check result
                msg_label = soup_submit.find('span', id=re.compile(r'ProcessMsg'))
                msg = msg_label.text.strip() if msg_label else ""

                if "成功" in msg or "完成選課" in msg:
                    logger.info(f"Enrollment SUCCESS for {course_id}: {msg}")
                    success = True
                    break

                # If we still see a captcha input on the response page, captcha was wrong → retry
                if soup_submit.find('input', id=re.compile(r'CaptchaTextBox', re.I)):
                    logger.warning(f"Captcha attempt {captcha_attempt + 1} wrong, retrying with new captcha...")
                    current_soup = soup_submit  # Use new page with fresh captcha
                    continue

                # No more captcha input → final result page
                logger.info(f"Enrollment result for {course_id}: {msg}")
                success = "成功" in msg or "完成選課" in msg or "預定加選" in msg
                break
            else:
                logger.error(f"Failed to solve enrollment captcha after {max_captcha_retries} attempts")

            return success, msg

        except Exception as e:
            logger.error(f"Enrollment error for {course_id}: {e}")
            return False, str(e)
