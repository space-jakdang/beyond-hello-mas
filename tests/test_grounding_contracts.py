import json
import pytest
from eval.grounding_contracts import load_grounding, Metric
from backend.tools.indicators import digest
from eval.quality_metrics import validate_predictions
from test_quality_metrics import fixture


def test_grounding_hash_binding_state_and_private_references(tmp_path):
    f,l,p=fixture((3,),(3,));p['predictions'][0]['run_id']='source'
    payload={'schema_version':'6','dataset_hash':f['dataset_hash'],
        'prediction_hash':digest(validate_predictions(f,p).model_dump()),'reference_hash':digest({'0':'private reference'}),
        'references':{'0':'private reference'},'judge_run_id':'judge','judge_model':'fixture','ragas_version':'0.4.3','state':'evaluated',
        'rows':[{'case_id':'0','source_run_id':'source','source_call_key':'call','source_hash':'hash','role':'workflow_analyst',
            'metrics':{'faithfulness':{'value':.5,'state':'evaluated'}}}], 'human_judge_alignment':None,
        'cost':{'calls':2,'reserved_usd':.1,'known_usd':.01,'unknown_cost_calls':0},'limitations':['fixture']}
    file=tmp_path/'grounding-one.json';file.write_text(json.dumps(payload))
    result=load_grounding(tmp_path,f,p,{'0'})
    assert 'references' not in result and result['rows'][0]['metrics']['faithfulness']['value']==.5
    assert load_grounding(tmp_path,f,p,set())['rows']==[]
    payload['rows'].append(payload['rows'][0].copy());file.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='mapping'):load_grounding(tmp_path,f,p,{'0'})
    payload['rows'].pop();payload['rows'][0]['source_run_id']='other';file.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='mapping'):load_grounding(tmp_path,f,p,{'0'})
    payload['rows'][0]['source_run_id']='source'
    original=tmp_path/'private.json';file.rename(original);file.symlink_to(original)
    with pytest.raises(ValueError,match='symlink'):load_grounding(tmp_path,f,p,{'0'})
    file.unlink();original.rename(file)
    payload['prediction_hash']='changed';file.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='versions'):load_grounding(tmp_path,f,p,{'0'})
    for value,state in [(1.1,'evaluated'),(None,'evaluated'),(.5,'failed'),(float('nan'),'evaluated')]:
        with pytest.raises(ValueError):Metric(value=value,state=state)
