import requests
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

load_dotenv()

class BaseNotifier:
    def send_message(self, text: str):
        pass

class DiscordNotifier(BaseNotifier):
    def __init__(self):
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    def send_message(self, text: str):
        if not self.webhook_url:
            return

        payload = {
            "content": text
        }

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Details: {e.response.text}")

class NotificationManager:
    def __init__(self):
        self.notifier = DiscordNotifier()
        
    def send_message(self, text: str):
        self.notifier.send_message(text)
            

