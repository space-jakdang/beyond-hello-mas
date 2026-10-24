import {test,expect} from '@playwright/test';

test('index explains the workspace and every page returns home',async({page})=>{
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'무엇을 확인하고 싶으신가요?'})).toBeVisible();
  for(const name of ['동네 분석','관찰','정책 탐색','담당자 콘솔','평가']) {
    const link=page.getByRole('navigation').getByRole('link',{name,exact:true});
    if(!await link.isVisible())await page.getByText('검증·연구 도구',{exact:true}).click();
    await link.click();
    await expect(page.getByRole('heading',{level:1})).toHaveText(name);
    await expect(page.getByRole('navigation').getByRole('link',{name,exact:true})).toHaveAttribute('aria-current','page');
    await page.getByRole('link',{name:'Beyond Hello MAS 인덱스'}).click();
    await expect(page.getByRole('heading',{level:1})).toHaveText('프로젝트 안내');
  }
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('contentinfo')).toContainText('연구·개발용');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('navigation').getByRole('link',{name:'인덱스',exact:true}).click();
  await expect(page.getByRole('heading',{level:1})).toHaveText('프로젝트 안내');
  await page.goto('/unknown-page');
  await expect(page.getByRole('heading',{level:1})).toHaveText('페이지를 찾을 수 없습니다');
});

test('policy page distinguishes credential, cached list, live detail and failed refresh',async({page})=>{
  const policy={id:'fixture-policy',title:'검증용 돌봄 정책',agency:'서울특별시',scope:'seoul',summary:'합성 정책 UI 검증',support:'방문 돌봄',eligibility:'담당자 확인',criteria:'조건 검토',deadline:'별도 문의',application:'방문 신청',contact:'기관 문의',url:'https://www.gov.kr/'};
  const coverage={credentials_configured:true,status:'cached',fetched_at:'2026-10-20T00:00:00Z',stale:false,scopes:{central:0,seoul:1,gangnam:0,gangwon:0,chuncheon:0},source_count:1,limitation:'등록 정보 범위이며 자격·정원 미확인',last_attempt:{status:'success'}};
  await page.route('**/policies**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/policies/refresh') {coverage.last_attempt={status:'failed',reason:'TimeoutError'};await route.fulfill({json:coverage});}
    else if(url.pathname==='/policies/fixture-policy') await route.fulfill({json:{status:'live',policy,checked_at:'2026-10-20T00:00:00Z',limitation:coverage.limitation}});
    else await route.fulfill({json:{items:url.searchParams.get('query')==='없는정책'?[]:[policy],total:url.searchParams.get('query')==='없는정책'?0:1,page:1,next_page:null,coverage}});
  });
  await page.goto('/policy');
  await expect(page.getByText('연결 설정됨',{exact:true})).toBeVisible();
  await expect(page.getByText('저장된 목록',{exact:true})).toBeVisible();
  await page.getByLabel('관할',{exact:true}).selectOption('seoul');
  await page.getByLabel('정책 검색',{exact:true}).fill('돌봄');
  const searched=page.waitForRequest(r=>r.url().includes('/policies?')&&new URL(r.url()).searchParams.get('query')==='돌봄');
  await page.getByRole('button',{name:'검색',exact:true}).click();
  expect(new URL((await searched).url()).searchParams.getAll('scopes')).toEqual(['seoul']);
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'상세 확인 · 검증용 돌봄 정책'}).click();
  await expect(page.getByLabel('정책 상세')).toBeFocused();
  await expect(page.getByLabel('정책 상세')).toBeInViewport();
  await expect(page.getByLabel('정책 상세')).toContainText('정부24 최신 상세 확인');
  await expect(page.getByRole('link',{name:'공식 안내 원문 열기'})).toHaveAttribute('href','https://www.gov.kr/');
  await page.getByRole('button',{name:'정부24 목록 갱신'}).click();
  const refreshAlert=page.getByRole('alert');await expect(refreshAlert).toContainText('기존 저장 목록은 계속 확인할 수 있습니다.');
  const refreshReason=refreshAlert.getByText(/TimeoutError/);await expect(refreshReason).toBeHidden();
  await refreshAlert.getByText('조회 오류 상세',{exact:true}).click();await expect(refreshReason).toBeVisible();
  await page.getByLabel('정책 검색',{exact:true}).fill('없는정책');
  await page.getByRole('button',{name:'검색',exact:true}).click();
  await expect(page.getByText('저장된 목록에서 이 조건에 맞는 정책을 찾지 못했습니다.',{exact:false})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('link',{name:'정책 조사 지시하기'}).click();
  await expect(page.locator('#policy-task')).toBeInViewport();
});


