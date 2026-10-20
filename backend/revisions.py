"""Atomic parent rejection and idempotent child registration; no external action."""
import json
import time
from uuid import uuid4
from backend.app.contracts import Approval,Run,Scenario
from backend.events import utcnow
from backend.tools.indicators import digest


def request_revision(service,run_id,snapshot_version,operator,reason):
    if not operator.strip() or not reason.strip() or len(reason)>1000:
        raise ValueError('revision needs operator and reason up to 1000 characters')
    # The same author and reason identify a retry; a different author must review the existing child.
    request_hash=digest({'snapshot':snapshot_version,'operator':operator.strip(),'reason':reason.strip()})
    with service.lock(run_id),service.graph() as graph:
        parent=service.store.get_run(run_id)
        if parent.llm_mode!=service.settings.llm_mode or parent.data_mode!=service.settings.data_mode:
            raise ValueError('restore original data and model mode')
        state=graph.get_state({'configurable':{'thread_id':run_id}})
        with service.store.connection(write=True) as db:
            existing=db.execute('SELECT child_run_id,request_hash FROM revisions WHERE parent_run_id=?',(run_id,)).fetchone()
            if existing:
                if existing['request_hash']!=request_hash:raise ValueError('different revision already exists')
                return Run.model_validate_json(db.execute('SELECT body FROM runs WHERE id=?',(existing['child_run_id'],)).fetchone()[0])
            row=db.execute('SELECT body,proposal FROM approvals WHERE run_id=?',(run_id,)).fetchone()
            if row is None:raise KeyError(run_id)
            approval=Approval.model_validate_json(row['body']);proposal=json.loads(row['proposal'])
            if not proposal.get('workflow_version'):raise ValueError('revision requires regional workflow')
            if approval.status!='pending' or approval.snapshot_version!=snapshot_version:
                raise ValueError('approval changed; refresh before revision')
            if 'approval' not in state.next or state.values['proposal']['snapshot_version']!=snapshot_version:
                raise ValueError('approval checkpoint not ready')
            depth=0;cursor=run_id
            while ancestor:=db.execute('SELECT parent_run_id FROM revisions WHERE child_run_id=?',(cursor,)).fetchone():
                depth+=1;cursor=ancestor[0]
                if depth>=2:raise ValueError('revision depth limit reached')
            scenario=Scenario.model_validate_json(db.execute('SELECT scenario FROM workflows WHERE run_id=?',(run_id,)).fetchone()[0])
            body=scenario.model_dump(mode='json')
            body['id']='regional-workflow-revision'
            body['payload']['revision']={'parent_run_id':run_id,'snapshot_version':snapshot_version,'reason':reason.strip()}
            scenario=Scenario.model_validate(body)
            child=service.new_run(scenario,str(uuid4()))
            decision=Approval.model_validate({**approval.model_dump(),'status':'rejected','operator':operator.strip(),
                                             'reason':reason.strip(),'decided_at':utcnow()})
            db.execute('UPDATE approvals SET body=? WHERE run_id=?',(decision.model_dump_json(),run_id))
            db.execute('INSERT INTO runs VALUES (?,?)',(child.id,child.model_dump_json()))
            db.execute('INSERT INTO run_clocks VALUES (?,?,?)',(child.id,service.store.clock_id,time.monotonic()))
            db.execute('INSERT INTO workflows VALUES (?,?)',(child.id,scenario.model_dump_json()))
            db.execute('INSERT INTO revisions VALUES (?,?,?)',(run_id,child.id,request_hash))
            service.update_run(db,run_id,status='rejected',ended_at=utcnow(),error=None)
            service.once(db,state.values,'decision','approval',decision.model_dump(mode='json'),'approval')
            service.once(db,state.values,'revision','agent_message',{'sender':'approval','recipient':'supervisor',
                'child_run_id':child.id,'reason':reason.strip(),'parent_snapshot':snapshot_version},'approval')
            service.once(db,state.values,'run-end','run_end',{'status':'rejected'})
    service.execute(run_id)
    return child
