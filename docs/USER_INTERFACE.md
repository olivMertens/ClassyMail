# User Interface Guide

This guide explains how to use the *ClassiMail* web interface to manage, review, and analyze processed emails.

## Dashboard Overview

The Dashboard is the central hub for monitoring progress and managing the email classification pipeline.

### Status Cards

- **Total Emails**: The count of all emails ingested into the system.
- **To Review**: Emails flagged for human attention (no intents, too many intents, or any intent confidence below the review threshold).
- **Processed**: Emails finalized without requiring human review.
- **Avg. Quality**: Average confidence across **processed + to review** emails (excludes errors/missing intents).

> **Review Threshold**: `REVIEW_CONFIDENCE_THRESHOLD` (default **0.85**). Any intent **< threshold** ⇒ `REVIEW_REQUIRED`.
> Configure via env var or settings (`review_confidence_threshold`).

### Pipeline Progress

A visual progress bar tracking the completion of the classification task.

- **Auto-Refresh**: The dashboard data refreshes automatically every 15 seconds.
- **Blue**: Processing in progress / To Review.
- **Green**: Fully completed.

### Action Toolbar

- **Export CSV**: Downloads the full dataset including classification results, costs, and metadata in CSV format (Direct Download).
- **JSONL (Fine-tune)**: Exports the dataset in the specific JSONL format required for Azure OpenAI fine-tuning.
  - *Enabled only*: When sufficient reviewed data is available (default 50, configurable).
  - *Tip*: Hover over the '?' icon for best practices on fine-tuning.
- **Combined Filters**:
  - **Status Tabs**: "All", "To Review", "Processed", "Errors".
  - **Search**: Real-time filtering by subject or sender.
  - **Category**: Filter by specific intent name (e.g., "Address Change").
  - **Confidence**: Filer by confidence range (e.g., "< 50%" for spotting errors, or "100%" for gold-standard examples).

## Email List View

Emails are displayed as cards containing:

> **PDF Access (SAS)**
> - The UI fetches `/api/emails/{id}` which generates a SAS **on demand** (per request).
> - **Private containers** return `ResourceNotFound` for direct blob URL without SAS.
> - Always use the **SAS URL** (`file_url_sas`) for sharing/downloading PDFs.

- **Score Badge**: Color-coded confidence score (Green > 0.85, Amber > 0.5, Red < 0.5).
- **Icons**: Status indicators (Checkmark for Processed, Clock for Review, Exclamation for Error).
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
  - *Mandatory*: If you change or invalidate a category, you MUST provide a reason. This ensures high-quality data for fine-tuning.
- **Actions**:
  - **Mark as Garbage/Invalid**: Flags the email as irrelevant or trash (Reason required).
  - **Validate & Save**: Commits the category changes. If you changed the category and provided a reason, this triggers the "Lesson Learned" analysis.

### 3. History Tab

Tracks the lifecycle of the classification.
- **Timeline**: Shows every status change and who performed it (system vs. user).
- **AI Insights**: If you provided a correction reason, the system ("Phi-4") analyzes it and posts a "Lesson Learned" card in the history, confirming it understood your logic.

---

## Developer Documentation

Access via the "Developer" link in the navigation bar.

- **API Reference**: Interactive Redoc interface for the Backend API.
- **Architecture**: Dynamic Mermaid diagram showing the system component flow.
- **Repository**: Process & Codebase links.

## Chat Assistant (Developer Tab)

- Floating button in the bottom-right corner when the dashboard is loaded.
- Uses **tool calling** to query Cosmos DB (`search_emails`, `search_email_by_text`, `get_latest_errors`, `get_stats_summary`, `get_top_intents`).
- Example prompts:
  - "Find emails about invoices"
  - "Show latest errors"
  - "What are the top intents?"
- Stays scoped to **ClassificationG2S**; refuses unrelated topics.

## Settings & Danger Zone

The application settings allow customization of the classification engine and environment management.

### Settings Tab

- **Dark Mode**: Toggle the application theme.
- **Cost Overrides**: Adjust the unit prices used for cost estimation (Useful for "What-If" analysis).
- **Processing Strategy**: Switch between "Standard" (Fast), "Reasoning" (CoT), or "Vision" modes.
- **Telemetry Logs**: Real-time view of traces and exceptions from Azure Application Insights (requires `LOG_ANALYTICS_WORKSPACE_ID` configuration).

### Developer Tab (Danger Zone)

This restricted area allows administrators to test, diagnose, and manage the environment.

#### Diagnostics Section

- **Check Connectivity**: Performs active read/write tests on Storage, Cosmos DB, and Service Bus to verify permissions and connectivity.
  - **Results**: Shows status of each service (ok / error message).
  - **Use Case**: Troubleshooting authentication or network issues.

#### Testing Section

- **Simulate Flow**: Generates a realistic French insurance email PDF and sends it through the entire pipeline (upload → process → queue).
  - **Output**: Returns the `item_id` to track via the email list.
  - **Expected Category**: Randomly selected based on template.
  - **Use Case**: End-to-end testing without manual PDF uploads.

#### Dead Letter Queue Management

- **View Dead Letter Messages**: Peeks into the Service Bus Dead Letter Queue to diagnose failed messages.
  - **Details**: Shows message ID, delivery count, error reason, and linked email processing log.
  - **Use Case**: Investigating why emails failed processing.
- **Purge Dead Letter Queue**: Clears all messages from the Dead Letter Queue.
  - **Safety**: Direct action, no confirmation required (use cautiously).
  - **Use Case**: Cleanup after investigating errors.

#### Reset Section

- **Delete All Data**: Completely wipes the database and storage.
  - **Actions Performed**: Deletes all items in Cosmos DB container, deletes all blobs in `pdf-inputs`, and purges the Dead Letter Queue.
  - **Safety**: Requires two confirmations to proceed.
  - **Use Case**: Cleaning up after a POC session or before a new demo run.