test('runtime status distinguishes missing real input from a synthetic demo',async({page})=>{
 await page.route('**/readiness',route=>route.fulfill({json:{ready:false,data_mode:'local',llm_mode:'live',storage:'temporary_instance',warnings:['인스턴스 변경 후 이력이 사라질 수 있습니다.'],analysis:{status:'unavailable'},catalog:{status:'unavailable'}}}));
 await page.goto('/');
 const status=page.getByRole('complementary',{name:'서버 준비 상태'});
 await expect(status).toContainText('실제 자료 모드 (입력 확인 필요)');await expect(status).toContainText('자료 미준비');
 await status.getByText(/자료·저장소 확인 항목/).click();await expect(status).toContainText('인스턴스별 임시 저장');
 await expect(page.getByRole('navigation').getByRole('link',{name:'지역 업무',exact:true})).toBeVisible();
 await expect(page.getByRole('navigation').getByRole('link',{name:'미래 시나리오',exact:true})).toBeHidden();
 await page.screenshot({path:'../.local-plans/ux-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:'../.local-plans/ux-mobile.png',fullPage:true});
});

test('runtime status can retry a failed diagnostic without starting work',async({page})=>{
 let failed=true;
 await page.route('**/readiness',route=>failed?route.fulfill({status:503,json:{detail:'private readiness failure'}}):route.fulfill({json:{ready:true,data_mode:'sample',llm_mode:'fake',storage:'local_directory',warnings:[],analysis:{status:'ready',geometry:'synthetic_grid'},catalog:{status:'ready'}}}));
 await page.goto('/');await expect(page.getByRole('alert')).toContainText('자료 준비 상태를 확인하지 못했습니다');
 await expect(page.getByRole('alert').locator('pre')).toBeHidden();
 await page.getByText('기술 오류 상세',{exact:true}).click();await expect(page.getByRole('alert')).toContainText('private readiness failure');
 failed=false;await page.getByRole('button',{name:'서버 상태 다시 확인'}).click();
 await expect(page.getByRole('complementary',{name:'서버 준비 상태'})).toContainText('합성 시연 자료');
});

test('runtime status does not guess when a mode or readiness state is unknown',async({page})=>{
 let unknownMode=true;
 await page.route('**/readiness',route=>route.fulfill({json:{ready:false,data_mode:unknownMode?'future_mode':'local',llm_mode:'future_model',storage:'future_storage',warnings:[],analysis:{status:'future_status',geometry:'future_geometry'},catalog:{status:'future_status'}}}));
 await page.goto('/');const status=page.getByRole('complementary',{name:'서버 준비 상태'});
 await expect(status).toContainText('자료 모드 확인 필요');await expect(status).toContainText('자료 유형 확인 필요');await expect(status).toContainText('모델 실행 방식 확인 필요');
 await status.getByText('자료·저장소 확인 항목',{exact:false}).click();await expect(status).toContainText('자료 상태 확인 필요');await expect(status).toContainText('운영 환경에서 확인 필요');
 await expect(status).not.toContainText('합성 시연 자료');await expect(status).not.toContainText('정해진 테스트 응답');
 unknownMode=false;await page.reload();await expect(status).toContainText('실제 자료 모드 (상태 확인 필요)');await expect(status).not.toContainText('실제 지역 집계');
});


test('policy search explains a missing snapshot and keeps API detail collapsed',async({page})=>{
 const coverage={credentials_configured:false,status:'unavailable',fetched_at:null,stale:true,scopes:{central:null,seoul:null,gangnam:null,gangwon:null,chuncheon:null},source_count:null,limitation:'정부24 등록 정책 범위이며 개인 자격·정원은 미확인',last_attempt:null};
 let firstSearch=true;
 await page.route('**/policies**',route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/policies/refresh')return route.fulfill({json:coverage});
  if(firstSearch){firstSearch=false;return route.fulfill({json:{items:[],total:0,page:1,next_page:null,coverage}});}
  return route.fulfill({status:503,json:{detail:'private gateway failure'}});
 });
 await page.goto('/policy');
 await expect(page.getByText('연결 설정 필요',{exact:true})).toBeVisible();
 await expect(page.getByRole('region',{name:'정책 검색 결과'})).toContainText('저장된 정책 목록이 없어 결과를 확인할 수 없습니다.');
 await expect(page.getByRole('button',{name:'정부24 목록 갱신'})).toBeDisabled();
 await expect(page.locator('body')).not.toContainText('GOV24_SERVICE_KEY');
 await page.getByRole('button',{name:'검색',exact:true}).click();
 const alert=page.getByRole('alert');await expect(alert).toContainText('정책 정보를 불러오지 못했습니다.');
 const raw=alert.getByText(/private gateway failure/);await expect(raw).toBeHidden();
 await alert.getByText('오류 상세',{exact:true}).click();await expect(raw).toBeVisible();
});

test('unknown policy coverage status does not claim a saved list is missing',async({page})=>{
 const coverage={credentials_configured:true,status:'future_status',fetched_at:'2026-10-24T00:00:00Z',stale:false,scopes:{central:2,seoul:0,gangnam:0,gangwon:0,chuncheon:0},source_count:2,limitation:'목록 해석에 제한이 있습니다.',last_attempt:null};
 await page.route('**/policies**',route=>route.fulfill({json:{items:[],total:0,page:1,next_page:null,coverage}}));
 await page.goto('/policy');
 const status=page.getByRole('region',{name:'정부24 연결 및 수집 상태'});
 await expect(status).toContainText('자료 상태 확인 필요');
 await expect(status).toContainText('확인 가능한 정책 목록 2건에서 검색합니다');
 await expect(status).not.toContainText('저장된 정책 목록이 없습니다');
 const results=page.getByRole('region',{name:'정책 검색 결과'});
 await expect(results).toContainText('목록 상태를 확인할 수 없어 조건에 맞는 정책을 판단할 수 없습니다.');
});
