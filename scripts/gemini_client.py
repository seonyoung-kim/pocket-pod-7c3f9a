from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Iterable

from google import genai
from google.genai import types


_FLASH_MODEL = "gemini-2.5-flash"
# Pro tier has free-tier limit=0; use Flash for Stage 2 as well.
# Quality drops vs Pro but stays within free tier.
_PRO_MODEL = "gemini-2.5-flash"


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
        """Stage 2: send YouTube URL as fileData; return summary + final score."""
        # Extract video_id from URL for the response
        video_id = video_url.split("watch?v=")[-1].split("&")[0]

        prompt = (
            "You are evaluating a single YouTube video for a personal podcast feed.\n"
            "Watch the video and judge how well it matches the interest profile below.\n"
            'Return ONLY a JSON object: {"score": float 0-10, "summary": "1-2 Korean sentences"}.\n\n'
            "=== INTERESTS ===\n"
            f"{interests_yaml_text}\n"
        )
        contents = types.Content(
            role="user",
            parts=[
                types.Part(file_data=types.FileData(file_uri=video_url)),
                types.Part(text=prompt),
            ],
        )
        resp = self._client.models.generate_content(
            model=_PRO_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        data = json.loads(resp.text)
        # Stage 2 rate limit: 5 RPM on free tier. Sleep to be safe.
        time.sleep(13)
        return Stage2Verdict(
            video_id=video_id,
            score=float(data["score"]),
            summary=str(data["summary"]),
        )
