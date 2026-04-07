"""
Seed script: Deploy AI Search, create per-intent indexes, and upload
sample email data (positive + negative examples) for agentic classification.

Usage:
    uv run python scripts/seed_ai_search.py

Prerequisites:
    - az login (already done)
    - pip install azure-search-documents azure-identity
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config — reads from environment or secrets.env, falls back to defaults
# ---------------------------------------------------------------------------
import os
from pathlib import Path

# Load secrets.env if present
_env_file = Path(__file__).parent.parent / "secrets.env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

RG = os.getenv("AZURE_RESOURCE_GROUP", "email-poc-rg")
LOCATION = os.getenv("AZURE_LOCATION", "swedencentral")
SEARCH_NAME = os.getenv("AZURE_SEARCH_SERVICE_NAME", "")
AI_FOUNDRY_NAME = os.getenv("AI_FOUNDRY_NAME", "")
EMBEDDING_DEPLOYMENT = os.getenv("EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536

CATEGORIES = [
    {
        "name": "Billing inquiry",
        "slug": "billing-inquiry",
        "description": "Questions about invoices, payments, charges, refunds, or account balance.",
    },
    {
        "name": "Technical support",
        "slug": "technical-support",
        "description": "Requests for help with technical issues, product malfunctions, or troubleshooting.",
    },
    {
        "name": "Account management",
        "slug": "account-management",
        "description": "Requests related to account creation, modification, closure, or profile updates.",
    },
    {
        "name": "Document request",
        "slug": "document-request",
        "description": "Requests for certificates, statements, certificates, or official documents.",
    },
    {
        "name": "General inquiry",
        "slug": "general-inquiry",
        "description": "General questions, feedback, or inquiries that do not fit other categories.",
    },
]

# ---------------------------------------------------------------------------
# Sample emails — 5 positive + 2 negative per category
# ---------------------------------------------------------------------------
SAMPLE_EMAILS: dict[str, list[dict]] = {
    "billing-inquiry": [
        # ── Positive (human_verified / human_reinforced) ──
        {
            "content": """# Invoice Discrepancy

From: marie.dupont@acme-corp.fr
Date: 2025-11-15

Dear Billing Department,

I received invoice #INV-2025-4782 dated November 10, 2025 for the amount of €1,245.00. However, my contract specifies a monthly fee of €980.00. Could you please explain the €265.00 difference?

Additionally, I noticed that my last payment of €980.00 made on October 5 has not been reflected on my account statement.

Please send me an updated invoice at your earliest convenience.

Best regards,
Marie Dupont
Account #AC-78432""",
            "label": "billing-inquiry",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Refund Request

From: john.smith@globaltech.com
Date: 2025-12-03

Hello,

I was charged twice for the same service on December 1st — two transactions of $450.00 each on my Visa ending in 4521. Order reference: ORD-99281.

Please process a refund for the duplicate charge. I have attached my bank statement showing both debits.

Thank you,
John Smith""",
            "label": "billing-inquiry",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Payment Plan Request

From: sarah.chen@outlook.com
Date: 2026-01-20

Dear Team,

My current outstanding balance is $3,200.00 (invoices INV-001 through INV-003). Due to temporary cash flow issues, I'd like to request a 3-month payment plan.

Could you confirm if installment payments are possible and what the terms would be?

Regards,
Sarah Chen
Customer ID: CUS-55123""",
            "label": "billing-inquiry",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Account Balance Inquiry

From: accounting@riverside-hotel.com
Date: 2026-02-14

Bonjour,

Pouvez-vous nous envoyer un relevé de compte détaillé pour la période janvier-février 2026 ? Nous devons vérifier le solde restant avant la clôture trimestrielle.

Notre numéro de compte est PRO-88210.

