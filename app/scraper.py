import requests
import re
import urllib3
from bs4 import BeautifulSoup
from typing import Tuple, Optional

class CourseScraper:
    BASE_URL = "https://webapp.yuntech.edu.tw/WebNewCAS/Course/QueryCour.aspx"

    def __init__(self, session_manager=None):
        if session_manager:
            self.session = session_manager
        else:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            })
            # Disable SSL warning for the target server with non-standard certificate
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.verify = False

    def get_course_info(self, course_id: str) -> Tuple[int, int, str]:
        """
        Returns (enrolled_count, capacity_limit, course_name)
        """
        # Step 1: GET to get tokens
        response = self.session.get(self.BASE_URL, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        viewstate = soup.find('input', {'name': '__VIEWSTATE'})['value']
        viewstate_gen = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})['value']
        event_validation = soup.find('input', {'name': '__EVENTVALIDATION'})['value']
        acad_seme_elem = soup.find('select', {'id': 'ctl00_MainContent_AcadSeme'}).find('option', selected=True)
        acad_seme = acad_seme_elem['value'] if acad_seme_elem else ""
        
        # Extract hidden toolkit script manager field
        toolkit_hidden = soup.find('input', {'id': 'ctl00_MainContent_ToolkitScriptManager1_HiddenField'})
        toolkit_value = toolkit_hidden['value'] if toolkit_hidden else ''
        
        # Step 2: POST to query course
        payload = {
            "__LASTFOCUS": "",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstate_gen,
            "__VIEWSTATEENCRYPTED": "",
            "__EVENTVALIDATION": event_validation,
            "ctl00_MainContent_ToolkitScriptManager1_HiddenField": toolkit_value,
            "ctl00$MainContent$AcadSeme": acad_seme,
            "ctl00$MainContent$College": "",
            "ctl00$MainContent$DeptCode": "",
            "ctl00$MainContent$CurrentSubj": course_id,
            "ctl00$MainContent$TextBoxWatermarkExtender3_ClientState": "",
            "ctl00$MainContent$SubjName": "",
            "ctl00$MainContent$TextBoxWatermarkExtender1_ClientState": "",
            "ctl00$MainContent$Instructor": "",
            "ctl00$MainContent$TextBoxWatermarkExtender2_ClientState": "",
            "ctl00$MainContent$Submit": "執行查詢"
        }
        
        response = self.session.post(self.BASE_URL, data=payload, timeout=10)
        response.raise_for_status()
        
        # Step 3: Parse result
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # The result table ID from reference: ctl00_MainContent_Course_GridView
        # Current app was using: ctl00_MainContent_GridView1
        # Let's try both or prioritize the one from the reference
        grid = soup.find('table', {'id': 'ctl00_MainContent_Course_GridView'})
        if not grid:
            grid = soup.find('table', {'id': 'ctl00_MainContent_GridView1'})
            
        if not grid:
            raise Exception(f"Course {course_id} not found: The course grid was not rendered.")
            
        rows = grid.find_all('tr')[1:] # Skip header
        for row in rows:
            if 'PageBar' in str(row): # Skip pagination rows
                continue
                
            cols = row.find_all('td')
            if len(cols) < 11: continue
            
            # Reference uses index 0 for course_id link text
            row_course_id_elem = cols[0].find('a')
            if not row_course_id_elem:
                # Fallback to older index 1 if needed
                row_course_id = cols[1].text.strip()
            else:
                row_course_id = row_course_id_elem.text.strip()

            if row_course_id == course_id:
                # Based on reference:
                # Name at index 2 (link)
                # Enrolled at index 9 (span)
                # Limit at index 10 (span)
                
                course_name_elem = cols[2].find('a')
                course_name = course_name_elem.text.strip() if course_name_elem else "未知課程"
                
                enrolled_elem = cols[9].find('span')
                enrolled_text = enrolled_elem.text.strip() if enrolled_elem else "0"
                enrolled = int(enrolled_text) if enrolled_text.isdigit() else 0
                
                limit_elem = cols[10].find('span')
                limit_text = limit_elem.text.strip() if limit_elem else "0"
                
                # Use regex for limit parsing as in reference
                limit_match = re.search(r'(\d+)', limit_text)
                limit = int(limit_match.group(1)) if limit_match else 0
                
                return enrolled, limit, course_name
                
        raise Exception(f"Course {course_id} not found in the search results.")
