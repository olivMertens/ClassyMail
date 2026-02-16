# Email Generation for E2E Testing

This document explains how to generate realistic email PDFs for end-to-end testing of the classification pipeline.

## Quick Start

Generate 10 random realistic emails:

```bash
uv run python scripts/generate_realistic_emails.py --count 10
```

Generate emails for specific categories:

```bash
uv run python scripts/generate_realistic_emails.py --count 5 --categories "Attestation habitation" "Résiliation"
```

Custom output directory:

```bash
uv run python scripts/generate_realistic_emails.py --count 20 --out dataset/test_pdfs
```

## Available Categories

The script includes realistic email templates for all supported categories.

> **G2S Insurance categories**: See [G2S_CUSTOMIZATION.md](G2S_CUSTOMIZATION.md#insurance-category-taxonomy) for the full category taxonomy (Attestation habitation, Résiliation, Sinistre, etc.).
>
> **Other organizations**: Customize the category templates in `scripts/generate_realistic_emails.py` for your domain.

## Email Content

Each generated email includes:

- **Realistic sender** (name + email)
- **Contextual subject line**
- **Natural text** with domain-specific vocabulary
- **Specific details** (addresses, contract numbers, dates, amounts)
- **Proper formatting** (greetings, body, signature)

## Testing Workflow

1. **Generate test emails:**

   ```bash
   uv run python scripts/generate_realistic_emails.py --count 50
   ```

2. **Upload via API:**

   ```bash
   curl -X POST http://localhost:8000/api/upload \
     -H "Content-Type: multipart/form-data" \
     -F "file=@dataset/pdf/Attestation_habitation_20260127_123456_abc123.pdf"
   ```

3. **Or use the Web UI:**

   - Navigate to <http://localhost:8000/>
   - Use the upload interface
   - Check dashboard for classification results

## Integration with Email Sending

To test the full E2E flow including email sending:

1. Generate test PDFs with this script
2. Configure SendGrid API key (`SENDGRID_API_KEY`)
3. Set test recipient email (`TEST_EMAIL_RECIPIENT`)
4. Use the webhook endpoint:

   ```bash
   curl -X POST http://localhost:8000/api/webhook \
     -H "Content-Type: application/json" \
     -d '{
       "email_from": "test@example.com",
       "subject": "Test Insurance Email",
       "attachments": [{"filename": "test.pdf", "content": "...base64..."}]
     }'
   ```

## Script Features

- **Automatic PDF generation** using fpdf2
- **Unique filenames** with timestamps and random IDs
- **Category distribution tracking** - shows how many emails per category
- **Configurable count** - generate as many as needed
- **Category filtering** - focus on specific use cases

## Dependencies

The script requires `fpdf2` which is included in the dev dependencies:

```bash
uv sync --extra dev
```

## Examples

### Generate 100 mixed emails

```bash
uv run python scripts/generate_realistic_emails.py --count 100
```

### Generate only attestation and résiliation emails

```bash
uv run python scripts/generate_realistic_emails.py --count 30 \
  --categories "Attestation habitation" "Résiliation"
```

### Custom output with many emails

```bash
uv run python scripts/generate_realistic_emails.py \
  --count 200 \
  --out dataset/pdf/test_batch_$(date +%Y%m%d)
```

## Tips

- **Start small:** Generate 10-20 emails first to verify pipeline works
- **Mix categories:** Use default (no `--categories`) for realistic distribution
- **Check results:** Use dashboard to verify classification accuracy
- **Iterate:** Adjust email templates in the script for edge cases

## See Also

- [SCENARIO_E2E.md](./SCENARIO_E2E.md) - Full E2E testing scenarios
- [LOCAL_DEVELOPMENT.md](./LOCAL_DEVELOPMENT.md) - Running the app locally
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Understanding the classification pipeline
