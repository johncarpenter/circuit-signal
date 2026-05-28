from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from circuit_api.config import settings
from circuit_api.routes import datasets, deviations, runs, signals, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    from circuit_api.services.storage import storage
    await storage.ensure_bucket()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Circuit Signal",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router, prefix="/api", tags=["system"])
    app.include_router(datasets.router, prefix="/api", tags=["datasets"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(signals.router, prefix="/api", tags=["signals"])
    app.include_router(deviations.router, prefix="/api", tags=["deviations"])

    from circuit_api import ws
    app.include_router(ws.router)

    return app


app = create_app()
