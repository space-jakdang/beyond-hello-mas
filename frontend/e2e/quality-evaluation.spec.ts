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

test('matching keeps unknown recommendations and missing constraints visible',async({page})=>{
 const matching={rows:[{case_id:'a',neighborhood:'예제동',source:'synthetic',methodology:'v1',policy_as_of:'2026-01-01',state:'partial',output_status:'completed',candidate_count:4,judged_count:3,reference_coverage:.75,suitability_macro_f1:.5,retrieval_recall:.5,recommendation_recall_at_3:.5,recall_at_3_ceiling:1,precision:null,precision_bounds:[1/3,2/3],conditional_rate:null,ndcg_at_3:null,recommended_count:3,unknown_returned:['unknown'],correct_hold:null,constraint_violations:null,constraint_unchecked_resources:3,constraint_checked:0,constraint_unknown:0,retrieval_misses:['missing'],ranking_misses:[],recommendations:[{id:'unknown',reference:'unknown',title:'미평정 정책',url:'https://example.org/policy'}]}],limitations:['고정 후보 평가']};
 await page.route('**/reports/quality**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith(id)?{...detail,matching}:[brief]}));
 await page.goto('/evaluation');const panel=page.getByLabel('자원 매칭 품질');
 await expect(panel).toContainText('독립 평정 3 / 고정 후보 4');await expect(panel).toContainText('미평정 추천 1건');
 await panel.getByText('검색 누락·추천 누락·정책 원문',{exact:true}).press('Enter');
 await expect(panel).toContainText('미평정 정책 · 참조 unknown');await expect(panel.getByRole('link',{name:'정책 원문 ↗'})).toHaveAttribute('href','https://example.org/policy');
});

test('grounding distinguishes evaluator failure from zero and exposes cost scope',async({page})=>{
 const grounding={judge_model:'test-judge',ragas_version:'0.4.3',state:'partial',human_judge_alignment:null,cost_scope:'whole_judge_run_before_filters',cost:{calls:2,reserved_usd:.1,known_usd:.01,unknown_cost_calls:1},rows:[{case_id:'a',role:'workflow_analyst',source_run_id:id,source_call_key:'call',metrics:{faithfulness:{value:0,state:'evaluated'},context_recall:{value:null,state:'failed',error_type:'TimeoutError'}}}],limitations:['분류 정확도가 아닙니다.']};
 await page.route('**/reports/quality**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith(id)?{...detail,grounding}:[brief]}));
 await page.goto('/evaluation');const panel=page.getByLabel('RAGAS 근거 평가');
 await expect(panel).toContainText('0.0%');await expect(panel).toContainText('평가 실패');
 await expect(panel).toContainText('비용 미확인 1회');await expect(panel).toContainText('독립 사람 평정과의 일치도 미검증');
});
