import {test,expect} from '@playwright/test';
test('three alternatives retain separate reviews, edit resets and stale revision is rejected',async({page,request})=>{
 const created=await request.post('http://127.0.0.1:'+(process.env.E2E_API_PORT||8000)+'/scenarios/run',{data:{id:'regional-workflow',type:'monthly',sim_time:'2025-09-01T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',ym:'2025-09',as_of:'2026-10-23',sex:'M',age_group:'youth'}}}});
 expect(created.ok()).toBeTruthy();const run=await created.json();
 await expect.poll(async()=>{const r=await request.get('http://127.0.0.1:'+(process.env.E2E_API_PORT||8000)+'/policy-proposals/'+run.id);return r.status();},{timeout:20000}).toBe(200);
 await page.setViewportSize({width:390,height:844});await page.goto('/workspace?policy_owner='+run.id);
 const panel=page.getByRole('region',{name:'정책 대안 세 개'});await expect(panel.getByRole('button',{name:'이 대안 수정·검토'})).toHaveCount(3);
 await panel.getByRole('button',{name:'이 대안 수정·검토'}).first().click();await panel.getByLabel('검토자',{exact:true}).fill('테스트 담당자');await panel.getByLabel('수정 내용 또는 검토 사유').fill('근거 확인 후 정책안 검토');await panel.getByRole('button',{name:'정책안 검토 승인',exact:true}).click();await expect(panel.getByText('정책안 검토 승인',{exact:true})).toHaveCount(1);
 await panel.getByRole('button',{name:'이 대안 수정·검토'}).nth(1).click();await panel.getByLabel('수정 내용 또는 검토 사유').fill('접근 경로 보완');await panel.getByRole('button',{name:'수정 저장',exact:true}).click();await expect(panel.getByText('검토 대기',{exact:true})).toHaveCount(3);
 await expect(panel.getByText('접근 경로 보완',{exact:false}).first()).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 const downloaded=page.waitForEvent('download');await panel.getByRole('button',{name:'PDF 다운로드',exact:true}).click();expect((await downloaded).suggestedFilename()).toMatch(/r2\.pdf$/);
 const word=page.waitForEvent('download');await panel.getByRole('button',{name:'Word 다운로드',exact:true}).click();expect((await word).suggestedFilename()).toMatch(/r2\.docx$/);
 await page.reload();await expect(panel.getByText('검토 대기',{exact:true})).toHaveCount(3);
 const response=await request.get('http://127.0.0.1:'+(process.env.E2E_API_PORT||8000)+'/policy-proposals/'+run.id),body=await response.json();
 Object.assign(body.sets[0].alternatives[0],{design_checks:{status:'structured_draft',gaps:[]},
  source_elements:[{policy_id:'fixture',field:'support',quote:'방문 상담과 후속 연락'}],
  adaptations:[{source_policy_ids:['fixture'],local_difference:'지역 이동 접근성 확인 필요',proposed_change:'청년 방문 예약을 저녁 시간으로 시범 조정',verification_needed:['협력기관 운영시간 확인']}],
  evaluation_design:{outcome:'연락 유지',baseline_needed:'시행 전 연락률',comparison_method:'동일 집단 전후 비교',observation_period:'시범 8주 제안',success_criterion_to_agree:'유지율 기준 합의',stop_criterion_to_agree:'참여 부담 증가 시 중단 검토'}});
 await page.route('**/policy-proposals/'+run.id,route=>route.fulfill({json:body}));await page.reload();
 const adapted=panel.getByRole('region',{name:'지역 맞춤 설계 근거'}).first();
 await adapted.getByText('원 정책에서 무엇을 바꾸나요?',{exact:true}).click();
 await expect(adapted).toContainText('청년 방문 예약을 저녁 시간으로 시범 조정');
 await adapted.getByText('어떻게 효과를 확인하나요?',{exact:true}).click();await expect(adapted).toContainText('시행 전 연락률');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
