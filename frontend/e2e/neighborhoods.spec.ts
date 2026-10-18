import {test,expect} from '@playwright/test';

test('neighborhood map filters and keyboard selection match API stages',async({page,request})=>{
  const data=await(await request.get('/analysis')).json();
  await page.goto('/neighborhoods');
  await expect(page.getByRole('heading',{name:'동네 분석',exact:true})).toBeVisible();
  await expect(page.getByText('합성 데이터 · 격자는 실제 동네 위치가 아닙니다.',{exact:false})).toBeVisible();
  await page.getByLabel('분석 월',{exact:true}).selectOption('2025-07');
  await page.getByLabel('연령',{exact:true}).selectOption('20s');
  const dong=data.neighborhoods[1];
  const value=data.segments.find((s:any)=>s.ym==='2025-07'&&s.age_band==='20s'&&s.dong_cd===dong.dong_cd);
  const region=page.locator('svg[aria-label="합성 동 격자"] [role="button"]').filter({hasText:dong.dong_nm});
  await region.focus();await page.keyboard.press('Enter');
  await expect(page.getByTestId('selected-neighborhood')).toHaveText(`${dong.dong_nm} · ${value.stage}단계`);
  await page.getByRole('button',{name:'지도 확대',exact:true}).click();
  await expect(page.getByText('확대 1.5×',{exact:false})).toBeVisible();
  await page.getByLabel('지역',{exact:true}).selectOption('32010');
  await expect(page.locator('svg[aria-label="합성 동 격자"] [role="button"]')).toHaveCount(25);
  await expect(page.getByText('확대 1×',{exact:false})).toBeVisible();
  await page.screenshot({path:'../runtime/sample/screenshots/neighborhoods.png',fullPage:true});
});

test('analysis errors can retry and missing stages stay missing',async({page,request})=>{
  const data=await(await request.get('/analysis')).json();
  data.segments.forEach((s:any)=>{s.stage=null;});
  let fail=true;
  await page.route('**/analysis',route=>fail?route.fulfill({status:503,body:'분석 입력 없음'}):route.fulfill({json:data}));
  await page.goto('/neighborhoods');
  await expect(page.getByRole('alert')).toContainText('503');
  fail=false;await page.getByRole('button',{name:'분석 다시 불러오기'}).click();
  await expect(page.getByTestId('selected-neighborhood')).toContainText('결측');
  await expect(page.locator('svg[aria-label="합성 동 격자"] [role="button"]').first()).toHaveAttribute('fill','#b8c3c0');
});

test('detail values, chart clicks, URL restore and responsive layout stay linked',async({page,request})=>{
  const data=await(await request.get('/analysis')).json();
  const dong=data.neighborhoods.find((d:any)=>d.sgg==='32010');
  const expected=data.segments.find((s:any)=>s.dong_cd===dong.dong_cd&&s.ym==='2025-08'&&s.age_band==='20s');
  await page.goto(`/neighborhoods?region=32010&month=2025-08&age=20s&dong=${dong.dong_cd}`);
  await expect(page.getByRole('table',{name:'연령별 분석 결과'}).getByRole('row').filter({has:page.getByRole('button',{name:'20대',exact:true})})).toContainText(expected.score.toFixed(3));
  await expect(page.getByRole('table',{name:'원지표와 점수 기여도'}).getByRole('row').filter({has:page.getByRole('rowheader',{name:'20대',exact:true})})).toContainText(expected.indicators.age_share.toFixed(3));
  await page.getByRole('group',{name:'월별 단계 추이'}).getByRole('button',{name:/2025-07 단계/}).click();
  await expect(page.getByLabel('분석 월',{exact:true})).toHaveValue('2025-07');
  await expect(page).toHaveURL(/month=2025-07/);
  await page.reload();await expect(page.getByLabel('분석 월',{exact:true})).toHaveValue('2025-07');
  await page.goBack();await expect(page.getByLabel('분석 월',{exact:true})).toHaveValue('2025-08');
  await page.getByRole('table',{name:'연령별 분석 결과'}).getByRole('button',{name:'30대',exact:true}).click();
  await expect(page.getByLabel('연령',{exact:true})).toHaveValue('30s');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:'../runtime/sample/screenshots/neighborhood-details-mobile.png',fullPage:true});
});

test('trend gaps are not connected and refresh reads new analysis',async({page,request})=>{
  const data=await(await request.get('/analysis')).json();const dong=data.neighborhoods[0];
  data.segments.forEach((s:any)=>{if(s.ym==='2025-09'){s.stage=null;s.score=null;}});
  await page.route('**/analysis',route=>route.fulfill({json:data}));
  await page.goto(`/neighborhoods?month=2025-08&age=20s&dong=${dong.dong_cd}`);
  await expect(page.getByTestId('trend-line-stage')).toHaveCount(2);
  await expect(page.getByTestId('trend-line-score')).toHaveCount(2);
  await expect(page.getByRole('group',{name:'월별 단계 추이'}).getByRole('button',{name:/2025-09/})).toHaveCount(0);
  data.segments.forEach((s:any)=>{s.stage=1;});
  await page.getByRole('button',{name:'분석 새로고침',exact:true}).click();
  await expect(page.getByTestId('selected-neighborhood')).toHaveText(`${dong.dong_nm} · 1단계`);
});
