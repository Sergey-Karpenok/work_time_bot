FROM python:3.11-slim

WORKDIR /app

# Зависимости отдельным слоем — при изменении кода не пересобирается
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходники
COPY config.py database.py utils.py main.py ./

# Директория для SQLite — монтируй сюда volume чтобы данные пережили перезапуск
VOLUME ["/data"]

ENTRYPOINT ["python", "main.py"]
