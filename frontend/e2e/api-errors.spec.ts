import {test,expect} from '@playwright/test';

test('denied batch lookup stops polling and shows recovery without exposing HTML',async({page})=>{
 let calls=0,posts=0;
 page.on('request',r=>{if(r.method()==='POST')posts++;});
 await page.route('**/regional/batches/lost',route=>{calls++;return route.fulfill({status:403,contentType:'text/html',body:'<html>private upstream debug</html>'});});
 await page.goto('/workspace?batch=lost');
 await expect(page.getByRole('alert')).toContainText('접근이 거부되었습니다');
 await expect(page.getByRole('alert')).not.toContainText('private upstream');
 await expect(page.getByRole('link',{name:'실행 목록 다시 확인'})).toBeVisible();
 await page.waitForTimeout(2300);
 expect(calls).toBe(1);expect(posts).toBe(0);
});

test('missing run stops refresh and HTML success is not parsed as analysis',async({page})=>{
 let calls=0;
 await page.route('**/runs/lost/overview',route=>{calls++;return route.fulfill({status:404,json:{detail:'run not found'}});});
 await page.route('**/runs/lost/traces/stream',route=>route.fulfill({status:404,body:''}));
 await page.goto('/workspace?run=lost');
 await expect(page.getByRole('alert')).toContainText('실행을 찾을 수 없습니다');
 await page.waitForTimeout(2300);expect(calls).toBe(1);
 await page.route('**/analysis/groups*',route=>route.fulfill({contentType:'text/html',body:'<html>Login</html>'}));
 await page.goto('/neighborhoods');
 await expect(page.getByRole('alert')).toContainText('API 대신 웹페이지');
});

test('missing analysis inputs explain configuration rather than a JSON dump',async({page})=>{
 await page.route('**/analysis/groups*',route=>route.fulfill({status:503,json:{detail:'집단 분석 입력이 없거나 유효하지 않습니다.'}}));
 await page.goto('/neighborhoods');
 await expect(page.getByRole('alert')).toContainText('데이터 설정과 서버 상태');
 await expect(page.getByRole('button',{name:'집단 분석 다시 불러오기'})).toBeVisible();
 await page.goto('/workspace');
 await expect(page.getByRole('button',{name:'지역 자료 다시 불러오기'})).toBeVisible();
});


test('SSE failure leaves overview polling available without stream retries',async({page})=>{
 let streams=0,overviews=0;
 await page.route('**/runs/stream-blocked/overview',route=>{overviews++;return route.fulfill({status:503,json:{detail:'temporarily unavailable'}});});
 await page.route('**/runs/stream-blocked/traces/stream',route=>{streams++;return route.fulfill({status:403,body:''});});
 await page.goto('/workspace?run=stream-blocked');
 await expect(page.getByRole('alert')).toContainText('503');
 await page.waitForTimeout(4300);
 expect(streams).toBe(1);expect(overviews).toBeGreaterThan(1);
});
