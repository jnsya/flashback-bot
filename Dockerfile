FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY flashback_bot/ flashback_bot/

RUN pip install --no-cache-dir .

CMD ["python", "-m", "flashback_bot.main"]
