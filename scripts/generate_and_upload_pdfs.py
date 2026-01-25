"""Generate PDFs via the existing dummy generator.

This script is intentionally **generation-only**.

Notes:
- We do NOT upload from local/IDE in this repo anymore (direct Blob upload or /api/upload).
- To ingest documents, use the app UI/API running in Azure (or your own approved upload path).

Usage:
    uv run python scripts/generate_and_upload_pdfs.py --count 20 --out dataset/pdf
    uv run python scripts/generate_and_upload_pdfs.py --count 20 --out dataset/pdf --use-aoai
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def load_env_from_file(path: str = "secrets.env", *, override: bool = False) -> None:
    """Minimal env loader for KEY=VALUE lines (ignores comments/blank lines).

    This is mainly used to pick up optional Azure OpenAI settings for `--use-aoai`.
    """

    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key or value is None:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PDF files for local testing")
    parser.add_argument("--count", type=int, default=20, help="Number of PDFs to generate (default: 20)")
    parser.add_argument("--out", type=str, default="dataset/pdf", help="Output folder for PDFs")
    parser.add_argument("--use-aoai", action="store_true", help="Use Azure OpenAI for richer email bodies")
    parser.add_argument(
        "--aoai-deployment",
        type=str,
        default=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--target-words",
        type=int,
        default=300,
        help="Target word count for the email body (approx; default: 300)",
    )
    parser.add_argument("--include-corrupted", type=int, default=0, help="Generate N corrupted PDFs alongside valid ones")
    parser.add_argument("--env-file", type=str, default="secrets.env", help="Path to env file to load (default: secrets.env)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    return parser.parse_args()


async def run() -> int:
    load_env_from_file()  # load defaults from secrets.env before parsing
    args = parse_args()
    if args.env_file and args.env_file != "secrets.env":
        load_env_from_file(args.env_file, override=True)
    out_dir = Path(args.out)

    # Generate PDFs using existing generator (subprocess because it parses argv)
    gen_script = Path(__file__).resolve().parent / "generate_dummy_pdfs.py"
    gen_args = [
        str(gen_script),
        "--count",
        str(args.count),
        "--out",
        str(out_dir),
        "--target-words",
        str(args.target_words),
    ]
    if args.use_aoai:
        gen_args += ["--use-aoai", "--aoai-deployment", args.aoai_deployment]
    if args.seed is not None:
        gen_args += ["--seed", str(args.seed)]

    proc = await asyncio.create_subprocess_exec(sys.executable, *gen_args)
    exit_code = await proc.wait()
    if exit_code:
        return exit_code

    # Optionally add corrupted PDFs locally (simple non-PDF bytes)
    for i in range(args.include_corrupted):
        corrupted = out_dir / f"corrupted_{i+1:02d}.pdf"
        corrupted.write_bytes(b"NOT_A_PDF\n" + os.urandom(512))

    pdf_files = sorted(list(out_dir.glob("*.pdf")) + list(out_dir.glob("*.PDF")))
    if not pdf_files:
        raise SystemExit(f"No PDFs found in {out_dir}")

    print(f"Generated {len(pdf_files)} PDFs in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
