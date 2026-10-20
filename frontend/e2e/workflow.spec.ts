import {test,expect} from '@playwright/test';

test('regional task links agents, immutable results and a fresh revision approval',async({page})=>{
 await page.goto('/workspace');
 await page.getByRole('button',{name:'Supervisor에게 업무 지시'}).click();
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 const original=page.url();
 await expect(page.getByRole('list',{name:'에이전트 업무 진행'}).locator('li')).toHaveCount(5);
 await expect(page.getByRole('tabpanel')).toContainText('지역 분석가');
 await page.screenshot({path:'runtime/sample/workflow-desktop.png',fullPage:true});
 await page.getByRole('tab',{name:'통계 근거'}).click();
 await expect(page.getByRole('tabpanel')).toContainText('판정 가능');
 await expect(page.getByRole('img',{name:'실제 관측 월의 지수 추이. 수치는 아래 표에 표시됩니다.'})).toBeVisible();
 await page.getByRole('tab',{name:'통계 근거'}).press('ArrowRight');
 await expect(page.getByRole('tab',{name:'자원 제안'})).toBeFocused();
 await expect(page.getByRole('tabpanel')).toContainText('실제 배정은 하지 않습니다');
 await page.getByLabel('지역',{exact:true}).selectOption('32010');
 await expect(page.locator('.workflow-context')).toContainText('강남구');
 await page.reload();
 await expect(page.locator('.workflow-context')).toContainText('강남구');
 await page.getByRole('link',{name:'공무원 검토함에서 제안 확인 →'}).click();
 await expect(page.getByTestId('review-panel')).toContainText('조건부');
 await page.getByLabel('담당자 이름').fill('워크플로 검토자');
 await page.getByLabel('반려 사유').fill('통계의 출처와 누락 근거를 보완하세요.');
 await page.getByRole('button',{name:'보완 요청'}).click();
 await expect(page).toHaveURL(/\/workspace\?run=/);
 expect(page.url()).not.toBe(original);
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await expect(page.getByLabel('합성 동 격자',{exact:true})).toBeVisible();
 await page.screenshot({path:'runtime/sample/workflow-mobile-result.png',fullPage:true});
 await expect(page.getByRole('link',{name:'이전 제안 보기'})).toHaveAttribute('href',new URL(original).pathname+new URL(original).search);
});

test('regional workspace has responsive navigation and an explicit empty state',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.goto('/');
 await page.getByRole('link',{name:'지역 업무 시작하기 →'}).click();
 await expect(page.getByText('아직 선택한 업무가 없습니다')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:'runtime/sample/workflow-mobile.png',fullPage:true});
 await page.getByRole('link',{name:'인덱스',exact:true}).click();
 await expect(page).toHaveURL(/\/$/);
});


test('map scope reaches Supervisor and missing data blocks new tasks',async({page,request})=>{
 const data=await(await request.get('/analysis/groups')).json();
 const dong=data.neighborhoods.find((d:any)=>d.sgg==='32010');
 await page.goto('/neighborhoods?'+new URLSearchParams({region:'32010',dong:dong.dong_cd,sex:'F',age:'prime'}));
 await page.getByRole('link',{name:'이 동·집단을 Supervisor에게 분석 지시 →'}).click();
 await expect(page.getByLabel('분석 대상 동')).toHaveValue(dong.dong_cd);
 await expect(page.getByLabel('성별',{exact:true})).toHaveValue('F');
 await expect(page.getByLabel('집단',{exact:true})).toHaveValue('prime');
 await page.getByRole('button',{name:'Supervisor에게 업무 지시'}).click();
 await expect(page.getByTestId('workflow-status')).toContainText('승인 대기',{timeout:20000});
 await expect(page.getByRole('tabpanel').locator('tbody tr')).toHaveCount(1);
 await expect(page.getByLabel('실행별 에이전트 상호작용')).toContainText('지역 분석가 → 통계 분석가');
 await page.route('**/analysis/groups',r=>r.fulfill({status:503,body:'자료 없음'}));
 await page.goto('/workspace');
 await expect(page.getByRole('button',{name:'Supervisor에게 업무 지시'})).toBeDisabled();
 await expect(page.getByRole('alert')).toContainText('원자료를 불러오지 못해');
});

test('index explains feedback and period aggregates are not labelled observed months',async({page,request})=>{
 await page.goto('/');
 await expect(page.getByLabel('멀티에이전트 시스템 구조')).toContainText('통계 분석가 ↔ 지역 분석가');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 const data=await(await request.get('/analysis/groups')).json();
 data.period_aggregate=true;data.months=[];
 await page.route('**/analysis/groups',r=>r.fulfill({json:data}));
 await page.goto('/workspace');
 await expect(page.getByLabel('실행 기준 월')).toHaveValue(data.metadata.selected_week.slice(0,7));
 await expect(page.getByText('해당 월의 관측이 아닙니다.',{exact:false})).toBeVisible();
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
