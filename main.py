"""
Telegram-бот для учёта рабочего времени.
Переменные окружения: BOT_TOKEN, DATABASE_PATH, DEFAULT_TIMEZONE
"""

import logging
import re
from datetime import timedelta, date
from typing import Optional

import pytz
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import database as db
from config import BOT_TOKEN, WORK_DAY_DURATION
from utils import (
    WEEKDAY_NAMES,
    WEEKDAY_NAMES_ACCUSATIVE,
    now_in_tz,
    today_in_tz,
    to_utc_str,
    from_utc_str,
    parse_time_arg,
    format_duration,
    get_week_workdays,
    calculate_day_worked,
    calculate_remaining_today,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Состояния диалога заполнения пропущенных дней
FILL_CHECKIN, FILL_CHECKOUT = range(2)

KEY_MISSING_DAYS = "missing_days"
KEY_CURRENT_IDX = "fill_current_idx"
KEY_CURRENT_CI = "fill_checkin_utc"


# ── Утилиты ───────────────────────────────────────────────────────────────────


def _uid(update: Update) -> int:
    return update.effective_user.id


def _tz(update: Update) -> str:
    return db.get_user_timezone(_uid(update))


def _extract_time_arg(args: list[str]) -> Optional[str]:
    if args and re.fullmatch(r"\d{1,2}:\d{2}", args[0]):
        return args[0]
    return None


# ── /start ────────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz_name = _tz(update)
    await update.message.reply_text(
        "Привет! Я веду учёт рабочего времени.\n\n"
        "Команды:\n"
        "  /in [ЧЧ:ММ] — пришёл на работу\n"
        "  /out [ЧЧ:ММ] — ушёл с работы\n"
        "  /today — сколько осталось сегодня\n"
        "  /week — статистика за неделю\n"
        f"  /timezone <зона> — сменить часовой пояс (сейчас: {tz_name})\n\n"
        f"Норма: {format_duration(WORK_DAY_DURATION)} в день."
    )


# ── /timezone ─────────────────────────────────────────────────────────────────


async def cmd_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        current = _tz(update)
        await update.message.reply_text(
            f"Текущий часовой пояс: {current}\n"
            "Чтобы изменить: /timezone Europe/Moscow"
        )
        return
    tz_name = context.args[0]
    try:
        pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        await update.message.reply_text(
            f"Неизвестный часовой пояс: {tz_name}\n"
            "Примеры: Europe/Moscow, Asia/Yekaterinburg, UTC"
        )
        return
    db.set_user_timezone(_uid(update), tz_name)
    await update.message.reply_text(f"✅ Часовой пояс установлен: {tz_name}")


# ── /in ───────────────────────────────────────────────────────────────────────


async def cmd_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _uid(update)
    tz_name = _tz(update)
    today = today_in_tz(tz_name)

    time_arg = _extract_time_arg(context.args or [])
    if time_arg:
        check_in_dt = parse_time_arg(time_arg, today, tz_name)
        if not check_in_dt:
            await update.message.reply_text("Неверный формат. Пример: /in 09:00")
            return
    else:
        check_in_dt = now_in_tz(tz_name)

    existing = db.get_session(uid, today.isoformat())
    if existing and existing.get("check_in"):
        old = from_utc_str(existing["check_in"], tz_name).strftime("%H:%M")
        await update.message.reply_text(
            f"Уже был приход в {old}. Обновляю на {check_in_dt.strftime('%H:%M')}."
        )

    db.upsert_check_in(uid, today.isoformat(), to_utc_str(check_in_dt))
    await update.message.reply_text(
        f"✅ Приход: {check_in_dt.strftime('%H:%M')}. Удачного дня!"
    )


# ── /out ──────────────────────────────────────────────────────────────────────


async def cmd_out(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _uid(update)
    tz_name = _tz(update)
    today = today_in_tz(tz_name)

    session = db.get_session(uid, today.isoformat())
    if not session or not session.get("check_in"):
        await update.message.reply_text("Сначала отметь приход: /in")
        return

    time_arg = _extract_time_arg(context.args or [])
    if time_arg:
        check_out_dt = parse_time_arg(time_arg, today, tz_name)
        if not check_out_dt:
            await update.message.reply_text("Неверный формат. Пример: /out 18:30")
            return
    else:
        check_out_dt = now_in_tz(tz_name)

    ci_dt = from_utc_str(session["check_in"], tz_name)
    if check_out_dt <= ci_dt:
        await update.message.reply_text(
            f"Время ухода ({check_out_dt.strftime('%H:%M')}) "
            f"раньше прихода ({ci_dt.strftime('%H:%M')}). Проверь данные."
        )
        return

    db.upsert_check_out(uid, today.isoformat(), to_utc_str(check_out_dt))
    worked = check_out_dt - ci_dt
    diff = worked - WORK_DAY_DURATION

    if diff.total_seconds() >= 0:
        diff_str = f"переработка {format_duration(diff)}"
    else:
        diff_str = f"недоработка {format_duration(abs(diff))}"

    await update.message.reply_text(
        f"✅ Уход: {check_out_dt.strftime('%H:%M')}.\n"
        f"Отработано: {format_duration(worked)} ({diff_str})."
    )


# ── /today ────────────────────────────────────────────────────────────────────


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _uid(update)
    tz_name = _tz(update)
    today = today_in_tz(tz_name)

    session = db.get_session(uid, today.isoformat())
    if not session or not session.get("check_in"):
        await update.message.reply_text("Сегодня приход не отмечен. Используй /in")
        return

    ci_dt = from_utc_str(session["check_in"], tz_name)

    if session.get("check_out"):
        co_dt = from_utc_str(session["check_out"], tz_name)
        worked = co_dt - ci_dt
        diff = worked - WORK_DAY_DURATION
        if diff.total_seconds() >= 0:
            label = f"переработка {format_duration(diff)}"
        else:
            label = f"недоработка {format_duration(abs(diff))}"
        await update.message.reply_text(
            f"День завершён.\n"
            f"Приход: {ci_dt.strftime('%H:%M')}\n"
            f"Уход: {co_dt.strftime('%H:%M')}\n"
            f"Отработано: {format_duration(worked)} ({label})"
        )
    else:
        now_dt = now_in_tz(tz_name)
        worked_so_far = now_dt - ci_dt
        remaining = WORK_DAY_DURATION - worked_so_far

        if remaining.total_seconds() > 0:
            finish_dt = now_dt + remaining
            await update.message.reply_text(
                f"Приход: {ci_dt.strftime('%H:%M')}\n"
                f"Отработано: {format_duration(worked_so_far)}\n"
                f"Осталось: {format_duration(remaining)}\n"
                f"Можно уходить в: {finish_dt.strftime('%H:%M')}"
            )
        else:
            await update.message.reply_text(
                f"Приход: {ci_dt.strftime('%H:%M')}\n"
                f"Отработано: {format_duration(worked_so_far)}\n"
                f"Переработка: {format_duration(abs(remaining))} — можно уходить!"
            )


# ── /week и диалог заполнения пропусков ───────────────────────────────────────


async def _show_week_stats(
    update: Update,
    uid: int,
    tz_name: str,
    workdays: list[date],
    sessions_by_date: dict[str, dict],
) -> None:
    """Формирует и отправляет итоговую статистику за неделю."""
    lines = []
    total_worked = timedelta(0)
    total_norm = WORK_DAY_DURATION * len(workdays)

    for d in workdays:
        s = sessions_by_date.get(d.isoformat())
        day_name = WEEKDAY_NAMES[d.weekday()].capitalize()

        if s and s.get("check_in") and s.get("check_out"):
            worked = calculate_day_worked(s, tz_name)
            total_worked += worked
            ci_str = from_utc_str(s["check_in"], tz_name).strftime("%H:%M")
            co_str = from_utc_str(s["check_out"], tz_name).strftime("%H:%M")
            diff = worked - WORK_DAY_DURATION
            if diff.total_seconds() >= 0:
                mark = f"+{format_duration(diff)}"
            else:
                mark = f"-{format_duration(abs(diff))}"
            lines.append(
                f"  {day_name} {d.strftime('%d.%m')}: "
                f"{ci_str}–{co_str} = {format_duration(worked)} ({mark})"
            )
        else:
            lines.append(f"  {day_name} {d.strftime('%d.%m')}: нет данных")

    diff_total = total_worked - total_norm
    if diff_total.total_seconds() >= 0:
        summary = f"Переработка за неделю: +{format_duration(diff_total)}"
    else:
        summary = f"Недоработка за неделю: -{format_duration(abs(diff_total))}"

    header = "📊 Статистика за неделю (без учёта сегодня):\n"
    footer = (
        f"\nОтработано: {format_duration(total_worked)} "
        f"из {format_duration(total_norm)}\n{summary}"
    )
    await update.message.reply_text(header + "\n".join(lines) + footer)


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = _uid(update)
    tz_name = _tz(update)
    today = today_in_tz(tz_name)
    workdays = get_week_workdays(today)

    if not workdays:
        await update.message.reply_text(
            "Сегодня понедельник — данных за прошлые дни ещё нет.\n"
            "Используй /today для текущего дня."
        )
        return ConversationHandler.END

    sessions_by_date = {
        s["work_date"]: s
        for s in db.get_sessions_range(
            uid, workdays[0].isoformat(), workdays[-1].isoformat()
        )
    }

    missing_days = []
    for d in workdays:
        s = sessions_by_date.get(d.isoformat())
        if not s or not s.get("check_in") or not s.get("check_out"):
            missing_days.append(d)

    if missing_days:
        context.user_data[KEY_MISSING_DAYS] = missing_days
        context.user_data[KEY_CURRENT_IDX] = 0
        return await _ask_checkin(update, context)

    await _show_week_stats(update, uid, tz_name, workdays, sessions_by_date)
    return ConversationHandler.END


async def _ask_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    missing = context.user_data[KEY_MISSING_DAYS]
    idx = context.user_data[KEY_CURRENT_IDX]
    day = missing[idx]
    day_name = WEEKDAY_NAMES_ACCUSATIVE[day.weekday()]
    await update.message.reply_text(
        f"Нет данных за {day_name} {day.strftime('%d.%m')}.\n"
        f"Введи время прихода (ЧЧ:ММ):"
    )
    return FILL_CHECKIN


async def fill_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    uid = _uid(update)
    tz_name = _tz(update)
    missing = context.user_data[KEY_MISSING_DAYS]
    idx = context.user_data[KEY_CURRENT_IDX]
    day = missing[idx]

    dt = parse_time_arg(text, day, tz_name)
    if not dt:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ, например 09:00:")
        return FILL_CHECKIN

    utc_str = to_utc_str(dt)
    db.upsert_check_in(uid, day.isoformat(), utc_str)
    context.user_data[KEY_CURRENT_CI] = utc_str

    await update.message.reply_text(
        f"Принято: приход {text}. Теперь введи время ухода (ЧЧ:ММ):"
    )
    return FILL_CHECKOUT


async def fill_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    uid = _uid(update)
    tz_name = _tz(update)
    missing = context.user_data[KEY_MISSING_DAYS]
    idx = context.user_data[KEY_CURRENT_IDX]
    day = missing[idx]

    dt = parse_time_arg(text, day, tz_name)
    if not dt:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ, например 18:00:")
        return FILL_CHECKOUT

    ci_dt = from_utc_str(context.user_data[KEY_CURRENT_CI], tz_name)
    if dt <= ci_dt:
        await update.message.reply_text(
            f"Уход ({text}) раньше прихода ({ci_dt.strftime('%H:%M')}). Повтори:"
        )
        return FILL_CHECKOUT

    db.upsert_check_out(uid, day.isoformat(), to_utc_str(dt))

    idx += 1
    context.user_data[KEY_CURRENT_IDX] = idx

    if idx < len(missing):
        return await _ask_checkin(update, context)

    # Все пропуски заполнены — показываем статистику
    today = today_in_tz(tz_name)
    workdays = get_week_workdays(today)
    sessions_by_date = {
        s["work_date"]: s
        for s in db.get_sessions_range(
            uid, workdays[0].isoformat(), workdays[-1].isoformat()
        )
    }
    await _show_week_stats(update, uid, tz_name, workdays, sessions_by_date)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(KEY_MISSING_DAYS, None)
    context.user_data.pop(KEY_CURRENT_IDX, None)
    context.user_data.pop(KEY_CURRENT_CI, None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


# ── Запуск ────────────────────────────────────────────────────────────────────


def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан. Установите переменную окружения.")
        return

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    week_conv = ConversationHandler(
        entry_points=[CommandHandler("week", cmd_week)],
        states={
            FILL_CHECKIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fill_checkin)
            ],
            FILL_CHECKOUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fill_checkout)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("in", cmd_in))
    app.add_handler(CommandHandler("out", cmd_out))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("timezone", cmd_timezone))
    app.add_handler(week_conv)

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
