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
