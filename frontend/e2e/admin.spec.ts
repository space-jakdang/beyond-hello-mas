import {test, expect} from '@playwright/test';

test('admin screening and mandatory handoff reach the operator console',async({page})=>{
  await page.goto('/observatory');
  await page.getByRole('combobox',{name:'시나리오',exact:true}).selectOption({label:'admin-synthetic'});
  await page.getByRole('button',{name:'실행',exact:true}).click();
  await expect(page.getByTestId('run-status')).toHaveText('완료');
  const admin=await page.getByTestId('run-id').innerText();
  await page.goto('/console');
  await expect(page.getByTestId(`alert-${admin}-screening_requested`)).toContainText('선별 질문 준비');
  await page.goto('/observatory');
  await page.getByRole('combobox',{name:'시나리오',exact:true}).selectOption({label:'case-handoff-synthetic'});
  await page.getByRole('button',{name:'실행',exact:true}).click();
  await expect(page.getByTestId('run-status')).toHaveText('완료');
  const handoff=await page.getByTestId('run-id').innerText();
  await page.goto('/console');
  await expect(page.getByTestId(`alert-${handoff}-human_handoff`)).toContainText('담당자 확인 요청');
});
