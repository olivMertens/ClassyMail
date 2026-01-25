import { test, expect } from '@playwright/test';

const fixtureEmails = {
  items: [
    {
      id: 'email-1',
      sender: 'alice@example.com',
      subject: 'Attestation scolaire',
      status: 'PROCESSED',
      classification: {
        detected_intents: [
          { intent: 'Attestation scolaire', confidence: 0.92 },
        ],
        needs_review: false,
      },
      updated_at: new Date().toISOString(),
      markdown: '# Hello',
      usage: {
        phi4: { model: 'phi-4', cost_usd: 0.001 },
        mistral: { cost_usd: 0.01 },
      },
    },
    {
      id: 'email-2',
      sender: 'bob@example.com',
      subject: 'Dommages électriques',
      status: 'REVIEW_REQUIRED',
      classification: {
        detected_intents: [
          { intent: 'Dommages électriques', confidence: 0.65 },
        ],
        needs_review: true,
      },
      updated_at: new Date().toISOString(),
      markdown: '## Dommages',
      usage: {
        phi4: { model: 'phi-4', cost_usd: 0.002 },
        mistral: { cost_usd: 0.02 },
      },
    },
  ],
  page: 1,
  page_size: 20,
  total: 2,
  finetune_min_required: 50,
  finetune_reviewed_ready: 1,
};

const fixtureStats = {
  processed: 1,
  review_required: 1,
  total: 2,
  finetune: {
    reviewed_ready: 1,
    min_required: 50,
    ready: false,
  },
};

// Mock API responses to make UI deterministic
async function mockApi(page) {
  await page.route('**/api/emails**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/api/emails')) {
      return route.fulfill({ status: 200, body: JSON.stringify(fixtureEmails) });
    }
    if (url.pathname.includes('/export')) {
      return route.fulfill({ status: 200, body: 'id,file_url,status' });
    }
    route.continue();
  });
  await page.route('**/api/stats**', async (route) => {
    return route.fulfill({ status: 200, body: JSON.stringify(fixtureStats) });
  });
}

test.describe('Dashboard UI', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
    await page.goto('/');
  });

  test('renders tabs and switches to upload', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Liste|tab_list/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Upload|Téléversement/i })).toBeVisible();
    await page.getByRole('button', { name: /Upload|Téléversement/i }).click();
    await expect(page.locator('form')).toBeVisible();
  });

  test('shows filters, search, pagination', async ({ page }) => {
    await expect(page.getByPlaceholder(/Rechercher|Search/)).toBeVisible();
    await expect(page.getByRole('button', { name: /Tous|All/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Traités|Processed/ })).toBeVisible();
    await expect(page.locator('select')).toHaveValue('20');
  });

  test('displays email cards from fixture and opens modal', async ({ page }) => {
    const card = page.locator('div.bg-slate-800', { hasText: 'Attestation scolaire' }).first();
    await expect(card).toBeVisible();
    await card.click();
    const modal = page.locator('div.bg-slate-900');
    await expect(modal).toBeVisible();
    await expect(modal).toContainText('Attestation scolaire');
  });
});
