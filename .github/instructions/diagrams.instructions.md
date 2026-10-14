---
applyTo: "**/*.drawio,docs/assets/**/*.svg,docs/**/*.md,README.md"
description: "ClassyMail rules for architecture diagrams; use with the architecture-diagram-author skill."
---

# ClassyMail diagram rules

- Author and update architecture diagrams with the `architecture-diagram-author` skill (`.github/skills/architecture-diagram-author/SKILL.md`): editable `.drawio` source, then self-contained SVG and PNG exports kept in sync.
- Icons: CAE (Cloud Architecture Enterprise) Flat Design only; do not mix with older Azure icon sets. Use current product names (Microsoft Entra ID, Microsoft Foundry).
- Draw the architecture that is actually implemented (`infra/main.tf`, `classymail/`); label planned or pilot components as such.
- Link diagram descriptions to code with the `#` notation (e.g. `#infra/main.tf`, `#classymail/agents/workflow.py`).
- Mermaid in Markdown: `flowchart LR/TD`, plain-text labels without HTML tags, validated with `uv run python scripts/validate_mermaid.py <files>`.
