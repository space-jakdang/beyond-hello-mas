import {test,expect} from '@playwright/test';

test('saved review changes distinguish applied analysis from held drafts and old runs',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-changes',type:'monthly',sim_time:'2026-10-24T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',sex:'M',age_group:'youth',ym:source.months.at(-1),as_of:'2026-10-24'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;},{timeout:20000}).toBe('awaiting_approval');
 await page.goto(`/workspace?run=${run.id}`);
 const changes=page.getByRole('region',{name:'판단 보완 결과'});
 await expect(changes).toContainText('저장된 분석 보완은 없습니다.');
 await expect(changes.getByRole('table')).toHaveCount(0);
 const proposal=overview.review.proposal,review=proposal.workflow.statistics;
 const ids=proposal.assessment.segments.slice(0,2).map((r:any)=>r.evidence_id);
 Object.assign(review,{initial_plan:{summary:'최초 검토 범위',priority_evidence_ids:ids},revised_plan:{summary:'누락 관측을 제외한 검토 범위',priority_evidence_ids:ids.slice(1)},review_history:[{phase:'initial',action:'revise',reason:'누락 관측 제외 요청'},{phase:'final',action:'finish',reason:'보완 범위 재확인'}],status:'reviewed',revision_check:'final_statistics_review'});
 proposal.workflow.analysis=review.revised_plan;
 await page.route(`**/runs/${run.id}/overview`,r=>r.fulfill({json:overview}));
 await page.setViewportSize({width:390,height:844});await page.reload();
 await expect(changes).toContainText('현재 결과에 반영했습니다.');
 await expect(changes.getByRole('table')).toContainText('누락 관측을 제외한 검토 범위');
 const detail=changes.locator('summary');await detail.focus();await page.keyboard.press('Enter');
 await expect(changes).toContainText('보완 범위 재확인');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 Object.assign(review,{status:'needs_human',revision_check:null});proposal.workflow.analysis=review.initial_plan;
 await page.reload();await expect(changes).toContainText('현재 결과에는 최초 분석을 유지합니다.');
 await expect(changes.getByRole('table')).toContainText('미검토 초안');
 await expect(page.locator('.workflow-result-intro')).toContainText('최초 검토 범위');
 delete review.initial_plan;delete review.revised_plan;delete review.review_history;delete review.review_version;
 await page.reload();await expect(changes).toContainText('비교할 분석 전후 기록이 없습니다.');
 await expect(changes.getByRole('table')).toHaveCount(0);
});

test('need and search states supply next actions without turning slots into policy absence',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-next-action',type:'monthly',sim_time:'2026-10-24T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'32010',sex:'F',age_group:'prime',ym:source.months.at(-1),as_of:'2026-10-24'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;},{timeout:20000}).toBe('awaiting_approval');
 await page.goto(`/workspace?run=${run.id}`);await page.getByRole('tab',{name:'자원 제안'}).click();
 const gap=page.locator('.policy-gap-summary').first();
 await expect(gap).toContainText('서비스 필요 확인 전');await expect(gap).toContainText('현장 필요를 확인');
 await expect(gap).toContainText('빈 추천 슬롯 3개는 실제 서비스 부족을 뜻하지 않습니다.');
 overview.review.proposal.assignments[0].policy_gap.search_status='search_failed';
 await page.route(`**/runs/${run.id}/overview`,r=>r.fulfill({json:overview}));
 await page.reload();await page.getByRole('tab',{name:'자원 제안'}).click();await expect(gap).toContainText('정책 검색 실패');
});
