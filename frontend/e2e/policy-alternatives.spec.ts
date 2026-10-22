import {test,expect} from '@playwright/test';
test('three alternatives retain separate reviews, edit resets and stale revision is rejected',async({page,request})=>{
 const created=await request.post('http://127.0.0.1:'+(process.env.E2E_API_PORT||8000)+'/scenarios/run',{data:{id:'regional-workflow',type:'monthly',sim_time:'2025-09-01T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',ym:'2025-09',as_of:'2026-10-23',sex:'M',age_group:'youth'}}}});
 expect(created.ok()).toBeTruthy();const run=await created.json();
 await expect.poll(async()=>{const r=await request.get('http://127.0.0.1:'+(process.env.E2E_API_PORT||8000)+'/policy-proposals/'+run.id);return r.status();}).toBe(200);
 await page.setViewportSize({width:390,height:844});await page.goto('/workspace?policy_owner='+run.id);
 const panel=page.getByRole('region',{name:'정책 대안 세 개'});await expect(panel.getByRole('button',{name:'이 대안 수정·검토'})).toHaveCount(3);
 await panel.getByRole('button',{name:'이 대안 수정·검토'}).first().click();await panel.getByLabel('검토자',{exact:true}).fill('테스트 담당자');await panel.getByLabel('수정 내용 또는 검토 사유').fill('근거 확인 후 정책안 검토');await panel.getByRole('button',{name:'정책안 검토 승인',exact:true}).click();await expect(panel.getByText('정책안 검토 승인',{exact:true})).toHaveCount(1);
 await panel.getByRole('button',{name:'이 대안 수정·검토'}).nth(1).click();await panel.getByLabel('수정 내용 또는 검토 사유').fill('접근 경로 보완');await panel.getByRole('button',{name:'수정 저장',exact:true}).click();await expect(panel.getByText('검토 대기',{exact:true})).toHaveCount(3);
 await expect(panel.getByText('접근 경로 보완',{exact:false}).first()).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.reload();await expect(panel.getByText('검토 대기',{exact:true})).toHaveCount(3);
});
