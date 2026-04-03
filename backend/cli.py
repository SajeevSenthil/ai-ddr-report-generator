from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.pipeline import DDRPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI DDR pipeline on two PDF inputs.")
    parser.add_argument("--inspection", required=True, help="Path to the inspection/sample report PDF.")
    parser.add_argument("--thermal", required=True, help="Path to the thermal report PDF.")
    parser.add_argument(
        "--output-md",
        default="artifacts/output/ddr_report.md",
        help="Where to write the rendered markdown report.",
    )
    parser.add_argument(
        "--output-json",
        default="artifacts/output/ddr_report.json",
        help="Where to write the structured JSON report.",
    )
    args = parser.parse_args()

    pipeline = DDRPipeline()
    result = pipeline.run(args.inspection, args.thermal)

    output_md = Path(args.output_md)
    output_json = Path(args.output_json)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    output_md.write_text(result.markdown_report, encoding="utf-8")
    output_json.write_text(
        json.dumps(result.structured_report.model_dump(), indent=2),
        encoding="utf-8",
    )

    print(f"Markdown report written to: {output_md}")
    print(f"Structured JSON written to: {output_json}")


if __name__ == "__main__":
    main()
