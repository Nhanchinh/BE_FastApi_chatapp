import os
from typing import Optional

from zego_server_assistant import ServerAssistant
from dotenv import load_dotenv


def generate_zego_token(
    app_id: int,
    user_id: str,
    server_secret: str,
    effective_time_in_seconds: int = 3600,
    payload: str = "",
) -> str:
    """
    Generate Zego token using the bundled ServerAssistant.
    `payload` must be a JSON string.
    """
    token_result = ServerAssistant().generate_token(
        app_id=app_id,
        signature=server_secret,
        device_id=user_id,
        expiry=effective_time_in_seconds,
        payload=payload,
    )
    return token_result


def get_zego_config():
    load_dotenv()
    app_id = os.getenv("ZEGO_APP_ID")
    server_secret = os.getenv("ZEGO_SERVER_SECRET")
    return app_id, server_secret

