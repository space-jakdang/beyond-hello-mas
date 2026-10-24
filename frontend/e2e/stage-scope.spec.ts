import {test,expect} from '@playwright/test';

test('source stages keep basic and weekly exploration separate and common priority unevaluated',async({page,request})=>{
 const data=await(await request.get('/analysis/groups?week=all&card_age=all')).json();
 const row=data.segments.find((r:any)=>r.sgg==='11230'&&r.sex==='M'&&r.age_group==='youth'&&r.ym===data.months.at(-1));
 expect(row.reachable_base_stages).toEqual([1,2,3]);expect(row.priority_review).toBeNull();
 await page.goto('/neighborhoods?'+new URLSearchParams({sex:'M',age:'youth',month:row.ym,dong:row.dong_cd,week:'all',card_age:'all'}));
 await expect(page.getByTestId('group-detail')).toContainText(`기본 단계 ${row.base_stage}단계`);
 await expect(page.getByTestId('group-detail')).toContainText('신호 미결합');
 await expect(page.getByTestId('group-detail')).toContainText('공통 우선 검토 기준 미확정');
 await page.getByRole('combobox',{name:'연령집단',exact:true}).selectOption('all');
 const summary=page.getByRole('region',{name:'전체 집단 요약'});
 await expect(summary).toContainText('우선 검토 기준은 미확정');
 await expect(summary).toContainText('미평가');
});
