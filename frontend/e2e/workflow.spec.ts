import {test,expect} from '@playwright/test';

test('regional task links agents, immutable results and a fresh revision approval',async({page})=>{
 await page.goto('/workspace?sex=M&age=youth');
 await page.getByLabel('업무 목표').fill('월별 추이를 확인하세요.');
 await page.getByRole('button',{name:'지역 분석 요청'}).click();
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 const original=page.url();
 await expect(page.getByRole('list',{name:'업무 진행 단계'}).locator('li')).toHaveCount(6);
 await expect(page.getByRole('tabpanel')).toContainText('지역별 우선 확인 결과');
 await expect(page.locator('.workflow-result-intro')).toContainText('개인의 위험도');
 await expect(page.locator('.workflow-result-intro')).toContainText('관측 근거와 자료 한계를 검토한 잠정 지역 분석입니다.');
 await expect(page.locator('.workflow-result-intro')).not.toContainText('fake:');
 await expect(page.locator('.workflow-context')).toContainText('자료: 합성 테스트 자료');
 await expect(page.locator('.workflow-agent-log')).not.toHaveAttribute('open','');
 await page.screenshot({path:'runtime/sample/workflow-desktop.png',fullPage:true});
 await page.locator('.workflow-result-intro').getByRole('button',{name:'통계 근거'}).click();
 await expect(page.getByRole('tab',{name:'통계 근거'})).toBeFocused();
 await expect(page.getByRole('tabpanel')).toContainText('근거 확인 가능');
 const insights=page.getByRole('region',{name:'정책 판단 참고',exact:true});
 await expect(insights).toContainText('추가 확인');
 await insights.locator('details').first().locator('summary').click();
 await expect(insights).toContainText('위험 확률이나 인과 효과가 아닙니다');
 const policyStats=page.getByLabel('정책 판단 참고 통계');
 await expect(policyStats).toContainText('주민 수요 인원이나 고립 유병률이 아닙니다');
 await policyStats.locator('summary').filter({hasText:'근거 ·'}).first().click();
 await expect(page.getByLabel('정책 판단 참고 통계')).toContainText('추가 확인 자료');
 await expect(page.getByRole('img',{name:'실제 관측 월의 지수 추이. 수치는 아래 표에 표시됩니다.'})).toBeVisible();
 await expect(page.getByLabel('추이 집단').locator('option').first()).toContainText('합성동01 · 남성 청년');
 await page.getByRole('tab',{name:'통계 근거'}).press('ArrowRight');
 await expect(page.getByRole('tab',{name:'자원 제안'})).toBeFocused();
 await expect(page.getByRole('tabpanel')).toContainText('실제 배정은 하지 않습니다');
 await page.getByText('추천·보류 근거와 미확인 사항',{exact:true}).first().press('Enter');
 await expect(page.locator('.decision-evidence[open]').first()).toContainText('관측 근거');
 await expect(page.locator('.decision-evidence[open]').first()).toContainText('개인별 자격·접수 여부·남은 지원 규모는 미확인');
 await page.getByLabel('지역',{exact:true}).selectOption('32010');
 await expect(page.locator('.workflow-context')).toContainText('강남구');
 await page.reload();
 await expect(page.locator('.workflow-context')).toContainText('강남구');
 await page.getByRole('link',{name:'담당자 검토함에서 제안 확인 →'}).click();
 await expect(page.getByTestId('review-panel')).toContainText('조건부');
 await expect(page.getByTestId('review-panel').locator('.workflow-context')).toContainText('자료: 합성 테스트 자료');
 await page.getByLabel('담당자 이름').fill('워크플로 검토자');
 await page.getByLabel('검토 사유').fill('통계의 출처와 누락 근거를 보완하세요.');
 await page.getByRole('button',{name:'보완 요청'}).click();
 await expect(page).toHaveURL(/\/workspace\?run=/);
 expect(page.url()).not.toBe(original);
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await expect(page.getByLabel('합성 동 격자',{exact:true})).toBeVisible();
 await page.screenshot({path:'runtime/sample/workflow-mobile-result.png',fullPage:true});
 await expect(page.getByRole('link',{name:'이전 제안 보기'})).toHaveAttribute('href','/workspace?run='+new URL(original).searchParams.get('run'));
});

test('regional workspace has responsive navigation and an explicit empty state',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.goto('/');
 await page.getByRole('link',{name:'지역 업무 시작하기 →'}).click();
 await expect(page.getByText('아직 선택한 분석이 없습니다')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:'runtime/sample/workflow-mobile.png',fullPage:true});
 await page.getByRole('link',{name:'인덱스',exact:true}).click();
 await expect(page).toHaveURL(/\/$/);
});

