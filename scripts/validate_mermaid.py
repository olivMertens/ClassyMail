#!/usr/bin/env python3
"""
Validate Mermaid diagrams in markdown files.
This script checks for common syntax errors in Mermaid diagrams.
"""
import re
import sys
from pathlib import Path


def validate_mermaid_block(block_content: str, file_path: str, line_num: int) -> list[str]:
    """Validate a single Mermaid code block and return list of errors."""
    errors = []

    lines = block_content.strip().split('\n')
    if not lines:
        return errors

    # Check diagram type
    first_line = lines[0].strip()
    valid_types = [
        'graph', 'flowchart', 'sequenceDiagram', 'classDiagram',
        'stateDiagram', 'erDiagram', 'gantt', 'pie', 'gitGraph'
    ]

    if not any(first_line.startswith(t) for t in valid_types):
        errors.append(f"{file_path}:{line_num}: Invalid diagram type '{first_line}'")

    # Check for inconsistent indentation
    if first_line.startswith('sequenceDiagram'):
        indent_levels = []
        for i, line in enumerate(lines[1:], 1):
            if line.strip() and not line.strip().startswith('#'):
                # Count leading spaces
                spaces = len(line) - len(line.lstrip())
                indent_levels.append(spaces)

        # All non-empty lines should have consistent indentation (0 or 4 spaces typically)
        if indent_levels:
            unique_indents = set(indent_levels)
            # Allow 0 and 4 as valid, but not mixed random indentation
            if len(unique_indents) > 2:
                errors.append(
                    f"{file_path}:{line_num}: Inconsistent indentation in sequenceDiagram. "
                    f"Found indent levels: {sorted(unique_indents)}"
                )

    # Check for common syntax errors
    for i, line in enumerate(lines, line_num):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Check for invalid arrow syntax in flowcharts
        if first_line.startswith(('graph', 'flowchart')):
            if '-->' in stripped and stripped.count('-->') > 1:
                errors.append(f"{file_path}:{i}: Multiple arrows '-->' on same line may cause issues")

        # Check for participant declarations in sequence diagrams
        if first_line.startswith('sequenceDiagram'):
            if 'participant' in stripped.lower() and not stripped.strip().startswith('participant'):
                errors.append(f"{file_path}:{i}: 'participant' must be at start of line")

    return errors


def validate_file(file_path: Path) -> list[str]:
    """Validate all Mermaid blocks in a markdown file."""
    all_errors = []

    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return [f"{file_path}: Failed to read file: {e}"]

    # Find all mermaid code blocks
    pattern = r'```mermaid\n(.*?)```'
    matches = re.finditer(pattern, content, re.DOTALL)

    for match in matches:
        # Calculate line number
        line_num = content[:match.start()].count('\n') + 1
        block_content = match.group(1)
        errors = validate_mermaid_block(block_content, str(file_path), line_num)
        all_errors.extend(errors)

    return all_errors


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: validate_mermaid.py <file1.md> [file2.md ...]")
        sys.exit(0)

    all_errors = []
    for file_arg in sys.argv[1:]:
        file_path = Path(file_arg)
        if not file_path.exists():
            print(f"Warning: File not found: {file_path}")
            continue

        errors = validate_file(file_path)
        all_errors.extend(errors)

    if all_errors:
        print("\n🔴 Mermaid Validation Errors:\n")
        for error in all_errors:
            print(f"  {error}")
        print(f"\n❌ Found {len(all_errors)} error(s)")
        sys.exit(1)
    else:
        print("✅ All Mermaid diagrams are valid")
        sys.exit(0)


if __name__ == '__main__':
    main()
