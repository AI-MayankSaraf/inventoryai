
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

msg = EmailMessage()
msg["Subject"] = "InventoryAI - Email Test"
msg["From"] = (
    f'{os.getenv("EMAIL_FROM_NAME")} '
    f'<{os.getenv("EMAIL_FROM")}>'
)
msg["To"] = "sharad2810@yopmail.com"
msg.set_content(
    "Hello! This is a test email from InventoryAI "
    "using Brevo SMTP."
)

with smtplib.SMTP(
    os.getenv("SMTP_HOST"),
    int(os.getenv("SMTP_PORT", "587"))
) as server:
    server.starttls()
    server.login(
        os.getenv("SMTP_USERNAME"),
        os.getenv("SMTP_PASSWORD")
    )
    server.send_message(msg)

print("Email sent successfully!")
