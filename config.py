import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Telegram ID барбера (і за потреби твій, як розробника), через кому: 123,456
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

# На Railway: змонтуй volume в /data і постав DB_PATH=/data/barber.db
DB_PATH = os.getenv("DB_PATH", "barber.db")

# Не використовуємо змінну TZ — вона системна в Linux
TZ = ZoneInfo(os.getenv("TZ_NAME", "Europe/Kyiv"))
