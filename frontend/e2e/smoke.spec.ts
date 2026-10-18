import { test, expect } from '@playwright/test';
test('three pages connect to the sample/fake backend', async ({page}) => {
  await page.goto('/');
  for (const name of ['관찰', '담당자 콘솔', '평가']) {
    await page.getByRole('link', {name, exact: true}).click();
    await expect(page.getByRole('heading', {name, exact: true})).toBeVisible();
    await expect(page.getByRole('status')).toHaveText('서버 연결됨 · 데이터 sample · LLM fake');
  }
});
