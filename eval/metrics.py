"""Metrics keep missing/failed runs in their declared denominators."""
from collections import Counter
from math import ceil
from statistics import mean


def fraction(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator, 'value': numerator/denominator if denominator else None}


def percentile(values, quantile):
    return sorted(values)[max(0, ceil(len(values)*quantile)-1)] if values else None


def summarize(results, ratings=()):
    crisis_cases = [r for r in results if r['scenario_id'].startswith('S3-')]
    matrix = Counter(('TP' if r['predicted_crisis'] else 'FN') if r['expected_crisis'] else ('FP' if r['predicted_crisis'] else 'TN') for r in crisis_cases)
    cases = [r for r in results if r['scenario_id'].startswith('S2-')]
    questions = [r for r in results if r['scenario_id'].startswith('S4-')]
    latencies = [r['receipt_ms'] for r in results if r['receipt_ms'] is not None]
    crisis_latencies = [r['receipt_ms'] for r in crisis_cases if r['predicted_crisis'] and r['receipt_ms'] is not None]
    known_cost = sum(r['known_cost_usd'] for r in results)
    unknown_calls = sum(r['unknown_cost_calls'] for r in results)
    scores = [r['score'] for r in ratings]
    return {'path_accuracy': fraction(sum(r['path_correct'] for r in results), len(results)),
            'crisis_confusion': {key:matrix[key] for key in ('TP','FN','FP','TN')},
            'crisis_recall': fraction(matrix['TP'],matrix['TP']+matrix['FN']),
            'crisis_false_positive_rate': fraction(matrix['FP'],matrix['FP']+matrix['TN']),
            'subscales_accuracy':fraction(sum(r.get('subscales_correct',False) for r in cases),len(cases)),
            'cause_accuracy': fraction(sum(r['causes_correct'] for r in cases),len(cases)),
            'question_routing': fraction(sum(r['route_correct'] for r in questions),len(questions)),
            'precision_at_3': fraction(sum(r['relevant_recommendations'] for r in cases),3*len(cases)),
            'needs_coverage': fraction(sum(r['relevant_recommendations']>0 for r in cases),len(cases)),
            'recommendation_shortfall': sum(3-r['recommendation_count'] for r in cases),
            'evidence': {'checked':sum(r['evidence_checked'] for r in results), 'mismatches':sum(r['evidence_mismatches'] for r in results), 'method':'exact catalog field comparison, not a natural-language hallucination evaluation'},
            'latency': {'count':len(latencies),'missing':sum(r['expects_alert'] and r['receipt_ms'] is None for r in results),'not_applicable':sum(not r['expects_alert'] for r in results), 'p50_ms':percentile(latencies,.5),'p95_ms':percentile(latencies,.95),'definition':'server monotonic run start to first alert browser receipt acknowledgement; nearest-rank percentile'},
            'crisis_latency':{'count':len(crisis_latencies),'p50_ms':percentile(crisis_latencies,.5),'p95_ms':percentile(crisis_latencies,.95)},
            'cost':{'known_usd':known_cost,'unknown_calls':unknown_calls,'total_usd':known_cost if not unknown_calls else None,'basis':'uncached token price estimate; not invoiced cost'},
            'human_suitability':{'count':len(scores),'missing':len(cases)-len(scores),'mean':mean(scores) if scores else None,'distribution':{str(i):scores.count(i) for i in range(1,6)}},
            'execution':dict(Counter(r['status'] for r in results))}
