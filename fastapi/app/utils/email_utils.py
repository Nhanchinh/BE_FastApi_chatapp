import os
from typing import Optional

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("GMAIL")
SMTP_PASS = os.getenv("APP_PASSWORD")


async def send_otp_email(to_email: str, otp: str) -> None:
    """
    Send OTP email using Gmail SMTP.

    Raises:
        ValueError: if SMTP credential env vars are missing.
    """
    if not SMTP_USER or not SMTP_PASS:
        raise ValueError("SMTP credentials are not configured. Please set GMAIL and APP_PASSWORD env vars.")

    message = MIMEMultipart()
    message["From"] = SMTP_USER
    message["To"] = to_email
    message["Subject"] = "Mã OTP xác minh"

    body = f"Mã OTP của bạn là {otp}. Hiệu lực trong 2 phút."
    message.attach(MIMEText(body, "plain", "utf-8"))

    await aiosmtplib.send(
        message,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        start_tls=True,
        username=SMTP_USER,
        password=SMTP_PASS,
    )

