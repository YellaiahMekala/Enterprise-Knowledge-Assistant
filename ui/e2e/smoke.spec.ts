// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { expect, Page, test } from '@playwright/test';
import path from 'node:path';

// Sign in, upload, wait for indexing, ask, see a cited answer, see a refusal, sign out.
// The API key comes from e2e/stack.sh (a fresh one per run).
const KEY = process.env['E2E_API_KEY'] ?? '';
const FIXTURE = path.join(__dirname, 'fixtures', 'leave-policy.md');

// Forms wire themselves up a moment after render and can reset a value typed in that instant.
async function type(page: Page, selector: string, text: string): Promise<void> {
  await expect(async () => {
    await page.fill(selector, text);
    await page.waitForTimeout(100);
    expect(await page.inputValue(selector)).toBe(text);
  }).toPass({ timeout: 5_000 });
}

test('a user signs in, uploads a document and gets a cited answer', async ({ page }) => {
  expect(KEY, 'set E2E_API_KEY (see e2e/stack.sh)').not.toBe('');
  const consoleErrors: string[] = [];
  let expected401 = 1; // the deliberate wrong-key attempt
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (m.text().includes('401') && expected401-- > 0) return;
    consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => consoleErrors.push(String(e)));

  await page.goto('/');
  await page.waitForURL('**/login');

  await type(page, 'input[name=key]', 'wrong-key');
  await page.click('button[type=submit]');
  await expect(page.locator('.error')).toContainText('not accepted');

  await type(page, 'input[name=key]', KEY);
  await page.click('button[type=submit]');
  await page.waitForURL('**/chat');

  await page.click('text=Documents');
  await page.setInputFiles('input[type=file]', FIXTURE);
  const row = page.locator('tbody tr', { hasText: 'leave-policy.md' });
  await expect(row).toBeVisible();
  // The worker downloads the embedding model on its first start, so allow a few minutes.
  await expect(row.locator('.badge')).toHaveText('ready', { timeout: 5 * 60_000 });

  await page.click('text=Chat');
  await type(page, 'textarea', 'How many days of paid annual leave does a full-time employee get?');
  await page.click('button[type=submit]');
  const answer = page.locator('article.assistant').last();
  await expect(answer.locator('.citations li').first()).toBeVisible({ timeout: 60_000 });
  await expect(answer).toContainText('24 days');
  await expect(answer.locator('.citations')).toContainText('leave-policy.md');

  await type(page, 'textarea', 'What is the airspeed velocity of an unladen swallow?');
  await page.click('button[type=submit]');
  await expect(page.getByText('Not answered')).toBeVisible({ timeout: 60_000 });

  await expect(page.locator('.conversations li').first()).toBeVisible();

  await page.click('text=Sign out');
  await page.waitForURL('**/login');
  await page.goto('/chat');
  await page.waitForURL('**/login');

  expect(consoleErrors).toEqual([]);
});
