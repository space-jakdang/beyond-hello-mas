import asyncio
import json
from types import SimpleNamespace
import pytest
from importlib.util import find_spec
if find_spec('ragas') is None:pytest.skip('evaluation extra not installed',allow_module_level=True)
from langchain_core.prompt_values import StringPromptValue
from eval.ragas_judge import BudgetedJudge
from backend.events import EventStore
from backend.app.config import Settings


class Usage:
    input_tokens=100
    output_tokens=50
    def model_dump(self):return {'input_tokens':100,'output_tokens':50}


class Client:
    calls=0
    def __init__(self,**kwargs):self.responses=self;assert kwargs['max_retries']==0
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def create(self,**kwargs):
        Client.calls+=1
        prompt=kwargs['input']
        output={'statements':[{'statement':'전화 지원','reason':'근거와 일치','verdict':1}]} if 'verdict' in prompt else {'statements':['전화 지원']}
        return SimpleNamespace(usage=Usage(),status='completed',output_text=json.dumps(output),model='test-judge')


def setup(tmp_path,**kwargs):
    settings=Settings(_env_file=None,llm_mode='live',openai_api_key='test-only',openai_model='test-judge',llm_budget_usd=1,
        input_usd_per_million=1,output_usd_per_million=1,price_version='fixture',**kwargs)
    store=EventStore(tmp_path/'events.sqlite3')
    return store,settings


def test_every_completion_is_reserved_cached_and_call_limited(tmp_path):
    Client.calls=0;store,settings=setup(tmp_path,llm_max_calls=1)
    judge=BudgetedJudge(store,settings,client_factory=Client)
    prompt=StringPromptValue(text='one')
    judge.generate_text(prompt);judge.generate_text(prompt)
    assert Client.calls==1
    with pytest.raises(ValueError,match='budget'):judge.generate_text(StringPromptValue(text='different'))
    with store.connection() as db:
        row=db.execute('SELECT status,reserve_usd,body FROM llm_calls').fetchone()
    assert row['status']=='ok' and row['reserve_usd']>=json.loads(row['body'])['cost_usd']
    judge.finish();assert store.get_run(judge.run_id).status=='completed'


def test_real_ragas_metric_uses_guarded_adapter(tmp_path):
    from ragas import SingleTurnSample
    from ragas.metrics import Faithfulness
    Client.calls=0;store,settings=setup(tmp_path)
    judge=BudgetedJudge(store,settings,client_factory=Client)
    sample=SingleTurnSample(user_input='무슨 지원?',response='전화 지원',retrieved_contexts=['전화 지원'])
    assert asyncio.run(Faithfulness(llm=judge).single_turn_ascore(sample))==1
    assert Client.calls==2


def test_historical_ledger_and_provider_failure_are_not_success(tmp_path):
    store,settings=setup(tmp_path/'old');old=BudgetedJudge(store,settings,client_factory=Client)
    old.generate_text(StringPromptValue(text='paid'))
    with store.connection(write=True) as db:db.execute('UPDATE llm_calls SET reserve_usd=1')
    newer,_=setup(tmp_path/'new');judge=BudgetedJudge(newer,settings,[store.path],client_factory=Client)
    with pytest.raises(ValueError,match='budget'):judge.generate_text(StringPromptValue(text='another'))
    class Broken(Client):
        def create(self,**kwargs):raise RuntimeError('private provider body')
    safe,_=setup(tmp_path/'failure');failed=BudgetedJudge(safe,settings,client_factory=Broken)
    with pytest.raises(ValueError,match='RuntimeError'):failed.generate_text(StringPromptValue(text='failure'))
    with safe.connection() as db:
        row=db.execute('SELECT status,body,reserve_usd FROM llm_calls').fetchone()
    assert row['status']=='error' and row['reserve_usd']>0 and 'private provider body' not in row['body']


def test_provider_failure_stops_remaining_paid_calls(tmp_path):
    class Broken(Client):
        calls=0
        def create(self,**kwargs):
            Broken.calls+=1
            raise RuntimeError('private')
    store,settings=setup(tmp_path);judge=BudgetedJudge(store,settings,client_factory=Broken)
    for text in ('first','next'):
        with pytest.raises(ValueError):judge.generate_text(StringPromptValue(text=text))
    assert Broken.calls==1
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM llm_calls').fetchone()[0]==1


def test_unreadable_history_fails_closed(tmp_path):
    import sqlite3
    history=tmp_path/'empty.sqlite3'
    sqlite3.connect(history).close()
    store,settings=setup(tmp_path/'current')
    judge=BudgetedJudge(store,settings,[history],client_factory=Client)
    with pytest.raises(ValueError,match='historical ledger unreadable'):
        judge.generate_text(StringPromptValue(text='not paid'))
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM llm_calls').fetchone()[0]==0
