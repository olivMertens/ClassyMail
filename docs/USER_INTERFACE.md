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
- **Confidence Filters**: Filter by "Any Level", "Low Confidence", "High Confidence" (FR: "Tout Niveau", "Niveau de Confiance Faible", "Niveau de Confiance Élevé")

## Email List View
Emails are displayed as cards containing:
- **Score Badge**: Color-coded confidence score (Green > 0.85, Amber > 0.5, Red < 0.5).
- **Icons**: Status indicators (Checkmark for Processed, Clock for Review, Exclamation for Error).
- **PII Indicator** (NEW): Amber shield icon (🛡️ ShieldExclamationIcon) when email contains personal data
    - Tooltip: "Cet email contient des données à caractère personnel (DCP/PII)"
    - Visible in both card and table views
    - Table view shows "DCP" badge (FR) or "PII" badge (EN)
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
    - **Reprocess** (NEW): Re-run classification with different settings:
        - **Model Selection**: Choose Phi-4, GPT-4o-mini, GPT-5-mini, or "Both" (comparison mode)
        - **Strategy Override**: Change processing strategy (Standard/Reasoning/Vision)
        - **Sync/Async Mode**: Immediate processing (<30s) or background queue
        - **Use Case**: Test different models, fix OCR errors, compare strategies
    - **Validate & Save**: Commits the category changes. If you changed the category and provided a reason, this triggers the "Lesson Learned" analysis.

### 3. History Tab
Tracks the lifecycle of the classification.
- **Timeline**: Shows every status change and who performed it (system vs. user).
- **AI Insights**: If you provided a correction reason, the system ("Phi-4") analyzes it and posts a "Lesson Learned" card in the history, confirming it understood your logic.

### 4. Comparison Tab (Adversarial Mode)
*Only visible when a secondary model comparison is recorded.*

This tab provides a side-by-side analysis of two models (e.g., **Phi-4** vs **GPT-4o-mini** or **GPT-5-mini**) running on the same document.

- **Visual Diff**:
    - **Blue Pill**: Primary Model (Phi-4)
    - **Orange Pill**: Secondary/Fallback Model (GPT-4o-mini or GPT-5-mini)
- **Agreement Status**:
    - ✅ **Match**: Both models found the same intent/category.
    - ❌ **Conflict**: Models disagree. The UI highlights the discrepancy.
- **Confidence Score**: Compares the probability scores of both models.
- **Processing Time**: Shows latency comparison between models
- **Token Usage**: Displays input/output tokens for cost analysis
- **Vote/Selection**: The human reviewer can "Vote" for the best answer, which helps in evaluating model performance for future tuning.
- **Run Comparison**: If no comparison exists, button to trigger comparison (sync or async mode)

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
- **Language**: Switch between French (FR) and English (EN)
- **Cost Overrides**: Adjust the unit prices used for cost estimation (Useful for "What-If" analysis).
    - Configure pricing per model: Phi-4, GPT-4o/4o-mini, GPT-5-mini/nano, Mistral OCR
    - Prices in € per 1K tokens (input/output)
    - Disclaimer: "Costs are configurable and region-dependent. Verify with Azure pricing."
- **Processing Strategy**: Switch between "Standard" (Fast), "Reasoning" (CoT), or "Vision" modes.
- **Email Preprocessing**: Advanced settings for subject extraction, PII detection, conversation isolation

### Categories Tab (NEW)
Manage classification categories with AI assistance:
- **Category List**: View all defined categories with name, slug, description, exclusions
- **Add/Edit Categories**: Define category name, technical slug, description ("what it IS"), exclusions ("what it ISN'T")
- **Get AI Advice** (NEW): Click button to analyze category quality with GPT-5 Nano
    - **Assessment Quality**: Rates category as Good / Needs Improvement / Poor
    - **Actionable Advice**: Concrete suggestions with rewriting examples
    - **LLM Prompt Engineering**: Explains WHY suggestions improve classification accuracy
    - **Multi-Strategy Support**: Considers Standard, Reasoning, and Vision processing modes
    - **Copy-Paste Ready**: All text snippets formatted for direct insertion into prompts
    - **Focus Areas**: Keyword density, boundary precision, prompt structure, LLM comprehension
- **French/English UI**: All category form fields fully translated (settings.categories.form.*)

### Developer Tab (Danger Zone)
This restricted area allows administrators to reset the environment for testing.
- **Delete All Data**: Completely wipes the database and storage.
    - **Atomic Nuke**: Deletes Cosmos DB items and Blob Storage files in a single transactional operation where possible.
    - **Safety**: Copilot-style confirmation ("I authorize...") required to proceed.
    - **Use Case**: Cleaning up after a POC session or before a new demo run.
- **Test Connectivity**:
    - **Test GPT-4o**: Verifies connectivity to the OpenAI endpoint.
    - **Test New Models**: Validates availability of GPT-5/4.1 deployments if configured.
