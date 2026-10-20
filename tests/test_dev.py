from types import SimpleNamespace
import argparse
import pytest
from scripts.dev import environment, port


def test_live_preflight_keeps_ledger_and_does_not_fallback(monkeypatch):
    from backend.app import config
    from backend.tools import neighborhoods, catalog
    checked=[]
    settings=SimpleNamespace(evaluation_id=None,openai_model='configured',llm_budget_usd=20,
        input_usd_per_million=1,output_usd_per_million=1,price_version='configured',
        gov24_service_key=SimpleNamespace(get_secret_value=lambda:'configured'),catalog_path='existing')
    def make_settings(**kwargs):
        assert kwargs==dict(data_mode='local',llm_mode='live',resource_catalog='v3')
        return settings
    monkeypatch.setattr(config,'Settings',make_settings)
    monkeypatch.setattr(neighborhoods,'group_analysis',lambda s:checked.append('real-input'))
    monkeypatch.setattr(catalog,'load_catalog',lambda p:checked.append(p))
    env=environment(True,8002)
    assert checked==['real-input','existing']
    assert env['DATA_MODE']=='local' and env['LLM_MODE']=='live' and env['RESOURCE_CATALOG']=='v3'
    assert env['VITE_API_TARGET']=='http://127.0.0.1:8002'
    settings.evaluation_id='isolated-ledger'
    with pytest.raises(ValueError,match='existing local ledger'):environment(True,8002)
    settings.evaluation_id=None
    settings.gov24_service_key=None
    with pytest.raises(ValueError,match='GOV24_SERVICE_KEY'):environment(True,8002)
    settings.gov24_service_key=SimpleNamespace(get_secret_value=lambda:'configured')
    settings.llm_budget_usd=0
    with pytest.raises(ValueError,match='model, budget'):environment(True,8002)
    settings.llm_budget_usd=20
    def absent(_):raise FileNotFoundError('missing input')
    monkeypatch.setattr(neighborhoods,'group_analysis',absent)
    with pytest.raises(FileNotFoundError):environment(True,8002)


def test_sample_mode_is_explicitly_preserved(monkeypatch):
    monkeypatch.setenv('DATA_MODE','sample');monkeypatch.setenv('LLM_MODE','fake')
    env=environment(False,8003)
    assert env['DATA_MODE']=='sample' and env['LLM_MODE']=='fake'
    assert port('5176')==5176
    with pytest.raises(argparse.ArgumentTypeError):port('65536')


def test_colliding_ports_fail_before_start(monkeypatch):
    from scripts import dev
    monkeypatch.setattr('sys.argv',['dev','--api-port','8002','--ui-port','8002'])
    monkeypatch.setattr(dev,'environment',lambda *args:pytest.fail('preflight should not run'))
    with pytest.raises(SystemExit) as error:dev.main()
    assert error.value.code==2
