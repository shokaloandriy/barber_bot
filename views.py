"""Тексти й клавіатури екранів (без логіки обробників)."""
from datetime import date, timedelta

from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import ApptCB, ClientCB, DayCB, MyCB, SaleCB, WeekCB
from utils import (EMOJI, STATUS_TXT, WD_FULL, appt_line, btn, client, client_stats, d2k, day_appts,
                   day_hours, e, fdate, money, rel_day, sales_of, sdt, today)


def kb_confirm(aid: int):
    kb = InlineKeyboardBuilder()
    kb.row(btn("✅ Підтвердити", ApptCB(a="cf", id=aid)), btn("❌ Відхилити", ApptCB(a="rj", id=aid)))
    kb.row(btn("📋 Відкрити запис", ApptCB(a="v", id=aid)))
    return kb.as_markup()


def kb_client_appt(aid: int, with_ok: bool = False):
    kb = InlineKeyboardBuilder()
    if with_ok:
        kb.row(btn("✅ Буду", MyCB(a="ok", id=aid)))
    kb.row(btn("🔁 Перенести", MyCB(a="rs", id=aid)), btn("❌ Скасувати", MyCB(a="cx", id=aid)))
    return kb.as_markup()


def kb_book_again():
    kb = InlineKeyboardBuilder()
    kb.row(btn("✂️ Обрати інший час", "c:book"))
    return kb.as_markup()


def _short(name: str | None, n: int = 12) -> str:
    name = name or "?"
    return name if len(name) <= n else name[: n - 1] + "…"


async def appt_money(a) -> tuple[int, int]:
    sales = await sales_of(a["id"])
    return a["price"] or 0, sum(s["price"] for s in sales)


# ---------- день / тиждень ----------

async def render_day(d: date):
    hours = await day_hours(d)
    appts = await day_appts(d)
    head = f"📅 <b>{WD_FULL[d.weekday()]}, {d:%d.%m}</b>"
    if d == today():
        head += " · сьогодні"
    lines = [head, f"🕘 {hours[0]:%H:%M}–{hours[1]:%H:%M}" if hours else "💤 Вихідний", ""]
    kb = InlineKeyboardBuilder()
    fact = plan = clients = 0
    for a in appts:
        s, en = sdt(a["start_at"]), sdt(a["end_at"])
        if a["status"] == "block":
            lines.append(f"🔒 <b>{s:%H:%M}–{en:%H:%M}</b> {e(a['note']) or 'заблоковано'}")
            kb.button(text=f"🔒 {s:%H:%M}", callback_data=ApptCB(a="v", id=a["id"]))
            continue
        lines.append(f"{EMOJI[a['status']]} <b>{s:%H:%M}–{en:%H:%M}</b> {e(a['sname'])} — {e(a['cname'])}")
        kb.button(text=f"{EMOJI[a['status']]} {s:%H:%M} {_short(a['cname'])}",
                  callback_data=ApptCB(a="v", id=a["id"]))
        if a["status"] == "done":
            p, sl = await appt_money(a)
            fact += p + sl
            clients += 1
        elif a["status"] in ("pending", "confirmed"):
            plan += a["sprice"] or 0
            clients += 1
    if len(lines) == 3:
        lines.append("Записів немає.")
    stat = [f"👥 Клієнтів: {clients}"]
    if fact:
        stat.append(f"💵 Каса: {money(fact)}")
    if plan:
        stat.append(f"📈 Ще очікується: {money(plan)}")
    lines += ["", " · ".join(stat)]
    kb.adjust(2)
    kb.row(
        btn("◀️", DayCB(a="v", day=d2k(d - timedelta(days=1)))),
        btn("Сьогодні", DayCB(a="v", day=d2k(today()))),
        btn("▶️", DayCB(a="v", day=d2k(d + timedelta(days=1)))),
    )
    kb.row(btn("➕ Запис", DayCB(a="add", day=d2k(d))), btn("🔒 Блок часу", DayCB(a="blk", day=d2k(d))))
    return "\n".join(lines), kb.as_markup()


