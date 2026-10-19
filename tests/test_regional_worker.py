from types import SimpleNamespace
import pytest
from backend.agents.regional_worker import single, lookup, RegionalDecision

OBS = {'facts': [{'id':'a', 'stage':4}], 'required_limitations':['not_individual'], 'goal':'review'}
PLAN = {'summary':'supported', 'focus_ids':['a'], 'limitations':['not_individual']}


def test_single_can_lookup_then_revise_itself_without_labels():
    received=[]
    class Agents:
        def call(self, run, ts, role, payload):
            received.append(payload)
            step=payload['step']
            if step==1: output={'action':'lookup','targets':['a'],'reason':'check source','plan':None}
            else:
                assert payload['retrieved'][0]['evidence']['period']=='aggregate'
                output={'action':'finish','targets':[],'reason':'reviewed','plan':{**PLAN,'summary':f'version {step}'}}
            return RegionalDecision.model_validate(output)
    output=single(Agents(),'r','t',OBS,{'a':{'period':'aggregate'}},lambda *a:None)
    assert output['status']=='submitted' and output['plan']['summary']=='version 3'
    assert received[2]['previous_plan']['summary']=='version 2'
    assert all('labels' not in p for p in received)


def test_lookup_boundary_and_budget_never_publish_unreviewed_plan():
    with pytest.raises(ValueError):lookup(OBS,{},['outside'])
    with pytest.raises(ValueError):lookup(OBS,{},['a','a'])
    assert lookup(OBS,{},['a'])[0]['status']=='unavailable'
    class Agents:
        def call(self,*args):return RegionalDecision(action='finish',targets=[],reason='draft',plan=PLAN)
    output=single(Agents(),'r','t',OBS,{},lambda *a:None,max_calls=1)
    assert output['status']=='needs_human' and output['plan'] is None
    with pytest.raises(ValueError):RegionalDecision(action='human',targets=[],reason='hold',plan=PLAN)
