"""Старт, меню (reply-кнопки), скасування, fallback. Підключається ПЕРШИМ і ОСТАННІМ (fallback)."""
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
import keyboards as K
from handlers import admin_book, admin_clients, admin_finance, admin_schedule, admin_settings, client
from utils import IsAdmin, client_by_tg, e, ensure_client, is_admin, notify_admins, today

router = Router()
fallback = Router()


@router.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext, bot: Bot):
    await state.clear()
    if is_admin(m.from_user.id):
        await m.answer(
            "💈 <b>Панель барбера</b>\n\n"
            "📅 Сьогодні — записи на день, закриття візитів\n"
            "🗓 Графік роботи — відкрий дні й години, коли працюєш (інші дні закриті для запису)\n"
            "➕ Запис — записати клієнта вручну\n"
            "👥 Клієнти — база, пошук, кому час на стрижку\n"
            "💰 Фінанси — заробіток за тиждень і місяць\n"
            "⚙️ Налаштування — послуги, ціни, контакти\n\n"
            "Подивитись бота очима клієнта: /client",
            reply_markup=K.ADMIN_MENU,
        )
        return
    src = command.args if command.args and re.fullmatch(r"[\w-]{1,32}", command.args) else None
    is_new = not await client_by_tg(m.from_user.id)
    await ensure_client(m.from_user, source=src)
    barber = e(await db.get("barber_name"))
    await m.answer(
        f"Привіт, {e(m.from_user.first_name)}! 👋\nЯ бот для запису до <b>{barber}</b>.\n\n"
        "✂️ Записатися — оберіть послугу і вільний час\n"
        "📋 Мої записи — перенести або скасувати\n"
        "💈 Послуги і ціни\n📍 Контакти",
        reply_markup=K.CLIENT_MENU,
    )
    if is_new:
        uname = f" @{e(m.from_user.username)}" if m.from_user.username else ""
        await notify_admins(bot, f"👋 Новий підписник: {e(m.from_user.full_name)}{uname} · джерело: {e(src) or 'бот'}")


@router.message(Command("id"))
async def my_id(m: Message):
    await m.answer(f"Ваш Telegram ID: <code>{m.from_user.id}</code>")


@router.message(Command("admin"), IsAdmin())
async def admin_menu(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("💈 Панель барбера", reply_markup=K.ADMIN_MENU)


@router.message(Command("client"), IsAdmin())
async def client_mode(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("👀 Режим клієнта. Повернутись: /admin", reply_markup=K.CLIENT_MENU)


@router.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Скасовано.", reply_markup=K.ADMIN_MENU if is_admin(m.from_user.id) else K.CLIENT_MENU)


@router.callback_query(F.data == "x")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("✖️ Скасовано.")
    except Exception:  # noqa: BLE001
        pass
    await cb.answer()


# ---------- reply-меню барбера (працює з будь-якого стану) ----------

@router.message(F.text == K.A_TODAY, IsAdmin())
async def a_today(m: Message, state: FSMContext):
    await state.clear()
    await admin_schedule.send_day(m, today())


@router.message(F.text == K.A_SCHED, IsAdmin())
async def a_sched(m: Message, state: FSMContext):
    await state.clear()
    await admin_schedule.send_sched(m)


@router.message(F.text == K.A_ADD, IsAdmin())
async def a_add(m: Message, state: FSMContext):
    await admin_book.start(m, state)


@router.message(F.text == K.A_CLIENTS, IsAdmin())
async def a_clients(m: Message, state: FSMContext):
    await admin_clients.home(m, state)


@router.message(F.text == K.A_FIN, IsAdmin())
async def a_fin(m: Message, state: FSMContext):
    await state.clear()
    await admin_finance.send(m)


@router.message(F.text == K.A_SETTINGS, IsAdmin())
async def a_settings(m: Message, state: FSMContext):
    await admin_settings.home(m, state)


# ---------- reply-меню клієнта ----------

@router.message(F.text == K.C_BOOK)
async def c_book(m: Message, state: FSMContext):
    await client.book_entry(m, state, m.from_user)


@router.message(F.text == K.C_MY)
async def c_my(m: Message, state: FSMContext):
    await state.clear()
    await client.my_list(m, m.from_user)


@router.message(F.text == K.C_PRICES)
async def c_prices(m: Message, state: FSMContext):
    await state.clear()
    await client.prices(m)


@router.message(F.text == K.C_CONTACTS)
async def c_contacts(m: Message, state: FSMContext):
    await state.clear()
    await client.contacts(m)


# ---------- fallback (підключається останнім) ----------

@fallback.message()
async def unknown_message(m: Message):
    if is_admin(m.from_user.id):
        await m.answer("Скористайся меню 👇", reply_markup=K.ADMIN_MENU)
    else:
        await m.answer("Оберіть дію в меню 👇", reply_markup=K.CLIENT_MENU)


@fallback.callback_query()
async def stale_button(cb: CallbackQuery):
    await cb.answer("Ця кнопка вже неактуальна. Почніть заново з меню.", show_alert=True)
