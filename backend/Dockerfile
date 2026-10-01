# libgomp (OpenMP) нужен LightGBM. Берём его из полного образа той же версии Python/Debian, а не через apt:
# сборка не зависит от доступа к репозиториям Debian, финальный образ остаётся slim.
FROM python:3.11 AS runtime-libs
RUN mkdir -p /out && cp /usr/lib/*-linux-gnu/libgomp.so.1 /out/

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=runtime-libs /out/libgomp.so.1 /usr/local/lib/libgomp.so.1
RUN ldconfig

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
