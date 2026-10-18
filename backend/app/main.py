from fastapi import FastAPI
from backend.app.config import Settings
from backend.events import EventStore
from backend.app.event_routes import event_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Beyond Hello MAS", version="0.1.0")

    store = EventStore(settings.runtime_dir / "events.sqlite3", settings.data_mode)
    app.state.store = store
    app.include_router(event_router(store))

    @app.get("/health")
    def health():
        return {"status": "ok", "data_mode": settings.data_mode,
                "llm_mode": settings.llm_mode, "capabilities": ["foundation"]}

    return app
