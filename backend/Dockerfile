FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libgomp нужен LightGBM/XGBoost и scikit-learn (OpenMP)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY experiments ./experiments

# /models — точка монтирования общего тома с моделью: каталог создаётся заранее с владельцем appuser,
# чтобы том унаследовал права и сервисы обучения могли записывать артефакт.
RUN useradd --create-home appuser && mkdir -p /app/models /app/data /models && chown -R appuser /app /models
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
