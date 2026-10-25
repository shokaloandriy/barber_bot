"""Барбер: послуги, допродаж, контакти, нагадування, розсилка, посилання. Графік роботи — в admin_schedule."""
import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import Bcast, ItCB, ItemEdit, SchedCB, SetCB, SetEdit, SvCB, SvcEdit
from config import ADMIN_IDS
from utils import IsAdmin, btn, d2k, e, money, parse_time, safe_edit, to_int, today

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

SETTINGS_META = {
    "barber_name": ("Імʼя барбера / назва (бачать клієнти)", "text"),
    "default_remind_days": ("Через скільки днів після візиту нагадувати про стрижку (стандарт)", "int", 3, 180),
    "booking_days": ("На скільки днів уперед клієнти бачать вільний час", "int", 1, 60),
    "min_lead_min": ("Мінімум хвилин до початку, щоб клієнт міг записатися", "int", 0, 1440),
    "slot_step": ("Крок сітки часу в хвилинах (15 або 30)", "int", 5, 120),
    "morning_time": ("Час ранкового звіту про день", "time"),
    "haircut_time": ("Час розсилки нагадувань «пора на стрижку»", "time"),
    "evening_time": ("Час вечірньої перевірки незакритих візитів", "time"),
    "info_text": ("Текст «📍 Контакти» для клієнтів (адреса, Telegram, Instagram)", "text"),
}


# ---------- головне меню ----------

def _home_kb():
    kb = InlineKeyboardBuilder()
    kb.row(btn("✂️ Послуги і ціни", SvCB(a="menu")), btn("🛍 Допродаж", ItCB(a="menu")))
    kb.row(btn("📍 Контакти", SetCB(a="ed", k="info_text")), btn("🗓 Графік роботи", SchedCB(a="wk", day=d2k(today()))))
    kb.row(btn("🔔 Нагадування", SetCB(a="menu", k="rem")), btn("📲 Запис клієнтів", SetCB(a="menu", k="bk")))
    kb.row(btn("📣 Розсилка", "bc"), btn("🔗 Посилання", "lk"))
    return kb.as_markup()


async def home(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer("⚙️ <b>Налаштування</b>", reply_markup=_home_kb())


@router.callback_query(SetCB.filter((F.a == "menu") & (F.k == "home")))
async def home_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cb.message, "⚙️ <b>Налаштування</b>", _home_kb())
    await cb.answer()


def _back():
    return btn("⬅️ Налаштування", SetCB(a="menu", k="home"))


# ---------- нагадування та параметри запису ----------

async def _rem_screen():
    r24, r2 = await db.get_int("remind_24"), await db.get_int("remind_2")
    text = (
        "🔔 <b>Нагадування</b>\n\n"
        f"✂️ «Пора на стрижку»: через <b>{await db.get('default_remind_days')}</b> дн. після візиту, "
        f"о {await db.get('haircut_time')}\n"
        "<i>Інтервал можна змінити окремо для кожного клієнта в його картці.</i>\n\n"
        f"Перед візитом: за 24 год {'✅' if r24 else '❌'} · за 2 год {'✅' if r2 else '❌'}\n\n"
        f"🌅 Ранковий звіт барберу: {await db.get('morning_time')}\n"
        f"🌙 Перевірка незакритих візитів: {await db.get('evening_time')}"
    )
    kb = InlineKeyboardBuilder()
    kb.row(btn("⏱ Інтервал стрижки", SetCB(a="ed", k="default_remind_days")),
           btn("🕐 Час розсилки", SetCB(a="ed", k="haircut_time")))
    kb.row(btn(f"{'✅' if r24 else '❌'} За 24 год", SetCB(a="tog", k="remind_24")),
           btn(f"{'✅' if r2 else '❌'} За 2 год", SetCB(a="tog", k="remind_2")))
    kb.row(btn("🌅 Ранковий звіт", SetCB(a="ed", k="morning_time")),
           btn("🌙 Вечірня перевірка", SetCB(a="ed", k="evening_time")))
    kb.row(_back())
    return text, kb.as_markup()


async def _bk_screen():
    text = (
        "📲 <b>Запис клієнтів через бота</b>\n\n"
        f"Видно вільний час на <b>{await db.get('booking_days')}</b> дн. уперед\n"
        f"Записатися можна не пізніше ніж за <b>{await db.get('min_lead_min')}</b> хв до початку\n"
        f"Крок сітки: <b>{await db.get('slot_step')}</b> хв\n"
        f"Імʼя в привітанні: <b>{e(await db.get('barber_name'))}</b>\n\n"
        "<i>Кожна заявка клієнта приходить тобі на підтвердження.</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.row(btn("📅 Днів уперед", SetCB(a="ed", k="booking_days")),
           btn("⏱ Мін. запас", SetCB(a="ed", k="min_lead_min")))
    kb.row(btn("📏 Крок сітки", SetCB(a="ed", k="slot_step")), btn("✏️ Імʼя", SetCB(a="ed", k="barber_name")))
    kb.row(_back())
    return text, kb.as_markup()


