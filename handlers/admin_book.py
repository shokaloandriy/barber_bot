"""Барбер записує клієнта вручну: пошук / новий клієнт → послуга → дата → час."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import ABook, ClientCB
from handlers import booking
from utils import IsAdmin, btn, client, dts, e, fdate, k2d, norm_phone, now, search_clients

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def start(msg: Message, state: FSMContext, date: str | None = None) -> None:
    await state.clear()
    await state.set_state(ABook.search)
    await state.update_data(preset_date=date)
    kb = InlineKeyboardBuilder()
    kb.row(btn("➕ Новий клієнт", "ab_new"))
    kb.row(btn("✖️ Скасувати", "x"))
    when = f" на {fdate(k2d(date))}" if date else ""
    await msg.answer(
        f"➕ <b>Новий запис{when}</b>\n\nВведи імʼя або номер телефону клієнта для пошуку 👇",
        reply_markup=kb.as_markup(),
    )


async def _to_services(msg: Message, state: FSMContext, cid: int, edit: bool) -> None:
    data = await state.get_data()
    c = await client(cid)
    extra = {"client_id": cid, "client_name": c["name"]}
    if data.get("preset_date"):
        extra["date"] = data["preset_date"]
    await booking.start_new(msg, state, "admin_new", edit=edit, **extra)


@router.message(ABook.search, F.text)
async def search(m: Message, state: FSMContext):
    rows = await search_clients(m.text)
    await state.update_data(last_q=m.text.strip())
    kb = InlineKeyboardBuilder()
    for c in rows:
        kb.button(text=f"{c['name']} · {c['phone'] or '—'}", callback_data=ClientCB(a="bk", id=c["id"]))
    kb.adjust(1)
    kb.row(btn("➕ Новий клієнт", "ab_new"))
    kb.row(btn("✖️ Скасувати", "x"))
    text = f"Знайдено: {len(rows)}. Обери клієнта або введи інший запит." if rows else \
        "Нікого не знайдено. Введи інший запит або створи нового клієнта."
    await m.answer(text, reply_markup=kb.as_markup())


@router.callback_query(ClientCB.filter(F.a == "bk"))
async def pick_client(cb: CallbackQuery, callback_data: ClientCB, state: FSMContext):
    if not await client(callback_data.id):
        await cb.answer("Клієнта не знайдено", show_alert=True)
        return
    await _to_services(cb.message, state, callback_data.id, edit=True)
    await cb.answer()


@router.callback_query(ABook.search, F.data == "ab_new")
async def new_client(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(ABook.name)
    kb = InlineKeyboardBuilder()
    q = data.get("last_q") or ""
    if q and not any(ch.isdigit() for ch in q):
        kb.row(btn(f"Використати «{q[:30]}»", "ab_useq"))
    kb.row(btn("✖️ Скасувати", "x"))
    await cb.message.answer("Імʼя клієнта:", reply_markup=kb.as_markup())
    await cb.answer()


async def _ask_phone(msg: Message, state: FSMContext, name: str) -> None:
    await state.update_data(new_name=name)
    await state.set_state(ABook.phone)
    kb = InlineKeyboardBuilder()
    kb.row(btn("Без телефону", "ab_skip"))
    await msg.answer(f"Телефон для <b>{e(name)}</b>:", reply_markup=kb.as_markup())


@router.callback_query(ABook.name, F.data == "ab_useq")
async def use_query_as_name(cb: CallbackQuery, state: FSMContext):
    await _ask_phone(cb.message, state, (await state.get_data())["last_q"][:60])
    await cb.answer()


@router.message(ABook.name, F.text)
async def new_name(m: Message, state: FSMContext):
    await _ask_phone(m, state, m.text.strip()[:60])


async def _create(msg: Message, state: FSMContext, phone: str | None) -> None:
    data = await state.get_data()
    if phone:
        existing = await db.q1("SELECT * FROM clients WHERE phone = ? LIMIT 1", phone)
        if existing:
            await msg.answer(f"ℹ️ Клієнт з цим номером уже є: <b>{e(existing['name'])}</b> — записую його.")
            await _to_services(msg, state, existing["id"], edit=False)
            return
    cid = await db.ex(
        "INSERT INTO clients(name, phone, source, created_at) VALUES(?, ?, 'manual', ?)",
        data["new_name"], phone, dts(now()),
    )
    await _to_services(msg, state, cid, edit=False)


@router.message(ABook.phone, F.text)
async def new_phone(m: Message, state: FSMContext):
    phone = norm_phone(m.text)
    if not phone:
        await m.answer("Не схоже на номер. Приклад: 0671234567 — або натисни «Без телефону».")
        return
    await _create(m, state, phone)


@router.callback_query(ABook.phone, F.data == "ab_skip")
async def skip_phone(cb: CallbackQuery, state: FSMContext):
    await _create(cb.message, state, None)
    await cb.answer()
