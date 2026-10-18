from types import SimpleNamespace
from eval.run_v2 import inputs
from eval.oracle_v2 import regional
from backend.graph import crisis_evidence
from backend.agents.person_stub import assess_stage


def test_sixty_inputs_have_no_labels_and_protocol_stages_are_not_clinical():
    scenarios,labels=inputs()
    assert len(scenarios)==len(labels)==60
    assert [sum(s.type==kind for s in scenarios) for kind in ('monthly','case','crisis','question','admin')]==[6,24,8,10,12]
    assert all('expected' not in s.model_dump_json() for s in scenarios)
    for stage in range(1,6):
        result=assess_stage('youth',24,{'synthetic-contract-fixture':{'case':100+stage}}, {})
        assert result['stage']==stage and result['human_handoff']==(stage>=4)
        assert result['rule_version']=='stub-v02'


def test_independent_regional_table_boundaries_and_missing():
    row=SimpleNamespace(value=.206,index_name='S1',source_stage=None)
    assert regional(row,['strong'])==5
    row.value=.206001
    assert regional(row,['strong'])==4
    row.value=.292
    assert regional(row)==1 and regional(row,['weak'])==3 and regional(row,['weak','weak'])==5
    assert regional(row,[],True)==2
    row.value=None
    assert regional(row,['strong'],True) is None
    row.index_name='v3';row.value=.54
    assert regional(row,['weak'])==4


def test_known_indirect_crisis_phrases_and_negation():
    assert crisis_evidence('모든 것을 끝내고 사라지고 싶습니다.')
    assert crisis_evidence('내일은 더 이상 이 세상에 없을 것 같습니다.')
    assert not crisis_evidence('끝내고 사라지고 싶지 않아요. 자살 예방 교육을 듣습니다.')

    assert not crisis_evidence('더 이상 이 세상에 없을 것 같지 않습니다.')
    assert not crisis_evidence('모든 것을 끝내고 사라지고 싶지는 않아요.')
    assert crisis_evidence('자살 예방 교육을 받았지만 지금 죽고 싶어요.')
