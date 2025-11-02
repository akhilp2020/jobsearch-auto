FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

CMD ["uvicorn", "notify_svc.main:app", "--host", "0.0.0.0", "--port", "8000"]
