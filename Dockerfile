FROM node:24-alpine AS frontend-build

WORKDIR /app/frontend/front-tom-hanks
COPY frontend/front-tom-hanks/package*.json ./
RUN npm ci
COPY frontend/front-tom-hanks/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY backend ./backend
COPY --from=frontend-build /app/frontend/front-tom-hanks/dist/front-tom-hanks/browser ./backend/static

COPY start.sh ./
RUN chmod +x start.sh

EXPOSE 5000

CMD ["./start.sh"]

