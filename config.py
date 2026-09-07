import os
from datetime import timedelta

# Токен бота — передаётся через переменную окружения
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

# Путь к базе данных (удобно монтировать volume на этот путь)
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "/data/worktime.db")

# Часовой пояс по умолчанию (пользователь может переопределить через /timezone)
DEFAULT_TIMEZONE: str = os.environ.get("DEFAULT_TIMEZONE", "Europe/Moscow")

# Длительность рабочего дня
WORK_DAY_DURATION: timedelta = timedelta(hours=8, minutes=30)
