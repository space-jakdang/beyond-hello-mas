import {test, expect} from '@playwright/test';

test('Supervisor delegates policy research and exposes tool observations and missing data',async ({page,request})=>{
  await page.goto('/observatory');
  await page.getByLabel('조사 목표').fill('합성 테스트: 고립 지원 정책 조사');
  await page.getByRole('button',{name:'정책 조사 위임',exact:true}).click();
  await expect(page.getByTestId('policy-result')).toBeVisible({timeout:15000});
  await expect(page.getByTestId('policy-result')).toContainText('missing_credentials');
  await expect(page.getByText('실행 경로: supervisor → policy',{exact:true})).toBeVisible();
  const id=await page.getByTestId('run-id').innerText();
  const overview=await (await request.get(`/runs/${id}/overview`)).json();
  expect(overview.policy.status).toBe('search_incomplete');
  expect(overview.policy.allocation_performed).toBe(false);
  expect(overview.traces.some((t:any)=>t.agent==='supervisor' && t.kind==='route' && t.payload.worker==='policy')).toBe(true);
  expect(overview.traces.some((t:any)=>t.agent==='policy' && t.kind==='tool_result')).toBe(true);
  await page.reload();
  await expect(page.getByTestId('policy-result')).toContainText('missing_credentials');
});
