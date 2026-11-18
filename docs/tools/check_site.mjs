/** Browser verification. Use an existing Playwright installation; no backend dependencies change. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(process.env.PLAYWRIGHT_MODULE_ROOT || import.meta.url);
const { chromium } = require('playwright');
const base = process.env.DOCS_BASE_URL || 'http://127.0.0.1:8833/taskiller-backend/';
const output = process.env.DOCS_QA_OUTPUT || path.resolve('docs/qa-output');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
const errors = [], externalRequests = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if (!request.url().startsWith(new URL(base).origin) && /^https?:/.test(request.url())) externalRequests.push(request.url()); });

async function visit(route = '') {
  await page.goto(base + '#/' + route);
  await page.waitForLoadState('networkidle');
  await page.locator('main h1').waitFor();
  assert.equal(await page.getByRole('heading', { name: 'This page could not open.' }).count(), 0, route);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2);
  assert.equal(overflow, false, `Document overflow: ${route}`);
}

try {
  await visit();
  const data = await page.evaluate(() => window.TASKILLER_DATA);
  assert.equal(data.operations.length, 57);
  assert.equal(Object.keys(data.schemas).length, 80);
  await page.screenshot({ path: path.join(output, 'desktop-home.png'), fullPage: true });
  await page.locator('[data-hero="2"]').click();
  assert.match(await page.locator('#hero-insight').innerText(), /Focus Plan/);

  await visit('api/createWorkItem');
  await page.getByRole('tab', { name: 'Request & response' }).click();
  await page.getByLabel('Include optional properties in the example').check();
  assert.ok(await page.locator('.code-wrap').count());
  await page.getByRole('tab', { name: 'Data impact' }).click();
  assert.match(await page.locator('#api-tab-content').innerText(), /work_items/);
  await page.screenshot({ path: path.join(output, 'desktop-api.png'), fullPage: true });
  await page.selectOption('#endpoint-method', 'PUT');
  assert.ok(await page.locator('#endpoint-list .catalog-item').count());
  await page.selectOption('#endpoint-method', 'all');
  await page.selectOption('#endpoint-group', 'health');
  assert.equal(await page.locator('#endpoint-list .catalog-item').count(), 3);
  await page.selectOption('#endpoint-group', 'all');
  await page.fill('#endpoint-search', 'no-such-endpoint-xyz');
  await page.getByRole('button', { name: 'Clear filters' }).click();
  assert.equal(await page.locator('#endpoint-list .catalog-item').count(), 57);

  for (const operation of data.operations) {
    await visit('api/' + operation.id);
    assert.equal(await page.getByRole('heading', { level: 2, name: operation.title, exact: true }).count(), 1, operation.id);
  }
  for (const name of Object.keys(data.schemas)) {
    await visit('objects/' + encodeURIComponent(name));
    assert.equal(await page.locator('.dictionary-header .schema-kind').innerText(), name);
  }
  for (const entity of data.entities) {
    await visit('database/' + entity.id);
    if(await page.locator('#all-database-fields').count())await page.locator('#all-database-fields').click();
    assert.equal(await page.locator('.entity-fields tbody tr:visible').count(), entity.fields.length, entity.id);
  }
  await visit('database/work_items');
  await page.getByLabel('Include Django’s ' + data.meta.frameworkEntities + ' internal tables').uncheck();
  await page.screenshot({ path: path.join(output, 'desktop-database.png'), fullPage: true });
  await page.getByLabel('Include Django’s ' + data.meta.frameworkEntities + ' internal tables').check();
  assert.equal(await page.locator('[data-table]:visible').count(), data.entities.length);

  await page.locator('#global-search').fill('refresh_tokens');
  await page.locator('.search-result[href="#/database/refresh_tokens"]').click();
  assert.match(page.url(), /database\/refresh_tokens/);

  await visit('journey');
  for (let i = 0; i < data.guides.journey.length; i++) {
    await page.locator(`[data-journey-step="${i}"]`).click();
    await page.locator('#play-step').click();
  }
  assert.equal(await page.locator('.journal-entry').count(), 7);
  await page.getByRole('button', { name: 'Start over', exact: true }).click();
  assert.equal(await page.locator('.journal-entry').count(), 0);
  for (const guide of data.guides.mechanics) await visit('mechanics/' + guide.id);
  await visit('glossary');
  await page.fill('#glossary-search', 'ETag');
  assert.ok(await page.locator('.glossary-entry').count());
  await visit('reference/' + encodeURIComponent('ARCHITECTURE.md'));
  await page.locator('#markdown-content h1').waitFor();
  assert.match(await page.locator('#markdown-content').innerText(), /Django/);
  await visit('reference/' + encodeURIComponent('audits/2026-11-18-backend-audit.md'));
  await page.getByRole('link', { name: 'the remediation record' }).click();
  await page.waitForURL(url => url.hash.includes('2026-11-18-backend-hardening.md'));
  await page.locator('#markdown-content h1').waitFor();

  let accessibility = [];
  try {
    const AxeBuilder = require('@axe-core/playwright').default;
    for (const route of ['', 'api/createWorkItem', 'database/work_items', 'objects/WorkItemResponse', 'journey']) {
      await visit(route);
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      accessibility.push({ route, violations: result.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target) })) });
    }
    assert.equal(accessibility.flatMap(item => item.violations).length, 0, JSON.stringify(accessibility, null, 2));
  } catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND') throw error;
    accessibility = [{ skipped: 'Install @axe-core/playwright to run the optional accessibility audit.' }];
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await visit();
  await page.screenshot({ path: path.join(output, 'mobile-home.png'), fullPage: true });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#menu-toggle').evaluate(element => element === document.activeElement), true);
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.locator('[data-nav="api"]').click();
  await page.waitForURL(url => url.hash === '#/api');
  await page.waitForFunction(() => document.getElementById('menu-toggle').getAttribute('aria-expanded') === 'false');
  assert.equal(await page.locator('#menu-toggle').getAttribute('aria-expanded'), 'false');
  for (const route of ['api/createWorkItem', 'database/work_items', 'objects/WorkItemResponse', 'journey', 'mechanics', 'reference']) await visit(route);
  await page.screenshot({ path: path.join(output, 'mobile-reference.png'), fullPage: true });
  assert.deepEqual(errors, [], 'Browser errors');
  assert.deepEqual(externalRequests, [], 'The guide should make no external requests');
  const report = { operations: data.operations.length, entities: data.entities.length, fields: data.meta.fields, schemas: Object.keys(data.schemas).length, browserErrors: errors, externalRequests, accessibility, desktop: '1440 × 1000', mobile: '390 × 844' };
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
