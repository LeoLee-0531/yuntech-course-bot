import requests
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

load_dotenv()


class NotificationManager:
    def __init__(self):
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    def send_message(self, text: str):
        if not self.webhook_url:
            return

        try:
            response = requests.post(self.webhook_url, json={"content": text}, timeout=10)
            response.raise_for_status()
            logger.info("Notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Details: {e.response.text}")
