import os
from dotenv import load_dotenv

load_dotenv()

TICKETMASTER_KEY = os.environ["TICKETMASTER_KEY"]

SMTP_FROM = os.environ.get("SMTP_FROM", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))