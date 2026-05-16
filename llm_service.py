import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


@dataclass
class ParsedAssignment:
    assignment_text: str
    student_name: str
    due_date: str


@dataclass
class ProgressClassification:
    category: str
    summary: str
    confidence: str


class BaseLLMService(ABC):
    @abstractmethod
    def parse_assignment(self, message: str) -> ParsedAssignment:
        pass

    @abstractmethod
    def classify_progress(
        self, progress_text: str, assignment_text: str
    ) -> ProgressClassification:
        pass

    @abstractmethod
    def generate_reminder(
        self,
        assignment_text: str,
        due_date: str,
        status: str,
    ) -> str:
        pass

    @abstractmethod
    def summarize_student(self, student_data: dict[str, Any]) -> str:
        pass


class GeminiLLMService(BaseLLMService):
    def __init__(self, api_key: str, model_name: str) -> None:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai is required for Gemini. "
                "Install it with: pip install google-generativeai"
            ) from exc

        self._genai = genai
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)

    def _generate(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text.strip()

    def _generate_json(self, prompt: str) -> dict[str, Any]:
        raw = self._generate(
            prompt
            + "\n\nRespond with valid JSON only. No markdown fences or extra text."
        )
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse LLM JSON response: {raw}") from exc
        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")
        return data

    def parse_assignment(self, message: str) -> ParsedAssignment:
        data = self._generate_json(
            "Extract assignment details from the teacher message below.\n"
            "Return JSON with keys:\n"
            '- "assignment_text" (string)\n'
            '- "student_name" (string, Telegram username without @)\n'
            '- "due_date" (string, YYYY-MM-DD)\n\n'
            f"Message:\n{message}"
        )
        try:
            return ParsedAssignment(
                assignment_text=str(data["assignment_text"]).strip(),
                student_name=str(data["student_name"]).strip().lstrip("@"),
                due_date=str(data["due_date"]).strip(),
            )
        except KeyError as exc:
            raise ValueError("Assignment parse response missing required fields") from exc

    def classify_progress(
        self, progress_text: str, assignment_text: str
    ) -> ProgressClassification:
        data = self._generate_json(
            "Classify the student's progress update.\n"
            "Return JSON with keys:\n"
            '- "category" (one of: on_track, needs_help, blocked, complete)\n'
            '- "summary" (short string)\n'
            '- "confidence" (one of: low, medium, high)\n\n'
            f"Assignment:\n{assignment_text}\n\n"
            f"Progress update:\n{progress_text}"
        )
        try:
            return ProgressClassification(
                category=str(data["category"]).strip(),
                summary=str(data["summary"]).strip(),
                confidence=str(data["confidence"]).strip(),
            )
        except KeyError as exc:
            raise ValueError(
                "Progress classification response missing required fields"
            ) from exc

    def generate_reminder(
        self,
        assignment_text: str,
        due_date: str,
        status: str,
    ) -> str:
        return self._generate(
            "Write a short, friendly Telegram reminder for a student.\n"
            "Keep it under 120 words. Do not use markdown.\n"
            "Mention they can use /progress or /submit.\n\n"
            f"Assignment: {assignment_text}\n"
            f"Due date: {due_date}\n"
            f"Status: {status}"
        )

    def summarize_student(self, student_data: dict[str, Any]) -> str:
        payload = json.dumps(student_data, indent=2, default=str)
        return self._generate(
            "Summarize this student's classroom activity for their teacher.\n"
            "Use 3-5 bullet points. Be concise and factual.\n\n"
            f"Student data:\n{payload}"
        )


def create_llm_service() -> BaseLLMService:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

    if provider in {"gemini", "google"}:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file."
            )
        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
        return GeminiLLMService(api_key=api_key, model_name=model_name)

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider}'. Supported values: gemini, google"
    )