SCREENS = {"rem": _rem_screen, "bk": _bk_screen}
KEY_SCREEN = {"default_remind_days": "rem", "haircut_time": "rem", "morning_time": "rem", "evening_time": "rem",
              "booking_days": "bk", "min_lead_min": "bk", "slot_step": "bk", "barber_name": "bk"}


@router.callback_query(SetCB.filter((F.a == "menu") & F.k.in_(["rem", "bk"])))
async def screen(cb: CallbackQuery, callback_data: SetCB, state: FSMContext):
    await state.clear()
    text, kb = await SCREENS[callback_data.k]()
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(SetCB.filter(F.a == "tog"))
async def toggle(cb: CallbackQuery, callback_data: SetCB):
    await db.put(callback_data.k, 0 if await db.get_int(callback_data.k) else 1)
    text, kb = await _rem_screen()
    await safe_edit(cb.message, text, kb)
    await cb.answer("Збережено")


@router.callback_query(SetCB.filter(F.a == "ed"))
async def edit_prompt(cb: CallbackQuery, callback_data: SetCB, state: FSMContext):
    meta = SETTINGS_META.get(callback_data.k)
    if not meta:
        await cb.answer()
        return
    await state.clear()
    await state.set_state(SetEdit.value)
    await state.update_data(key=callback_data.k)
    current = await db.get(callback_data.k)
    hint = {"int": "Введи число.", "time": "Введи час, наприклад 09:00.", "text": "Надішли новий текст."}[meta[1]]
    kb = InlineKeyboardBuilder()
    kb.row(btn("✖️ Скасувати", "x"))
    await cb.message.answer(f"<b>{meta[0]}</b>\nЗараз: {e(current)}\n\n{hint}", reply_markup=kb.as_markup())
    await cb.answer()


@router.message(SetEdit.value, F.text)
async def edit_value(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    meta = SETTINGS_META[key]
    kind = meta[1]
    if kind == "int":
        v = to_int(m.text)
        if v is None or not meta[2] <= v <= meta[3]:
            await m.answer(f"Потрібне число від {meta[2]} до {meta[3]}.")
            return
        value = v
    elif kind == "time":
        t = parse_time(m.text)
        if not t:
            await m.answer("Формат часу: 09:00")
            return
        value = t.strftime("%H:%M")
    else:
        value = m.text.strip()[:1500]
    await db.put(key, value)
    await state.clear()
    if key in KEY_SCREEN:
        text, kb = await SCREENS[KEY_SCREEN[key]]()
        await m.answer("✅ Збережено\n\n" + text, reply_markup=kb)
    else:
        await m.answer("✅ Збережено", reply_markup=_home_kb())


# ---------- послуги ----------

async def _svc_list():
    rows = await db.q("SELECT * FROM services WHERE active = 1 ORDER BY sort, id")
    kb = InlineKeyboardBuilder()
    for s in rows:
        kb.button(text=f"{s['name']} · {s['duration']} хв · {s['price']} грн", callback_data=SvCB(a="v", id=s["id"]))
    kb.adjust(1)
    kb.row(btn("➕ Додати послугу", SvCB(a="add")))
    kb.row(_back())
    return "✂️ <b>Послуги</b>\nТапни послугу, щоб змінити ціну, тривалість чи назву.", kb.as_markup()


async def _svc_card(sid: int):
    s = await db.q1("SELECT * FROM services WHERE id = ?", sid)
    kb = InlineKeyboardBuilder()
    kb.row(btn("💵 Ціна", SvCB(a="price", id=sid)), btn("⏱ Тривалість", SvCB(a="dur", id=sid)))
    kb.row(btn("✏️ Назва", SvCB(a="name", id=sid)), btn("🗑 Прибрати", SvCB(a="off", id=sid)))
    kb.row(btn("⬅️ Послуги", SvCB(a="menu")))
    return f"✂️ <b>{e(s['name'])}</b>\n⏱ {s['duration']} хв · 💵 {money(s['price'])}", kb.as_markup()


@router.callback_query(SvCB.filter(F.a == "menu"))
async def svc_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _svc_list()
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(SvCB.filter(F.a == "v"))
async def svc_view(cb: CallbackQuery, callback_data: SvCB):
    text, kb = await _svc_card(callback_data.id)
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(SvCB.filter(F.a == "off"))
async def svc_off(cb: CallbackQuery, callback_data: SvCB):
    # не видаляємо фізично — щоб історія і фінанси старих візитів лишились коректними
    await db.ex("UPDATE services SET active = 0 WHERE id = ?", callback_data.id)
    text, kb = await _svc_list()
    await safe_edit(cb.message, text, kb)
    await cb.answer("Послугу прибрано з меню")


@router.callback_query(SvCB.filter(F.a == "add"))
async def svc_add_prompt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SvcEdit.add)
    await cb.message.answer("Нова послуга у форматі <code>Назва; хвилини; ціна</code>\n"
                            "Наприклад: <code>Камуфляж сивини; 30; 350</code>")
    await cb.answer()


