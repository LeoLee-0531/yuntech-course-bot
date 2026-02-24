import base64
import numpy as np
import cv2
import easyocr

class CaptchaSolver:
    def __init__(self):
        # We only need English alphanumeric characters for the CAPTCHA
        # verbose=False suppresses EasyOCR startup logs
        self.reader = easyocr.Reader(['en'], verbose=False)

    def solve_base64(self, base64_str: str) -> str:
        """
        Takes a base64 encoded image string (or data-URI), decodes it,
        and reads the text using EasyOCR.

        Strategy: concatenate ALL recognized text fragments (alphanumeric only)
        and return the first 4 characters. This handles small captcha images
        where OCR splits one 4-char code into multiple fragments
        (e.g. AAXCCS 30x130px captcha: '628 34R' -> '62834R' -> take '6283').
        """
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]

        img_bytes = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        results = self.reader.readtext(img)

        # Concatenate all alphanumeric chars from all fragments
        all_chars = ''.join(
            c for (_, text, _) in results
            for c in text if c.isalnum()
        )

        # Return only the first 4 characters (the captcha is always 4 chars)
        if len(all_chars) >= 4:
            return all_chars[:4]
        return ""
