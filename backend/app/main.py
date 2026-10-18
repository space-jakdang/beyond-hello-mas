from fastapi import FastAPI
from backend.app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Beyond Hello MAS", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "data_mode": settings.data_mode,
                "llm_mode": settings.llm_mode, "capabilities": ["foundation"]}

    return app
