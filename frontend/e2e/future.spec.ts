import {test,expect} from '@playwright/test';
test('one click schedules future periods and dong selection reveals resources without duplicating on reload',async({page})=>{
 test.setTimeout(60000);
 await page.setViewportSize({width:390,height:844});
 let posts=0;page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/future/batches')posts++;});
 await page.goto('/');await page.getByText('정책 검색·평가·연구 도구 더 보기',{exact:true}).click();await page.getByRole('main').getByRole('link',{name:'미래 시나리오',exact:true}).click();
 await page.getByLabel('시나리오 지역').selectOption('32010');
 await page.getByRole('button',{name:'미래 시나리오 분석 시작',exact:true}).click();
 await expect(page).toHaveURL(/future\?batch=/);
 await expect(page.getByRole('status').filter({hasText:'3 / 3 기간 실행 종료'})).toBeVisible({timeout:40000});
 await expect(page.getByLabel('기간별 분석 상태').getByRole('button')).toHaveCount(3);
 await page.getByLabel('기간별 분석 상태').getByRole('button').last().click();
 await expect(page.getByText('합성 미래 결과',{exact:true})).toBeVisible({timeout:20000});
 const dong=page.getByLabel('동 선택',{exact:true});await dong.selectOption({index:1});
 await expect(page.getByRole('tab',{name:'자원 제안',exact:true})).toHaveAttribute('aria-selected','true');
 await expect(page.locator('.selected-resource-summary')).toContainText('자원 제안');
 await expect(page.getByRole('meter',{name:'추천 슬롯 충족 수'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:'runtime/sample/future-mobile.png',fullPage:true});
 const url=page.url();await page.reload();await expect(page.getByLabel('기간별 분석 상태')).toBeVisible();
 expect(page.url()).toBe(url);expect(posts).toBe(1);await expect(page.getByLabel('기간별 분석 상태').getByRole('button').last()).toHaveAttribute('aria-pressed','true');
 await page.getByLabel('합성 동 격자',{exact:true}).locator('[role="button"]').first().focus();
 await page.keyboard.press('Enter');await expect(page.locator('.selected-resource-summary')).toBeVisible();
});

test('future start retry reuses the same request and unavailable data is not replaced',async({page})=>{
 const ids:string[]=[];
 await page.route('**/future/batches',route=>{expect(route.request().postDataJSON().sgg).toBe('11230');ids.push(route.request().postDataJSON().request_id);return route.fulfill({status:422,json:{detail:'baseline unavailable'}});});
 await page.route('**/future/batches/*',route=>route.fulfill({status:404,json:{detail:'not found'}}));
 await page.goto('/future');await page.getByRole('button',{name:'미래 시나리오 분석 시작',exact:true}).click();
 await expect(page.getByRole('alert')).toBeVisible();await page.getByRole('button',{name:'같은 요청 다시 확인'}).click();
 await expect(page.getByRole('alert')).toBeVisible();expect(ids).toHaveLength(2);expect(ids[0]).toBe(ids[1]);
 await expect(page.getByLabel('기간별 분석 상태')).toHaveCount(0);
});
