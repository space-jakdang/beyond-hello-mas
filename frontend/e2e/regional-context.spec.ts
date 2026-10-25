import {test,expect} from '@playwright/test';
for(const [sgg,dong] of [['11230','11230001'],['32010','32010023']]){
 // /ship Step 7 pass 1 extension (one case per region)
 // Value: protects=frozen mobile context, official guidance, outreach copy and keyboard design-to-fact links for zero or three drafts;
 // fails_when=source metadata or saved outreach disappears, draft cards are forced or a fact link points outside the stored profile;
 // why_new=the existing cases checked zero drafts, row counts and filenames without metadata or positive draft interactions;
 // seam=none; no_claim=zero-draft fake runtime plus routed three-draft fixture; no real model quality or three-draft runtime acceptance.
 // Pass 2: protects=exact stored values, need ownership links and material uncertainty labels;
 // fails_when=values drift or need links/reason labels disappear; why_new=original oracles omitted those fields;
 // seam=none; no_claim=the positive three-card portion remains a stored-response UI fixture.
 test(`regional policy response keeps frozen context and exports without forced drafts ${sgg}`,async({page,request})=>{
  const root='http://127.0.0.1:'+(process.env.E2E_API_PORT||8000);
  const response=await request.post(root+'/scenarios/run',{data:{id:'regional-workflow',type:'monthly',sim_time:'2026-10-25T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',policy_context_version:'regional-policy-2',task:{sgg,dong_cd:dong,ym:'2025-09',as_of:'2026-10-25',sex:'M',age_group:'youth'}}}});
  expect(response.ok()).toBeTruthy();const run=await response.json();
  await expect.poll(async()=>{const r=await request.get(root+'/policy-proposals/'+run.id);return r.status();},{timeout:20000}).toBe(200);
  const stored=await(await request.get(root+'/policy-proposals/'+run.id)).json();expect(stored.sets[0].proposal_version).toBe('regional-policy-2');expect(stored.sets[0].alternatives).toHaveLength(0);
  await page.setViewportSize({width:390,height:844});await page.goto('/workspace?policy_owner='+run.id);
  const panel=page.getByRole('region',{name:'지역 정책 대응안',exact:true});await expect(panel.getByRole('heading',{name:'지역 근거에 따른 정책 대응안'})).toBeVisible();
  await expect(panel).toContainText('새 정책 대안을 작성하지 않았습니다.');await expect(panel).toContainText('합성 테스트 통계');
  await expect(panel.getByLabel('출력 범위')).toHaveValue('');
  await expect(panel.getByRole('option',{name:'동별 대응 판단·근거 전체',exact:true})).toHaveCount(1);
  const facts=panel.getByRole('region',{name:'지역 인구·가구 근거'});await expect(facts.getByRole('row')).toHaveCount(10);
  const summary=facts.getByText('원문과 정의',{exact:true}).first();await summary.focus();await page.keyboard.press('Enter');await expect(facts.getByText('통계 원문 열기',{exact:true}).first()).toBeVisible();
  const profile=stored.sets[0].evidence.regional_profile;
  const metricLabels:Record<string,string>={total_population:'총인구',total_households:'전체 가구',general_households:'일반가구',one_person_households:'1인가구',senior_population:'65세 이상 인구',youth_population:'19–34세 인구',total_housing:'주택',population_density:'인구밀도',average_age:'평균연령'};
  const units:Record<string,string>={persons:'명',households:'가구',houses:'호',persons_per_km2:'명/㎢',years:'세'};
  for(const fact of profile.facts){
   const row=facts.getByRole('row').filter({hasText:metricLabels[fact.metric]});
   await expect(row).toContainText(fact.status==='observed'?`${fact.value.toLocaleString('ko-KR')} ${units[fact.unit]||fact.unit}`:'미확보');
   await expect(row).toContainText(`${fact.reference_year}년`);
   await expect(facts).toContainText(fact.fact_id);await expect(facts).toContainText(fact.source_hash);
   await expect(facts).toContainText(fact.geography_code);await expect(facts).toContainText(fact.geography_version);
   await expect(facts).toContainText(fact.fetched_at);await expect(facts).toContainText(fact.population);await expect(facts).toContainText(fact.age_definition);
   if(fact.source_table)await expect(facts).toContainText(fact.source_table);
   for(const value of [...(fact.source_items||[]),...(fact.source_dimensions||[])])await expect(facts).toContainText(value);
   if(fact.published_at)await expect(facts).toContainText(fact.published_at);
  }
  await expect(facts.getByRole('link',{name:'통계 원문 열기',exact:true}).first()).toHaveAttribute('href',profile.facts[0].source_url);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  for(const [button,suffix] of [['PDF 다운로드','.pdf'],['Word 다운로드','.docx']]){
   const download=page.waitForEvent('download');await panel.getByRole('button',{name:button,exact:true}).click();expect((await download).suggestedFilename()).toContain(suffix);
  }
  await page.reload();await expect(panel.getByRole('row')).toHaveCount(10);await expect(panel).toContainText(stored.sets[0].dong_nm);
  for(const fact of profile.facts)await expect(facts).toContainText(fact.source_hash);
  // This stored-response fixture isolates positive UI behavior from generation quality.
  const fixture=structuredClone(stored),set=fixture.sets[0],fact=profile.facts.find((f:any)=>f.status==='observed');
  const outreach='보관된 안내 첫 줄\n신청 전 담당 기관과 대상 조건을 확인하세요.';
  set.status='draft';set.fallback_reason='policy_source_snapshot_conflict';
  set.response_decisions=[{need_id:'ui-need',target_group:'M/youth',need:'relationship',decision:'adapt_existing',reason:'stale_policy_detail',
   unmet_requirements:['퇴근 후 운영 가능 시간 확인'],missing_evidence:['현지 운영시간 확인'],guidance:[{id:'ui-policy',title:'고정 안내 정책',agency:'테스트 담당기관',support:'상담과 관계 활동',eligibility:'확인된 대상 범위',application:'방문 신청 검토',deadline:'기한 별도 확인',contact:'담당 부서 문의',url:'https://www.gov.kr/'}],
   outreach_draft:{channel_proposal:'지역 게시판 검토',text:outreach,dispatch_performed:false}},
   {need_id:'ui-held-need',target_group:'M/youth',need:'health',decision:'needs_evidence',reason:'material_policy_target_missing',guidance:[],
    missing_evidence:['material_policy_time_missing','material_target_coverage_gap','source_age_definition_unavailable','unrecognized_policy_reason','fake: 담당자 확인 문장']}];
  set.alternatives=[0,1,2].map(i=>({id:`ui-alternative-${i}`,strategy:`ui-choice-${i}`,title:`지역 운영 제안 ${i+1}`,target_groups:['M/youth'],rationale:'고정 지역 근거로 운영 접점을 검토합니다.',
   proposed_service:`운영 경로 ${i+1}`,need_ids:['ui-need'],operating_steps:['담당자 확인'],required_roles:['담당자 검토'],budget_questions:['예산 확인'],equity_risks:['접근성 확인'],evaluation_plan:'시행 전 현장 합의',missing_evidence:['현장 조건'],generation_mode:'fixture',evidence_status:'concept_only',review_status:'pending',citations:[],
   context_links:[{fact_id:fact.fact_id,design_choice:`지역 사실에 따른 선택 ${i+1}`,verification_needed:'실제 접근 방식 확인'}]}));
  await page.route('**/policy-proposals/'+run.id,route=>route.fulfill({json:fixture}));await page.reload();
  await expect(panel.getByRole('button',{name:'이 대안 수정·검토',exact:true})).toHaveCount(3);
  await expect(panel).toContainText('같은 정책의 고정 원문·공식 대상 조건이 서로 달라 확인이 필요합니다.');
  await expect(panel).toContainText('오래된 정책 자료의 최신성을 다시 확인해야 합니다.');
  for(const text of ['보완할 요건: 퇴근 후 운영 가능 시간 확인','공식 정책의 대상 연령·성별 조건을 확인하지 못했습니다.',
   '정책의 유효 시점을 확인할 자료가 부족합니다.','정책 대상 연령이 요청 집단의 일부만 포함합니다.',
   '요청 집단의 실제 원천 연령 범위를 확인하지 못했습니다.','세부 사유는 진행 기록에서 확인하세요.','담당자 확인 문장'])await expect(panel).toContainText(text);
  await expect(panel).not.toContainText('unrecognized_policy_reason');await expect(panel).not.toContainText('material_policy_time_missing');
  const needLink=panel.getByRole('link',{name:'남성 청년 · 관계망',exact:true}).first(),needAnchor=`need-${set.owner_id}-ui-need`;
  await expect(needLink).toHaveAttribute('href','#'+needAnchor);await needLink.focus();await page.keyboard.press('Enter');
  expect(await page.evaluate(id=>document.getElementById(id)?.textContent,needAnchor)).toContain('기존 정책과 운영 보완');
  const guidance=panel.getByText('고정 안내 정책 · 활용 조건과 신청 정보',{exact:true});await guidance.click();
  for(const value of ['테스트 담당기관','상담과 관계 활동','확인된 대상 범위','방문 신청 검토','기한 별도 확인','담당 부서 문의'])await expect(panel).toContainText(value);
  await expect(panel.getByRole('link',{name:'공식 출처 확인',exact:true})).toHaveAttribute('href','https://www.gov.kr/');
  await panel.getByText('담당자 검토용 안내 초안',{exact:true}).click();
  await expect(panel.locator('.outreach-draft')).toHaveText(outreach);await expect(panel).toContainText('제안 채널: 지역 게시판 검토');
  await expect(panel).toContainText('실제 발송·게시하지 않은 초안입니다.');
  const link=panel.getByRole('link',{name:'설계에 사용한 지역 근거 1',exact:true}).first(),anchor=`regional-${set.owner_id}-${fact.fact_id}`;
  await expect(link).toHaveAttribute('href','#'+anchor);await link.focus();await page.keyboard.press('Enter');
  expect(await page.evaluate(()=>decodeURIComponent(location.hash.slice(1)))).toBe(anchor);
  expect(await page.evaluate(id=>document.getElementById(id)?.tagName,anchor)).toBe('TR');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  let rejectedDownloads=0;page.on('download',()=>rejectedDownloads++);
  await page.route('**/policy-proposals/'+run.id+'/'+dong+'/download/pdf?*',route=>route.fulfill({contentType:'text/html',body:'<html>upstream login</html>'}));
  await panel.getByRole('button',{name:'PDF 다운로드',exact:true}).click();
  const report=panel.getByRole('region',{name:'정책 보고서 다운로드'});
  await expect(report.getByRole('alert')).toContainText('보고서 대신 다른 응답이 반환되었습니다.');
  await expect(report.getByRole('button',{name:'PDF 다운로드',exact:true})).toBeEnabled();expect(rejectedDownloads).toBe(0);
 });
}

