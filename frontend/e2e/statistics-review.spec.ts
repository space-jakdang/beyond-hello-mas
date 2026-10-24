import {test,expect} from '@playwright/test';

test('a sufficient regional summary reaches review without a fabricated tool round trip',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-summary',type:'monthly',sim_time:'2026-10-21T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',sex:'M',age_group:'youth',ym:source.months.at(-1),as_of:'2026-10-21'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;},{timeout:20000}).toBe('awaiting_approval');
 const stats=overview.review.proposal.workflow.statistics;
 expect(stats.status).toBe('reviewed');expect(stats.observations).toEqual([]);
 expect(stats.review_history.map((r:any)=>r.action)).toEqual(['finish']);
 const traces=await(await request.get(`/runs/${run.id}/traces?limit=1000`)).json();
 const items=Array.isArray(traces)?traces:traces.traces;
 expect(items.filter((t:any)=>t.kind==='llm_call'&&t.payload.role==='workflow_statistics')).toHaveLength(1);
 expect(items.filter((t:any)=>t.kind==='llm_call'&&t.payload.role==='workflow_matching')).toHaveLength(0);
 expect(overview.review.proposal.workflow.matching.matching_mode).toBe('deterministic-regional-1');
 await page.goto(`/workspace?run=${run.id}`);await page.getByRole('tab',{name:'통계 근거'}).click();
 await expect(page.locator('.stat-observation')).toHaveCount(0);
});
