from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.metrics import PrometheusMiddleware, mark_worker_dead
from app.core.metrics import router as metrics_router
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware

settings = get_settings()
configure_logging(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    mark_worker_dead()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

# Added first so it runs inside CORS: 500s produced here keep CORS headers.
app.add_middleware(RequestContextMiddleware)
# Outside RequestContextMiddleware so the final status of unhandled errors is recorded.
app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", REQUEST_ID_HEADER],
)

register_exception_handlers(app)

app.include_router(api_router)
app.include_router(metrics_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
