from eval.run_comparison import load_cases, run


def test_frozen_sets_separate_labels_and_cover_challenges():
    import json
    from backend.app.config import ROOT
    contract,dev=load_cases('dev');_,test=load_cases('test')
    assert len(dev)==8 and len(test)==24
    assert not {r['id'] for r in dev}&{r['id'] for r in test}
    assert len({(r['sex'],r['age_group']) for r in test})==8
    labels=json.loads((ROOT/'scenarios/comparison/test_labels.json').read_text())
    assert all(sum(r['kind']==kind for r in labels)==4 for kind in {r['kind'] for r in labels})
    assert all('labels' not in r and 'required_review' not in r for r in dev+test)
    assert contract['max_calls_per_method']==6


def test_fake_baselines_keep_pairing_and_do_not_claim_quality():
    report=run('dev')
    assert report['quality'] is None and report['adoption_decision']=='not_evaluated'
    assert report['case_count']==8 and len(report['results'])==16
    for a,b in zip(report['results'][::2],report['results'][1::2]):
        assert a['input_hash']==b['input_hash'] and a['case_id']==b['case_id']
        assert a['calls']==0 and b['calls']==3
        assert b['content_rating'] is None
