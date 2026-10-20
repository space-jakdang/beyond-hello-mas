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
