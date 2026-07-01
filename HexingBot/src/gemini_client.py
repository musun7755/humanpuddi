"""Gemini API 的最小 REST 用戶端。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Final

import requests
from dotenv import load_dotenv


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"
DEFAULT_MODEL: Final = "gemini-2.5-flash"
API_BASE: Final = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiAPIError(RuntimeError):
    """Gemini 設定、連線或回應格式錯誤。"""


class GeminiClient:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        load_dotenv(ENV_FILE, override=False)
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = model
        if not self.api_key:
            raise GeminiAPIError(
                "尚未設定 GEMINI_API_KEY。請在 HexingBot 根目錄的 .env 填入 Gemini API Key。"
            )

    def generate_json(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        system_instruction: str,
    ) -> dict[str, Any]:
        """要求 Gemini 依 JSON Schema 產生可解析的物件。"""
        url = f"{API_BASE}/{self.model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }

        response = None
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    url,
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120,
                )
            except requests.RequestException as exc:
                if attempt == max_attempts - 1:
                    raise GeminiAPIError(f"無法連線到 Gemini API：{exc}") from exc
                time.sleep(min(5 * (2 ** attempt), 40))
                continue
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == max_attempts - 1:
                break
            retry_after = response.headers.get("Retry-After", "").strip()
            try:
                wait_seconds = float(retry_after) if retry_after else 5 * (2 ** attempt)
            except ValueError:
                wait_seconds = 5 * (2 ** attempt)
            time.sleep(max(1, min(wait_seconds, 40)))

        if response is None:
            raise GeminiAPIError("Gemini API 未回傳結果。")

        if not response.ok:
            try:
                error_body = response.json()
                detail = error_body.get("error", {}).get("message", response.text)
            except (ValueError, AttributeError):
                detail = response.text
            detail = str(detail).strip() or "Gemini 未提供錯誤內容"
            raise GeminiAPIError(
                f"Gemini API 失敗。HTTP 狀態：{response.status_code}；錯誤內容：{detail}"
            )

        try:
            body = response.json()
            candidates = body["candidates"]
            parts = candidates[0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GeminiAPIError("Gemini 回應中沒有可讀取的候選內容。") from exc

        if not text:
            raise GeminiAPIError("Gemini 回傳空白內容。")

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().lower() in {"```", "```json"}:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiAPIError("Gemini 回應不是有效 JSON，請重新執行。") from exc

        if not isinstance(result, dict):
            raise GeminiAPIError("Gemini 回應格式錯誤：最外層必須是物件。")
        return result
