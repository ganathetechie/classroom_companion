import json
import os
import re
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


@dataclass
class ParsedAssignment:
    assignment_text: str
    student: str
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


class LLMServiceError(Exception):
    """Raised when the underlying LLM service fails for transient/API errors."""


class GeminiLLMService(BaseLLMService):
    def __init__(self, api_key: str, model_name: str) -> None:
        try:
            import google.genai as genai
        except ImportError as exc:
            raise ImportError(
                "google-genai is required for Gemini. Install it with: pip install google-genai"
            ) from exc

        self._genai = genai
        # Create a client instance; callers may pass api_key or rely on env
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    def _generate(self, prompt: str) -> str:
        # Use the genai client to generate content
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        # The response object exposes `text` for generated text
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text.strip()

    def _generate_json(self, prompt: str) -> dict[str, Any]:
        raw = self._generate(
            prompt + "\n\nRespond with valid JSON only. No markdown fences or extra text."
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
        try:
            data = self._generate_json(
                "Extract assignment details from the teacher message below.\n"
                "Return JSON with keys:\n"
                '- "assignment_text" (string)\n'
                '- "student" (string, Telegram username without @)\n'
                '- "due_date" (string)\n\n'
                f"Today is {date.today().isoformat()}.\n"
                "If the due date is expressed as a weekday or relative term, select the next upcoming matching date from today.\n"
                "If the due date can be converted to YYYY-MM-DD, do so. Otherwise return the date text as given.\n\n"
                f"Message:\n{message}"
            )
        except Exception as exc:
            print("LLM error in parse_assignment:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM parse_assignment failed") from exc

        try:
            return ParsedAssignment(
                assignment_text=str(data["assignment_text"]).strip(),
                student=str(data["student"]).strip().lstrip("@"),
                due_date=str(data["due_date"]).strip(),
            )
        except KeyError as exc:
            raise ValueError("Assignment parse response missing required fields") from exc

    def classify_progress(
        self, progress_text: str, assignment_text: str
    ) -> ProgressClassification:
        try:
            data = self._generate_json(
                "Classify the student's progress update.\n"
                "Return JSON with keys:\n"
                '- "category" (one of: on_track, needs_help, blocked, complete)\n'
                '- "summary" (short string)\n'
                '- "confidence" (one of: low, medium, high)\n\n'
                f"Assignment:\n{assignment_text}\n\n"
                f"Progress update:\n{progress_text}"
            )
        except Exception as exc:
            print("LLM error in classify_progress:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM classify_progress failed") from exc

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
        try:
            return self._generate(
                "Write a short, friendly Telegram reminder for a student.\n"
                "Keep it under 120 words. Do not use markdown.\n"
                "Mention they can use /progress or /submit.\n\n"
                f"Assignment: {assignment_text}\n"
                f"Due date: {due_date}\n"
                f"Status: {status}"
            )
        except Exception as exc:
            print("LLM error in generate_reminder:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM generate_reminder failed") from exc

    def summarize_student(self, student_data: dict[str, Any]) -> str:
        payload = json.dumps(student_data, indent=2, default=str)
        try:
            return self._generate(
                "Summarize this student's classroom activity for their teacher.\n"
                "Use 3-5 bullet points. Be concise and factual.\n\n"
                f"Student data:\n{payload}"
            )
        except Exception as exc:
            print("LLM error in summarize_student:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM summarize_student failed") from exc


class GroqLLMService(BaseLLMService):
    def __init__(self, api_key: str, model_name: str) -> None:
        try:
            import groq
        except ImportError as exc:
            raise ImportError(
                "groq is required for Groq provider. Install it with: pip install groq"
            ) from exc

        self._groq = groq
        # Attempt to construct a client using common SDK entrypoints
        client = None
        if hasattr(groq, "GroqClient"):
            client = groq.GroqClient(api_key=api_key)
        elif hasattr(groq, "Client"):
            client = groq.Client(api_key=api_key)
        elif hasattr(groq, "client"):
            try:
                client = groq.client(api_key=api_key)
            except Exception:
                client = None

        if client is None:
            raise ImportError(
                "groq SDK found but could not create a client. Check the installed groq package version."
            )

        self._client = client
        self._model_name = model_name

    def _call_model(self, prompt: str) -> str:
        # Prefer the official Groq chat completions API: client.chat.completions.create(...)
        try:
            chat = getattr(self._client, "chat", None)
            if chat is not None and hasattr(chat, "completions"):
                create_fn = getattr(self._client.chat.completions, "create", None)
                if callable(create_fn):
                    resp = create_fn(
                        model=self._model_name,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    # Expected shape: response.choices[0].message.content
                    # Support both object-like and dict-like responses
                    choices = None
                    if isinstance(resp, dict):
                        choices = resp.get("choices")
                    else:
                        choices = getattr(resp, "choices", None)

                    if choices and len(choices) > 0:
                        first = choices[0]
                        message = None
                        if isinstance(first, dict):
                            message = first.get("message")
                        else:
                            message = getattr(first, "message", None)

                        if message:
                            content = None
                            if isinstance(message, dict):
                                content = message.get("content")
                            else:
                                content = getattr(message, "content", None)
                            if content:
                                return content.strip()
        except Exception:
            # Fall through to compatibility attempts below
            pass

        # Fallback: try other common client methods for broader compatibility
        for method_name in ("generate", "generate_text", "predict", "complete", "run"):
            fn = getattr(self._client, method_name, None)
            if not callable(fn):
                continue
            try:
                try:
                    resp = fn(model=self._model_name, prompt=prompt)
                except TypeError:
                    try:
                        resp = fn(prompt)
                    except TypeError:
                        resp = fn(prompt=prompt, model=self._model_name)

                # Normalize possible response shapes
                if isinstance(resp, dict) and "text" in resp:
                    return resp["text"].strip()
                text = getattr(resp, "text", None) or getattr(resp, "output", None)
                if text:
                    return text.strip()
                return str(resp).strip()
            except Exception:
                continue
        raise RuntimeError("Groq client failed to generate text")

    def _generate(self, prompt: str) -> str:
        text = self._call_model(prompt)
        if not text:
            raise RuntimeError("Groq returned an empty response")
        return text

    def _generate_json(self, prompt: str) -> dict[str, Any]:
        raw = self._generate(
            prompt + "\n\nRespond with valid JSON only. No markdown fences or extra text."
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
        try:
            data = self._generate_json(
                "Extract assignment details from the teacher message below.\n"
                "Return JSON with keys:\n"
                '- "assignment_text" (string)\n'
                '- "student" (string, Telegram username without @)\n'
                '- "due_date" (string)\n\n'
                f"Today is {date.today().isoformat()}.\n"
                "If the due date is expressed as a weekday or relative term, select the next upcoming matching date from today.\n"
                "If the due date can be converted to YYYY-MM-DD, do so. Otherwise return the date text as given.\n\n"
                f"Message:\n{message}"
            )
        except Exception as exc:
            print("LLM error in parse_assignment:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM parse_assignment failed") from exc

        try:
            return ParsedAssignment(
                assignment_text=str(data["assignment_text"]).strip(),
                student=str(data["student"]).strip().lstrip("@"),
                due_date=str(data["due_date"]).strip(),
            )
        except KeyError as exc:
            raise ValueError("Assignment parse response missing required fields") from exc

    def classify_progress(
        self, progress_text: str, assignment_text: str
    ) -> ProgressClassification:
        try:
            data = self._generate_json(
                "Classify the student's progress update.\n"
                "Return JSON with keys:\n"
                '- "category" (one of: on_track, needs_help, blocked, complete)\n'
                '- "summary" (short string)\n'
                '- "confidence" (one of: low, medium, high)\n\n'
                f"Assignment:\n{assignment_text}\n\n"
                f"Progress update:\n{progress_text}"
            )
        except Exception as exc:
            print("LLM error in classify_progress:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM classify_progress failed") from exc

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
        try:
            return self._generate(
                "Write a short, friendly Telegram reminder for a student.\n"
                "Keep it under 120 words. Do not use markdown.\n"
                "Mention they can use /progress or /submit.\n\n"
                f"Assignment: {assignment_text}\n"
                f"Due date: {due_date}\n"
                f"Status: {status}"
            )
        except Exception as exc:
            print("LLM error in generate_reminder:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM generate_reminder failed") from exc

    def summarize_student(self, student_data: dict[str, Any]) -> str:
        payload = json.dumps(student_data, indent=2, default=str)
        try:
            return self._generate(
                "Summarize this student's classroom activity for their teacher.\n"
                "Use 3-5 bullet points. Be concise and factual.\n\n"
                f"Student data:\n{payload}"
            )
        except Exception as exc:
            print("LLM error in summarize_student:", file=sys.stderr)
            traceback.print_exc()
            raise LLMServiceError("LLM summarize_student failed") from exc


def create_llm_service() -> BaseLLMService:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

    if provider in {"gemini", "google"}:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
        return GeminiLLMService(api_key=api_key, model_name=model_name)

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        model_name = os.getenv("GROQ_MODEL", "llama3-70b-8192").strip()
        return GroqLLMService(api_key=api_key, model_name=model_name)

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider}'. Supported values: gemini, google, groq"
    )
