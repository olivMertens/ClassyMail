# ADR 001: OCR & Classification Strategy

## Context
We need to extract intents and metadata (Sender, Subject) from PDF emails (images/scanned).
We considered two approaches for the Mistral/AI pipeline:

1. **Mistral Document AI (Structured)**: Using specific endpoints to extract key-value pairs directly.
2. **Mistral OCR (Markdown) + LLM Classification**: Using Mistral to generate a full Markdown representation of the document, then feeding that into a reasoning LLM (Phi-4) for classification.

## Decision
We chose **Mistral OCR (Markdown) + LLM Classification**.

## Rationale

### 1. Token Efficiency & Context
- **Document AI** is excellent for rigid forms (e.g., extracting "Invoice Total" or "Tax ID").
- **Email Classification** requires understanding the *nuance* and *tone* of the text.
- By converting the PDF to **Markdown**, we preserve the structure (headers, lists, bold text) which is critical for understanding the document's hierarchy, but we provide the LLM with the *full text* so it can reason about "implied" intents (e.g., a customer sounding angry about a delay, even if they don't explicitly say "Complaint").

### 2. Image & Vision Capabilities
- **Current State**: Mistral OCR (`mistral-ocr-2505`) already analyzes images within the PDF and describes them in the Markdown output (e.g., `![Image: Logo of AXA Assurance]`).
- **Future Vision**: If we need to analyze specific damage photos (e.g., a car crash photo attached), the Markdown approach allows us to see *where* the image is. We can then upgrade our pipeline to send the specific image slices to a Vision-Language Model (VLM) like `Pixtral` or `GPT-4o` only when necessary, rather than processing every pixel of every page as an image (which is cost-prohibitive).

### 3. Flexibility
- Markdown is a universal format. If we switch LLMs (e.g., from Phi-4 to GPT-4o or Llama 3), the input format stays the same.
- Structured Document AI output often requires re-training or complex schema definitions for every new intent we want to discover.

## Implementation Plan
We have implemented a **"Processing Strategy"** setting in the UI to allow flexibility:

- **Standard (Text/Markdown)**: Best balance of speed and cost. Relies on text and layout.
- **Deep Reasoning (CoT)**: Adds a "Chain of Thought" requirement to the LLM prompt. It asks the AI to "Think step-by-step" before deciding. This improves accuracy for complex/ambiguous emails but increases output token costs.
- **Vision (Future)**: Placeholder for full VLM integration.