// /ship Step 7 pass 1 addition
// Value: protects=each v3/v4 single or batch UI submission carries regional-policy-2 without changing its source-age or week scope;
// fails_when=any submission branch drops the flag, changes methodology or sends a source-age cell as a legacy age group;
// why_new=existing tests submit directly through the API or inspect older unflagged UI requests;
// seam=none; no_claim=browser-to-request serialization against routed source/HTTP fixtures; no backend acceptance or batch execution.
test('regional UI selects the policy context for both methodologies and single or batch requests',async({page})=>{
 const week='2025-12-15',dong='32010023',posts:{path:string;body:any}[]=[];
 const base={data_mode:'sample',period_aggregate:false,months:['2025-09'],neighborhoods:[{sgg:'32010',dong_cd:dong,dong_nm:'테스트 동'}],metadata:{selected_week:week},segments:[]};
 let v4=false;
 await page.route('**/runs',route=>route.fulfill({json:[]}));
 await page.route('**/analysis/groups*',route=>route.fulfill({json:v4?{...base,period_aggregate:true,
  segments:[{sgg:'32010',source_age_band:'60대+'}],weekly:{selected_week:week,signals:[{week}]},
  metadata:{...base.metadata,workflow_version:'regional-workflow-2',dataset_version:'ui-v4-fixture'}}:base}));
 for(const path of ['/scenarios/run','/regional/batches'])await page.route('**'+path,route=>{
  posts.push({path,body:route.request().postDataJSON()});return route.fulfill({status:503,json:{detail:'fixture request captured; nothing executed'}});
 });
 for(const version of ['regional-workflow-1','regional-workflow-2']){
  v4=version==='regional-workflow-2';
  for(const batch of [false,true]){
   const query=new URLSearchParams({workflow_version:version,region:'32010',dong,sex:batch?'all':'F',as_of:'2026-10-25',
    ...(v4?{source_age_band:batch?'all':'60대+',card_week:week}:{age:batch?'all':'prime',month:'2025-09'})});
   await page.goto('/workspace?'+query);await expect(page.getByRole('button',{name:'지역 분석 요청',exact:true})).toBeEnabled();
   await page.getByRole('button',{name:'지역 분석 요청',exact:true}).click();
   await expect(page.getByRole('alert')).toContainText('fixture request captured');
   const sent=posts.at(-1)!;expect(sent.path).toBe(batch?'/regional/batches':'/scenarios/run');
   const payload=batch?sent.body:sent.body.payload;
   expect(payload.policy_context_version).toBe('regional-policy-2');expect(payload.task.dong_cd).toBe(dong);expect(payload.task.sgg).toBe('32010');
   if(v4){expect(payload.workflow_version).toBe(version);expect(payload.task.methodology_version).toBe(version);expect(payload.task.source_age_band).toBe(batch?'all':'60대+');expect(payload.task.card_week).toBe(week);expect(payload.task).not.toHaveProperty('age_group');}
   else{expect(payload.task.ym).toBe('2025-09');expect(batch?payload.age_group:payload.task.age_group).toBe(batch?'all':'prime');}
   if(batch)expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/);
  }
 }
 expect(posts).toHaveLength(4);
});

