# User Interface Guide

This guide explains how to use the *ClassiMail* web interface to manage, review, and analyze processed emails.

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
- **JSONL (Fine-tune)**: Exports the dataset in the specific JSONL format required for Azure OpenAI fine-tuning.
    - *Best Practice*: Ensure you have at least 50 reviewed examples per category before fine-tuning.
    - *Tip*: Quality is more important than quantity. Use the validation modal to correct inputs.
- **Search**: Real-time filtering of emails by subject or sender.
- **Status Filters**: Toggle between "All", "To Review", "Processed", and "Errors".

## Email List View
Emails are displayed as cards containing:
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
    - *Important*: This text is used by the AI to learn from your corrections.
- **Actions**:
    - **Mark as Garbage/Invalid**: Flags the email as irrelevant or trash.
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
