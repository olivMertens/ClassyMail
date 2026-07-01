# User Interface Guide

This guide explains how to use the *ClassyMail* web interface to manage, review, and analyze processed emails.

## Dashboard Overview

The Dashboard is the central hub for monitoring progress and managing the email classification pipeline.

### Status Cards
- **Total Emails**: The count of all emails ingested into the system.
- **To Review**: The number of emails that require human attention (low confidence or explicit "Review needed" flag).
- **Processed**: The number of emails successfully classified and finalized.

### Pipeline Progress
A visual progress bar tracking the completion of the classification task.
- **Auto-Refresh**: The dashboard data refreshes automatically every 15 seconds.
- **Blue**: Processing in progress / To Review.
- **Green**: Fully completed.

### Action Toolbar
- **Export CSV**: Downloads the full dataset including classification results, costs, and metadata in CSV format.
    - **Format Minimal**: Subject, sender, categories, confidence (for client integration)
    - **Format Enrichi**: Full metadata, PII data, costs, tokens, model info (for audit)
- **JSONL (Fine-tune)**: Exports the dataset in the specific JSONL format required for Azure OpenAI fine-tuning.
    - *Best Practice*: Ensure you have at least 50 reviewed examples per category before fine-tuning.
    - *Tip*: Quality is more important than quantity. Use the validation modal to correct inputs.
- **Search**: Real-time filtering of emails by subject or sender.
- **Status Filters**: Toggle between "All", "To Review", "Processed", and "Errors".
- **Confidence Filters**: Filter by "Any Level", "Low Confidence", "High Confidence"

## Email List View
Emails are displayed as cards containing:
- **Score Badge**: Color-coded confidence score (Green > 0.85, Amber > 0.5, Red < 0.5).
- **Icons**: Status indicators (Checkmark for Processed, Clock for Review, Exclamation for Error).
- **PII Indicator** (NEW): Amber shield icon (🛡️ ShieldExclamationIcon) when email contains personal data
    - Tooltip: "This email contains personal data (PII)"
    - Visible in both card and table views
    - Table view shows "PII" badge
- **Subject & Sender**: Quick summary.
- **Open Details**: Opens the validation modal.

---

## Validation & Review Modal

Clicking "Open Details" on any email opens the classification workbench.

### 1. Visualization
- **PDF Preview**: On the left, the original email/document is displayed (if available).
- **Markdown**: On the right, the extracted text content.

### 2. Review & Classify Tab
This is where human-in-the-loop validation happens.
- **Categories**:
    - **Multi-Select**: Click to toggle categories. Selected items turn blue.
    - **Custom Categories**: Click "+ Custom" to add a new category tag on the fly.
- **Correction Reason**: A text box to explain *why* you are changing a category.
    - *Important*: This text is used by the AI to learn from your corrections.
- **Actions**:
    - **Mark as Garbage/Invalid**: Flags the email as irrelevant or trash.
    - **Reprocess**: Re-run classification with current settings
    - **Validate & Save**: Commits the category changes. If you changed the category and provided a reason, this triggers the "Lesson Learned" analysis.

### 3. History Tab
Tracks the lifecycle of the classification.
- **Timeline**: Shows every status change and who performed it (system vs. user).
- **AI Insights**: If you provided a correction reason, the system ("Phi-4") analyzes it and posts a "Lesson Learned" card in the history, confirming it understood your logic.

---

## AI Chatbot

A floating chat panel (bottom-right FAB button) powered by Microsoft Agent Framework:

- **Semantic search**: Find emails by concept, not just exact keywords. Uses vector embeddings (1536-dim) in Cosmos DB
- **Date filtering**: Ask "urgent emails from last week" — the agent passes `days=7` to filter by time
- **Case-insensitive text search**: Fallback keyword search uses `LOWER()` for matching
- **Agent-driven action pills**: After each response, the LLM suggests contextual follow-up actions (💡 pills)
- **Email cards**: Results are formatted as blockquote cards with emoji status (✅ ⏳ ❌)
- **View email links**: Click `[View email]` links in chat responses to open the detail modal directly
- **12 tools**: search_emails, get_email_by_id, search_email_by_text, search_similar_emails, get_latest_errors, get_stats_summary, get_top_intents, get_low_confidence_items, get_processing_stats_by_day, reclassify_email, review_classification, explain_email
- **Prompt shield**: Security rules prevent prompt injection from email content
- **Expandable**: Toggle full-viewport mode for complex conversations

---

## Developer Documentation

