import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from backend.app.config import Settings
from backend.events import EventStore
from backend.graph import GraphService
from backend.app.graph_routes import graph_router
from backend.app.event_routes import event_router
from backend.app.report_routes import report_router
from backend.app.analysis_routes import analysis_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = EventStore(settings.runtime_dir / "events.sqlite3", settings.data_mode)
    service = GraphService(store, settings)

    @asynccontextmanager
    async def lifespan(app):
        recovery = asyncio.create_task(asyncio.to_thread(service.recover))
        yield
        await recovery

    app = FastAPI(title="Beyond Hello MAS", version="0.1.0", lifespan=lifespan)
    app.state.graph = service
    app.include_router(graph_router(service))
    app.state.store = store
    app.include_router(event_router(store))
    app.include_router(report_router(settings))
    app.include_router(analysis_router(settings))

    @app.get("/health")
    def health():
        return {"status": "ok", "data_mode": settings.data_mode,
                "llm_mode": settings.llm_mode, "capabilities": ["foundation"]}

    return app
