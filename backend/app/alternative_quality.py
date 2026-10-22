import json
from uuid import UUID
from fastapi import APIRouter,HTTPException
from eval.alternative_quality import quality,Ratings


def router(store):
    with store.connection() as db:db.execute('CREATE TABLE IF NOT EXISTS alternative_ratings (owner_id TEXT,input_hash TEXT,body TEXT,PRIMARY KEY(owner_id,input_hash))')
    result=APIRouter(prefix='/policy-proposals')
    def sets(db,owner):
        rows=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? ORDER BY dong_cd',(owner,)).fetchall()
        if not rows:raise HTTPException(404,'정책 제안 없음')
        return [json.loads(r[0]) for r in rows]
    @result.get('')
    def history():
        with store.connection() as db:
            owners=[r[0] for r in db.execute('SELECT owner_id FROM policy_alternative_sets GROUP BY owner_id ORDER BY MAX(rowid) DESC LIMIT 100')]
            return [{'owner_id':owner,'dong_count':len(data),'created_at':data[0]['created_at'],'data_mode':data[0]['data_mode'],'synthetic_future':bool((data[0].get('scope') or {}).get('synthetic_future'))} for owner in owners for data in [sets(db,owner)]]
    @result.get('/{owner_id}/quality')
    def get(owner_id:UUID):
        with store.connection() as db:
            data=sets(db,str(owner_id));initial=quality(data)
            saved=db.execute('SELECT body FROM alternative_ratings WHERE owner_id=? AND input_hash=?',(str(owner_id),initial['input_hash'])).fetchone()
            table=db.execute("SELECT 1 FROM sqlite_master WHERE name='alternative_grounding'").fetchone()
            grounding=db.execute('SELECT body FROM alternative_grounding WHERE owner_id=? AND input_hash=?',(str(owner_id),initial['input_hash'])).fetchone() if table else None
        report=quality(data,json.loads(saved[0])) if saved else initial
        report['grounding']=json.loads(grounding[0]) if grounding else None
        return report
    @result.post('/{owner_id}/quality/ratings')
    def save(owner_id:UUID,ratings:Ratings):
        with store.connection(write=True) as db:
            try:report=quality(sets(db,str(owner_id)),ratings.model_dump())
            except ValueError as exc:raise HTTPException(422,str(exc))
            old=db.execute('SELECT body FROM alternative_ratings WHERE owner_id=? AND input_hash=?',(str(owner_id),ratings.input_hash)).fetchone()
            merged=ratings.model_dump()
            if old:
                previous=json.loads(old[0])
                reviewers={r['id']:r for r in previous['reviewers']}
                values={(r['alternative_id'],r['reviewer']):r for r in previous['ratings']}
                for reviewer in merged['reviewers']:
                    if reviewer['id'] in reviewers and reviewers[reviewer['id']]!=reviewer:raise HTTPException(409,'기존 검토자 정보를 덮어쓸 수 없습니다.')
                    reviewers[reviewer['id']]=reviewer
                for rating in merged['ratings']:
                    key=(rating['alternative_id'],rating['reviewer'])
                    if key in values and values[key]!=rating:raise HTTPException(409,'기존 평정을 덮어쓸 수 없습니다.')
                    values[key]=rating
                merged.update(reviewers=list(reviewers.values()),ratings=list(values.values()))
                try:report=quality(sets(db,str(owner_id)),merged)
                except ValueError as exc:raise HTTPException(422,str(exc))
                if merged==previous:return report
            if merged['ratings']:
                db.execute('INSERT INTO alternative_ratings VALUES (?,?,?) ON CONFLICT(owner_id,input_hash) DO UPDATE SET body=excluded.body',(str(owner_id),ratings.input_hash,json.dumps(merged,ensure_ascii=False)))
        return report
    return result
