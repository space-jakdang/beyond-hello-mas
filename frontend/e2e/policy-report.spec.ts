import {test,expect} from '@playwright/test';
test('policy report has separate versioned review, readable sources and mobile print',async({page,request})=>{
 await page.goto('/workspace');await page.getByRole('button',{name:'Supervisor에게 업무 지시'}).click();
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 const runId=new URL(page.url()).searchParams.get('run')!;
 const overview=await (await request.get(`/runs/${runId}/overview`)).json();overview.review.proposal.policy_design={status:'draft'};
 const draft={status:'needs_human',title:'지역 연결 시범안',target_group:'강남 청년',proposed_service:'방문과 연결 활동을 현지 여건에 맞게 검토',problem_evidence_ids:['observed'],adaptations:[{source_policy_ids:['p'],local_difference:'운영기관 미확인',proposed_change:'접근 수단 확인 후 방식 조정',verification_needed:['이동 여건']}],citations:[{policy_id:'p',field:'title',quote:'공식 관계 지원'}],operating_steps:['대상 확인','시범 계획'],required_roles:['담당자'],feasibility_checks:['예산 확인'],equity_risks:['낙인 방지'],reviewer_questions:['운영기관 확보 여부'],evaluation:{outcome:'참여 유지',baseline_needed:'참여 기준선',comparison_method:'전후 비교',observation_period:'합의 필요',success_criterion_to_agree:'유지 기준 합의',stop_criterion_to_agree:'민원 기준 합의'}};
 let saved:any={revision:0,document:{status:'needs_human',version:'v1',review_status:'pending',draft,gap:{search_scope:['gangnam:관계'],limitations:['검색 범위 한정']},analogues:[{policy_id:'p',title:'공식 관계 지원',source_url:'https://example.org/official',checked_at:'2026-10-22'}]},history:[]};let posts=0;let stale=false;
 await page.route(`**/runs/${runId}/overview`,route=>route.fulfill({json:overview}));
 await page.route(`**/runs/${runId}/policy-design**`,async route=>{
  if(route.request().method()==='POST'){
   if(stale){saved={...saved,revision:3,document:{...saved.document,version:'v3',draft:{...saved.document.draft,title:'다른 담당자의 수정안'}}};stale=false;await route.fulfill({status:409,json:{detail:'changed'}});return;}
   const b=route.request().postDataJSON();posts++;
   expect(b.expected_revision).toBe(saved.revision);
   const document=b.action==='revise'?{...saved.document,version:'v2',status:b.draft.status,draft:b.draft,review_status:'pending'}:{...saved.document,review_status:b.action};
   saved={revision:saved.revision+1,document,history:[...saved.history,{revision:saved.revision+1,action:b.action,operator:b.operator,reason:b.reason,at:'2026-10-22',document}]};
  }
  await route.fulfill({json:saved});
 });
 await page.goto(`/console?run=${runId}`);await page.getByRole('tab',{name:'자원 제안'}).click();
 const report=page.getByLabel('정책 설계 보고서');await expect(report).toContainText('예산 편성·법률 적합성·실제 시행 승인이 아닙니다');
 await expect(report.getByRole('link',{name:'공식 출처 확인'})).toHaveAttribute('href','https://example.org/official');
 await expect(report.getByRole('button',{name:'정책안 검토 승인'})).toBeDisabled();
 await report.getByLabel('정책 검토자',{exact:true}).fill('정책 담당자');await report.getByLabel('정책 검토 사유').fill('현지 운영 방식 보완');
 await expect(report.getByRole('button',{name:'정책안 검토 승인'})).toBeDisabled();
 await report.getByText('담당자가 수정본 작성',{exact:true}).press('Enter');await report.getByLabel('수정본 검토 상태').selectOption('draft');await report.getByLabel('현지 제공 방식').fill('현지 이동 여건을 먼저 확인하는 수정안');
 await report.getByRole('button',{name:'새 버전으로 저장'}).click();await expect(report).toContainText('정책 검토·수정 이력 1건');
 await report.getByRole('button',{name:'정책안 검토 승인'}).click();await expect(report).toContainText('정책 검토·수정 이력 2건');expect(posts).toBe(2);
 await page.reload();await page.getByRole('tab',{name:'자원 제안'}).click();await expect(report).toContainText('현지 이동 여건을 먼저 확인하는 수정안');
 await expect(report.getByRole('button',{name:'정책안 검토 승인'})).toBeDisabled();
 stale=true;await report.getByText('담당자가 수정본 작성',{exact:true}).press('Enter');await report.getByLabel('정책 검토자',{exact:true}).fill('담당자');await report.getByLabel('정책 검토 사유').fill('보완');await report.getByLabel('정책안 제목').fill('내 수정안');await report.getByRole('button',{name:'새 버전으로 저장'}).click();await expect(report.getByRole('alert')).toContainText('최신 보고서를 다시 확인');await expect(report).toContainText('다른 담당자의 수정안');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.emulateMedia({media:'print'});await expect(report.getByRole('heading',{name:'담당자 검토용 정책 설계 보고서'})).toBeVisible();await expect(report.getByRole('button',{name:'정책 보고서 인쇄'})).toBeHidden();
});
