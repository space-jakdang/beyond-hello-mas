import {test,expect} from '@playwright/test';

test('conditional regional candidates show partial ages and pending eligibility without claiming support',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-conditional',type:'monthly',sim_time:'2026-10-21T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',sex:'M',age_group:'youth',ym:source.months.at(-1),as_of:'2026-10-21'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;},{timeout:20000}).toBe('awaiting_approval');
 const proposal=overview.review.proposal;
 const row=proposal.assignments.find((r:any)=>r.recommendations.length);
 const conditions={candidate_status:'conditional',age_coverage:'partial',eligible_age_ranges:[[25,29]],unknown_conditions:['age','eligibility:resident','support_stage','support_intensity','unstructured_eligibility']};
 Object.assign(row.recommendations[0],conditions);
 Object.assign(row.decision_evidence.presented_candidates.find((c:any)=>c.id===row.recommendations[0].id),conditions);
 await page.route(`**/runs/${run.id}/overview`,r=>r.fulfill({json:overview}));
 await page.goto(`/workspace?run=${run.id}`);
 await page.getByRole('tab',{name:'자원 제안'}).click();
 const item=page.locator('.resource-row').filter({hasText:row.dong_nm}).first();
 await expect(item).toContainText('조건부 검토 후보');
 await expect(item).toContainText('지원 확정 아님');
 await expect(item).toContainText('일부 연령만 해당: 25–29세');
 await expect(item).toContainText('추가 확인: 해당 연령 일부 · 지원 자격');
 await expect(item).toContainText('지원 단계 확인 필요');
 await expect(item).toContainText('지원 강도 확인 필요');
 await expect(item).toContainText('지원 자격 확인 필요');
 await item.locator('.decision-evidence > summary').click();
 await expect(item.locator('.decision-evidence')).toContainText('일부 연령만 해당: 25–29세');
 delete row.recommendations[0].candidate_status;
 delete row.decision_evidence.presented_candidates.find((c:any)=>c.id===row.recommendations[0].id).candidate_status;
 await page.reload();await page.getByRole('tab',{name:'자원 제안'}).click();
 await expect(item).not.toContainText('일부 연령만 해당: 25–29세');
});


test('unmapped source factors yield a concrete field-check plan rather than invented needs',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-unmapped',type:'monthly',sim_time:'2026-10-21T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'32010',sex:'F',age_group:'prime',ym:source.months.at(-1),as_of:'2026-10-21'}}}});
 const run=await response.json();
 await expect.poll(async()=> (await(await request.get(`/runs/${run.id}`)).json()).status,{timeout:20000}).toBe('awaiting_approval');
 await page.goto(`/workspace?run=${run.id}`);await page.getByRole('tab',{name:'자원 제안'}).click();
 const evidence=page.locator('.need-evidence').first();
 await expect(evidence).toContainText('서비스 욕구를 확정할 근거가 부족합니다.');
 await expect(evidence).toContainText('현장 욕구를 확인한 뒤 자원을 다시 조회');
 await evidence.locator('summary').click();
 await expect(evidence).toContainText('원천 요인 정의·욕구별 측정 자료');
 await expect(evidence).toContainText('경제·주거·건강 욕구로 환산하지 않습니다.');
});
