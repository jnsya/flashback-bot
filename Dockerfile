FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY flashback_bot/ flashback_bot/

RUN pip install --no-cache-dir .

COPY entrypoint.sh .

CMD ["sh", "entrypoint.sh"]
