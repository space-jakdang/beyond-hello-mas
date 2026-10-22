from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import Settings


def test_vercel_runtime_uses_writable_temporary_directory(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    settings = Settings(_env_file=None, data_mode="sample", llm_mode="fake")

    assert settings.runtime_dir == settings.runtime_root / "sample"
    assert str(settings.runtime_root).startswith("/tmp/")


def test_frontend_routes_fall_back_to_index(tmp_path, monkeypatch):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>demo</main>")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    app = main.create_app(Settings(_env_file=None, llm_mode="fake"))

    with TestClient(app) as client:
        browser = {"accept": "text/html"}
        assert client.get("/", headers=browser).text == "<main>demo</main>"
        assert client.get("/workspace", headers=browser).text == "<main>demo</main>"
        assert client.get("/health").json()["status"] == "ok"
