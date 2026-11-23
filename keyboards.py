from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# --- кнопки барбера ---
A_TODAY = "📅 Сьогодні"
A_WEEK = "🗓 Тиждень"
A_ADD = "➕ Запис"
A_CLIENTS = "👥 Клієнти"
A_FIN = "💰 Фінанси"
A_SETTINGS = "⚙️ Налаштування"

# --- кнопки клієнта ---
C_BOOK = "✂️ Записатися"
C_MY = "📋 Мої записи"
C_PRICES = "💈 Послуги і ціни"
C_CONTACTS = "📍 Контакти"
C_SHARE_PHONE = "📱 Поділитися номером"

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=A_TODAY), KeyboardButton(text=A_WEEK)],
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

# Без кнопки «пропустити»: поки клієнт не дасть номер, бот нічого іншого не робить
CONTACT_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=C_SHARE_PHONE, request_contact=True)]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="або введіть номер: 0671234567",
)
