import {test,expect} from '@playwright/test';

test('unconfirmed needs keep three tentative alternatives without declaring a policy gap',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-gap',type:'monthly',sim_time:'2026-10-24T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',research_gaps:true,task:{sgg:'32010',sex:'F',age_group:'prime',ym:source.months.at(-1),as_of:'2026-10-24'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;},{timeout:20000}).toBe('awaiting_approval');
 expect(overview.review.proposal.policy_research).toBeUndefined();
 for(const row of overview.review.proposal.assignments){expect(row.policy_gap.status).toBe('needs_unconfirmed');expect(row.policy_gap.absence_established).toBe(false);}
 const alternatives=await(await request.get(`/policy-proposals/${run.id}`)).json();
 for(const set of alternatives.sets){expect(set.alternatives).toHaveLength(3);expect(set.evidence.source_search_status).toBe('not_requested');for(const item of set.alternatives)expect(item.claim_limits.effectiveness).toBe('not_evaluated');}
 await page.goto(`/workspace?run=${run.id}`);await page.getByRole('tab',{name:'자원 제안'}).click();
 await expect(page.locator('.need-evidence').first()).toContainText('서비스 욕구를 확정할 근거가 부족합니다.');
});
