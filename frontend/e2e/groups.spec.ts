import {test,expect} from '@playwright/test';

test('eight-group filters, weekly replay, map and URL stay linked on mobile',async({page,request})=>{
  await page.goto('/neighborhoods?sex=M&age=youth&card_age=20s&week=2025-12-08');
  await expect(page.getByTestId('group-selected')).toBeVisible();
  await page.getByRole('combobox',{name:'성별',exact:true}).selectOption('F');
  await page.getByRole('combobox',{name:'연령집단',exact:true}).selectOption('prime');
  const source=await(await request.get('/analysis/groups')).json();
  const month=source.metadata.selected_week.slice(0,7);
  const row=source.segments.find((r:any)=>r.sgg==='11230'&&r.sex==='F'&&r.age_group==='prime'&&r.ym===month&&r.preferred);
  await page.getByRole('button',{name:row.dong_nm,exact:true}).click();
  await expect(page.getByTestId('group-selected')).toHaveText(`${row.dong_nm} · ${row.stage}단계`);
  await expect(page.locator('.mode-banner').first()).toContainText('합성 데모 자료');
  await expect(page.locator('.mode-banner').first()).toContainText('강남구');
  await expect(page.getByTestId('group-result-summary')).toContainText('우선 확인');
  await page.reload();
  await expect(page.getByRole('combobox',{name:'성별',exact:true})).toHaveValue('F');
  await expect(page.getByRole('combobox',{name:'연령집단',exact:true})).toHaveValue('prime');
  await page.getByRole('combobox',{name:'연령집단',exact:true}).selectOption('youth');
  const firstWeek=source.weekly.weeks[0];
  await page.getByRole('combobox',{name:'신호 주',exact:true}).selectOption(firstWeek);
  await expect(page.getByTestId('group-detail')).toContainText('"baseline": null');
  await expect(page.getByTestId('group-detail')).toContainText('비교 기준이 없어 신호를 계산하지 않았습니다.');
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
  await page.goto('/neighborhoods?sex=M&age=elderly&card_age=20s&week=2025-12-08');
  await expect(page.getByTestId('group-selected')).toContainText('1단계');
  await page.getByRole('combobox',{name:'단계 기준',exact:true}).selectOption('seoul');
  await expect(page.getByTestId('group-selected')).toContainText('5단계');
  const detail=page.getByTestId('group-detail');
  await expect(detail).toContainText('서울 제공 비교 지표');
  await expect(detail.locator('details')).not.toHaveAttribute('open');
  await detail.getByText('자료 출처와 계산 기준 보기').click();
  await expect(detail.locator('details')).toContainText('G_seoul');
});


