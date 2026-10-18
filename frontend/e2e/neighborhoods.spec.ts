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
  const region=page.locator('svg [role="button"]').filter({hasText:dong.dong_nm});
  await region.focus();await page.keyboard.press('Enter');
  await expect(page.getByTestId('selected-neighborhood')).toHaveText(`${dong.dong_nm} · ${value.stage}단계`);
  await page.getByRole('button',{name:'지도 확대',exact:true}).click();
  await expect(page.getByText('확대 1.5×',{exact:false})).toBeVisible();
  await page.getByLabel('지역',{exact:true}).selectOption('32010');
  await expect(page.locator('svg [role="button"]')).toHaveCount(25);
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
  await expect(page.locator('svg [role="button"]').first()).toHaveAttribute('fill','#b8c3c0');
});
