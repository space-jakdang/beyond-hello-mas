import { test, expect } from '@playwright/test';
test('three pages connect to the sample/fake backend', async ({page}) => {
  const initialReady=page.waitForResponse(r=>r.url().endsWith('/readiness')&&r.ok());
  await page.goto('/');await(await initialReady).finished();
  for (const name of ['관찰', '담당자 콘솔', '평가']) {
    const link=page.getByRole('navigation').getByRole('link',{name,exact:true});
    if(!await link.isVisible())await page.getByText('검증·연구 도구',{exact:true}).click();
    const ready=page.waitForResponse(r=>r.url().endsWith('/readiness')&&r.ok());
    await link.click();await(await ready).finished();
    await expect(page.getByRole('heading', {name, exact: true})).toBeVisible();
    await expect(page.getByRole('status').filter({hasText:/자료:/})).toContainText('합성 시연 자료');
  }
});


test('evaluation shows saved JSON counts and metrics',async({page,request})=>{
  const reports=await (await request.get('/reports')).json();
  test.skip(!reports.length,'No saved suite; run make eval first');
  const selected=reports.find((r:any)=>r.schema_version==='2')||reports.find((r:any)=>!['3','4'].includes(r.schema_version));
  test.skip(!selected,'No saved v1/v2 contract report');
  const summary=await(await request.get(`/reports/${selected.id}`)).json();
  await page.goto('/evaluation');
  await page.getByRole('combobox',{name:'평가 실행'}).selectOption(summary.id);
  await expect(page.getByTestId('suite-id')).toHaveText(summary.id);
  await expect(page.getByTestId('suite-count')).toHaveText(String(summary.evaluated_scenarios));
  await expect(page.getByRole('row').filter({has:page.getByRole('rowheader',{name:'실행 경로 일치',exact:true})})).toContainText(String(summary.metrics.path_accuracy.denominator));
  await page.screenshot({path:'../runtime/sample/screenshots/evaluation.png',fullPage:true});
});
