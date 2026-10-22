import {test,expect} from '@playwright/test';
test('regional agents exchange evidence and retain human approval',async({page})=>{
 await page.goto('/observatory');
 await page.getByRole('combobox',{name:'시나리오',exact:true}).selectOption({label:'monthly-collaboration'});
 await page.getByRole('button',{name:'실행',exact:true}).click();
 await expect(page.getByTestId('run-status')).toHaveText('승인 대기');
 await expect(page.getByTestId('agent-messages')).toContainText('지역 분석 → 근거 검토');
 await expect(page.getByTestId('agent-messages')).toContainText('근거 검토 → Supervisor');
 await page.reload();await expect(page.getByTestId('agent-messages').getByRole('listitem')).toHaveCount(4);
});

test('temporal comparison filters seed and explains scope',async({page,request})=>{
 const reports=await(await request.get('/reports?source=sample')).json();
 const report=reports.find((r:any)=>r.schema_version==='3');expect(report).toBeTruthy();
 await page.goto('/evaluation');await page.getByRole('combobox',{name:'평가 실행'}).selectOption(report.id);
 await expect(page.getByTestId('temporal-evaluation')).toContainText('실제 고립 발생 예측은 미평가');
 await page.getByRole('combobox',{name:'시험 seed'}).selectOption('29');
 await expect(page.getByRole('img',{name:'seed 29 월별 평균 절대 오차 비교'})).toBeVisible();
 const summary=await(await request.get(`/reports/${report.id}?source=sample`)).json();
 const row=summary.temporal.by_month.find((r:any)=>r.seed===29&&r.month==='2025-07'&&r.method==='last_value');
 await expect(page.getByTestId('temporal-evaluation').getByRole('row').filter({hasText:'2025-07'}).filter({hasText:'직전 관측 유지'})).toContainText(row.mae.toFixed(3));
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
});


test('source review requests lookup, revises plan and retains approval after reload',async({page})=>{
 await page.goto('/observatory');
 await page.getByRole('combobox',{name:'시나리오',exact:true}).selectOption({label:'monthly-evidence-loop'});
 await page.getByRole('button',{name:'실행',exact:true}).click();
 await expect(page.getByTestId('run-status')).toHaveText('승인 대기');
 await expect(page.getByTestId('agent-messages')).toContainText('원천 상세 확인 필요');
 await expect(page.getByTestId('agent-messages')).toContainText('추가 조회 근거를 반영한 검토안');
 await page.reload();
 await expect(page.getByTestId('agent-messages').getByRole('listitem')).toHaveCount(7);
});

test('resource gap research stays a candidate outside approved assignments',async({page,request})=>{
 await page.goto('/observatory');
 await page.getByRole('combobox',{name:'시나리오',exact:true}).selectOption({label:'monthly-resource-research'});
 await page.getByRole('button',{name:'실행',exact:true}).click();
 await expect(page.getByTestId('run-status')).toHaveText('승인 대기');
 const id=await page.getByTestId('run-id').innerText();
 const review=await(await request.get(`/runs/${id}/approval`)).json();
 expect(review.proposal.policy_research.eligibility_verified).toBe(false);
 expect(review.proposal.policy_research.remaining_capacity).toBeNull();
 expect(review.proposal.policy_research.allocation_performed).toBe(false);
 expect((await request.get(`/runs/${id}/linkage`)).status()).toBe(404);
 await page.goto('/console');
 await page.getByTestId(`alert-${id}-approval_requested`).getByRole('button',{name:'실행 상세'}).click();
 await expect(page.getByText('정책 조사 결과는 후보입니다.',{exact:false})).toBeVisible();
});

test('workflow evaluation separates synthetic contracts from unmeasured field quality',async({page,request})=>{
 const reports=await(await request.get('/reports?source=sample')).json();
 const report=reports.find((r:any)=>r.schema_version==='5');expect(report).toBeTruthy();
 await page.goto('/evaluation');await page.getByRole('combobox',{name:'평가 실행'}).selectOption(report.id);
 await expect(page.getByTestId('suite-count')).toHaveText('36');
 await expect(page.getByRole('tabpanel')).toContainText('실제 지역 분류 타당성: 미측정');
 await page.getByRole('tab',{name:'자원 적합성'}).click();
 await expect(page.getByRole('tabpanel')).toContainText('전문가 자원 적합성: 미측정');
 await page.getByRole('tab',{name:'자원 적합성'}).press('End');
 await expect(page.getByRole('tabpanel')).toContainText('새 업무의 다중 에이전트 효과: 미측정');
 await page.getByRole('tab',{name:'지역·시간 전이'}).click();
 await expect(page.getByRole('tabpanel')).toContainText('2025-12');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});


test('evaluation summary retains report denominators on mobile',async({page,request})=>{
 const reports=await(await request.get('/reports?source=sample')).json();const report=reports.find((r:any)=>r.schema_version==='5');expect(report).toBeTruthy();
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');
 await page.getByRole('combobox',{name:/평가 실행/}).selectOption(report.id);
 await expect(page.getByLabel('평가 핵심 요약')).toContainText(String(report.evaluated_scenarios));
 await expect(page.getByLabel('지역 업무 계약 요약')).toContainText('미측정');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
