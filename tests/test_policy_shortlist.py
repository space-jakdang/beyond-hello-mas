from backend.policy.agent import PolicyAgent


def test_funnel_counts_distinct_retrieved_checked_selected_and_never_fills_quota():
    agent=object.__new__(PolicyAgent)
    from types import SimpleNamespace
    agent.settings=SimpleNamespace(llm_mode='fake')
    observations=[{'action':{'action':'policy_search'},'arguments':{'query':'support','scopes':['central'],'page':1},'result':{'items':[{'id':str(i)} for i in range(5)],'total':5,'next_page':None}},
                  {'action':{'action':'policy_details'},'result':{'items':[{'status':'live','policy':{'id':str(i)}} for i in range(4)]}}]
    selected=[{'policy':{'id':'0'}}]
    result=agent.finish('completed',selected,observations)
    assert result['recommendations']==selected
    assert result['candidate_funnel']['retrieved']==5
    assert result['candidate_funnel']['details_checked']==4
    assert result['candidate_funnel']['shortfall']==2
    assert len(result['candidate_funnel']['not_selected'])==3
    failed=agent.finish('step_limit',[],observations)
    assert failed['recommendations']==[] and failed['candidate_funnel']['details_checked']==4

    assert result['candidate_funnel']['reason']=='search_incomplete'
    assert agent.finish('completed',[],observations)['status']=='search_incomplete'
    observations[0]['result']['coverage']={'source_complete':True,'stale':False,'last_attempt':{'status':'success'}}
    observations[1]['result']['items'].append({'status':'live','policy':{'id':'4','title':'Fifth'}})
    assert agent.finish('completed',[],observations)['status']=='no_verified_candidates'
    all_selected=[{'policy':{'id':str(i)}} for i in range(5)]
    funnel=agent.finish('completed',all_selected,observations)['candidate_funnel']
    assert funnel['selected']==5 and funnel['shortfall']==0 and not funnel['not_selected']
    assert funnel['reason']=='enough_candidates'
