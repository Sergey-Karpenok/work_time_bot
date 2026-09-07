"""Вспомогательные функции: работа со временем и форматирование."""

from datetime import datetime, timedelta, date, timezone
from typing import Optional

import pytz

from config import WORK_DAY_DURATION

# Названия дней недели на русском
WEEKDAY_NAMES = {
    0: "понедельник",
    1: "вторник",
    2: "среда",
    3: "четверг",
    4: "пятница",
    5: "суббота",
    6: "воскресенье",
}

WEEKDAY_NAMES_ACCUSATIVE = {
    0: "понедельник",
    1: "вторник",
    2: "среду",
    3: "четверг",
    4: "пятницу",
    5: "субботу",
    6: "воскресенье",
}


def get_tz(tz_name: str) -> pytz.BaseTzInfo:
    try:
        return pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("Europe/Moscow")


def now_in_tz(tz_name: str) -> datetime:
    """Текущее время в заданном часовом поясе."""
    return datetime.now(tz=get_tz(tz_name))


def today_in_tz(tz_name: str) -> date:
    return now_in_tz(tz_name).date()


def to_utc_str(local_dt: datetime) -> str:
    """Конвертирует aware datetime в UTC ISO-строку для хранения в БД."""
    return local_dt.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%S")


def from_utc_str(utc_str: str, tz_name: str) -> datetime:
    """Читает UTC ISO-строку из БД и переводит в локальное время пользователя."""
    utc_dt = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.utc)
    return utc_dt.astimezone(get_tz(tz_name))


def parse_time_arg(time_str: str, ref_date: date, tz_name: str) -> Optional[datetime]:
    """
    Разбирает строку вида 'ЧЧ:ММ' и возвращает aware datetime
    для ref_date в tz_name. Возвращает None при ошибке.
    """
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M").time()
        tz = get_tz(tz_name)
        naive = datetime.combine(ref_date, t)
        return tz.localize(naive)
    except ValueError:
        return None


def format_duration(td: timedelta) -> str:
    """Форматирует timedelta в строку 'Ч:ММ', поддерживает отрицательные значения."""
    negative = td.total_seconds() < 0
    total_seconds = abs(int(td.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    sign = "−" if negative else ""
    return f"{sign}{hours}:{minutes:02d}"


def get_week_workdays(ref_date: date) -> list[date]:
    """
    Возвращает список рабочих дней (пн–пт) с начала текущей недели
    до ref_date НЕ включая ref_date.
    """
    monday = ref_date - timedelta(days=ref_date.weekday())
    days = []
    current = monday
    while current < ref_date:
        if current.weekday() < 5:  # пн=0 ... пт=4
            days.append(current)
        current += timedelta(days=1)
    return days


def calculate_day_worked(session: dict, tz_name: str) -> Optional[timedelta]:
    """
    Возвращает отработанное время за день.
    None если нет check_in или check_out.
    """
    if not session.get("check_in") or not session.get("check_out"):
        return None
    ci = from_utc_str(session["check_in"], tz_name)
    co = from_utc_str(session["check_out"], tz_name)
    delta = co - ci
    return delta if delta.total_seconds() > 0 else timedelta(0)


def calculate_remaining_today(session: dict, tz_name: str) -> Optional[timedelta]:
    """
    Считает, сколько ещё нужно отработать сегодня.
    Отрицательное значение = переработка.
    Возвращает None если нет check_in.
    """
    if not session.get("check_in"):
        return None
    ci = from_utc_str(session["check_in"], tz_name)
    now = now_in_tz(tz_name)
    worked = now - ci
    remaining = WORK_DAY_DURATION - worked
    return remaining
