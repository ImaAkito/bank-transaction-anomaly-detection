"""Точка входа серверной части: REST API и WebSocket."""
import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, clients, system, transactions
from app.api.auth import ensure_admin
from app.config import get_settings
from app.db import init_db, session_factory
from app.security import read_token
from app.services.container import build_event_bus, build_queue, make_redis
from app.services.events import ConnectionManager, redis_listener
from app.services.logging_config import request_id_var, setup_logging
from app.services.pipeline import AnalysisService, ModelStore

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    init_db()
    if settings.auth_enabled:
        db = session_factory()()
        try:
            ensure_admin(db, settings.admin_username, settings.admin_password)
        finally:
            db.close()

    manager = ConnectionManager()
    manager.attach_loop(asyncio.get_running_loop())
    redis_client = make_redis(settings) if settings.queue_backend == "redis" else None
    model_store = ModelStore(settings.model_path, settings.model_reload_check_seconds)
    model_store.try_load()
    service = AnalysisService(settings, model_store, build_event_bus(settings, manager, redis_client))
    queue = build_queue(settings, service, redis_client)

    app.state.settings = settings
    app.state.manager = manager
    app.state.model_store = model_store
    app.state.service = service
    app.state.queue = queue

    listener = None
    if settings.queue_backend == "redis":
        listener = asyncio.create_task(redis_listener(settings, manager))
    else:
        queue.start()
    log.info("Сервис запущен (очередь: %s)", settings.queue_backend)
    try:
        yield
    finally:
        if listener:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        else:
            queue.stop()


app = FastAPI(
    title="Система выявления аномальных банковских транзакций",
    description="Оценка степени аномальности операций с учётом динамического профиля клиента. "
    "Результат модели является аналитической оценкой для специалиста и не означает установленного мошенничества.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["x-request-id"] = request_id
    return response


app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(clients.router)
app.include_router(system.router)


@app.websocket("/ws/transactions")
async def transactions_stream(websocket: WebSocket):
    """Поток результатов анализа в реальном времени."""
    manager: ConnectionManager = websocket.app.state.manager
    settings = websocket.app.state.settings
    if settings.auth_enabled:
        # Браузер не передаёт заголовки в WebSocket, поэтому токен приходит параметром ?token=...
        principal = read_token(websocket.query_params.get("token", ""), settings.auth_secret)
        if principal is None:
            await websocket.close(code=4401)
            return
    await manager.connect(websocket)
    try:
        while True:
            # Входящие сообщения (ping от клиента) игнорируются; чтение нужно для обнаружения разрыва.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
