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
 await Promise.all([page.waitForResponse(r=>r.url().includes(`/reports/quality/${id}?`)&&r.ok()),page.getByRole('button',{name:'평가 결과 새로고침'}).click()]);
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

test('method comparison exposes worse MAS and distinguishes synthetic from generalization',async({page})=>{
 const study={version:'fixture',protocol_hash:'hash',groups:[{source:'synthetic',methodology:'v1',split:'test',region:'샘플지역',period:'2026-01',case_count:4,family_count:3,transfer_scope:'synthetic_robustness',temporal_scope:'not_evaluated',arms:[{method:'mas',failed:1,resource_failed:0,abstained:0,missing:1,classification:{macro_f1:.5,priority_recall:.5}}],paired:[{baseline:'single',challenger:'mas',family_count:3,grade_accuracy_delta:-.25,corrected_cases:0,introduced_errors:1,ranking_family_count:0,ndcg_delta:null}]}],costs:[],limitations:['통계적 유의성 미평가']};
 await page.route('**/reports/quality**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith(id)?{...detail,study}:[brief]}));
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');
 const panel=page.getByLabel('지역·기간 및 MAS 비교');await expect(panel).toContainText('합성 견고성');await expect(panel).toContainText('실제 미래 예측 미평가');await expect(panel).toContainText('-25.0%p');await expect(panel).toContainText('새 오류 1');await expect(panel).toContainText('분류 개선 미확인');
 await panel.getByText('비용·지연 — 필터 전 전체 실행',{exact:true}).press('Enter');await expect(panel).toContainText('장부 대조 전');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});


test('evaluation execution restores history and blocks incompatible comparisons on mobile',async({page})=>{
 const jobId='00000000-0000-4000-8000-000000000002';let posts=0;
 const saved={comparison_key:'compatible',judge_model:null,judge_price_version:null,id:jobId,report_id:id,source:'sample',suite:'deterministic',version:'quality-job-1',status:'completed',created_at:'2026-01-01T00:00:00Z',error:null,result:{dataset_hash:'inputs',label_hash:'labels',status:'not_evaluated'}};
 const incompatible={...saved,id:'00000000-0000-4000-8000-000000000003',result:{...saved.result,label_hash:'different'}};
 await page.route('**/reports/quality**',async route=>{
  const u=new URL(route.request().url());let json:unknown;
  if(u.pathname.endsWith('/preflight'))json={grounding_available:false,grounding_reasons:['독립 참조 미등록'],grounding_max_reservation_usd:null,limitations:['미평가를 성공으로 바꾸지 않습니다.']};
  else if(u.pathname.endsWith('/jobs')){if(route.request().method()==='POST'){posts++;json=saved;}else json=posts?[saved,incompatible]:[];}
  else json=u.pathname.endsWith(id)?detail:[brief];
  await route.fulfill({json});
 });
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');
 let panel=page.getByLabel('평가 실행과 저장 이력');await panel.getByRole('button',{name:'평가 실행·저장'}).press('Enter');await expect(panel).toContainText('계산 완료는 품질 통과가 아닙니다');await expect.poll(()=>posts).toBe(1);
 await page.reload();panel=page.getByLabel('평가 실행과 저장 이력');await expect(panel.getByRole('combobox',{name:'저장 실행',exact:true})).toHaveValue(jobId);
 await panel.getByRole('combobox',{name:'비교 실행',exact:true}).selectOption(incompatible.id);await expect(panel).toContainText('비교 불가');expect(posts).toBe(1);
 await panel.getByText('저장 결과 펼치기',{exact:true}).press('Enter');await expect(panel).toContainText('기술적 결과');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('real evaluation API saves missing-reference results and reuses the job after reload',async({page,request})=>{
 const {execFileSync}=await import('node:child_process');const {resolve,basename}=await import('node:path');const {rmSync}=await import('node:fs');
 const folder=execFileSync('uv',['run','python','-m','eval.prepare_quality','eval/fixtures/quality-synthetic.json'],{cwd:'..',encoding:'utf8'}).trim();const reportId=basename(folder);
 try{
  await page.goto('/evaluation');await page.getByRole('combobox',{name:'품질 평가 자료',exact:true}).selectOption(reportId);
  const panel=page.getByLabel('평가 실행과 저장 이력');await panel.getByRole('button',{name:'평가 실행·저장'}).click();
  await expect(panel).toContainText('계산 완료는 품질 통과가 아닙니다');
  await expect.poll(async()=>{const r=await request.get(`/reports/quality/${reportId}/jobs?source=sample`);return (await r.json())[0]?.status;},{timeout:20000}).toBe('completed');
  const history=await request.get(`/reports/quality/${reportId}/jobs?source=sample`);const [saved]=await history.json();
  expect(saved.status).toBe('completed');expect(saved.result.status).toBe('not_evaluated');expect(saved).not.toHaveProperty('snapshot');
  const repeated=await request.post(`/reports/quality/${reportId}/jobs?source=sample`,{data:{suite:'deterministic'}});expect((await repeated.json()).id).toBe(saved.id);
  expect((await request.get(`/quality-jobs/${saved.id}`)).ok()).toBe(true);
  await page.reload();await page.getByRole('combobox',{name:'품질 평가 자료',exact:true}).selectOption(reportId);await expect(page.getByLabel('평가 실행과 저장 이력')).toContainText(saved.id);
 }finally{rmSync(resolve('..',folder),{recursive:true});}
});

test('case evidence links to the existing regional workspace without inventing evidence',async({page})=>{
 await page.route('**/reports/quality**',route=>{const u=new URL(route.request().url());return route.fulfill({json:u.pathname.endsWith('/evidence')?{run_id:id,rows:[],reason:'해당 관측 근거의 자원 제안 기록이 없습니다.'}:u.pathname.endsWith(id)?detail:[brief]});});
 await page.goto('/evaluation');await page.getByText('예제동 · 2026-01 · 합성 · 1개 미등록',{exact:true}).press('Enter');await page.getByRole('button',{name:'이 사례의 추천 근거 조회'}).click();
 await expect(page.getByRole('link',{name:'원래 에이전트 실행 보기 →'})).toHaveAttribute('href',`/workspace?run=${id}`);await expect(page.getByText('해당 관측 근거의 자원 제안 기록이 없습니다.',{exact:true})).toBeVisible();
});

test('policy design quality keeps independent scores missing and exposes disagreement',async({page})=>{
 const policy_design={rows:[{case_id:'a',neighborhood:'예제동',source:'synthetic',version:'v1',run_id:null,draft_status:'draft',source_validation:true,independent_reviews:2,field_effectiveness:null,rubric:{grounding:{state:'not_evaluated',mean:null,range:null,independent_count:0},feasibility:{state:'disagreement',mean:null,range:[1,5],independent_count:2}}}],limitations:['첨부 원문 대조는 정책 효과를 입증하지 않습니다.']};
 await page.route('**/reports/quality**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith(id)?{...detail,policy_design}:[brief]}));
 await page.goto('/evaluation');const panel=page.getByLabel('정책 설계 품질');await expect(panel).toContainText('실제 정책 효과 미평가');await expect(panel).toContainText('평정 불일치');await expect(panel).toContainText('독립 평정 0명');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