// /ship Step 7 pass 2 addition
// Value: protects=selected-dong uncertainty/notes, reference-only candidate warnings and batch evidence-hold state remain explicit;
// fails_when=missing facts become zero, hidden facts get links, reference candidates lose warnings or holds look completed;
// why_new=previous cases use complete owner profiles and stop batch requests before progress rendering;
// seam=none; no_claim=routed saved-state UI fixtures and sample map geometry, not provider/model or real batch acceptance.
test('regional review filters frozen notes and keeps missing context, reference candidates and batch holds explicit',async({page,request})=>{
 const response=await request.get('/analysis/groups?workflow_version=regional-workflow-1');expect(response.ok()).toBeTruthy();const source=await response.json();
 const dongs=source.neighborhoods.filter((d:any)=>d.sgg==='11230').slice(0,2),[first,second]=dongs,owner='regional-note-fixture';
 const fact={fact_id:'stored-population-fact',metric:'total_population',value:1200,unit:'persons',reference_year:2020,
  geography_level:'dong',geography_code:first.dong_cd,geography_version:'fixed-boundary',published_at:null,population:'residents',age_definition:'all_ages',sex:'all',
  source:'synthetic_fixture',source_url:'https://kosis.kr/',source_table:'fixture-population',source_items:['TOTAL'],source_dimensions:[],source_hash:'frozen-source-hash',fetched_at:'2026-10-25T00:00:00Z',status:'observed',reason:null};
 const missing={...fact,fact_id:'stored-missing-housing',metric:'total_housing',value:null,unit:'houses',source_url:'javascript:alert(1)',status:'missing',reason:'fixture_not_supplied'};
 const profile={status:'partial',source:'synthetic_fixture',request:{dong_cd:first.dong_cd,reference_year:2020},identity:{dong_nm:first.dong_nm},facts:[fact,missing],limitations:['집계 자료만으로 현장 수요를 확정하지 않습니다.'],input_hash:'profile-one'};
 const empty={...profile,status:'unavailable',request:{dong_cd:second.dong_cd,reference_year:2020},identity:{dong_nm:second.dong_nm},facts:[],input_hash:'profile-two'};
 const rows=dongs.map((d:any,i:number)=>({evidence_id:'segment-'+i,dong_cd:d.dong_cd,dong_nm:d.dong_nm,sex:'M',age_group:'youth',stage:2,stage_label:'관심',index_name:'S1',value:.5,source_period:'2025-09',source_bands:{population:['20대']}}));
 const candidates=[{candidate_status:'reference_only'},{local_eligibility:'not_established'},{}].map((flags,i)=>({...flags,
  policy:{id:'candidate-'+i,title:'공식 원문 후보 '+i,agency:'테스트 기관',scope:'seoul',support:'상담 지원',eligibility:'공식 대상 확인',url:'https://www.gov.kr/'},
  evidence:{field:'support',value:'상담 지원'},explanation:'원문을 확인한 참고 결과',detail_status:'cached'}));
 const proposal={workflow_version:'regional-workflow-1',snapshot_version:'stored-review',task:{sgg:'11230',ym:'2025-09',as_of:'2026-10-25',sex:'M',age_group:'youth',goal:'고정 자료 검토'},
  assessment:{segments:rows,period_aggregate:false,methodology_version:'regional-workflow-1',metadata:{input_hash:'fixed-assessment'},regional_context:{[first.dong_cd]:profile,[second.dong_cd]:empty}},
  workflow:{status:'reviewed',analysis:{summary:'고정 지역 자료 확인'},statistics:{status:'reviewed',reason:'',blocked_evidence_ids:[],regional_notes:[{fact_ids:[fact.fact_id],implication:'지역 구성에 맞는 접점 검토',hypothesis:'접근성 차이는 현장 확인이 필요합니다.',missing_evidence:['접점 이용 현황 확인']}]},matching:{status:'reviewed',summary:'후보 조건 확인'}},
  assignments:[],policy_research:{status:'completed',steps:1,candidates}};
 await page.route('**/analysis/groups*',route=>route.fulfill({json:source}));await page.route('**/runs',route=>route.fulfill({json:[]}));
 await page.route('**/runs/'+owner+'/overview',route=>route.fulfill({json:{run:{id:owner,status:'awaiting_approval',data_mode:'sample'},review:{approval:{status:'pending'},proposal},traces:[]}}));
 await page.route('**/runs/'+owner+'/traces/stream',route=>route.fulfill({status:404,body:''}));
 await page.setViewportSize({width:390,height:844});await page.goto('/workspace?run='+owner+'&workflow_version=regional-workflow-1');
 await page.getByRole('tab',{name:'통계 근거',exact:true}).click();
 const context=page.getByRole('region',{name:'지역 인구·가구 근거',exact:true});await expect(context).toContainText('일부 항목 미확보');
 await page.getByLabel('동 선택',{exact:true}).selectOption(first.dong_cd);
 await expect(context).toContainText(first.dong_nm);await expect(context).not.toContainText(second.dong_nm);
 await expect(context.getByRole('row').filter({hasText:'총인구'})).toContainText('1,200 명');
 const missingRow=context.getByRole('row').filter({hasText:'주택'});await expect(missingRow).toContainText('미확보');await expect(missingRow).not.toContainText('0 호');
 await missingRow.getByText('원문과 정의',{exact:true}).click();await expect(missingRow).toContainText('fixture_not_supplied');
 await expect(missingRow.getByRole('link')).toHaveCount(0);await expect(context).toContainText('과거 당시 가용성 미검증');
 const noteLink=context.getByRole('link',{name:'지역 근거 1 확인',exact:true}),anchor=`regional-${owner}-${fact.fact_id}`;
 await expect(noteLink).toHaveAttribute('href','#'+anchor);await noteLink.focus();await page.keyboard.press('Enter');
 expect(await page.evaluate(id=>document.getElementById(id)?.tagName,anchor)).toBe('TR');
 await expect(context).toContainText('지역 구성에 맞는 접점 검토');await expect(context).toContainText('접점 이용 현황 확인');
 await page.getByLabel('동 선택',{exact:true}).selectOption(second.dong_cd);
 await expect(context).toContainText('지역 자료를 확보하지 못했습니다.');await expect(context.getByRole('link',{name:'지역 근거 1 확인',exact:true})).toHaveCount(0);
 await expect(context).toContainText('다른 동의 근거 '+fact.fact_id+' · 해당 동을 선택해 확인하세요.');
 await page.getByRole('tab',{name:'자원 제안',exact:true}).click();const research=page.getByRole('region',{name:'추가 정책 조사 후보',exact:true});
 await expect(research.getByText('참고용 원문 · 현지 대상 적합성 미확인',{exact:true})).toHaveCount(2);
 await expect(research.locator('article').filter({hasText:'공식 원문 후보 2'})).not.toContainText('참고용 원문 · 현지 대상 적합성 미확인');
 const children=['M','F'].flatMap(sex=>['youth','midlife','prime','elderly'].map(age_group=>({sex,age_group,run_id:null,status:'completed'})));
 await page.route('**/regional/batches/held-fixture',route=>route.fulfill({json:{id:'held-fixture',status:'completed_with_evidence_hold',finished:8,total:8,children}}));
 await page.goto('/workspace?batch=held-fixture&workflow_version=regional-workflow-1');
 const progress=page.getByRole('region',{name:'전체 집단 업무',exact:true});await expect(progress.getByRole('status')).toContainText('일부 필요의 조사·근거 보완 필요');
 await expect(progress.getByRole('table',{name:'요청 집단별 진행 상황',exact:true}).locator('tbody tr')).toHaveCount(8);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
