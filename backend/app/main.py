import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from backend.app.config import ROOT, Settings
from backend.events import EventStore
from backend.graph import GraphService
from backend.app.graph_routes import graph_router
from backend.app.event_routes import event_router
from backend.app.report_routes import report_router
from backend.app.analysis_routes import analysis_router
from backend.app.policy_routes import policy_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = EventStore(settings.runtime_dir / "events.sqlite3", settings.data_mode)
    service = GraphService(store, settings)
    from backend.app.quality_jobs import QualityJobs, quality_job_router
    quality_jobs=QualityJobs(store,settings)

    @asynccontextmanager
    async def lifespan(app):
        quality_jobs.recover()
        recovery = asyncio.create_task(asyncio.to_thread(service.recover))
        yield
        await recovery

    app = FastAPI(title="Beyond Hello MAS", version="0.1.0", lifespan=lifespan)
    app.state.graph = service
    app.include_router(graph_router(service))
    from backend.regional_batch import router as batch_router
    app.include_router(batch_router(service))
    from backend.policy.review import policy_review_router
    app.include_router(policy_review_router(store))
    from backend.policy.alternative_export import router as alternative_export_router
    app.include_router(alternative_export_router(store))
    from backend.app.alternative_quality import router as alternative_quality_router
    app.include_router(alternative_quality_router(store))
    from backend.policy.alternative_review import router as alternative_review_router
    from backend.policy.alternative_regeneration import router as regeneration_router
    app.include_router(alternative_review_router(store))
    app.include_router(regeneration_router(service))
    from backend.policy.alternatives import router as alternatives_router
    app.include_router(alternatives_router(store))
    from backend.future import future_router
    app.include_router(future_router(service))
    app.state.store = store
    app.include_router(event_router(store))
    app.include_router(report_router(settings))
    app.include_router(quality_job_router(quality_jobs))
    app.include_router(analysis_router(settings))
    from backend.app.readiness import readiness_router
    app.include_router(readiness_router(settings))
    app.include_router(policy_router(settings))
    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.frontend("/", directory=frontend_dist, fallback="index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "data_mode": settings.data_mode,
                "llm_mode": settings.llm_mode, "capabilities": ["foundation"]}

    return app