Cordialement,
Service Comptabilité
Hôtel Riverside""",
            "label": "billing-inquiry",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Charge Dispute

From: alex.rodriguez@mail.com
Date: 2026-03-01

Hi,

I see a charge of £89.99 on my February statement that I don't recognize. Reference: TXN-2026-FEB-1192. I did not authorize this transaction and would like it reversed immediately.

Please investigate and confirm within 48 hours.

Alex Rodriguez
Member since 2019""",
            "label": "billing-inquiry",
            "label_source": "llm_classified",
            "human_verified": False,
            "is_positive": True,
        },
        # ── Negative (should NOT match billing-inquiry) ──
        {
            "content": """# Password Reset Request

From: mike.jones@company.org
Date: 2026-01-10

Hello Support,

I can't log into my account. I've tried resetting my password 3 times but I'm not receiving the reset email. My username is mjones_42.

Can you manually reset it for me?

Thanks,
Mike Jones""",
            "label": "billing-inquiry",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT billing — this is a technical support / account access issue",
        },
        {
            "content": """# Change of Address

From: laura.williams@gmail.com
Date: 2026-02-20

Dear Team,

I recently moved and need to update my mailing address. My new address is:
42 Oak Street, Apt 7B, Portland, OR 97201.

My account number is ACC-12345.

Thanks,
Laura Williams""",
            "label": "billing-inquiry",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT billing — this is account management (address update)",
        },
    ],

    "technical-support": [
        # ── Positive ──
        {
            "content": """# Application Crash on Login

From: dev.team@startup.io
Date: 2026-01-08

Hi Support,

Our application crashes with error code ERR-5502 every time we try to log in since the latest update (v3.2.1). The crash happens on both Chrome 120 and Firefox 115.

Stack trace attached. Environment: Windows 11, 16GB RAM.

Steps to reproduce:
1. Open app at https://app.example.com
2. Enter credentials
3. Click "Sign In"
4. App shows white screen then crashes

Please prioritize — this blocks our entire team.

Best,
DevOps Team""",
            "label": "technical-support",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Printer Not Connecting

From: reception@lawfirm.com
Date: 2026-02-05

Hello,

Our HP LaserJet Pro M404 (serial: VNB3K12345) stopped connecting to our network after the office WiFi was reconfigured. It was working fine before. We've tried:
- Restarting the printer
- Re-entering WiFi credentials
- Resetting network settings

Nothing works. We need this printer operational ASAP for court filings.

Thanks,
Front Desk""",
            "label": "technical-support",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# API Integration Error

From: integration@partner-co.com
Date: 2026-02-28

Dear Technical Team,

We're receiving HTTP 503 errors when calling your REST API endpoint /api/v2/orders since 14:00 UTC today. Our API key is valid (verified in dashboard) and we haven't changed anything on our side.

Request ID for failed call: req_abc123def456
Error response: {"error": "service_unavailable", "retry_after": 300}

This is impacting our production order flow. Can you check your service status?

Regards,
Integration Team""",
            "label": "technical-support",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Data Export Feature Bug

From: analyst@bigdata.co
Date: 2026-03-10

Hi,

The CSV export from the dashboard is producing corrupted files. When I click "Export to CSV" on the Analytics page, the downloaded file has:
- Missing column headers
- Date fields in wrong format (MM/DD instead of ISO)
- Special characters (é, ü) replaced with ???

Browser: Safari 18.2 on macOS 15.3
Account type: Enterprise

This worked correctly in v3.1.0.

Thank you,
Data Analytics Team""",
            "label": "technical-support",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Mobile App Freezing

From: user4829@proton.me
Date: 2026-03-15

Your mobile app version 5.1.2 freezes for 10-15 seconds whenever I open the notifications tab. This started after the last update. I'm on iPhone 14 Pro, iOS 18.3.

I've already tried reinstalling the app — same issue.

Not happy with the latest update quality.""",
            "label": "technical-support",
            "label_source": "llm_classified",
            "human_verified": False,
            "is_positive": True,
        },
        # ── Negative ──
        {
            "content": """# Invoice for Maintenance Contract

From: procurement@factory.com
Date: 2026-01-25

Hello,

Please send us the invoice for the annual maintenance contract renewal (Contract #MC-2026-001). Our purchase order number is PO-44821.

The payment terms should be Net 30 as per our agreement.

Regards,
Procurement Department""",
            "label": "technical-support",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT technical support — this is a billing/document request",
        },
        {
            "content": """# Thank You for the Great Service

From: happy.customer@email.com
Date: 2026-03-20

Hi Team,

Just wanted to say thank you for the excellent customer service I received from your agent Maria (ticket #T-9921). She resolved my issue quickly and professionally.

Keep up the great work!

Best,
A Happy Customer""",
            "label": "technical-support",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT technical support — this is general feedback/inquiry",
        },
    ],

    "account-management": [
        # ── Positive ──
        {
            "content": """# Account Closure Request

From: departing.user@company.com
Date: 2026-01-18

Dear Account Management,

I would like to close my account (ID: USR-77281) effective February 1, 2026. Please confirm:
1. Any remaining balance will be refunded
2. My personal data will be deleted per GDPR
3. I'll receive a confirmation email

I've already exported all my data using the self-service tool.

Regards,
Thomas Müller""",
            "label": "account-management",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Upgrade to Business Plan

From: ceo@growing-startup.com
Date: 2026-02-10

Hi,

We'd like to upgrade our account from the Starter plan to the Business plan. We currently have 12 users and expect to add 8 more this quarter.

Account: ORG-START-5521
Current plan: Starter (5 users)
Desired plan: Business (25 users)

Please send the updated terms and pricing.

Thanks,
CEO, Growing Startup Inc.""",
            "label": "account-management",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Change Primary Contact

From: hr@enterprise.com
Date: 2026-02-25

Hello,

Due to a personnel change, we need to update the primary contact for our enterprise account:

Old contact: James Wilson (james.wilson@enterprise.com)
New contact: Emma Thompson (emma.thompson@enterprise.com, +44 20 7946 0958)

Account ID: ENT-2024-UK-001

Please also transfer admin permissions to the new contact.

Regards,
HR Department""",
            "label": "account-management",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# New User Registration Issue

From: onboarding@client.org
Date: 2026-03-05

Bonjour,

Nous essayons de créer un nouveau compte pour notre employée Sophie Martin (sophie.martin@client.org) mais le formulaire d'inscription renvoie l'erreur "Domaine non autorisé".

Notre domaine @client.org devrait être dans la liste blanche depuis notre contrat signé en janvier 2026.

Pouvez-vous ajouter notre domaine et confirmer ?

Merci,
Service Onboarding""",
            "label": "account-management",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Enable Two-Factor Authentication

From: security@fintech.io
Date: 2026-03-12

Hi,

We need to enable mandatory 2FA for all users in our organization account (ORG-FIN-8821). This is a compliance requirement from our latest audit.

Can you also send us the SSO/SAML configuration guide for Azure AD integration?

Thanks,
Information Security Team""",
            "label": "account-management",
            "label_source": "llm_classified",
            "human_verified": False,
            "is_positive": True,
        },
        # ── Negative ──
        {
            "content": """# Why Am I Being Charged More?

From: confused.user@mail.com
Date: 2026-01-30

Hello,

My monthly charge went from $29 to $49 this month but I didn't change anything on my account. Can you explain this increase and reverse it if it's an error?

Transaction ref: CHG-2026-0130-8821

Thanks""",
            "label": "account-management",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT account management — this is a billing inquiry about charges",
        },
        {
            "content": """# Software Not Working After Update

From: user@corp.net
Date: 2026-03-18

Hi,

Since the account settings page was redesigned, I can no longer export my reports. The "Download" button does nothing when clicked.

Browser: Edge 122
OS: Windows 11

Can you fix this?""",
            "label": "account-management",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT account management — this is technical support (UI bug)",
        },
    ],

    "document-request": [
        # ── Positive ──
        {
            "content": """# Certificate of Insurance Request

From: legal@construction-co.com
Date: 2026-01-22

Dear Sir/Madam,

We need a Certificate of Insurance (COI) for our upcoming project bid. Requirements:
- Policy number: POL-2026-CC-001
- Named insured: Construction Co. LLC
- Additional insured: City of Portland
- Coverage dates: March 1 - December 31, 2026

Please send the certificate in PDF format by January 30.

Regards,
Legal Department""",
            "label": "document-request",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Tax Statement for 2025

From: accountant@freelance.me
Date: 2026-02-01

Hello,

I need my annual tax statement (1099 / attestation fiscale) for the year 2025 for my tax filing.

Account: FRL-2024-9921
Name: Pierre Lefebvre
Tax ID: ending in 4829

Please send it to this email address as a signed PDF.

Merci,
Pierre Lefebvre""",
            "label": "document-request",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Employment Verification Letter

From: mortgage.dept@bank.com
Date: 2026-02-18

Dear HR Department,

We are processing a mortgage application for your employee David Park (Employee ID: EMP-4421). We require:

1. Employment verification letter on company letterhead
2. Salary confirmation for the last 12 months
3. Employment status (full-time/part-time)

This is time-sensitive — please respond within 5 business days.

Sincerely,
Mortgage Department
National Bank""",
            "label": "document-request",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Attestation de Domicile

From: prefecture@gouv.fr
Date: 2026-03-01

Madame, Monsieur,

Dans le cadre de ma demande de renouvellement de titre de séjour, j'ai besoin d'une attestation de domicile à mon nom confirmant mon adresse actuelle :

15 Rue de la Paix, 75002 Paris

Numéro de contrat : LOC-2025-PAR-1582

Merci de m'envoyer ce document signé et tamponné dans les plus brefs délais.

Cordialement,
Amira Benali""",
            "label": "document-request",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Compliance Audit Documents

From: auditor@big4.com
Date: 2026-03-10

Dear Compliance Team,

As part of the annual audit (engagement ref: AUD-2026-Q1), we require the following documents:
- SOC 2 Type II report (latest)
- Data processing agreement (DPA)
- Business continuity plan (BCP)
- Incident response log for 2025

Deadline: March 25, 2026.

Thank you,
Senior Auditor""",
            "label": "document-request",
            "label_source": "llm_classified",
            "human_verified": False,
            "is_positive": True,
        },
        # ── Negative ──
        {
            "content": """# Cancel My Subscription

From: leaving@user.com
Date: 2026-02-12

Hi,

I want to cancel my subscription immediately. I no longer need the service.

Account: SUB-MONTHLY-7721

Please confirm cancellation and any final charges.

Thanks""",
            "label": "document-request",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT document request — this is account management (cancellation)",
        },
        {
            "content": """# Error When Downloading Report

From: analyst@co.com
Date: 2026-03-08

Hello,

When I try to download the monthly report PDF from the dashboard, I get a 500 Internal Server Error. I need this report for our board meeting tomorrow.

URL: https://app.example.com/reports/2026-02
Error: HTTP 500

Can you generate and send me the report manually?

Thanks""",
            "label": "document-request",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT document request — this is technical support (download error)",
        },
    ],

    "general-inquiry": [
        # ── Positive ──
        {
            "content": """# Product Roadmap Question

From: curious.prospect@tech.co
Date: 2026-01-12

Hi Team,

We're evaluating your platform for our Q2 rollout. A few questions:

1. Do you plan to add SSO support for Okta in 2026?
2. Is there a public API roadmap page?
3. What's the typical onboarding timeline for a 200-person team?

Looking forward to your response.

Best,
VP of Engineering""",
            "label": "general-inquiry",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Feedback on New UI

From: power.user@daily.com
Date: 2026-02-08

Hello,

I've been using your platform daily for 2 years and wanted to share feedback on the new UI released last week:

Positives:
- Dark mode is fantastic
- Search is much faster

Negatives:
- The new navigation is confusing (took me 10 minutes to find Settings)
- Font size is too small on mobile

Overall it's an improvement but please consider the navigation feedback.

Cheers,
A Loyal User""",
            "label": "general-inquiry",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Partnership Inquiry

From: bd@marketing-agency.com
Date: 2026-02-22

Dear Business Development,

We're a digital marketing agency with 50+ clients in the SaaS space. We'd like to explore a potential partnership or reseller agreement.

Could we schedule a call next week to discuss:
- Partner program details
- Revenue sharing model
- Co-marketing opportunities

Our website: www.marketing-agency.com

Best regards,
Head of Partnerships""",
            "label": "general-inquiry",
            "label_source": "human_verified",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Question About Data Privacy

From: dpo@eu-company.de
Date: 2026-03-05

Guten Tag,

As our company's Data Protection Officer, I need to understand:
1. Where is customer data stored? (EU/US?)
2. Do you have ISO 27001 certification?
3. Can we get a copy of your DPIA?

This is for our vendor risk assessment.

Mit freundlichen Grüßen,
DPO""",
            "label": "general-inquiry",
            "label_source": "human_reinforced",
            "human_verified": True,
            "is_positive": True,
        },
        {
            "content": """# Referral Program Question

From: existing.customer@gmail.com
Date: 2026-03-18

Hey,

I love your product and want to refer a friend. Do you have a referral program? If so, what's the reward for both the referrer and the new customer?

Thanks!""",
            "label": "general-inquiry",
            "label_source": "llm_classified",
            "human_verified": False,
            "is_positive": True,
        },
        # ── Negative ──
        {
            "content": """# My Account Was Hacked

From: panicked.user@mail.com
Date: 2026-02-15

URGENT — My account has been compromised! Someone changed my email and password. I can see unauthorized transactions on my account.

Original email: panicked.user@mail.com
Account ID: USR-11223

Please lock my account immediately and help me recover access!""",
            "label": "general-inquiry",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT general inquiry — this is account management (security/recovery) + potentially billing (unauthorized transactions)",
        },
        {
            "content": """# Request Annual Statement

From: tax.prep@accounting.com
Date: 2026-03-12

Hi,

I need the 2025 annual account statement for client Marie Dupont (Account #AC-78432) for tax preparation purposes.

Please send as PDF.

Thanks,
Tax Preparer""",
            "label": "general-inquiry",
            "label_source": "human_corrected",
            "human_verified": True,
            "is_positive": False,
            "correction_reason": "NOT general inquiry — this is a document request",
        },
    ],
}


# ---------------------------------------------------------------------------
# Index schema
# ---------------------------------------------------------------------------
def build_index_schema(slug: str) -> dict:
    return {
        "name": f"classymail-intent-{slug}",
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "email_id", "type": "Edm.String", "filterable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "label", "type": "Edm.String", "filterable": True},
            {"name": "label_source", "type": "Edm.String", "filterable": True},
            {"name": "human_verified", "type": "Edm.Boolean", "filterable": True},
            {"name": "is_positive", "type": "Edm.Boolean", "filterable": True},
            {"name": "correction_reason", "type": "Edm.String", "searchable": True},
            {"name": "confidence_original", "type": "Edm.Double"},
            {
                "name": "content_vector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "dimensions": EMBEDDING_DIMENSIONS,
                "vectorSearchProfile": "default-profile",
            },
            {"name": "created_at", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True},
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw", "kind": "hnsw", "hnswParameters": {"metric": "cosine"}}],
            "profiles": [{"name": "default-profile", "algorithm": "hnsw"}],
        },
        "semantic": {
            "configurations": [
                {
                    "name": "default-semantic",
                    "prioritizedFields": {
                        "prioritizedContentFields": [{"fieldName": "content"}],
                    },
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def run_az(args: list[str], check: bool = True) -> str:
    """Run an az CLI command and return stdout."""
    # On Windows, az is a .cmd script — need shell=True
    cmd = "az " + " ".join(args)
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, shell=True)
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


async def get_embedding(text: str, endpoint: str, credential) -> list[float]:
    """Get embedding from Azure OpenAI using admin key from az CLI."""
    import httpx

    try:
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}
    except Exception:
        # Fallback — get key from az CLI
        key_json = run_az(["cognitiveservices", "account", "keys", "list", "-g", RG, "-n", AI_FOUNDRY_NAME, "-o", "json"])
        key = json.loads(key_json).get("key1", "")
        headers = {"api-key": key, "Content-Type": "application/json"}

    url = f"{endpoint}/openai/deployments/{EMBEDDING_DEPLOYMENT}/embeddings?api-version=2024-08-01-preview"
    payload = {"input": text[:8000], "model": EMBEDDING_DEPLOYMENT}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    global SEARCH_NAME, AI_FOUNDRY_NAME, RG  # noqa: PLW0603

    from azure.identity import AzureCliCredential

    credential = AzureCliCredential()

    # ── Auto-discover resource names if not set ─────────────────────
    if not SEARCH_NAME:
        print("[auto-discover] Looking for AI Search services in RG:", RG)
        try:
            out = run_az(["search", "service", "list", "-g", RG, "-o", "json"], check=False)
            services = json.loads(out) if out else []
            if services:
                SEARCH_NAME = services[0]["name"]
                print(f"  Found: {SEARCH_NAME}")
            else:
                SEARCH_NAME = f"{RG.replace('-rg', '')}-search"
                print(f"  None found, will create: {SEARCH_NAME}")
        except Exception:
            SEARCH_NAME = f"{RG.replace('-rg', '')}-search"

    if not AI_FOUNDRY_NAME:
        print("[auto-discover] Looking for Cognitive Services in RG:", RG)
        try:
            out = run_az(["cognitiveservices", "account", "list", "-g", RG, "-o", "json"], check=False)
            accounts = json.loads(out) if out else []
            ai_accounts = [a for a in accounts if a.get("kind") in ("AIServices", "OpenAI", "CognitiveServices")]
            if ai_accounts:
                AI_FOUNDRY_NAME = ai_accounts[0]["name"]
                print(f"  Found: {AI_FOUNDRY_NAME}")
            else:
                AI_FOUNDRY_NAME = f"{RG.replace('-rg', '')}-aifoundry"
                print(f"  None found, will use: {AI_FOUNDRY_NAME}")
        except Exception:
            AI_FOUNDRY_NAME = f"{RG.replace('-rg', '')}-aifoundry"

    # ── Step 1: Deploy AI Search ─────────────────────────────────────
    print("\n=== Step 1: Deploy Azure AI Search ===")
    try:
        existing = run_az(["search", "service", "show", "-n", SEARCH_NAME, "-g", RG, "-o", "json"], check=False)
        if existing and "id" in existing:
            print(f"  AI Search '{SEARCH_NAME}' already exists — skipping creation.")
        else:
            raise RuntimeError("not found")
    except Exception:
        print(f"  Creating AI Search '{SEARCH_NAME}' (Basic + Semantic)...")
        run_az([
            "search", "service", "create",
            "--name", SEARCH_NAME,
            "--resource-group", RG,
            "--location", LOCATION,
            "--sku", "basic",
            "--semantic-search", "standard",
            "--identity-type", "SystemAssigned",
        ])
        print(f"  ✓ AI Search '{SEARCH_NAME}' created.")

    # Get search endpoint and admin key
    search_endpoint = f"https://{SEARCH_NAME}.search.windows.net"
    admin_key_json = run_az([
        "search", "admin-key", "show",
        "--service-name", SEARCH_NAME,
        "--resource-group", RG,
        "-o", "json",
    ])
    admin_key_data = json.loads(admin_key_json)
    admin_key = admin_key_data.get("primaryAdminKey") or admin_key_data.get("primaryKey") or list(admin_key_data.values())[0]
    print(f"  Search endpoint: {search_endpoint}")

    # ── Step 2: Deploy Model Router ──────────────────────────────────
    print("\n=== Step 2: Deploy Model Router ===")
    try:
        deployments_json = run_az([
            "cognitiveservices", "account", "deployment", "list",
            "-g", RG, "-n", AI_FOUNDRY_NAME, "-o", "json",
        ])
        deployments = json.loads(deployments_json) if deployments_json else []
        has_router = any(d.get("name") == "model-router" for d in deployments)

        if has_router:
            print("  Model Router already deployed — skipping.")
        else:
            print("  Deploying model-router (GlobalStandard, 250K TPM)...")
            run_az([
                "cognitiveservices", "account", "deployment", "create",
                "-g", RG, "-n", AI_FOUNDRY_NAME,
                "--deployment-name", "model-router",
                "--model-name", "model-router",
                "--model-version", "2025-11-18",
                "--model-format", "OpenAI",
                "--sku-name", "GlobalStandard",
                "--sku-capacity", "125",
            ])
            print("  ✓ Model Router deployed.")
    except Exception as e:
        print(f"  ⚠ Model Router deployment failed (may need manual setup): {e}")

    # Get AI Foundry endpoint for embeddings
    foundry_json = run_az([
        "cognitiveservices", "account", "show",
        "-g", RG, "-n", AI_FOUNDRY_NAME, "-o", "json",
    ])
    foundry_info = json.loads(foundry_json)
    ai_endpoint = foundry_info["properties"]["endpoint"]
    print(f"  AI Foundry endpoint: {ai_endpoint}")

    # ── Step 3: Create indexes (idempotent — create-or-update) ─────
    print("\n=== Step 3: Create per-intent indexes (idempotent) ===")
    import httpx

    for cat in CATEGORIES:
        slug = cat["slug"]
        index_name = f"classymail-intent-{slug}"
        schema = build_index_schema(slug)

        async with httpx.AsyncClient(timeout=30) as client:
            # Check if index exists — if so, skip (preserve data)
            check_resp = await client.get(
                f"{search_endpoint}/indexes/{index_name}?api-version=2024-07-01",
                headers={"api-key": admin_key},
            )
            if check_resp.status_code == 200:
                print(f"  Index '{index_name}' already exists — skipping (data preserved).")
                continue

            # Create index (PUT is idempotent)
            resp = await client.put(
                f"{search_endpoint}/indexes/{index_name}?api-version=2024-07-01",
                headers={"api-key": admin_key, "Content-Type": "application/json"},
                json=schema,
            )
            if resp.status_code in (200, 201):
                print(f"  ✓ Index '{index_name}' created.")
            else:
                print(f"  ✗ Failed to create '{index_name}': {resp.status_code} {resp.text[:200]}")

    # ── Step 4: Generate embeddings & upload documents ───────────────
    print("\n=== Step 4: Upload sample emails with embeddings ===")

    total_docs = 0
    for cat in CATEGORIES:
        slug = cat["slug"]
        index_name = f"classymail-intent-{slug}"
        emails = SAMPLE_EMAILS.get(slug, [])

        if not emails:
            print(f"  ⚠ No sample emails for '{slug}' — skipping.")
            continue

        docs = []
        for i, email_data in enumerate(emails):
            print(f"  Embedding {slug} [{i+1}/{len(emails)}]...", end=" ", flush=True)
            try:
                vector = await get_embedding(email_data["content"], ai_endpoint, credential)
                print("✓")
            except Exception as e:
                print(f"✗ ({e})")
                vector = [0.0] * EMBEDDING_DIMENSIONS  # fallback zero vector

            doc = {
                "@search.action": "mergeOrUpload",
                "id": f"sample-{slug}-{i:03d}",
                "email_id": f"sample-{slug}-{i:03d}",
                "content": email_data["content"],
                "label": email_data["label"],
                "label_source": email_data["label_source"],
                "human_verified": email_data["human_verified"],
                "is_positive": email_data["is_positive"],
                "correction_reason": email_data.get("correction_reason", ""),
                "confidence_original": 0.95 if email_data["is_positive"] else 0.15,
                "content_vector": vector,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            docs.append(doc)

        # Upload batch
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{search_endpoint}/indexes/{index_name}/docs/index?api-version=2024-07-01",
                headers={"api-key": admin_key, "Content-Type": "application/json"},
                json={"value": docs},
            )
            if resp.status_code in (200, 207):
                results = resp.json().get("value", [])
                success = sum(1 for r in results if r.get("status"))
                print(f"  ✓ Uploaded {success}/{len(docs)} docs to '{index_name}'")
                total_docs += success
            else:
                print(f"  ✗ Upload failed for '{index_name}': {resp.status_code} {resp.text[:200]}")

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  DEPLOYMENT SUMMARY")
    print(f"{'='*60}")
    print(f"  AI Search:    {search_endpoint}")
    print(f"  Indexes:      {len(CATEGORIES)} (one per category)")
    print(f"  Documents:    {total_docs} total")
    print("  Per category: 5 positive + 2 negative examples")
    print("  Label types:  human_verified, human_reinforced, human_corrected, llm_classified")
    print(f"  Model Router: deployed on {AI_FOUNDRY_NAME}")
    print(f"{'='*60}")
    print(f"\n  Set env var: AZURE_SEARCH_ENDPOINT={search_endpoint}")
    print("  Add to secrets.env to enable agentic pipeline.")


if __name__ == "__main__":
    asyncio.run(main())
