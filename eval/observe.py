from backend.tools.indicators import digest


def observe(scenario, label, run, traces, proposal, status, error=None, client_id=None):
    expected=label['expected']
    path=[t['agent'] for t in traces if t['kind']=='node_end']
    classification=next((t['payload'] for t in traces if t['agent']=='classify' and t['kind']=='node_end'),{})
    calls=[t['payload'] for t in traces if t['kind']=='llm_result' or (t['kind']=='error' and t['payload'].get('role'))]
    route=next((c['output']['route'] for c in calls if c.get('role')=='route' and 'output' in c),None)
    predicted_crisis=any(t['agent']=='supervisor' and t['kind']=='node_end' and t['payload'].get('evidence') for t in traces)
    recommendations={r['id']:r for assignment in proposal.get('assignments',[]) for r in assignment.get('recommendations',[])}
    relevant=sum(bool(set(r['needs']) & set(expected.get('needs',[]))) for r in recommendations.values())
    checked=mismatches=0
    for call in calls:
        if call.get('role')!='recommendations' or 'output' not in call:
            continue
        catalog={r['id']:r for r in call['input']['candidates']}
        for item in call['output']['items']:
            checked+=1
            mismatches+=int(item['resource_id'] not in catalog or not item['evidence'] or any(catalog.get(item['resource_id'],{}).get(e['field'])!=e['value'] for e in item['evidence']))
    alert=next((t for t in traces if t['kind']=='alert'),None)
    receipt=next((t for t in traces if t['kind']=='received' and alert and t['payload']['alert_id']==alert['payload']['id'] and t['payload']['client_id']==client_id),None)
    def timestamp(kind,agent=None):
        return next((t['wall_ts'] for t in traces if t['kind']==kind and (agent is None or t['agent']==agent)),None)
    unknown=sum(c.get('cost_usd') is None for c in calls)
    unknown+=max(0,sum(t['kind']=='llm_call' for t in traces)-len(calls))
    return {'scenario_id':scenario.id,'run_id':run.get('id'),'status':status,'error':error,'path':path,
            'expected_path':expected['path'],'path_correct':status in ('completed','rejected') and path==expected['path'],
            'expected_crisis':expected['crisis'],'predicted_crisis':predicted_crisis,
            'causes':classification.get('analysis',{}).get('causes',[]),
            'causes_correct':status in ('completed','rejected') and sorted(classification.get('analysis',{}).get('causes',[]))==sorted(expected.get('causes',[])),
            'route':route,'route_correct':status=='completed' and route==expected.get('route'),
            'subscales':classification.get('result',{}).get('subscales') if classification.get('result') else None,
            'subscales_correct':classification.get('result',{}).get('subscales')==expected.get('subscales') if classification.get('result') else False,
            'recommendation_count':len(recommendations),'relevant_recommendations':relevant,
            'evidence_checked':checked,'evidence_mismatches':mismatches,
            'expects_alert':expected.get('route') not in ('history','human','classify','match'),
            'receipt_ms':receipt['payload']['run_to_receipt_ms'] if receipt else None,
            'known_cost_usd':sum(c.get('cost_usd') or 0 for c in calls),'unknown_cost_calls':unknown,
            'trace_hash':digest(traces),'trace_count':len(traces),
            'clocks':{'t0':run.get('started_at'),'t1':timestamp('node_end','classify'),'t2':timestamp('node_end','match'),
                      't3':alert['wall_ts'] if alert else None,'t4_browser':receipt['payload']['browser_received_at'] if receipt else None,
                      'ack_server':receipt['payload']['server_received_at'] if receipt else None,'t5_human':timestamp('acknowledged'),
                      'approval':timestamp('approval'),'t6':timestamp('node_end','link')}}
