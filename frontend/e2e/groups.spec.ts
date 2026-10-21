import {test,expect} from '@playwright/test';

test('eight-group filters, weekly replay, map and URL stay linked on mobile',async({page,request})=>{
  await page.goto('/neighborhoods');
  await expect(page.getByTestId('group-selected')).toBeVisible();
  await page.getByRole('combobox',{name:'성별',exact:true}).selectOption('F');
  await page.getByRole('combobox',{name:'연령집단',exact:true}).selectOption('prime');
  const source=await(await request.get('/analysis/groups')).json();
  const month=source.metadata.selected_week.slice(0,7);
  const row=source.segments.find((r:any)=>r.sgg==='11230'&&r.sex==='F'&&r.age_group==='prime'&&r.ym===month&&r.preferred);
  await page.getByRole('button',{name:row.dong_nm,exact:true}).click();
  await expect(page.getByTestId('group-selected')).toHaveText(`${row.dong_nm} · ${row.stage}단계`);
  await page.reload();
  await expect(page.getByRole('combobox',{name:'성별',exact:true})).toHaveValue('F');
  await expect(page.getByRole('combobox',{name:'연령집단',exact:true})).toHaveValue('prime');
  await page.getByRole('combobox',{name:'연령집단',exact:true}).selectOption('youth');
  const firstWeek=source.weekly.weeks[0];
  await page.getByRole('combobox',{name:'신호 주',exact:true}).selectOption(firstWeek);
  await expect(page.getByTestId('group-detail')).toContainText('"baseline": null');
  const map=page.getByRole('button',{name:new RegExp(row.dong_nm+' .*단계')});
  await map.focus();await page.keyboard.press('Enter');
  await expect(map).toHaveAttribute('aria-pressed','true');
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByTestId('group-detail')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
  await page.screenshot({path:'../runtime/sample/screenshots/groups-mobile.png',fullPage:true});
});

test('Seoul and within-Gangnam comparison use their own stage rows',async({page,request})=>{
  const data=await(await request.get('/analysis/groups')).json();
  const ranks=data.segments.filter((r:any)=>r.index_name==='G_seoul').map((r:any)=>({...r,index_name:'G_gangnam_rank',stage:1,preferred:true}));
  data.segments=data.segments.map((r:any)=>r.index_name==='G_seoul'?{...r,preferred:false,stage:5}:r).concat(ranks);
  await page.route('**/analysis/groups*',route=>route.fulfill({json:data}));
  await page.goto('/neighborhoods?age=elderly');
  await expect(page.getByTestId('group-selected')).toContainText('1단계');
  await page.getByRole('combobox',{name:'단계 기준',exact:true}).selectOption('seoul');
  await expect(page.getByTestId('group-selected')).toContainText('5단계');
  await expect(page.getByTestId('group-detail')).toContainText('G_seoul');
});


test('source evidence starts with readable cards and raw data is collapsed',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/neighborhoods');
 await expect(page.getByLabel('T1b 요약')).toContainText('직전 8관측주 기준선');
 await expect(page.getByTestId('group-detail').locator('pre')).toBeHidden();
 await page.getByText('원천 기록 자세히 보기',{exact:true}).click();
 await expect(page.getByTestId('group-detail').locator('pre')).toBeVisible();
 await page.getByText('원천 기록 자세히 보기',{exact:true}).click();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('both sexes preserve source stages, selection, URL and missing rows',async({page,request})=>{
 const data=await(await request.get('/analysis/groups')).json();
 const dongs=data.neighborhoods.filter((d:any)=>d.sgg==='11230');
 const selected=dongs[1];
 await page.goto('/neighborhoods?sex=all');
 const male=page.getByRole('region',{name:'남성 분석 패널',exact:true}),female=page.getByRole('region',{name:'여성 분석 패널',exact:true});
 await expect(male).toBeVisible();await expect(female).toBeVisible();
 expect(await male.getByRole('img',{name:'T1b R1 주간 비율'}).locator('line').getAttribute('y1')).toBe(await female.getByRole('img',{name:'T1b R1 주간 비율'}).locator('line').getAttribute('y1'));
 await page.getByRole('region',{name:'남녀 동별 단계 비교'}).getByRole('button',{name:selected.dong_nm,exact:true}).click();
 for(const [sex,panel] of [['M',male],['F',female]] as const){
  const row=data.segments.find((r:any)=>r.dong_cd===selected.dong_cd&&r.sex===sex&&r.age_group==='youth'&&r.preferred&&r.ym===data.metadata.selected_week.slice(0,7));
  await expect(panel.getByTestId('group-detail')).toContainText(`${row.stage}단계`);
  await expect(panel.getByRole('link',{name:/Supervisor/})).toHaveAttribute('href',new RegExp('sex='+sex));
 }
 await page.getByRole('combobox',{name:'성별',exact:true}).selectOption('F');
 await page.goBack();await expect(male).toBeVisible();await page.reload();await expect(female).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 data.segments=data.segments.filter((r:any)=>!(r.dong_cd===selected.dong_cd&&r.sex==='F'));
 await page.route('**/analysis/groups*',route=>route.fulfill({json:data}));await page.reload();
 await expect(female).toContainText('선택한 동의 성별 자료 없음');await expect(female.getByRole('link',{name:/Supervisor/})).toHaveCount(0);
 await expect(male.getByTestId('group-detail')).toBeVisible();
 await page.getByRole('combobox',{name:'지역',exact:true}).selectOption('32010');
 await expect(male).toContainText('춘천시');await expect(female).toContainText('춘천시');
});
