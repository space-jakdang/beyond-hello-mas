import {test,expect} from '@playwright/test';
test('policy alternative evaluation separates completion from missing independent quality',async({page})=>{
 const owner='11111111-1111-4111-8111-111111111111';
 await page.route('**/policy-proposals',r=>r.fulfill({json:[{owner_id:owner,dong_count:1,created_at:'2026-10-23',data_mode:'sample',synthetic_future:false}]}));
 await page.route(`**/policy-proposals/${owner}/quality`,r=>r.fulfill({json:{input_hash:'test-hash',sets:1,exactly_three:1,alternatives:3,strategy_unique_sets:1,identical_service_sets:0,template_count:3,fixture_count:0,grounding_eligible:0,rows:[{alternative_id:'a',dong_nm:'검증동',generation_mode:'template_fallback',evidence_status:'concept_only',citation_match:null,grounding_eligible:false,rubric:{feasibility:{state:'not_evaluated',value:null,independent_count:0}}}],limitations:['실제 효과 미평가']}}));
 await page.setViewportSize({width:390,height:844});await page.goto('/evaluation');const panel=page.getByRole('region',{name:'정책 대안 품질',exact:true});
 await expect(panel.getByText('1/1',{exact:true})).toBeVisible();await expect(panel).toContainText('기본 구상안');await expect(panel).toContainText('원문 인용 대조 N/A');await panel.locator('summary').first().click();await expect(panel).toContainText('실행 가능성: 미평가');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
