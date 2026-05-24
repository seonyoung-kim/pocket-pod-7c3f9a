from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Iterable

from google import genai
from google.genai import types


_FLASH_MODEL = "gemini-2.0-flash"
_PRO_MODEL = "gemini-2.5-pro"


@dataclass(frozen=True)
class Stage1Score:
    video_id: str
    score: float
    reason: str


@dataclass(frozen=True)
class Stage2Verdict:
    video_id: str
    score: float
    summary: str


class GeminiClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ["GEMINI_API_KEY"]
        self._client = genai.Client(api_key=key)

    def score_candidates(
        self,
        interests_yaml_text: str,
        candidates: Iterable[dict],
    ) -> list[Stage1Score]:
        """Stage 1: rank candidates by metadata only.

        candidates: list of dicts {video_id, title, channel, description, duration_sec, view_count, published_at}
        Returns scored list (all candidates with 0-10 score).
        """
        cand_list = list(candidates)
        prompt = (
            "You are curating YouTube videos for a personal podcast feed.\n"
            "Below is the user's interest profile (YAML), followed by candidate videos.\n"
            "Score each candidate from 0 to 10 for how well it matches the interests.\n"
            "Return ONLY a JSON array, no markdown fences. "
            'Each element: {"video_id": str, "score": float, "reason": short str (Korean OK)}.\n\n'
            "=== INTERESTS ===\n"
            f"{interests_yaml_text}\n\n"
            "=== CANDIDATES ===\n"
            f"{json.dumps(cand_list, ensure_ascii=False, indent=2)}\n"
        )
        resp = self._client.models.generate_content(
            model=_FLASH_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        data = json.loads(resp.text)
        return [
            Stage1Score(
                video_id=item["video_id"],
                score=float(item["score"]),
                reason=str(item.get("reason", "")),
            )
            for item in data
        ]

    def deep_analyze(self, video_url: str, interests_yaml_text: str) -> Stage2Verdict:
        """Stage 2 placeholder; implemented in Task 6."""
        raise NotImplementedError
