import requests
import os
from dotenv import load_dotenv

load_dotenv()

class LineNotifier:
    def __init__(self):
        self.token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        self.group_id = os.getenv("LINE_GROUP_ID")
        self.api_url = "https://api.line.me/v2/bot/message/push"

    def send_message(self, text: str, mention_user_ids: list = None):
        if not self.token or not self.group_id:
            print(f"[Mock Notification to Group] {text} (mentions: {mention_user_ids})")
            return

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }
        
        message_obj = {
            "type": "textV2",
            "text": text
        }
        
        if mention_user_ids:
            mention_str = ""
            substitution = {}
            
            for index, uid in enumerate(mention_user_ids):
                placeholder = f"user{index}"
                substitution[placeholder] = {
                    "type": "mention",
                    "mentionee": {
                        "type": "user",
                        "userId": uid
                    }
                }
                mention_str += f"{{{placeholder}}} "
                
            # Put the mention placeholders right before the actual message
            message_obj["text"] = f"{mention_str}\n{text}"
            message_obj["substitution"] = substitution

        payload = {
            "to": self.group_id,
            "messages": [message_obj]
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"Failed to send LINE notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Details: {e.response.text}")
            raise
