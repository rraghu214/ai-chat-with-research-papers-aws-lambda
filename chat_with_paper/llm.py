import os
import math
from typing import List, Dict
from google import genai

# Model selection
# Defaults to Gemini Flash 2.x name. You can change via GEMINI_MODEL env var.
# If you have access to a specific preview like "gemini-2.5-flash", set it there.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def get_gemini_client():
    """Initialize Gemini client with API key from environment"""
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY env var is required")
    
    return genai.Client(api_key=GEMINI_API_KEY)

# -------------- Prompt helpers --------------
from prompts import CHAT_PROMPT


def _call_gemini(contents: List[Dict]) -> str:
    """Low-level call using client.models.generate_content; returns text."""
    client = get_gemini_client()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
    )
    # The SDK exposes either resp.output_text or resp.text depending on version
    text = getattr(resp, "output_text", None) or getattr(resp, "text", None)
    if not text:
        # Fallback: attempt to construct from candidates
        try:
            return resp.candidates[0].content.parts[0].text
        except Exception:
            return str(resp)
    return text


def chat_answer(doc_text: str, history: List[Dict[str, str]], max_context_chars: int = 60000) -> str:
    """Answer a user question grounded in doc_text and chat history.

    history: list of {role: 'user'|'model', text: str}
    """
    # Trim document context to fit prompt size
    context = doc_text[:max_context_chars]

    # Build contents from history + current user question (last item is user)
    contents: List[Dict] = []

    # Add system-like instruction by putting it in the first user message
    system_user_message = CHAT_PROMPT.format(context=context)
    contents.append({"role": "user", "parts": [{"text": system_user_message}]})

    for turn in history:
        contents.append({"role": turn["role"], "parts": [{"text": turn["text"]}]})

    return _call_gemini(contents)
