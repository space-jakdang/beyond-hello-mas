import {test,expect} from '@playwright/test';

test('index explains the workspace and every page returns home',async({page})=>{
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'무엇을 확인하고 싶으신가요?'})).toBeVisible();
  for(const name of ['동네 분석','관찰','정책 탐색','담당자 콘솔','평가']) {
    await page.getByRole('navigation').getByRole('link',{name,exact:true}).click();
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
    if(url.pathname==='/policies/refresh') {coverage.last_attempt={status:'failed'};await route.fulfill({json:coverage});}
    else if(url.pathname==='/policies/fixture-policy') await route.fulfill({json:{status:'live',policy,checked_at:'2026-10-20T00:00:00Z',limitation:coverage.limitation}});
    else await route.fulfill({json:{items:url.searchParams.get('query')==='없는정책'?[]:[policy],total:url.searchParams.get('query')==='없는정책'?0:1,page:1,next_page:null,coverage}});
  });
  await page.goto('/policy');
  await expect(page.getByText('설정됨',{exact:true})).toBeVisible();
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
  await expect(page.getByRole('alert')).toContainText('최근 갱신 실패');
  await page.getByLabel('정책 검색',{exact:true}).fill('없는정책');
  await page.getByRole('button',{name:'검색',exact:true}).click();
  await expect(page.getByText('조회된 정책이 없습니다.',{exact:false})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('link',{name:'정책 조사 지시하기'}).click();
  await expect(page.locator('#policy-task')).toBeInViewport();
});
