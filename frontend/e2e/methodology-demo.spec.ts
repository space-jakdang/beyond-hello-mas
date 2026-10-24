import {execFileSync} from 'node:child_process';
import {test,expect} from '@playwright/test';

test('three submission examples render actual conditional, revised and held records',async({page})=>{
 test.setTimeout(60000);
 const demo=JSON.parse(execFileSync('uv',['run','python','-m','scripts.prepare_methodology_demo'],{cwd:'..',env:{...process.env,EVALUATION_ID:process.env.PLAYWRIGHT_EVALUATION_ID},encoding:'utf8'}));
 expect(demo.mode).toBe('sample/fake');expect(demo.replay).toBe(false);
 for(const item of demo.cases){
  await page.goto(item.url);await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
  const changes=page.getByRole('region',{name:'판단 보완 결과'});
  if(item.case==='revision'){
   await expect(changes).toContainText('현재 결과에 반영했습니다.');
   await expect(changes.getByRole('table')).toContainText('우선 확인 순서');
  }else await expect(changes).toContainText('저장된 분석 보완은 없습니다.');
  await page.getByRole('tab',{name:'자원 제안'}).click();
  if(item.case==='conditional')await expect(page.locator('.resource-row').first()).toContainText('조건부 검토 후보');
  if(item.case==='unconfirmed_need')await expect(page.locator('.policy-gap-summary').first()).toContainText('서비스 필요 확인 전');
 }
});