async def render_week(start: date):
    lines = [f"🗓 <b>{start:%d.%m} – {start + timedelta(days=6):%d.%m}</b>", ""]
    kb = InlineKeyboardBuilder()
    for i in range(7):
        d = start + timedelta(days=i)
        hours = await day_hours(d)
        appts = [a for a in await day_appts(d) if a["status"] != "block"]
        pending = sum(1 for a in appts if a["status"] == "pending")
        mark = "👉 " if d == today() else ""
        hrs = f"{hours[0]:%H:%M}–{hours[1]:%H:%M}" if hours else "вихідний"
        line = f"{mark}<b>{fdate(d)}</b> · {hrs} · записів: {len(appts)}"
        if pending:
            line += f" (⏳ {pending})"
        lines.append(line)
        kb.button(text=fdate(d), callback_data=DayCB(a="v", day=d2k(d)))
    kb.adjust(4)
    kb.row(btn("◀️ Тиждень", WeekCB(day=d2k(start - timedelta(days=7)))),
           btn("Тиждень ▶️", WeekCB(day=d2k(start + timedelta(days=7)))))
    return "\n".join(lines), kb.as_markup()


# ---------- картка запису ----------

async def render_appt(a):
    s, en = sdt(a["start_at"]), sdt(a["end_at"])
    rel = rel_day(s.date())
    head = f"{EMOJI[a['status']]} <b>{appt_line(a)}</b>"
    if rel in ("сьогодні", "завтра"):
        head += f" · {rel}"
    lines = [head]
    kb = InlineKeyboardBuilder()
    aid = a["id"]

    if a["status"] == "block":
        lines.append(f"🔒 Заблокований час {('— ' + e(a['note'])) if a['note'] else ''}")
        kb.row(btn("🗑 Зняти блок", ApptCB(a="ub", id=aid)))
        kb.row(btn("⬅️ До дня", DayCB(a="v", day=d2k(s.date()))))
        return "\n".join(lines), kb.as_markup()

    dur = int((en - s).total_seconds() // 60)
    lines.append(f"✂️ {e(a['sname'])} · {dur} хв · {money(a['sprice'])}")
    who = f"👤 {e(a['cname'])}"
    if a["cphone"]:
        who += f" · {a['cphone']}"
    if a["cuser"]:
        who += f" · @{e(a['cuser'])}"
    lines.append(who)
    if a["note"]:
        lines.append(f"📝 {e(a['note'])}")
    src = " · записався сам через бота" if a["created_by"] == "client" else ""
    lines.append(f"Статус: <b>{STATUS_TXT[a['status']]}</b>{src}")

    if a["status"] == "done":
        price, _ = await appt_money(a)
        sales = await sales_of(aid)
        lines.append("")
        lines.append(f"💵 Послуга: {money(price)}")
        if sales:
            lines.append("🛍 Допродаж: " + ", ".join(f"{e(x['item_name'])} {x['price']}" for x in sales))
        else:
            lines.append("🛍 Допродажу не було")
        lines.append(f"<b>Разом: {money(price + sum(x['price'] for x in sales))}</b>")

    st = a["status"]
    if st == "pending":
        kb.row(btn("✅ Підтвердити", ApptCB(a="cf", id=aid)), btn("❌ Відхилити", ApptCB(a="rj", id=aid)))
    if st in ("pending", "confirmed"):
        kb.row(btn("💈 Завершити візит", ApptCB(a="done", id=aid)))
        kb.row(btn("🔁 Перенести", ApptCB(a="rs", id=aid)), btn("🚫 Не прийшов", ApptCB(a="ns", id=aid)))
        kb.row(btn("❌ Скасувати запис", ApptCB(a="cx", id=aid)))
    if st == "done":
        kb.row(btn("🛍 Допродаж", ApptCB(a="ups", id=aid)))
    if a["client_id"]:
        kb.row(btn("👤 Клієнт", ClientCB(a="v", id=a["client_id"])),
               btn("⬅️ До дня", DayCB(a="v", day=d2k(s.date()))))
    else:
        kb.row(btn("⬅️ До дня", DayCB(a="v", day=d2k(s.date()))))
    return "\n".join(lines), kb.as_markup()


# ---------- допродаж ----------

async def render_upsell(a):
    aid = a["id"]
    price, _ = await appt_money(a)
    sales = await sales_of(aid)
    lines = [f"🛍 <b>Допродаж</b> · {e(a['cname'])}", f"💵 Послуга: {money(price)}", ""]
    if sales:
        lines.append("Додано:")
        lines += [f" • {e(x['item_name'])} — {money(x['price'])}" for x in sales]
    else:
        lines.append("Поки нічого не додано.")
    total = price + sum(x["price"] for x in sales)
    lines += ["", f"<b>Разом за візит: {money(total)}</b>", "",
              "Тапни товар, щоб додати (повторний тап = ще одна штука)."]
    kb = InlineKeyboardBuilder()
    for it in await db.q("SELECT * FROM upsell_items WHERE active = 1 ORDER BY name"):
        kb.button(text=f"{it['name']} · {it['price']}", callback_data=SaleCB(a="add", ap=aid, it=it["id"]))
    kb.adjust(2)
    kb.row(btn("✍️ Інше", SaleCB(a="cus", ap=aid)), btn("↩️ Прибрати останнє", SaleCB(a="undo", ap=aid)))
    kb.row(btn("✅ Готово", SaleCB(a="fin", ap=aid)))
    return "\n".join(lines), kb.as_markup()


# ---------- картка клієнта ----------

async def render_client(cid: int):
    c = await client(cid)
    if not c:
        return "Клієнта не знайдено.", None
    st = await client_stats(cid)
    default = await db.get_int("default_remind_days", 21)
    lines = [f"👤 <b>{e(c['name'])}</b>"]
    contact = [c["phone"] or "без телефону"]
    if c["username"]:
        contact.append(f"@{e(c['username'])}")
    if c["tg_id"]:
        contact.append("💬 є в боті" + (" (заблокував)" if c["bot_blocked"] else ""))
    else:
        contact.append("📵 не в боті")
    lines.append(" · ".join(contact))
    lines.append(f"📥 Джерело: {e(c['source']) or '—'} · з {sdt(c['created_at']):%d.%m.%Y}")
    lines.append("")
    lines.append(f"✂️ Візитів: {st['visits']}" + (f" · 🚫 неявок: {st['no_show']}" if st["no_show"] else ""))
    if st["visits"]:
        lines.append(f"💵 Всього: {money(st['total'])} · середній чек {money(st['avg'])}")
        if st["upsell"]:
            lines.append(f"🛍 З них допродаж: {money(st['upsell'])}")
    if st["last"]:
        days = (today() - st["last"]).days
        lines.append(f"🕓 Останній візит: {st['last']:%d.%m.%Y} ({days} дн. тому)")
    if st["next"]:
        lines.append(f"📅 Наступний запис: {fdate(st['next'].date())}, {st['next']:%H:%M}")
    interval = c["remind_days"] or default
    rem = "вимкнено" if c["reminders_off"] else f"кожні {interval} дн." + ("" if c["remind_days"] else " (стандарт)")
    lines.append(f"🔔 Нагадування про стрижку: {rem}")
    if c["note"]:
        lines.append(f"📝 {e(c['note'])}")

    kb = InlineKeyboardBuilder()
    kb.row(btn("📅 Записати", ClientCB(a="bk", id=cid)), btn("🗂 Історія", ClientCB(a="hist", id=cid)))
    kb.row(btn("📝 Нотатка", ClientCB(a="note", id=cid)), btn("⏱ Інтервал", ClientCB(a="int", id=cid)))
    kb.row(btn("🔕 Вимкнути нагадування" if not c["reminders_off"] else "🔔 Увімкнути нагадування",
               ClientCB(a="tog", id=cid)),
           btn("📱 Телефон", ClientCB(a="ph", id=cid)))
    return "\n".join(lines), kb.as_markup()
