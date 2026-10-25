"""Callback-data фабрики та стани FSM в одному місці."""
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup


# ---------- callback data ----------

class DayCB(CallbackData, prefix="d"):
    a: str          # v = переглянути, add = запис на день, blk = блок часу
    day: str        # YYYYMMDD


class SchedCB(CallbackData, prefix="sc"):
    a: str          # wk = тиждень графіка, d = день, set = поставити години, cus = свої години, copy
    day: str        # YYYYMMDD
    v: str = ""     # HHMM-HHMM або off


class ApptCB(CallbackData, prefix="a"):
    a: str          # v, cf, rj, cx, cxy, ns, rs, done, ups, ub, cl
    id: int


class SvcPick(CallbackData, prefix="sp"):
    id: int


class PickDate(CallbackData, prefix="pd"):
    day: str


class PickTime(CallbackData, prefix="pt"):
    t: str          # HHMM


class ClientCB(CallbackData, prefix="cl"):
    a: str          # v, bk, hist, note, int, tog, ph
    id: int


class SaleCB(CallbackData, prefix="s"):
    a: str          # price (it = сума), add (it = товар), undo, next, tip (it = сума)
    ap: int
    it: int = 0


class FinCB(CallbackData, prefix="f"):
    p: str


class SetCB(CallbackData, prefix="st"):
    a: str          # menu, ed, tog
    k: str = ""


class SvCB(CallbackData, prefix="sv"):
    a: str          # menu, v, add, price, dur, name, off
    id: int = 0


class ItCB(CallbackData, prefix="it"):
    a: str          # menu, v, add, price, off
    id: int = 0


class MyCB(CallbackData, prefix="my"):
    a: str          # list, v, cx, cxy, rs, ok
    id: int = 0


# ---------- стани ----------

class Pick(StatesGroup):
    date = State()
    time = State()
    manual_date = State()
    manual_time = State()
    confirm = State()


class ABook(StatesGroup):
    search = State()
    name = State()
    phone = State()


class Done(StatesGroup):
    price = State()
    ups = State()
    tips = State()


class BlockSt(StatesGroup):
    rng = State()


class CSearch(StatesGroup):
    q = State()


class CEdit(StatesGroup):
    note = State()
    interval = State()
    phone = State()


class SchedSt(StatesGroup):
    custom = State()


class SvcEdit(StatesGroup):
    add = State()
    field = State()


class ItemEdit(StatesGroup):
    add = State()
    price = State()


class SetEdit(StatesGroup):
    value = State()


class Bcast(StatesGroup):
    msg = State()
    confirm = State()


class Reg(StatesGroup):
    phone = State()
