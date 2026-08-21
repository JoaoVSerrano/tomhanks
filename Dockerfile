FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY backend ./backend
COPY backend/static ./backend/static

COPY start.sh ./
RUN chmod +x start.sh

EXPOSE 5000

CMD ["./start.sh"]
