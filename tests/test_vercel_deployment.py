from fastapi.testclient import TestClient
import runpy

import pytest

from backend.app import main
from backend.app.config import Settings


def test_production_entrypoint_requires_existing_regional_inputs(tmp_path, monkeypatch):
    from backend.app.config import ROOT
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_ENV', 'production')
    monkeypatch.setenv('DATA_MODE', 'sample')
    monkeypatch.setenv('RUNTIME_STORAGE_ROOT', str(tmp_path / 'state'))
    monkeypatch.delenv('RUNTIME_INPUT_PACKAGE', raising=False)
    with pytest.raises(ValueError, match='RUNTIME_INPUT_PACKAGE'):
        runpy.run_path(str(ROOT / 'app.py'))


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


def test_api_404_works_before_frontend_build(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    app = main.create_app(Settings(_env_file=None, llm_mode="fake"))

    with TestClient(app) as client:
        assert client.get("/not-an-api-route").status_code == 404


def test_external_data_and_runtime_directories(tmp_path):
    from backend.app.readiness import inspect
    import shutil
    from backend.app.config import ROOT
    shutil.copytree(ROOT / 'data/sample', tmp_path / 'inputs/sample')
    settings = Settings(_env_file=None, data_mode='sample', llm_mode='fake',
                        input_root=tmp_path / 'inputs', runtime_storage_root=tmp_path / 'state')
    assert settings.data_dir == tmp_path / 'inputs/sample'
    assert settings.runtime_dir == tmp_path / 'state/sample'
    report = inspect(settings)
    assert report['ready'] and report['analysis']['geometry'] == 'synthetic_grid'
    assert report['warnings'] and not report['durability_verified']
    assert str(tmp_path) not in str(report)


def test_missing_real_data_never_falls_back_to_synthetic(tmp_path, monkeypatch):
    from backend.app.readiness import inspect
    monkeypatch.setenv('VERCEL', '1')
    settings = Settings(_env_file=None, data_mode='local', llm_mode='fake', input_root=tmp_path)
    report = inspect(settings)
    assert not report['ready']
    assert report['data_mode'] == 'local' and report['analysis']['status'] == 'unavailable'
    assert report['storage'] == 'temporary_instance'
    assert 'synthetic_grid' not in str(report)
    assert str(tmp_path) not in str(report)
