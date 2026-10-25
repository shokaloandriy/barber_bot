from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# --- кнопки барбера ---
A_TODAY = "📅 Сьогодні"
A_SCHED = "🗓 Графік роботи"
A_ADD = "➕ Запис"
A_CLIENTS = "👥 Клієнти"
A_FIN = "💰 Фінанси"
A_SETTINGS = "⚙️ Налаштування"

# --- кнопки клієнта ---
C_BOOK = "✂️ Записатися"
C_MY = "📋 Мої записи"
C_PRICES = "💈 Послуги і ціни"
C_CONTACTS = "📍 Контакти"
C_SKIP_PHONE = "✖️ Не зараз"

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=A_TODAY), KeyboardButton(text=A_SCHED)],
        [KeyboardButton(text=A_ADD), KeyboardButton(text=A_CLIENTS)],
        [KeyboardButton(text=A_FIN), KeyboardButton(text=A_SETTINGS)],
    ],
    resize_keyboard=True,
)

CLIENT_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=C_BOOK), KeyboardButton(text=C_MY)],
        [KeyboardButton(text=C_PRICES), KeyboardButton(text=C_CONTACTS)],
    ],
    resize_keyboard=True,
)

CONTACT_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
        [KeyboardButton(text=C_SKIP_PHONE)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
