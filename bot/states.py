from aiogram.fsm.state import StatesGroup, State

class Flow(StatesGroup):
    START = State()
    NAME = State()
    GENDER = State()
    SYSTEM = State()
    BIRTH_DATE = State()
    TIME_KNOWN = State()
    BIRTH_TIME = State()
    CITY = State()
    CALC_SPINNER = State()
    MENU = State()