test('failed workflow announces the failure and keeps raw errors collapsed',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-error-copy',type:'monthly',sim_time:'2026-10-21T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',sex:'M',age_group:'youth',ym:source.months.at(-1),as_of:'2026-10-21'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;}).toBe('awaiting_approval');
 overview.run.status='failed';overview.run.error='private stack trace';delete overview.review;
 await page.route(`**/runs/${run.id}/overview`,route=>route.fulfill({json:overview}));
 await page.goto(`/workspace?run=${run.id}`);
 const alert=page.getByRole('alert');
 await expect(alert).toContainText('실행에 실패했습니다.');
 await expect(alert.getByText('private stack trace',{exact:true})).toBeHidden();
 await alert.getByText('오류 내용',{exact:true}).click();
 await expect(alert.getByText('private stack trace',{exact:true})).toBeVisible();
});

test('map scope reaches the regional analysis request and missing data blocks new tasks',async({page,request})=>{
 const data=await(await request.get('/analysis/groups')).json();
 const dong=data.neighborhoods.find((d:any)=>d.sgg==='32010');
 await page.goto('/neighborhoods?'+new URLSearchParams({region:'32010',dong:dong.dong_cd,sex:'F',age:'prime'}));
 await page.getByRole('link',{name:'이 동·집단의 지역 업무 시작 →'}).click();
 await expect(page.getByLabel('분석 대상 동')).toHaveValue(dong.dong_cd);
 await expect(page.getByLabel('성별',{exact:true})).toHaveValue('F');
 await expect(page.getByLabel('집단',{exact:true})).toHaveValue('prime');
 await page.getByRole('button',{name:'지역 분석 요청'}).click();
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 await expect(page.getByRole('tabpanel').locator('tbody tr')).toHaveCount(1);
 await page.getByText(/에이전트 진행 기록 ·/).click();
 await expect(page.getByLabel('실행별 에이전트 상호작용')).toContainText('지역 분석가 → 통계 분석가');
 await page.route('**/analysis/groups*',r=>r.fulfill({status:503,body:'자료 없음'}));
 await page.goto('/workspace');
 await expect(page.getByRole('button',{name:'지역 분석 요청'})).toBeDisabled();
 await expect(page.getByRole('alert')).toContainText('지역 자료를 불러오지 못해 분석 요청을 중지했습니다');
});

