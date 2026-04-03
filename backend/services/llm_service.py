from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class LLMService:
    """Single entry point for model interactions."""

    def __init__(
        self,
        model: str | None = None,
        system_prompt_path: str | None = None,
    ) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5")
        self.enabled = os.getenv("DDR_ENABLE_LLM", "false").lower() == "true"
        self.system_prompt_path = system_prompt_path or str(
            Path(__file__).resolve().parents[2] / "prompt.md"
        )
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.system_prompt = self._load_system_prompt()

    def is_configured(self) -> bool:
        return self.enabled and self.client is not None

    def _load_system_prompt(self) -> str:
        prompt_path = Path(self.system_prompt_path)
        if not prompt_path.exists():
            return """
You are an AI system for generating a Detailed Diagnosis Report (DDR) from inspection and thermal documents.

Your job is to:
- extract only relevant observations from source documents
- combine inspection and thermal evidence logically
- avoid duplicates and repetitive checklist noise
- identify conflicts or uncertainty explicitly
- write in simple, client-friendly language
- return strict JSON only

Hard rules:
- Do not invent facts not present in the provided documents
- If data is missing, write "Not Available"
- If data conflicts, state the conflict explicitly
- Inspection report is the primary source
- Thermal report is supporting evidence and should not override unsupported inspection findings
- Use only relevant images from the extracted source image list
- Do not attach unrelated images
- Keep outputs concise but complete
""".strip()
        return prompt_path.read_text(encoding="utf-8")

    def generate_json(
        self,
        task_name: str,
        instructions: str,
        payload: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured. LLM-backed agent execution is unavailable."
            )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Task: {task_name}\n\n"
                    f"Instructions:\n{instructions}\n\n"
                    "Return valid JSON only.\n\n"
                    f"Input payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=messages,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
