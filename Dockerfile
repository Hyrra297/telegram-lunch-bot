FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway/Render inject PORT automatically; default to 8080
ENV PORT=8080

# Data directory for SQLite persistent volume
RUN mkdir -p /data
ENV DB_PATH=/data/lunch_bot.db

EXPOSE 8080

CMD ["python", "main.py"]
