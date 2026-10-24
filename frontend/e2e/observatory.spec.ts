import {test, expect} from '@playwright/test';
test('execute, inspect, restore, switch and reconnect a run', async ({page, context}) => {
  await page.goto('/observatory');
  await page.getByRole('button', {name:'실행', exact:true}).click();
  await expect(page.getByTestId('run-status')).toHaveText('승인 대기');
  const id = await page.getByTestId('run-id').innerText();
  await page.getByTestId('trace-row').first().click();
  await expect(page.getByRole('heading', {name:'이벤트 상세 #1'})).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('run-id')).toHaveText(id);
  await expect(page.getByTestId('trace-row').first()).toBeVisible();
  const count = await page.getByTestId('trace-row').count();
  await context.setOffline(true);
  await page.waitForTimeout(2200);
  await context.setOffline(false);
  await expect(page.getByText('실시간 기록 연결: 연결됨', {exact:true})).toBeVisible({timeout:15000});
  await expect.poll(()=>page.getByTestId('trace-row').count()).toBeGreaterThanOrEqual(count);
  const seqs = await page.getByTestId('trace-row').allTextContents();
  expect(new Set(seqs).size).toBe(seqs.length);
  await page.getByLabel('시나리오').selectOption('1');
  await page.getByRole('button', {name:'실행', exact:true}).click();
  await expect(page.getByTestId('run-id')).not.toHaveText(id);
  await expect(page.getByTestId('run-status')).toHaveText('완료');
  await expect(page.getByRole('heading', {name:'이벤트 상세 #1'})).toHaveCount(0);
  await page.getByLabel('실행 이력').selectOption(id);
  await expect(page.getByTestId('run-status')).toHaveText('승인 대기');
  await page.getByRole('button', {name:'기록 재생'}).click();
  await page.getByLabel('재생 배속').selectOption('4');
  await expect.poll(()=>page.getByTestId('trace-row').count()).toBeGreaterThanOrEqual(count);
  await page.screenshot({path:'../runtime/sample/screenshots/observatory.png', fullPage:true});
});


test('empty observatory guides a real regional task without starting a run',async({page})=>{
 let starts=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/scenarios/run'))starts++;});
 await page.goto('/observatory');
 await expect(page.getByLabel('개발·연구 도구 안내')).toContainText('실제 개인 판정');
 await expect(page.getByLabel('협업 관찰 시작 안내')).toContainText('추가 조회와 보완 확인');
 await expect(page.getByLabel('온라인 실행 그래프')).toHaveCount(0);
 await page.getByRole('link',{name:'지도에서 지역 업무 시작 →'}).click();
 await expect(page).toHaveURL(/neighborhoods/);expect(starts).toBe(0);
});

test('observatory explains failures and keeps API detail behind a disclosure',async({page})=>{
 await page.route('**/runs',route=>route.fulfill({status:503,json:{detail:'private trace failure'}}));
 await page.goto('/observatory');
 const alert=page.getByRole('alert');
 await expect(alert).toContainText('실행 이력을 불러오지 못했습니다');
 await expect(page.getByText('시나리오를 실행하거나 이전 실행을 선택하세요.')).toHaveCount(0);
 await expect(alert.locator('pre')).toBeHidden();
 await alert.getByText('기술 오류 상세',{exact:true}).click();
 await expect(alert).toContainText('private trace failure');
});
