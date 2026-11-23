"""Callback-data фабрики та стани FSM в одному місці."""
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup


# ---------- callback data ----------

class DayCB(CallbackData, prefix="d"):
    a: str          # v = переглянути, add = запис на день, blk = блок часу
    day: str        # YYYYMMDD


class WeekCB(CallbackData, prefix="w"):
    day: str


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
    a: str          # add, cus, undo, fin
    ap: int
    it: int = 0


class FinCB(CallbackData, prefix="f"):
    p: str


class SetCB(CallbackData, prefix="st"):
    a: str          # menu, ed, tog
    k: str = ""


class WhCB(CallbackData, prefix="wh"):
    a: str          # menu, d, ov, del
    v: str = ""


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
    custom = State()


class BlockSt(StatesGroup):
    rng = State()


class CSearch(StatesGroup):
    q = State()


class CEdit(StatesGroup):
    note = State()
    interval = State()
    phone = State()


class Hours(StatesGroup):
    wd = State()
    override = State()


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
