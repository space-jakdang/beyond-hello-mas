"""Durable approval graph with Supervisor-delegated policy research. No external notifications."""
from contextlib import contextmanager
from datetime import timedelta
import json
import time
from threading import RLock
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context

from backend.app.contracts import Alert, Approval, Run, Scenario, PersonCase, person_age_group
from backend.agents.llm import Agents
from backend.agents.scale import ScaleAdapter
from backend.agents.person import PersonAdapter
from backend.policy.agent import PolicyAgent, PolicyTask
from backend.events import utcnow
from backend.tools.catalog import load_catalog
from backend.tools.indicators import digest
from backend.tools.matching import MatchRequest, map_intensity, match
from backend.tools.segments import load_segments
from backend.tools.staging import classify


class State(TypedDict, total=False):
    run_id: str
    scenario: dict
    crisis: list[str]
    classification: dict
    proposal: dict
    decision: dict
    question_route: str
    local_action: str


def crisis_evidence(payload):
    if isinstance(payload, dict):
        return sorted({hit for value in payload.values() for hit in crisis_evidence(value)})
    if isinstance(payload, list):
        return sorted({hit for value in payload for hit in crisis_evidence(value)})
    if not isinstance(payload, str):
        return []
    text = payload.replace('죽고 싶지 않', '').replace('자살 예방', '')
    return [phrase for phrase in ('죽고 싶', '목숨을 끊', '자살할', '죽을 거야', '나를 해치고 싶') if phrase in text]


