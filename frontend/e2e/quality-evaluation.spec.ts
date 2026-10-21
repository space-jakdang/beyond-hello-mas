import {test,expect} from '@playwright/test';
const id='00000000-0000-4000-8000-000000000001';
const readiness={cases:1,reference_items:2,missing:2,unknown:0,disagreement:0,resolved:0,independent_resolved:0};
const brief={id,dataset:'평가 준비 예제',version:'1',status:'not_evaluated',readiness};
const detail={...brief,dataset_hash:'input-version',label_hash:'label-version',filters:{region:['샘플지역'],period:['2026-01'],methodology:['v1'],source:['synthetic']},cases:[{id:'a',region:'샘플지역',neighborhood:'예제동',period:'2026-01',methodology:'v1',source:'synthetic',references:[{policy_id:null,state:'missing',independent:false,review_count:0,adjudicated:false,provenance:[]}]}],limitations:['실제 지역 성능이 아닙니다.']};
test('quality readiness is distinct from successful execution and works on mobile',async({page})=>{
 await page.route('**/reports/quality**',async route=>{
  const u=new URL(route.request().url());
  await route.fulfill({json:u.pathname.endsWith(id)?detail:[brief]});
 });
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');
 const panel=page.getByTestId('quality-evaluation');
 await expect(panel.getByText('미평가',{exact:true})).toHaveCount(5);
 await expect(panel.getByLabel('기준답 준비 현황')).toContainText('독립 참조 등록0');
 await panel.getByRole('combobox',{name:'지역',exact:true}).selectOption('샘플지역');
 await expect(panel.getByLabel('기준답 준비 현황')).toBeVisible();
 await page.getByRole('button',{name:'평가 결과 새로고침'}).click();
 await expect(panel.getByRole('combobox',{name:'지역',exact:true})).toHaveValue('샘플지역');
 await expect(panel.getByLabel('기준답 준비 현황')).toBeVisible();
 await panel.getByText('예제동 · 2026-01 · 합성 · 1개 미등록',{exact:true}).press('Enter');
 await expect(panel.getByText('지역 등급: 미등록',{exact:false})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
test('quality errors and mode changes clear stale readiness',async({page})=>{
 await page.route('**/reports/quality**',async route=>{
  const u=new URL(route.request().url());
  if(u.searchParams.get('source')==='current'){await route.fulfill({json:[]});return;}
  if(u.pathname.endsWith(id)){await route.fulfill({status:409,json:{detail:'incomplete'}});return;}
  await route.fulfill({json:[{...brief,status:'failed'}]});
 });
 await page.goto('/evaluation');const panel=page.getByTestId('quality-evaluation');
 await expect(panel.getByRole('alert')).toContainText('평가 자료를 읽지 못했습니다');
 await expect(panel.getByLabel('기준답 준비 현황')).toHaveCount(0);
 await page.getByRole('combobox',{name:'평가 자료',exact:true}).selectOption('current');
 await expect(panel).toContainText('등록된 평가 자료가 없습니다');
 await expect(panel.getByRole('alert')).toHaveCount(0);
});

test('classification shows errors and preserves abstentions in its denominator',async({page})=>{
 const classification={model:'test-fixture',method:'rules',version:'1',prediction_hash:'fixture',groups:[{
  source:'synthetic',methodology:'v1',state:'evaluated',input_cases:4,reference_count:4,missing_labels:0,unknown_labels:0,non_independent_labels:0,valid_predictions:3,missing_predictions:1,
  macro_f1:.5,priority_precision:.5,priority_recall:.5,priority_support:2,priority_flagged:2,flag_rate:.5,coverage:.75,mae:2/3,
  confusion:[[1,0,0,0,0,0],[0,0,0,1,0,0],[0,0,0,0,0,0],[0,0,0,0,0,1],[0,0,0,0,1,0]],per_grade:[],errors:[{case_id:'a',neighborhood:'오류예제동',reference:4,predicted:null,status:'abstained',run_id:null}]}]};
 await page.route('**/reports/quality**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith(id)?{...detail,classification}:[brief]}));
 await page.goto('/evaluation');const panel=page.getByLabel('동네 등급 분류 품질');
 await expect(panel).toContainText('독립 참조 4 / 입력 4');await expect(panel).toContainText('미판정 1건은 재현율 분모에 남습니다');
 await panel.getByText('등급별 정밀도·재현율과 실패 사례',{exact:true}).press('Enter');
 await expect(panel).toContainText('오류예제동 · 기준 4 → 예측 미판정');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