test('index explains feedback and period aggregates are not labelled observed months',async({page,request})=>{
 await page.goto('/');
 await expect(page.getByLabel('멀티에이전트 시스템 구조')).toContainText('통계 분석가 ↔ 지역 분석가');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 const data=await(await request.get('/analysis/groups')).json();
 data.period_aggregate=true;data.months=[];
 await page.route('**/analysis/groups*',r=>r.fulfill({json:data}));
 await page.goto('/workspace');
 await expect(page.getByLabel('실행 기준 월')).toHaveValue(data.metadata.selected_week.slice(0,7));
 await expect(page.getByText('해당 월의 관측값이 아닙니다.',{exact:false})).toBeVisible();
 await expect(page.getByLabel('관측 월',{exact:true})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});


test('geographic geometry renders dong labels and keyboard selection',async({page,request})=>{
 const data=await(await request.get('/analysis/groups')).json();
 // Synthetic test geometry exercises geographic rendering; never used as local source data.
 data.data_mode='local';data.geography.crs='EPSG:4326';
 await page.route('**/analysis/groups*',r=>r.fulfill({json:data}));
 await page.goto('/neighborhoods');
 await expect(page.getByLabel('동별 분석 지도',{exact:true})).toBeVisible();
 const dong=data.neighborhoods.find((d:any)=>d.sgg==='11230');
 await expect(page.locator('.map-label').filter({hasText:dong.dong_nm})).toBeVisible();
 const shape=page.locator('.map-scroll path').first();await shape.focus();await page.keyboard.press('Enter');
 await expect(shape).toHaveAttribute('aria-pressed','true');
});


test('policy evidence cards remain tentative and responsive',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-cards',type:'monthly',sim_time:'2026-10-21T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',sex:'M',age_group:'youth',ym:source.months.at(-1),as_of:'2026-10-21'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;}).toBe('awaiting_approval');
 overview.review.proposal.policy_research={status:'completed',steps:3,candidate_funnel:{retrieved:3,details_checked:3,selected:1,shortfall:2,not_selected:[{policy_id:'cached-policy',title:'저장 상태 후보',reason:'not_selected_by_agent',detail_status:'cached'},{policy_id:'unknown-policy',title:'미상 상태 후보',reason:'not_selected_by_agent',detail_status:'unknown_detail_state'}]},candidates:[{policy:{id:'test',title:'테스트 관계망 지원',agency:'테스트 기관',scope:'gangnam',url:'https://www.gov.kr/'},explanation:'관계망 욕구의 조사 후보',evidence:{field:'title',value:'테스트 관계망 지원'},detail_status:'live',checked_at:'2026-10-21'}]};
 await page.route(`**/runs/${run.id}/overview`,r=>r.fulfill({json:overview}));
 await page.setViewportSize({width:390,height:844});await page.goto(`/workspace?run=${run.id}`);
 await page.getByRole('tab',{name:'자원 제안'}).click();
 await expect(page.getByLabel('추가 정책 조사 후보')).toContainText('확정 배정에 포함되지 않습니다');
 await expect(page.getByLabel('추가 정책 조사 후보')).toContainText('정부24 최신 상세 확인');
 await expect(page.getByLabel('추가 정책 조사 후보')).toContainText('원문 근거 · 정책명');
 await page.getByText('선택하지 않은 상세 조회 후보',{exact:true}).press('Enter');
 await expect(page.getByText('저장 상태 후보 · 저장된 상세 · 최신 확인 필요',{exact:true})).toBeVisible();
 await expect(page.getByText('미상 상태 후보 · 상세 상태 확인 필요',{exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'공식 정책 원문 ↗'})).toHaveAttribute('href','https://www.gov.kr/');
 const candidate=overview.review.proposal.policy_research.candidates[0];
 overview.review.proposal.policy_research.candidates=Array.from({length:5},(_,i)=>({...candidate,policy:{...candidate.policy,id:String(i),title:'관련 지원 '+i},...(i===4?{detail_status:'unknown_detail_state',evidence:{field:'unknown_source_field',value:'검토 근거'}}:{})}));
 await page.reload();await page.getByRole('tab',{name:'자원 제안'}).click();
 await expect(page.getByLabel('추가 정책 조사 후보').locator('article:visible')).toHaveCount(3);
 await page.getByText('추가 관련 후보 2개 보기',{exact:true}).click();
 await expect(page.getByLabel('추가 정책 조사 후보').locator('article:visible')).toHaveCount(5);
 const unknown=page.getByLabel('추가 정책 조사 후보').locator('article').filter({hasText:'관련 지원 4'});
 await expect(unknown).toContainText('상세 상태 확인 필요');await expect(unknown).toContainText('정책 원문 항목');await expect(unknown).not.toContainText('unknown_detail_state');

 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('unknown statistical reason codes use plain language and stay in details',async({page,request})=>{
 const source=await(await request.get('/analysis/groups')).json();
 const response=await request.post('/scenarios/run',{data:{id:'regional-workflow-unknown-reason',type:'monthly',sim_time:'2026-10-21T09:00:00+09:00',payload:{workflow_version:'regional-workflow-1',task:{sgg:'11230',sex:'M',age_group:'youth',ym:source.months.at(-1),as_of:'2026-10-21'}}}});
 const run=await response.json();let overview:any;
 await expect.poll(async()=>{overview=await(await request.get(`/runs/${run.id}/overview`)).json();return overview.run.status;}).toBe('awaiting_approval');
 overview.review.proposal.workflow.statistics.reason='unrecognized_reason';
 await page.route(`**/runs/${run.id}/overview`,route=>route.fulfill({json:overview}));
 await page.goto(`/workspace?run=${run.id}`);await page.getByRole('tab',{name:'통계 근거'}).click();
 const panel=page.getByRole('tabpanel');
 await expect(panel).toContainText('확인 사유는 세부정보에서 확인하세요.');
 const rawReason=panel.getByText('상태: reviewed · 사유 코드: unrecognized_reason',{exact:true});
 await expect(rawReason).toBeHidden();
 await panel.getByText('통계 검토 상태 코드',{exact:true}).click();
 await expect(rawReason).toBeVisible();
});

test('v4 workflow result keeps source status and weekly card evidence',async({page,request})=>{
 const base=await(await request.get('/analysis/groups')).json(),dong=base.neighborhoods.find((d:any)=>d.sgg==='32010');
 const week='2025-12-15',row={evidence_id:'v4-test',dong_cd:dong.dong_cd,dong_nm:dong.dong_nm,sex:'F',age_group:'60대+',stage:-1,stage_label:'판정 근거 부족',index_name:'source-stage',value:null,source_period:'2025',source_bands:{dong_stage_age:['60대+']},source_age_band:'60대+',source_stage:-1,source_stage_label:'판정 근거 부족',assessment_status:'insufficient_evidence',base_stage:null,final_stage:null,final_stage_label:'판정 근거 부족',card_alarm_status:'baseline_unavailable',card_week:week,card_source_age_bands:['60대'],card_evidence:[{source_age_band:'60대',baseline_status:'unavailable',v_ratio:null,n_ratio:null,v_stage:0,n_stage:0,alarm_stage:0}],stage_adjustment:0,priority_rank:1};
 const proposal={workflow_version:'regional-workflow-2',snapshot_version:'v4-test',task:{sgg:'32010',ym:'2025-12',as_of:'2026-10-25',sex:'F',age_group:'60대+',source_age_band:'60대+',card_week:week,goal:'근거 확인'},assessment:{segments:[row],period_aggregate:true,methodology_version:'v4-test',metadata:{input_hash:'fixture',synthetic_future:false}},workflow:{status:'reviewed',analysis:{summary:'집단 근거를 확인합니다.'},statistics:{status:'reviewed',reason:'',summary:{total:1,observed:0,missing:1,missing_rate:1,stage_counts:{'-1':1,'0':0},distributions:[{sgg:'32010',sex:'F',source_age_band:'60대+',n:1,assessment_counts:{insufficient_evidence:1},stage_counts:{'-1':1},card_alarm_counts:{baseline_unavailable:1}}]},observations:[{tool:'trend',status:'observed',series:[{cohort_id:'32010/F/60대+',points:[{ym:'2025-12',value:null,change:null,week,alarm_stage:0,baseline_status:'unavailable',source_age_bands:['60대'],v_stages:[0],n_stages:[0]}]}]},{tool:'source_check',status:'completed',items:[]}],blocked_evidence_ids:['v4-test']},matching:{status:'reviewed',summary:'추천 보류'}},assignments:[]};
 const source={...base,data_mode:'local',period_aggregate:true,segments:[row],weekly:{selected_week:week,signals:[]},metadata:{workflow_version:'regional-workflow-2',methodology_version:'v4-test',dataset_version:'v4-test',selected_week:week,input_schema_version:4,input_hash:'fixture',weekly_scope:'region × sex × source age',source:{source:'fixture',sha256:'fixture'},card_source:{source:'fixture',sha256:'fixture'}}};
 const overview={run:{id:'v4-run',scenario_id:'regional-workflow-v4',status:'completed',data_mode:'local',started_at:'2026-10-25T00:00:00Z'},review:{approval:{status:'pending'},proposal},traces:[]};
 await page.route('**/runs',r=>r.fulfill({json:[]}));await page.route('**/runs/v4-run/overview',r=>r.fulfill({json:overview}));await page.route('**/analysis/groups*',r=>r.fulfill({json:source}));
 await page.goto(`/workspace?run=v4-run&workflow_version=regional-workflow-2&region=32010&sex=F&source_age_band=60%EB%8C%80%2B&card_week=${week}&age=youth&card_age=20s`);
 await expect(page.locator('.workflow-context')).toContainText('60대+');await expect(page.getByRole('tabpanel')).toContainText('판정 근거 부족');
 await page.getByRole('tab',{name:'통계 근거'}).click();const panel=page.getByRole('tabpanel');
 await expect(panel.getByLabel('원천 판정 상태 분포')).toContainText('근거 부족 (−1): 1개');await expect(panel.getByLabel('원천 판정 상태 분포')).toContainText('인구 보류 (0): 0개');
 await panel.getByText('원천 연령별 상태 분포',{exact:true}).click();await expect(panel.getByRole('table',{name:'원천 연령별 단계와 자료 상태'})).toContainText('60대+');
 await expect(panel.getByRole('table',{name:'관측 카드 경보 근거 · 월별 지수나 미래 예측이 아닙니다'})).toContainText('기준선 없음 · 신호 미산출');
});


test('all cohort batch survives reload and opens a single cohort result',async({page})=>{
 await page.goto('/workspace');
 await expect(page.getByLabel('성별',{exact:true})).toHaveValue('all');
 await expect(page.getByLabel('집단',{exact:true})).toHaveValue('all');
 await page.getByRole('button',{name:'지역 분석 요청'}).click();
 const batch=page.getByRole('region',{name:'전체 집단 업무',exact:true});
 await expect(batch).toContainText('8 / 8집단',{timeout:60000});
 const first=page.url();await page.reload();await expect(batch.locator('tbody tr')).toHaveCount(8);
 await page.getByRole('button',{name:'지역 분석 요청'}).click();await expect(page.getByRole('button',{name:'지역 분석 요청'})).toBeEnabled();await expect(page).toHaveURL(first);
 await batch.getByRole('button',{name:'집단 결과 보기'}).first().click();
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