@router.message(SvcEdit.add, F.text)
async def svc_add(m: Message, state: FSMContext):
    parts = [p.strip() for p in m.text.split(";")]
    if len(parts) != 3 or not parts[0] or to_int(parts[1]) is None or to_int(parts[2]) is None:
        await m.answer("Формат: <code>Назва; хвилини; ціна</code>")
        return
    dur, price = to_int(parts[1]), to_int(parts[2])
    if not 5 <= dur <= 480:
        await m.answer("Тривалість — від 5 до 480 хв.")
        return
    mx = await db.q1("SELECT COALESCE(MAX(sort), 0) + 1 v FROM services")
    await db.ex("INSERT INTO services(name, duration, price, sort) VALUES(?, ?, ?, ?)",
                parts[0][:60], dur, price, mx["v"])
    await state.clear()
    text, kb = await _svc_list()
    await m.answer("✅ Додано\n\n" + text, reply_markup=kb)


@router.callback_query(SvCB.filter(F.a.in_(["price", "dur", "name"])))
async def svc_field_prompt(cb: CallbackQuery, callback_data: SvCB, state: FSMContext):
    await state.clear()
    await state.set_state(SvcEdit.field)
    await state.update_data(sid=callback_data.id, field=callback_data.a)
    prompt = {"price": "Нова ціна (грн):", "dur": "Нова тривалість (хв):", "name": "Нова назва:"}[callback_data.a]
    await cb.message.answer(prompt)
    await cb.answer()


@router.message(SvcEdit.field, F.text)
async def svc_field(m: Message, state: FSMContext):
    data = await state.get_data()
    field, sid = data["field"], data["sid"]
    if field == "name":
        await db.ex("UPDATE services SET name = ? WHERE id = ?", m.text.strip()[:60], sid)
    else:
        v = to_int(m.text)
        if v is None or (field == "dur" and not 5 <= v <= 480):
            await m.answer("Введи коректне число.")
            return
        col = "price" if field == "price" else "duration"
        await db.ex(f"UPDATE services SET {col} = ? WHERE id = ?", v, sid)
    await state.clear()
    text, kb = await _svc_card(sid)
    await m.answer("✅ Збережено\n\n" + text, reply_markup=kb)


# ---------- товари допродажу ----------

async def _items_list():
    rows = await db.q("SELECT * FROM upsell_items WHERE active = 1 ORDER BY id")
    kb = InlineKeyboardBuilder()
    for it in rows:
        kb.button(text=f"{it['name']} · {it['price']} грн", callback_data=ItCB(a="v", id=it["id"]))
    kb.adjust(1)
    kb.row(btn("➕ Додати товар / послугу", ItCB(a="add")))
    kb.row(_back())
    return ("🛍 <b>Допродаж</b>\nШвидкі кнопки на 2-му кроці закриття візиту. Будь-що інше барбер "
            "просто пише текстом. Тапни позицію, щоб змінити ціну або прибрати."), kb.as_markup()


@router.callback_query(ItCB.filter(F.a == "menu"))
async def items_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _items_list()
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(ItCB.filter(F.a == "v"))
async def item_view(cb: CallbackQuery, callback_data: ItCB):
    it = await db.q1("SELECT * FROM upsell_items WHERE id = ?", callback_data.id)
    kb = InlineKeyboardBuilder()
    kb.row(btn("💵 Ціна", ItCB(a="price", id=it["id"])), btn("🗑 Прибрати", ItCB(a="off", id=it["id"])))
    kb.row(btn("⬅️ Допродаж", ItCB(a="menu")))
    await safe_edit(cb.message, f"🛍 <b>{e(it['name'])}</b> · {money(it['price'])}", kb.as_markup())
    await cb.answer()


@router.callback_query(ItCB.filter(F.a == "off"))
async def item_off(cb: CallbackQuery, callback_data: ItCB):
    await db.ex("UPDATE upsell_items SET active = 0 WHERE id = ?", callback_data.id)
    text, kb = await _items_list()
    await safe_edit(cb.message, text, kb)
    await cb.answer("Прибрано")


@router.callback_query(ItCB.filter(F.a == "price"))
async def item_price_prompt(cb: CallbackQuery, callback_data: ItCB, state: FSMContext):
    await state.clear()
    await state.set_state(ItemEdit.price)
    await state.update_data(iid=callback_data.id)
    await cb.message.answer("Нова ціна (грн):")
    await cb.answer()


