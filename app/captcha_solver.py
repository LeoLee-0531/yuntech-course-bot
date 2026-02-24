import base64
import numpy as np
import cv2
import easyocr
import warnings

warnings.filterwarnings("ignore", message="'pin_memory' argument is set as true")

class CaptchaSolver:
    def __init__(self):
        # CAPTCHA 只需要英文與數字
        # verbose=False 隱藏 EasyOCR 啟動日誌
        self.reader = easyocr.Reader(['en'], verbose=False)

    def solve_base64(self, base64_str: str) -> str:
        # 接收 base64 編碼的圖片字串，解碼後使用 EasyOCR 辨識。
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]

        img_bytes = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        results = self.reader.readtext(img)

        # 串接所有片段中的英數字元
        all_chars = ''.join(
            c for (_, text, _) in results
            for c in text if c.isalnum()
        )

        # 回傳前 4 碼（驗證碼固定為 4 碼）
        if len(all_chars) >= 4:
            return all_chars[:4]
        return ""
