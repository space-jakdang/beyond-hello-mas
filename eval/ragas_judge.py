"""RAGAS adapter whose every paid completion uses the existing durable LLM ledger."""
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
os.environ.setdefault('RAGAS_DO_NOT_TRACK','true')
from langchain_core.outputs import Generation, LLMResult
from ragas.llms.base import BaseRagasLLM
from ragas.run_config import RunConfig
from openai import OpenAI
from backend.agents.llm import Agents
from backend.app.contracts import Run
from backend.tools.indicators import digest


class JudgeStopped(ValueError):
    """Terminal budget/provider failure; remaining paid work must not retry."""


class BudgetedJudge(BaseRagasLLM):
    def __init__(self, store, settings, other_ledgers=(), client_factory=OpenAI):
        super().__init__(run_config=RunConfig(max_retries=1,timeout=settings.llm_timeout_seconds))
        if settings.llm_mode!='live' or not all((settings.openai_api_key,settings.openai_model,settings.llm_budget_usd,
            settings.input_usd_per_million,settings.output_usd_per_million,settings.price_version)):
            raise ValueError('judge requires live model and verified budget/prices')
        self.store,self.settings,self.client_factory=store,settings,client_factory
        self.other_ledgers=tuple({Path(p).resolve() for p in other_ledgers}-{store.path.resolve()})
        Agents(store,settings)  # Reuse the established llm_calls schema.
        self.stopped=False
        self.run_id=str(uuid4())
        store.create_run(Run(id=self.run_id,thread_id=self.run_id,scenario_id='quality-ragas-judge',status='running',
            data_mode=settings.data_mode,llm_mode='live',input_version='ragas-0.4.3',rule_version='quality-6',
            model_version=settings.openai_model,prompt_version='ragas-0.4.3',catalog_version='not_applicable',started_at=datetime.now(timezone.utc)))

    def external_reserved(self):
        total=0.0
        for path in self.other_ledgers:
            if not path.is_file():raise ValueError('historical ledger missing')
            try:
                with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                    total+=db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]
            except sqlite3.Error:
                raise ValueError('historical ledger unreadable') from None
        return total

    def generate_text(self,prompt,n=1,temperature=0.01,stop=None,callbacks=None):
        if self.stopped:raise JudgeStopped('judge stopped after terminal failure')
        if n!=1 or stop:raise ValueError('judge only supports single completion without stop override')
        text=prompt.to_string();settings=self.settings
        size=len(text.encode())
        if size>settings.llm_max_input_bytes:raise ValueError('judge input budget exceeded')
        key=digest({'prompt':text,'model':settings.openai_model,'ragas':'0.4.3'})
        reserve=((size+8192)*settings.input_usd_per_million+settings.llm_max_output_tokens*settings.output_usd_per_million)/1e6
        with self.store.connection(write=True) as db:
            old=db.execute('SELECT status,body FROM llm_calls WHERE run_id=? AND call_key=?',(self.run_id,key)).fetchone()
            if old:
                if old['status']!='ok':raise ValueError('previous judge call unresolved or failed')
                return LLMResult(generations=[[Generation(text=json.loads(old['body'])['output'])]])
            count,spent=db.execute('SELECT COUNT(*),COALESCE(SUM(reserve_usd),0) FROM llm_calls WHERE run_id=?',(self.run_id,)).fetchone()
            total=db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]+self.external_reserved()
            if count>=settings.llm_max_calls or total+reserve>settings.llm_budget_usd or (settings.llm_run_budget_usd is not None and spent+reserve>settings.llm_run_budget_usd):
                self.stopped=True
                raise JudgeStopped('judge call or cumulative cost budget exceeded')
            db.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?,?)',(self.run_id,key,'evaluation_judge','pending',reserve,
                json.dumps({'prompt':text,'model':settings.openai_model,'ragas_version':'0.4.3'})))
        actual=None
        try:
            with self.client_factory(api_key=settings.openai_api_key.get_secret_value(),timeout=settings.llm_timeout_seconds,max_retries=0) as client:
                response=client.responses.create(model=settings.openai_model,input=text,max_output_tokens=settings.llm_max_output_tokens,store=False)
            if response.usage is not None:
                actual=(response.usage.input_tokens*settings.input_usd_per_million+response.usage.output_tokens*settings.output_usd_per_million)/1e6
            if response.status!='completed' or not response.output_text or actual is None:raise ValueError('incomplete judge response')
            body={'prompt':text,'output':response.output_text,'cost_usd':actual,'returned_model':response.model,
                  'usage':response.usage.model_dump(),'price_version':settings.price_version,'ragas_version':'0.4.3'}
            with self.store.connection(write=True) as db:
                db.execute('UPDATE llm_calls SET status=?,body=?,reserve_usd=? WHERE run_id=? AND call_key=?',
                    ('ok',json.dumps(body,ensure_ascii=False),max(reserve,actual),self.run_id,key))
            return LLMResult(generations=[[Generation(text=response.output_text)]])
        except Exception as exc:
            with self.store.connection(write=True) as db:
                db.execute('UPDATE llm_calls SET status=?,body=?,reserve_usd=? WHERE run_id=? AND call_key=?',
                    ('error',json.dumps({'error_type':type(exc).__name__,'cost_usd':actual}),max(reserve,actual or 0),self.run_id,key))
            self.stopped=True
            raise JudgeStopped('judge completion failed: '+type(exc).__name__) from None

    async def agenerate_text(self,prompt,n=1,temperature=0.01,stop=None,callbacks=None):
        return await asyncio.to_thread(self.generate_text,prompt,n,temperature,stop,callbacks)

    def is_finished(self,response):
        return True  # Incomplete provider responses already fail before constructing LLMResult.

    def finish(self,failed=False):
        run=self.store.get_run(self.run_id)
        run.status='failed' if failed else 'completed';run.ended_at=datetime.now(timezone.utc)
        with self.store.connection(write=True) as db:db.execute('UPDATE runs SET body=? WHERE id=?',(run.model_dump_json(),run.id))