class GraphService:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.agents = Agents(store, settings)
        self.scale = ScaleAdapter(store, settings)
        self.person = PersonAdapter(store, settings)
        self.policy_agent = PolicyAgent(store, settings, self.agents)
        self.locks = {}
        self.lock_guard = RLock()
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workflows (run_id TEXT PRIMARY KEY REFERENCES runs(id), scenario TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id), body TEXT NOT NULL, proposal TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS linkages (run_id TEXT PRIMARY KEY REFERENCES runs(id), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS effects (run_id TEXT NOT NULL REFERENCES runs(id), name TEXT NOT NULL, PRIMARY KEY(run_id,name));
            ''')

    def lock(self, run_id):
        with self.lock_guard:
            return self.locks.setdefault(run_id, RLock())

    def update_run(self, db, run_id, **changes):
        row = db.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        run = Run.model_validate({**json.loads(row['body']), **changes})
        db.execute('UPDATE runs SET body=? WHERE id=?', (run.model_dump_json(), run_id))

    def once(self, db, state, name, kind, payload, agent='system', **metrics):
        inserted = db.execute('INSERT OR IGNORE INTO effects VALUES (?,?)', (state['run_id'], name)).rowcount
        if inserted:
            self.store._trace(db, state['run_id'], state['scenario']['sim_time'], kind, payload, agent, **metrics)

    def node_event(self, state, node, payload, started):
        with self.store.connection(write=True) as db:
            self.once(db, state, node, 'node_end', payload, node, latency_ms=(time.monotonic()-started)*1000)

    def supervisor(self, state):
        started = time.monotonic()
        evidence = crisis_evidence(state['scenario']['payload'])
        self.node_event(state, 'supervisor', {'crisis_rule_version': 'provisional-1', 'evidence': evidence}, started)
        route = None
        if not evidence and state['scenario']['type'] == 'question':
            route = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'route', state['scenario']['payload']).route
        if not evidence and state['scenario']['type'] == 'policy':
            task = PolicyTask.model_validate(state['scenario']['payload'])
            with self.store.connection(write=True) as db:
                self.once(db, state, 'policy-delegation', 'route', {'worker': 'policy', 'task': task.model_dump()}, 'supervisor')
        return {'crisis': evidence, 'question_route': route}

    def classify_node(self, state):
        started = time.monotonic()
        scenario = Scenario.model_validate(state['scenario'])
        if scenario.type == 'admin' or 'person' in scenario.payload:
            person = PersonCase.model_validate(scenario.payload['person'])
            group = person_age_group(person.age)
            if scenario.type == 'admin':
                result = self.person.priority(state['run_id'], scenario.sim_time, group, {**person.features, **person.admin_flags})
                result['screening'] = {'status': 'verified_questions_required', 'external_delivery': False,
                    'message': '검증된 문항을 준비하여 담당자가 선별 질문을 확인해야 합니다.'}
                action = 'screening_requested'
            elif not person.consent or not person.responses_confirmed:
                result = {'status': 'assessment_pending', 'result': None, 'reason': 'consent_and_person_confirmation_required'}
                action = 'human_handoff'
            else:
                result = self.person.assess(state['run_id'], scenario.sim_time, {'age': person.age, 'age_group': group,
                    'responses': person.responses, 'admin_flags': person.admin_flags})
                assessment = result.get('result') or {}
                action = 'human_handoff' if result['status'] != 'assessed' or assessment.get('human_handoff') or assessment.get('crisis') or (group in ('midlife','prime') and assessment.get('stage') == 3) else ''
            result['age_group'] = group
            result['response_category'] = 'human_connection' if action == 'human_handoff' else 'screening' if scenario.type == 'admin' else 'referral'
            self.node_event(state, 'classify', result, started)
            return {'classification': result, 'local_action': action}
        if scenario.type == 'monthly':
            month = scenario.payload.get('ym')
            rows, source = load_segments(self.settings)
            if month not in {r.ym for r in rows}:
                raise ValueError('requested month missing from dataset')
            result = classify(rows)
            result['segments'] = [r for r in result['segments'] if r['ym'] == month]
            result['dongs'] = [r for r in result['dongs'] if r['ym'] == month]
            result['metadata']['source'] = source
            locations = {r.dong_cd: r for r in rows if r.ym == month}
            for dong in result['dongs']:
                row = locations[dong['dong_cd']]
                dong.update(dong_nm=row.dong_nm, x=row.x, y=row.y, crs=row.crs, coordinate_source=row.coordinate_source)
        elif scenario.type in ('case', 'crisis', 'question'):
            result = self.scale.score(state['run_id'], scenario.sim_time, scenario.payload.get('responses'))
            result['stage'] = None
        else:
            raise ValueError('non-crisis question routing is not implemented yet')
        summary_input = {'type': scenario.type, 'text': scenario.payload.get('text', ''),
                         'assessment': result.get('result'), 'aggregate_metadata': result.get('metadata')}
        result['analysis'] = self.agents.call(state['run_id'], scenario.sim_time, 'analysis', summary_input).model_dump()
        self.node_event(state, 'classify', result, started)
        return {'classification': result}

    def match_node(self, state):
        started = time.monotonic()
        result = state['classification']
        assignments = []
        if state['scenario']['type'] == 'monthly':
            resources = load_catalog(self.settings.catalog_path)
            for segment in result['segments']:
                if segment['stage'] is None:
                    assignments.append({**segment, 'recommendations': [], 'reason': 'unassessed'})
                    continue
                low = int(segment['age_band'][:2])
                request = MatchRequest(sgg=segment['dong_cd'][:5], age_min=low,
                    age_max=120 if low == 60 else low+9, needs=['relationship'],
                    intensity=map_intensity(segment['stage']), as_of=utcnow().date())
                recommendation = match(resources, request)
                assignments.append({'ym': segment['ym'], 'dong_cd': segment['dong_cd'], 'age_band': segment['age_band'],
                    'stage': segment['stage'], 'recommendations': recommendation['recommendations'],
                    'shortfall': recommendation['shortfall'], 'metadata': recommendation['metadata']})
        elif result.get('status') == 'assessed':
            payload = state['scenario']['payload']
            labels = {r['label'] for r in result['result'].get('matched', [])}
            needs = set(result.get('analysis', {}).get('needs', ['relationship']))
            if 'person' in payload:
                payload = {**payload, **payload['person']}
            flags = payload.get('admin_flags', {})
            if any(flags.get(k,False) for k in ('arrears_utility','arrears_rent','arrears_loan','hi_premium_unpaid')):needs.add('economic')
            if any(flags.get(k,False) for k in ('arrears_rent','eviction_risk','non_housing')):needs.add('housing')
            if '외로움 고위험군' in labels:
                needs.add('emotional')
            if '사회적 고립 고위험군' in labels:
                needs.add('relationship')
            if needs and payload.get('age') is not None and payload.get('sgg'):
                resources = load_catalog(self.settings.catalog_path)
                request = MatchRequest(sgg=payload['sgg'], age_min=payload['age'], age_max=payload['age'],
                    needs=sorted(needs), intensity='high' if labels else 'low',
                    eligibility=payload.get('eligibility', {}), stage=result['result'].get('stage'),
                    arrears=any(payload.get('admin_flags', {}).get(k,False) for k in ('arrears_utility','arrears_rent','arrears_loan','hi_premium_unpaid')), as_of=utcnow().date())
                assignments.append(match(resources, request))
        candidates = {r['id']: r for assignment in assignments for r in assignment.get('recommendations', [])}
        explanations = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'recommendations',
                                        {'candidates': list(candidates.values())}).model_dump()
        draft = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'draft',
                                {'resource_ids': sorted(candidates), 'assessment': result.get('status')}).model_dump()
        proposal = {'scope': 'monthly_group_allocation' if state['scenario']['type'] == 'monthly' else ('case_referral_plan' if result.get('status') == 'assessed' else 'assessment_followup'),
                    'assignments': assignments, 'assessment': result.get('status'), 'fake': self.settings.llm_mode == 'fake',
                    'explanations': explanations, 'draft': draft,
                    'external_delivery': False, 'scenario_hash': digest(state['scenario'])}
        proposal['snapshot_version'] = digest(proposal)
        self.node_event(state, 'match', {'snapshot_version': proposal['snapshot_version'], 'assignment_count': len(assignments)}, started)
        return {'proposal': proposal}

    def approval_node(self, state):
        started = time.monotonic()
        decision = interrupt({'snapshot_version': state['proposal']['snapshot_version'], 'proposal': state['proposal']})
        self.node_event(state, 'approval', decision, started)
        return {'decision': decision}

    def link_node(self, state):
        started = time.monotonic()
        with self.store.connection(write=True) as db:
            existing = db.execute('SELECT body FROM linkages WHERE run_id=?', (state['run_id'],)).fetchone()
            if existing:
                self.update_run(db, state['run_id'], status='completed', ended_at=json.loads(existing['body'])['created_at'], error=None)
                return {}
            crisis = bool(state.get('crisis'))
            approval = None
            local_action = state.get('local_action', '')
            if not crisis and not local_action:
                row = db.execute('SELECT body FROM approvals WHERE run_id=?', (state['run_id'],)).fetchone()
                approval = Approval.model_validate_json(row['body']) if row else None
                if (not approval or approval.status != 'approved' or
                        approval.snapshot_version != state['proposal']['snapshot_version']):
                    raise ValueError('link requires approval of this exact snapshot')
            now = utcnow()
            kind = 'crisis' if crisis else local_action or state['proposal']['scope']
            local_text = '위기 신호를 담당자가 확인할 로컬 알림' if crisis else ('선별 질문 준비·담당자 확인 요청' if local_action == 'screening_requested' else '개인 판정·응답을 담당자가 확인할 인계 요청')
            linkage = {'run_id': state['run_id'], 'kind': kind,
                       'fake': self.settings.llm_mode == 'fake', 'external_delivery': False, 'created_at': now.isoformat(),
                       'draft': {'text': local_text, 'resource_ids': []} if crisis or local_action else state['proposal']['draft'],
                       'followup_at': None if crisis or local_action else (now + timedelta(days=7)).isoformat(),
                       'snapshot_version': approval.snapshot_version if approval else None}
            db.execute('INSERT INTO linkages VALUES (?,?)', (state['run_id'], json.dumps(linkage)))
            alert = Alert(id=f"link-{state['run_id']}", run_id=state['run_id'],
                approval_id=approval.id if approval else None, type=kind if crisis or local_action else 'linkage_completed',
                status='created', created_at=now)
            db.execute('INSERT INTO alerts(id,run_id,body) VALUES (?,?,?)', (alert.id, alert.run_id, alert.model_dump_json()))
            self.once(db, state, 'link', 'node_end', linkage, 'link', latency_ms=(time.monotonic()-started)*1000)
            self.once(db, state, 'link-alert', 'alert', alert.model_dump(mode='json'))
            self.once(db, state, 'run-end', 'run_end', {'status': 'completed'})
            self.update_run(db, state['run_id'], status='completed', ended_at=now, error=None)
        return {}

    def reject_node(self, state):
        with self.store.connection(write=True) as db:
            self.once(db, state, 'run-end', 'run_end', {'status': 'rejected'})
            self.update_run(db, state['run_id'], status='rejected', ended_at=utcnow(), error=None)
        return {}

    def question_node(self, state):
        route = state['question_route']
        payload = state['scenario']['payload']
        if route == 'history':
            result = {'runs': self.store.list_runs(20)}
        elif route == 'classify':
            result = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'analysis', payload).model_dump()
        elif route == 'match' and payload.get('match_request'):
            result = match(load_catalog(self.settings.catalog_path), MatchRequest.model_validate(payload['match_request']))
        else:
            result = {'review_required': True, 'reason': '담당자 검토 또는 명시적 매칭 조건이 필요합니다.'}
        with self.store.connection(write=True) as db:
            self.once(db, state, 'question-result', 'tool_result', {'route': route, 'result': result}, 'supervisor')
            self.once(db, state, 'run-end', 'run_end', {'status': 'completed'})
            self.update_run(db, state['run_id'], status='completed', ended_at=utcnow(), error=None)
        return {}

    def policy_node(self, state):
        started = time.monotonic()
        # A completed worker result survives a crash before LangGraph checkpoints this node.
        with self.store.connection() as db:
            done = db.execute('SELECT 1 FROM effects WHERE run_id=? AND name=?', (state['run_id'], 'policy')).fetchone()
        if done:return {}
        result = self.policy_agent.run(state['run_id'], state['scenario']['sim_time'], state['scenario']['payload'])
        with self.store.connection(write=True) as db:
            self.once(db, state, 'policy', 'node_end', result, 'policy', latency_ms=(time.monotonic()-started)*1000)
            self.once(db, state, 'run-end', 'run_end', {'status': 'completed'})
            self.update_run(db, state['run_id'], status='completed', ended_at=utcnow(), error=None)
        return {}

    @contextmanager
    def graph(self):
        with SqliteSaver.from_conn_string(str(self.settings.runtime_dir / 'checkpoints.sqlite3')) as saver:
            builder = StateGraph(State)
            for name, action in [('supervisor', self.supervisor), ('classify', self.classify_node), ('match', self.match_node),
                                 ('approval', self.approval_node), ('link', self.link_node), ('reject', self.reject_node), ('question', self.question_node), ('policy', self.policy_node)]:
                builder.add_node(name, action)
            builder.add_edge(START, 'supervisor')
            builder.add_conditional_edges('supervisor', lambda s: 'link' if s['crisis'] else 'policy' if s['scenario']['type'] == 'policy' else ('question' if s.get('question_route') in ('history', 'human', 'classify', 'match') else 'classify'))
            builder.add_conditional_edges('classify', lambda s: 'link' if s.get('local_action') else 'match')
            builder.add_edge('match', 'approval')
            builder.add_conditional_edges('approval', lambda s: 'link' if s['decision']['status'] == 'approved' else 'reject')
            builder.add_edge('link', END)
            builder.add_edge('reject', END)
            builder.add_edge('question', END)
            builder.add_edge('policy', END)
            yield builder.compile(checkpointer=saver)

    def publish_approval(self, state):
        approval = Approval(id=f"approval-{state['run_id']}", run_id=state['run_id'],
                            snapshot_version=state['proposal']['snapshot_version'], status='pending')
        with self.store.connection(write=True) as db:
            if db.execute('SELECT 1 FROM approvals WHERE run_id=?', (state['run_id'],)).fetchone():
                return
            db.execute('INSERT INTO approvals VALUES (?,?,?,?)', (approval.id, approval.run_id, approval.model_dump_json(), json.dumps(state['proposal'])))
            now = utcnow()
            alert = Alert(id=approval.id, run_id=approval.run_id, approval_id=approval.id,
                          type='approval_requested', status='created', created_at=now)
            db.execute('INSERT INTO alerts(id,run_id,body) VALUES (?,?,?)', (alert.id, alert.run_id, alert.model_dump_json()))
            self.once(db, state, 'interrupt', 'interrupt', approval.model_dump(mode='json'), 'approval')
            self.once(db, state, 'approval-alert', 'alert', alert.model_dump(mode='json'))
            self.update_run(db, state['run_id'], status='awaiting_approval')

    def drive(self, run_id, initial=None):
        if self.store.get_run(run_id).llm_mode != self.settings.llm_mode:
            raise ValueError('restore the original LLM_MODE before resuming this run')
        config = {'configurable': {'thread_id': run_id}}
        with self.lock(run_id), self.graph() as graph, tracing_context(enabled=False):
            snapshot = graph.get_state(config)
            with self.store.connection() as db:
                row = db.execute('SELECT body FROM approvals WHERE run_id=?', (run_id,)).fetchone()
            decision = Approval.model_validate_json(row['body']) if row else None
            command = initial
            if not snapshot.values and initial is None:
                with self.store.connection() as db:
                    row = db.execute('SELECT scenario FROM workflows WHERE run_id=?', (run_id,)).fetchone()
                if row is None:
                    raise KeyError(run_id)
                command = {'run_id': run_id, 'scenario': json.loads(row['scenario'])}
            if snapshot.next and decision and decision.status != 'pending' and 'approval' in snapshot.next:
                command = Command(resume=decision.model_dump(mode='json'))
            try:
                if command is not None or snapshot.next:
                    graph.invoke(command, config)
                snapshot = graph.get_state(config)
                if 'approval' in snapshot.next:
                    self.publish_approval(snapshot.values)
            except Exception as exc:
                with self.store.connection(write=True) as db:
                    self.update_run(db, run_id, status='failed', error=type(exc).__name__, ended_at=utcnow())
                    scenario = json.loads(db.execute('SELECT scenario FROM workflows WHERE run_id=?', (run_id,)).fetchone()[0])
                    self.store._trace(db, run_id, scenario['sim_time'], 'error', {'type': type(exc).__name__, 'message': 'run failed; see typed tool/agent error'})
                raise
        return self.store.get_run(run_id)

    def register(self, scenario):
        if 'person' in scenario.payload:
            person = PersonCase.model_validate(scenario.payload['person'])
            if person.reply_to:
                with self.store.connection() as db:
                    row = db.execute('SELECT scenario FROM workflows WHERE run_id=?', (person.reply_to,)).fetchone()
                parent = Scenario.model_validate_json(row['scenario']) if row else None
                if scenario.type != 'case' or parent is None or parent.type != 'admin' or self.store.get_run(person.reply_to).status != 'completed':
                    raise ValueError('reply_to requires completed admin run')
                original = PersonCase.model_validate(parent.payload['person'])
                if (person.person_id, person.age, person.sgg) != (original.person_id, original.age, original.sgg):
                    raise ValueError('reply_to person mismatch')
        run_id = str(uuid4())
        run = Run(id=run_id, scenario_id=scenario.id, thread_id=run_id, status='running',
            data_mode=self.settings.data_mode, llm_mode=self.settings.llm_mode, input_version=digest(scenario.model_dump(mode='json')),
            rule_version='person-v02' if 'person' in scenario.payload else 'provisional-1', model_version=(self.settings.openai_model or 'unconfigured') if self.settings.llm_mode == 'live' else 'fake-v1', prompt_version='agents-v1', catalog_version='seohee-resources-3' if self.settings.resource_catalog == 'v3' else 'curated-20261018-1' if self.settings.resource_catalog == 'curated' else ('synthetic-1' if self.settings.data_mode == 'sample' else 'local'), started_at=utcnow())
        with self.lock(run_id):
            self.store.create_run(run)
            with self.store.connection(write=True) as db:
                db.execute('INSERT INTO workflows VALUES (?,?)', (run_id, scenario.model_dump_json()))
            return run

    def start(self, scenario):
        return self.drive(self.register(scenario).id)

    def execute(self, run_id):
        try:
            self.drive(run_id)
        except Exception:
            pass  # drive persists failure; background work must not raise after the HTTP response.

    def approval(self, run_id):
        with self.store.connection() as db:
            row = db.execute('SELECT body,proposal FROM approvals WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {'approval': json.loads(row['body']), 'proposal': json.loads(row['proposal'])}

    def decide(self, run_id, snapshot_version, status, operator, reason=None):
        if self.store.get_run(run_id).llm_mode != self.settings.llm_mode:
            raise ValueError('restore the original LLM_MODE before deciding this run')
        with self.lock(run_id), self.graph() as graph:
            current = self.approval(run_id)['approval']
            if current['snapshot_version'] != snapshot_version:
                raise ValueError('snapshot mismatch')
            if current['status'] != 'pending':
                if current['status'] != status:
                    raise ValueError('approval already decided differently')
                return self.drive(run_id)
            state = graph.get_state({'configurable': {'thread_id': run_id}})
            if 'approval' not in state.next or state.values['proposal']['snapshot_version'] != snapshot_version:
                raise ValueError('resumable approval checkpoint not ready')
            decision = Approval.model_validate({**current, 'status': status, 'operator': operator, 'reason': reason, 'decided_at': utcnow()})
            with self.store.connection(write=True) as db:
                db.execute('UPDATE approvals SET body=? WHERE run_id=?', (decision.model_dump_json(), run_id))
                self.once(db, state.values, 'decision', 'approval', decision.model_dump(mode='json'), 'approval')
            return self.drive(run_id)

    def recover(self):
        with self.store.connection() as db:
            ids = [r[0] for r in db.execute('SELECT run_id FROM workflows')]
        for run_id in ids:
            try:
                self.drive(run_id)
            except Exception:
                pass  # Failure is persisted by drive; other runs must still recover.