Access via the "Developer" link in the navigation bar.
- **API Reference**: Interactive Redoc interface for the Backend API.
- **Architecture**: Dynamic Mermaid diagram showing the system component flow.
- **Repository**: Process & Codebase links.

## Settings & Danger Zone

The application settings allow customization of the classification engine and environment management.

### Settings Tab
- **Dark Mode**: Toggle the application theme.
- **Language**: Switch between 5 languages (EN, FR, DE, ES, IT)
- **Cost Overrides**: Adjust the unit prices used for cost estimation (Useful for "What-If" analysis).
    - Configure pricing per model: Phi-4, GPT-4o/4o-mini, GPT-4.1/5 family, Kimi-K2.5, Mistral OCR
    - Prices in € per 1K tokens (input/output)
    - Links to [Microsoft Azure OpenAI Pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/)
- **Processing Strategy**: Switch between "Standard" (Fast), "Reasoning" (CoT), "Vision" (Multimodal), or "Agentic" (Multi-Agent) modes.
- **OCR Provider**: Choose the primary OCR engine — **Mistral OCR 4** (`mistral-document-ai-2512`) or **Azure AI Content Understanding**. Azure Document Intelligence stays the automatic fallback. Content Understanding requires `CONTENT_UNDERSTANDING_ENDPOINT`; the UI warns if it is selected but not configured.
- **Email Preprocessing**: Advanced settings for subject extraction, PII detection, conversation isolation
- **Model Selection**: Primary model auto-discovered from AI Foundry deployments

### Agentic Configuration Panel
Visible only when "Agentic (Multi-Agent)" strategy is selected. Provides full control over the multi-agent classification pipeline:

**Model Selection** (per role):
- **Orchestrator Model**: Dropdown **auto-discovered from your AI Foundry deployments** (same dynamic list as the tier and General model selectors), with `gpt-4.1-nano` recommended as a fast, cheap default and `model-router` available for automatic routing
  - When `model-router` is selected, an additional **Routing Mode** dropdown appears: `Balanced` (default), `Cost`, `Quality`
- **Agent Tier 1 (Simple)**: Model for clear, unambiguous intents
- **Agent Tier 2 (Ambiguous)**: Model for emails with subtle signals
- **Agent Tier 3 (Critical)**: Robust model for business-sensitive intents
- **Red Team Model**: Model for the quality gate / second opinion

**RAG Configuration**:
- **Retrieval Mode**: `Vector` (fastest) / `Hybrid` (balanced) / `Semantic` (highest quality)
  - Controls how each specialized agent queries its per-intent AI Search index
  - Each index stores positive examples (verified matches) and negative examples (known misclassifications with correction reasons)

**Pipeline Control**:
- **Max Parallel Agents**: Number spinner (1-10, default 6) — limits the fan-out width
- **Red Team Threshold**: Slider (0.0-1.0, default 0.7) — quality gate activates when max confidence falls below this value

> **Tip**: The agentic strategy is most valuable when you have 5+ categories with overlapping definitions. For simple use cases (2-3 categories), "Standard" mode is faster and cheaper.

### Categories Tab
Manage classification categories with AI assistance:
- **Category List**: View all defined categories with name, slug, description, exclusions
- **Add/Edit Categories**: Define category name, technical slug, description ("what it IS"), exclusions ("what it ISN'T")
- **Get AI Advice**: Click button to analyze category quality with the configured assessment model
    - **Assessment Quality**: Rates category as Good / Needs Improvement / Poor
    - **Actionable Advice**: Concrete suggestions with one-click Apply buttons
    - **Multi-Strategy Support**: Considers Standard, Reasoning, and Vision processing modes

### Danger Zone Tab
Admin operations organized into three severity-grouped sections:

**Maintenance & Diagnostics** (blue, safe):
- **Test LLM Models**: Verify all configured model endpoints
- **Test Service Connectivity**: Check Azure services (Cosmos, Storage, Service Bus)
- **Simulate E2E Flow**: Generate and process a synthetic test email
- **Validate ACA Configuration**: Check Container Apps environment variables

**Bulk Operations** (amber, reversible):
- **Batch Reprocessing**: Re-enqueue all processed emails for new classification with current settings
- **Rebuild Vector Index**: Delete all chunks and regenerate embeddings for semantic search
- **Reseed AI Search Indexes** (Agentic): Rebuild per-intent AI Search indexes from classification history
- **DLQ Management**: View and purge dead-letter queue messages

**Destructive Operations** (red, irreversible):
- **Atomic Reset**: Delete ALL data (emails, blobs, DLQ) with double-confirmation. Preserves settings.