test('source evidence starts with readable cards and raw data is collapsed',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/neighborhoods?sex=M&age=youth&card_age=20s&week=2025-12-08');
 await expect(page.getByLabel('주간 지표 코드 T1b 요약')).toContainText('직전 8관측주 기준선');
 const detail=page.getByTestId('group-detail'),summary=detail.getByText('자료 출처와 계산 기준 보기',{exact:true});
 await expect(detail.locator('pre')).toBeHidden();
 await summary.focus();await page.keyboard.press('Enter');
 await expect(detail.locator('pre')).toBeVisible();
 await page.keyboard.press('Enter');
 await expect(detail.locator('pre')).toBeHidden();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('both sexes preserve source stages, selection, URL and missing rows',async({page,request})=>{
 const data=await(await request.get('/analysis/groups')).json();
 const dongs=data.neighborhoods.filter((d:any)=>d.sgg==='11230');
 const selected=dongs[1];
 await page.goto('/neighborhoods?sex=all&age=youth&card_age=20s&week=2025-12-08');
 const male=page.getByRole('region',{name:'남성 분석 패널',exact:true}),female=page.getByRole('region',{name:'여성 분석 패널',exact:true});
 await expect(male).toBeVisible();await expect(female).toBeVisible();
 expect(await male.getByRole('img',{name:'주간 카드 지표의 기준선 대비 비율'}).locator('line').getAttribute('y1')).toBe(await female.getByRole('img',{name:'주간 카드 지표의 기준선 대비 비율'}).locator('line').getAttribute('y1'));
 await page.getByRole('region',{name:'남녀 동별 단계 비교'}).getByRole('button',{name:selected.dong_nm,exact:true}).click();
 for(const [sex,panel] of [['M',male],['F',female]] as const){
  const row=data.segments.find((r:any)=>r.dong_cd===selected.dong_cd&&r.sex===sex&&r.age_group==='youth'&&r.preferred&&r.ym===data.metadata.selected_week.slice(0,7));
  await expect(panel.getByTestId('group-detail')).toContainText(`${row.stage}단계`);
  await expect(panel.getByRole('link',{name:/지역 업무 시작/})).toHaveAttribute('href',new RegExp('sex='+sex));
 }
 await page.getByRole('combobox',{name:'성별',exact:true}).selectOption('F');
 await page.goBack();await expect(male).toBeVisible();
 const reloadSource=page.waitForResponse(r=>r.url().includes('/analysis/groups?')&&r.ok());
 await page.reload();await(await reloadSource).finished();await expect(female).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 data.segments=data.segments.filter((r:any)=>!(r.dong_cd===selected.dong_cd&&r.sex==='F'));
 await page.route('**/analysis/groups*',route=>route.fulfill({json:data}));await page.reload();
 await expect(female).toContainText('선택한 동의 성별 자료 없음');await expect(female.getByRole('link',{name:/지역 업무 시작/})).toHaveCount(0);
 await expect(female.getByRole('button',{name:`${selected.dong_nm} 자료 없음`})).toBeVisible();
 await expect(male.getByTestId('group-detail')).toBeVisible();
 await page.getByRole('combobox',{name:'지역',exact:true}).selectOption('32010');
 await expect(male).toContainText('춘천시');await expect(female).toContainText('춘천시');
});


test('all four filters default to all and preserve independent cohorts',async({page,request})=>{
 await page.goto('/neighborhoods');
 const source=await(await request.get('/analysis/groups?week=all&card_age=all')).json();
 const month=source.months.at(-1),dong=source.neighborhoods.find((d:any)=>d.sgg==='11230');
 const rows=source.segments.filter((r:any)=>r.dong_cd===dong.dong_cd&&r.preferred&&r.ym===month);
 await expect(page.getByRole('region',{name:'전체 집단 요약'}).locator('tbody tr').first()).toContainText(`미평가 · ${rows.filter((r:any)=>r.stage!==null).length}/8개`);
 for(const name of ['성별','연령집단','신호 주','카드 연령'])await expect(page.getByRole('combobox',{name,exact:true})).toHaveValue('all');
 await expect(page.getByRole('region',{name:'선택한 동의 집단별 결과'}).locator('table').first().locator('tbody tr')).toHaveCount(8);
 await page.getByRole('combobox',{name:'성별',exact:true}).selectOption('F');
 await expect(page.getByRole('region',{name:'선택한 동의 집단별 결과'}).locator('table').first().locator('tbody tr')).toHaveCount(4);
 await page.goBack();await page.reload();
 await expect(page.getByRole('region',{name:'선택한 동의 집단별 결과'}).locator('table').first().locator('tbody tr')).toHaveCount(8,{timeout:20000});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('cohort matrix preserves 4/8 source cells, missing data and keyboard drilldown',async({page,request})=>{
 const data=await(await request.get('/analysis/groups?week=all&card_age=all')).json();
 const dong=data.neighborhoods.find((d:any)=>d.sgg==='11230'),month=data.months.at(-1);
 data.segments=data.segments.filter((r:any)=>!(r.dong_cd===dong.dong_cd&&r.sex==='F'&&r.age_group==='elderly'));
 await page.route('**/analysis/groups*',route=>route.fulfill({json:data}));
 await page.goto('/neighborhoods?sex=all&age=all');
 const matrix=page.getByRole('table',{name:'동별 성별 × 연령집단 단계'});
 await expect(matrix.getByRole('columnheader')).toHaveCount(9);
 for(const sex of ['M','F'])for(const [age,name] of Object.entries({youth:'청년',midlife:'중년',prime:'장년',elderly:'노년'})){
  const r=data.segments.find((r:any)=>r.dong_cd===dong.dong_cd&&r.sex===sex&&r.age_group===age&&r.preferred&&(r.ym===null||r.ym===month));
  await expect(matrix.getByRole('button',{name:new RegExp(`${dong.dong_nm} ${sex==='M'?'남성':'여성'} ${name} .* 상세 보기`)})).toHaveText(!r?'자료 없음':r.stage===null?'미평가':`${r.stage}단계`);
 }
 const details=page.getByRole('region',{name:'선택한 동의 집단별 결과',exact:true});
 await expect(details.locator('table').first().locator('tbody tr')).toHaveCount(8);await expect(details).toContainText('자료 없음');
 await page.getByRole('combobox',{name:'성별',exact:true}).selectOption('M');
 await expect(matrix.getByRole('columnheader')).toHaveCount(5);
 const cell=matrix.getByRole('button',{name:new RegExp(`${dong.dong_nm} 남성 청년 .* 상세 보기`)});
 await cell.focus();await page.keyboard.press('Enter');
 await expect(page.getByRole('combobox',{name:'연령집단',exact:true})).toHaveValue('youth');
 await expect(page.getByTestId('group-detail')).toBeVisible();
 await page.goBack();await expect(matrix.getByRole('columnheader')).toHaveCount(5);
 await page.goBack();await page.reload();await expect(matrix.getByRole('columnheader')).toHaveCount(9);
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('unknown regional labels stay generic until source details are opened',async({page,request})=>{
 const data=await(await request.get('/analysis/groups')).json(),month=data.metadata.selected_week.slice(0,7);
 const source=data.segments.find((r:any)=>r.sgg==='11230'&&r.sex==='M'&&r.age_group==='youth'&&r.preferred&&r.ym===month);
 const target={...source,index_name:'UNRECOGNIZED_INDEX',stage:null,source_period:'2026-10-18 delivered summary',source_bands:{unrecognized_source:['unknown-band']},flags:['unrecognized_flag'],weekly:{...source.weekly,metrics:{...source.weekly.metrics,T1b:{...source.weekly.metrics.T1b,ratio:1.0001}}}};
 data.segments=data.segments.map((r:any)=>r===source?target:r);
 await page.route('**/analysis/groups*',route=>route.fulfill({json:data}));
 await page.goto(`/neighborhoods?sex=M&age=youth&dong=${source.dong_cd}&week=${data.metadata.selected_week}&card_age=20s`);
 const detail=page.getByTestId('group-detail');
 await expect(detail).toContainText('지역 지표');
 await expect(detail).toContainText('자료 출처 확인 필요');
 await expect(detail).toContainText('연령 범위 확인 필요');
 await expect(detail).toContainText('2026년 10월 18일 자료 기준');
 await expect(detail).toContainText('기준선과 거의 같음 (1.000배)');
 await expect(page.getByRole('button',{name:`${source.dong_nm} 미평가`})).toBeVisible();
 await expect(detail.locator('details')).not.toHaveAttribute('open');
 await detail.getByText('자료 출처와 계산 기준 보기').click();
 await expect(detail.locator('details')).toContainText('UNRECOGNIZED_INDEX');
 await expect(detail.locator('details')).toContainText('unknown-band');
 await expect(detail.locator('details')).toContainText('unrecognized_flag');
});

test('v4 source ages keep hold, insufficient, partial card baseline, week and workspace link distinct',async({page,request})=>{
 const base=await(await request.get('/analysis/groups')).json(),dongs=base.neighborhoods.filter((d:any)=>d.sgg==='32010'),chosen=dongs[0],other=dongs[1];
 const evidence=(age:string,baseline:'observed'|'unavailable',v:number|null,n:number|null,alarm:number)=>({source_age_band:age,baseline_status:baseline,v_ratio:v,n_ratio:n,v_stage:baseline==='observed'?alarm:0,n_stage:baseline==='observed'?alarm:0,alarm_stage:alarm});
 const group=(dong:any,age:string,stage:number,rank:number,cardStatus:string,cards:any[])=>({dataset_version:'seohee-region-20261025-1',source_region:'춘천',sgg:'32010',dong_cd:dong.dong_cd,dong_nm:dong.dong_nm,source_dong_name:dong.dong_nm,sex:'F',source_age_band:age,frame:age==='20대'?'청년':age==='30대'?'중년':'노년',source_bands:{dong_stage_age:[age]},source_stage:stage,source_stage_label:stage===-1?'판정 근거 부족':stage===0?'판정 보류':'관심',assessment_status:stage===-1?'insufficient_evidence':stage===0?'small_population_hold':'assessed',base_stage:stage>0?stage:null,card_week:'2025-12-15',card_source_age_bands:cards.map(c=>c.source_age_band),card_evidence:cards,card_alarm_stage:cardStatus==='strong'?2:cardStatus==='weak'?1:null,card_alarm_status:cardStatus,stage_adjustment:stage>0&&cardStatus==='strong'?1:0,final_stage:stage>0?Math.min(5,stage+(cardStatus==='strong'?1:0)):null,final_stage_label:stage===-1?'판정 근거 부족':stage===0?'판정 보류':cardStatus==='strong'?'주의':'관심',priority_group:null,weakness_count:1,population:stage===0?45:700,reason:'원천 근거 예시',structural_risk_ratio:null,priority_rank:rank});
 const partial=[evidence('60대','observed',1.2,1.1,2),evidence('70대+','unavailable',null,null,0)];
 const signals=['60대','70대+','20대','30대'].flatMap(age=>['2025-12-08','2025-12-15'].map(week=>({source_region:'춘천',sex:'F',source_age_band:age,week,v_ratio:week.endsWith('15')?1.2:null,n_ratio:week.endsWith('15')?1.1:null,v_stage:week.endsWith('15')?2:0,n_stage:week.endsWith('15')?2:0,alarm_stage:week.endsWith('15')?2:0,baseline_status:week.endsWith('15')?'observed':'unavailable'})));
 const fixture={...base,data_mode:'local',period_aggregate:true,segments:[group(chosen,'60대+',2,1,'strong',partial),group(chosen,'20대',0,2,'none',[evidence('20대','observed',1,1,0)]),group(chosen,'30대',-1,3,'baseline_unavailable',[evidence('30대','unavailable',null,null,0)]),group(other,'60대+',1,4,'none',[evidence('60대','observed',1,1,0)])],weekly:{selected_week:'2025-12-15',signals},metadata:{workflow_version:'regional-workflow-2',methodology_version:'seohee-region-20261025-1',dataset_version:'seohee-region-20261025-1',selected_week:'2025-12-15',input_schema_version:4,input_hash:'private-test-hash',weekly_scope:'region × sex × source age band; not dong observations',source:{source:'segments-v4.parquet',sha256:'stage-hash'},card_source:{source:'card_alarm_weekly.csv',sha256:'card-hash'}}};
 await page.route('**/analysis/groups?*',route=>{const week=new URL(route.request().url()).searchParams.get('week')||'2025-12-15';void route.fulfill({json:{...fixture,metadata:{...fixture.metadata,selected_week:week},weekly:{...fixture.weekly,selected_week:week},segments:fixture.segments.map((r:any)=>({...r,card_week:week}))}});});
 await page.goto(`/neighborhoods?workflow_version=regional-workflow-2&region=32010&sex=F&source_age_band=60%EB%8C%80%2B&card_week=2025-12-15&dong=${chosen.dong_cd}&age=youth&card_age=20s`);
 await expect(page.locator('.mode-banner').first()).toContainText('실제 지역 자료');await expect(page.locator('.mode-banner').first()).toContainText('2025-12-15');
 await expect(page.getByTestId('v4-group-detail-F')).toContainText('부분 기준선 · 강한 경보');await expect(page.getByTestId('v4-group-detail-F')).toContainText('60대, 70대+');
 const link=page.getByRole('link',{name:'지역 업무 시작'}).first();await expect(link).toHaveAttribute('href',/workflow_version=regional-workflow-2/);await expect(link).toHaveAttribute('href',/source_age_band=60/);await expect(link).toHaveAttribute('href',/card_week=2025-12-15/);await link.click();await expect(page).toHaveURL(/\/workspace\?/);await expect(page.getByRole('combobox',{name:'원천 연령'})).toHaveValue('60대+');await expect(page.getByRole('combobox',{name:'카드 기준 주'})).toHaveValue('2025-12-15');await page.reload();await expect(page.getByRole('combobox',{name:'원천 연령'})).toHaveValue('60대+');await expect(page.getByRole('combobox',{name:'카드 기준 주'})).toHaveValue('2025-12-15');await page.goBack();
 await page.getByRole('combobox',{name:'카드 관측 주'}).selectOption('2025-12-08');await expect(page).toHaveURL(/card_week=2025-12-08/);await page.reload();await expect(page.getByRole('combobox',{name:'카드 관측 주'})).toHaveValue('2025-12-08');
 await page.getByRole('combobox',{name:'원천 연령'}).selectOption('30대');await expect(page.getByTestId('v4-group-detail-F')).toContainText('판정 근거 부족 (−1)');
 await page.getByRole('combobox',{name:'원천 연령'}).selectOption('20대');await expect(page.getByTestId('v4-group-detail-F')).toContainText('소규모 인구 보류 (0)');
 await page.getByRole('combobox',{name:'원천 연령'}).selectOption('60대+');const mapButton=page.getByRole('button',{name:new RegExp(`${chosen.dong_nm} .*주의`)});await mapButton.focus();await page.keyboard.press('Enter');await expect(mapButton).toHaveAttribute('aria-pressed','true');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
