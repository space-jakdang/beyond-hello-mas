import {test,expect} from '@playwright/test';
test('policy alternative evaluation separates completion from missing independent quality',async({page})=>{
 const owner='11111111-1111-4111-8111-111111111111';
 await page.route('**/policy-proposals',r=>r.fulfill({json:[{owner_id:owner,dong_count:1,created_at:'2026-10-23',data_mode:'sample',synthetic_future:false}]}));
 await page.route(`**/policy-proposals/${owner}/quality`,r=>r.fulfill({json:{input_hash:'test-hash',sets:1,exactly_three:1,alternatives:3,strategy_unique_sets:1,identical_service_sets:0,template_count:3,fixture_count:0,grounding_eligible:0,rows:[{alternative_id:'a',dong_nm:'검증동',generation_mode:'template_fallback',evidence_status:'concept_only',citation_match:null,grounding_eligible:false,rubric:{feasibility:{state:'not_evaluated',value:null,independent_count:0}}}],limitations:['실제 효과 미평가']}}));
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');const panel=page.getByRole('region',{name:'정책 대안 품질',exact:true});
 await expect(panel.getByText('1/1',{exact:true})).toBeVisible();await expect(panel).toContainText('기본 구상안');await expect(panel).toContainText('원문 인용 대조 N/A');await panel.locator('summary').first().click();await expect(panel).toContainText('실행 가능성: 미평가');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('malformed alternative ratings explain how to fix the upload',async({page})=>{
 const owner='11111111-1111-4111-8111-111111111111';
 await page.route('**/policy-proposals',r=>r.fulfill({json:[{owner_id:owner,dong_count:1,created_at:'2026-10-23',data_mode:'sample',synthetic_future:false}]}));
 await page.route(`**/policy-proposals/${owner}/quality`,r=>r.fulfill({json:{input_hash:'test-hash',sets:0,exactly_three:0,alternatives:0,strategy_unique_sets:0,template_count:0,fixture_count:0,grounding_eligible:0,rows:[],limitations:[]}}));
 await page.goto('/evaluation');const panel=page.getByRole('region',{name:'정책 대안 품질',exact:true});
 await panel.getByText('독립 평정 등록').click();
 await panel.getByLabel('평정 JSON').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from('{')});
 const alert=panel.getByRole('alert');await expect(alert).toContainText('평정 파일을 읽지 못했습니다');
 await expect(alert.locator('pre')).toBeHidden();await alert.getByText('기술 오류 상세',{exact:true}).click();
 await expect(alert).toContainText('SyntaxError');
});

// /ship Step 7 pass 2 addition
// Value: protects=zero-request policy results display not-applicable and mixed reports use requested-design denominators;
// fails_when=useful zero-draft sets look like failed generation or completion divides by every stored set;
// why_new=the existing quality fixtures cover legacy three-draft reports and malformed uploads;
// seam=none; no_claim=routed synthetic report rendering only, not backend aggregation, independent quality or live acceptance.
test('conditional policy quality keeps zero requests and mixed completion denominators distinct',async({page})=>{
 const zeroOwner='11111111-1111-4111-8111-111111111111',mixedOwner='22222222-2222-4222-8222-222222222222';
 const base={input_hash:'zero-conditional',sets:2,conditional_sets:2,design_requested_sets:0,reuse_sets:1,evidence_hold_sets:1,
  conditional_contract_pass_sets:2,exactly_three:0,alternatives:0,strategy_unique_sets:0,template_count:0,fixture_count:0,grounding_eligible:0,rows:[],limitations:['독립 정책 품질 미평가']};
 const mixed={...base,input_hash:'mixed-conditional',sets:4,conditional_sets:3,design_requested_sets:2,conditional_contract_pass_sets:3,
  exactly_three:2,alternatives:6,strategy_unique_sets:2,template_count:3,grounding_eligible:3,
  rows:Array.from({length:6},(_,i)=>({alternative_id:'alternative-'+i,title:'테스트 대안 '+i,dong_nm:'검증동',generation_mode:i<3?'llm':'template_fallback',
   evidence_status:i<3?'supported':'concept_only',citation_match:i<3?true:null,grounding_eligible:i<3,
   rubric:{feasibility:{state:'not_evaluated',value:null,independent_count:0}}}))};
 await page.route('**/policy-proposals',route=>route.fulfill({json:[zeroOwner,mixedOwner].map(owner_id=>({owner_id,dong_count:2,created_at:'2026-10-25',data_mode:'sample',synthetic_future:false}))}));
 await page.route('**/policy-proposals/*/quality',route=>route.fulfill({json:route.request().url().includes(zeroOwner)?base:mixed}));
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');
 const panel=page.getByRole('region',{name:'정책 대안 품질',exact:true});
 const completion=panel.locator('section').filter({has:page.getByRole('heading',{name:'세 대안 요청 대비 작성 동',exact:true})});
 await expect(completion.locator('strong')).toHaveText('해당 없음');
 await expect(panel).toContainText('기존 정책 활용만 제안한 동 1개 · 추가 확인 필요 1개 · 조건부 생성 계약 2/2동.');
 await expect(panel).toContainText('대안 미작성은 품질 0점을 뜻하지 않습니다.');
 await expect(panel.getByText('0/0',{exact:true})).toHaveCount(0);
 await expect(panel.locator('details').filter({hasText:'독립 평정 0명'})).toHaveCount(0);
 await panel.getByRole('combobox').selectOption(mixedOwner);
 await expect(completion.locator('strong')).toHaveText('2/2');
 await expect(panel).toContainText('조건부 생성 계약 3/3동.');
 await expect(panel.getByText('2/4',{exact:true})).toHaveCount(0);
 await panel.getByText('검증동 · 테스트 대안 0 · 모델 작성 · 원문 인용 대조 일치',{exact:true}).click();
 await expect(panel).toContainText('실행 가능성: 미평가 · 독립 평정 0명');
 await expect(panel).toContainText('독립 정책 품질 미평가');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