@router.message(ItemEdit.price, F.text)
async def item_price(m: Message, state: FSMContext):
    v = to_int(m.text)
    if v is None:
        await m.answer("Введи число.")
        return
    await db.ex("UPDATE upsell_items SET price = ? WHERE id = ?", v, (await state.get_data())["iid"])
    await state.clear()
    text, kb = await _items_list()
    await m.answer("✅ Збережено\n\n" + text, reply_markup=kb)


@router.callback_query(ItCB.filter(F.a == "add"))
async def item_add_prompt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ItemEdit.add)
    await cb.message.answer("Формат: <code>Назва; ціна</code>\nНаприклад: <code>Пудра для обʼєму; 320</code>")
    await cb.answer()


@router.message(ItemEdit.add, F.text)
async def item_add(m: Message, state: FSMContext):
    parts = [p.strip() for p in m.text.split(";")]
    if len(parts) != 2 or not parts[0] or to_int(parts[1]) is None:
        await m.answer("Формат: <code>Назва; ціна</code>")
        return
    await db.ex("INSERT INTO upsell_items(name, price) VALUES(?, ?)", parts[0][:60], to_int(parts[1]))
    await state.clear()
    text, kb = await _items_list()
    await m.answer("✅ Додано\n\n" + text, reply_markup=kb)


# ---------- розсилка ----------

async def _recipients():
    rows = await db.q("SELECT tg_id FROM clients WHERE tg_id IS NOT NULL AND bot_blocked = 0")
    return [r["tg_id"] for r in rows if r["tg_id"] not in ADMIN_IDS]


@router.callback_query(F.data == "bc")
async def bcast_prompt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Bcast.msg)
    n = len(await _recipients())
    kb = InlineKeyboardBuilder()
    kb.row(btn("✖️ Скасувати", "x"))
    await cb.message.answer(
        f"📣 <b>Розсилка</b> — отримають {n} клієнтів.\n\n"
        "Надішли повідомлення так, як воно має виглядати: текст або фото з підписом.\n"
        "<i>Не зловживай: 1–2 розсилки на місяць, інакше блокуватимуть бота.</i>",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.message(Bcast.msg)
async def bcast_preview(m: Message, state: FSMContext):
    await state.update_data(chat_id=m.chat.id, msg_id=m.message_id)
    await state.set_state(Bcast.confirm)
    n = len(await _recipients())
    kb = InlineKeyboardBuilder()
    kb.row(btn(f"✅ Надіслати {n} клієнтам", "bc_go"), btn("✖️ Скасувати", "x"))
    await m.answer("👆 Так побачать клієнти. Надсилаємо?", reply_markup=kb.as_markup())


@router.callback_query(Bcast.confirm, F.data == "bc_go")
async def bcast_go(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await cb.message.edit_text("⏳ Надсилаю…")
    await cb.answer()
    ok = fail = 0
    for uid in await _recipients():
        try:
            await bot.copy_message(uid, data["chat_id"], data["msg_id"])
            ok += 1
        except TelegramRetryAfter as err:
            await asyncio.sleep(err.retry_after)
            try:
                await bot.copy_message(uid, data["chat_id"], data["msg_id"])
                ok += 1
            except Exception:  # noqa: BLE001
                fail += 1
        except TelegramForbiddenError:
            await db.ex("UPDATE clients SET bot_blocked = 1 WHERE tg_id = ?", uid)
            fail += 1
        except Exception:  # noqa: BLE001
            fail += 1
        await asyncio.sleep(0.05)
    await cb.message.answer(f"📣 Розсилку завершено: доставлено {ok}, не вдалося {fail}.")


# ---------- посилання ----------

@router.callback_query(F.data == "lk")
async def links(cb: CallbackQuery, bot: Bot):
    me = await bot.get_me()
    u = me.username
    lines = [
        "🔗 <b>Посилання на бота з міткою джерела</b>",
        "Став різні посилання в різні місця — у картці клієнта й у звіті буде видно, звідки він прийшов.", "",
        f"Instagram (шапка профілю):\n<code>https://t.me/{u}?start=insta</code>",
        f"TikTok:\n<code>https://t.me/{u}?start=tiktok</code>",
        f"QR-код на дзеркалі / візитці:\n<code>https://t.me/{u}?start=qr</code>",
        f"Google Maps:\n<code>https://t.me/{u}?start=maps</code>",
        f"Від друга:\n<code>https://t.me/{u}?start=friend</code>",
        "", "Мітку можна придумати свою: латиниця, цифри, _ або -.",
    ]
    kb = InlineKeyboardBuilder()
    kb.row(_back())
    await safe_edit(cb.message, "\n".join(lines), kb.as_markup())
    await cb.answer()
