"""Shared single-prompt AI call helper for Claude (Anthropic) and Gemini.

Used by the Discover AI worker (evaluate a creator).
Mirrors the retry / cancel / error-handling shape of ``verify_worker`` but
returns a ``(text, error)`` tuple so callers can route errors to their own
signals.  ``error`` is None on success; ``text`` is None on failure.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from google import genai as google_genai
    from google.genai import types as genai_types
    from google.genai import errors as genai_errors
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = (1.0, 2.0, 4.0)
_GEMINI_RETRY_DELAYS = (10.0, 30.0, 60.0)


def is_gemini_model(model: str) -> bool:
    return model.startswith('gemini-')


def provider_name(model: str) -> str:
    return 'gemini' if is_gemini_model(model) else 'claude'


def build_client(model: str, api_key: str) -> Any:
    """Return an authenticated client for the model's provider."""
    if is_gemini_model(model):
        return google_genai.Client(api_key=api_key)
    return anthropic.Anthropic(api_key=api_key)


def call_ai(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    api_key: str,
    max_tokens: int = 512,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[str | None, str | None]:
    """Send a single prompt to the AI.  Returns ``(text, error)``.

    On success ``error`` is None.  On failure ``text`` is None and
    ``error`` is a human-readable message suitable for emitting to the UI.
    A cancellation returns ``(None, None)`` so the caller can distinguish
    "cancelled" from "errored".
    """
    is_gemini = is_gemini_model(model)

    if is_gemini and not GEMINI_AVAILABLE:
        return None, "The 'google-genai' Python package is not installed. Install it with: pip install google-genai"
    if not is_gemini and not ANTHROPIC_AVAILABLE:
        return None, "The 'anthropic' Python package is not installed. Install it with: pip install anthropic"

    try:
        client = build_client(model, api_key)
    except Exception as exc:
        return None, f"Failed to create AI client: {exc}"

    if is_gemini:
        return _call_gemini(client, model, system_prompt, user_message, max_tokens, cancel_check)
    return _call_anthropic(client, model, system_prompt, user_message, max_tokens, cancel_check)


def _call_anthropic(client, model, system_prompt, user_message, max_tokens, cancel_check) -> tuple[str | None, str | None]:
    create_kwargs: dict[str, Any] = {
        'model': model,
        'max_tokens': max_tokens,
        'system': system_prompt,
        'messages': [{'role': 'user', 'content': user_message}],
    }
    if model.startswith('claude-haiku'):
        create_kwargs['temperature'] = 0

    for attempt in range(_MAX_RETRIES + 1):
        if cancel_check and cancel_check():
            return None, None
        try:
            response = client.messages.create(**create_kwargs)
            return response.content[0].text, None
        except anthropic.AuthenticationError:
            return None, "Invalid Anthropic API key. Please check your key in Settings → API Keys."
        except anthropic.RateLimitError:
            if attempt < _MAX_RETRIES:
                _sleep(_RETRY_DELAYS[attempt], cancel_check)
            else:
                return None, "Anthropic API rate limit exceeded. Please wait a moment and try again."
        except anthropic.APIConnectionError:
            return None, "Network error connecting to Anthropic. Check your internet connection."
        except anthropic.APITimeoutError:
            return None, "Anthropic API request timed out. Check your internet connection and try again."
        except anthropic.BadRequestError as exc:
            return None, f"Anthropic request error: {exc}"
        except anthropic.APIStatusError as exc:
            return None, f"Anthropic API error: {exc}"
        except Exception as exc:
            return None, f"Unexpected error: {exc}"
    return None, "Anthropic API call failed after retries."


def _call_gemini(client, model, system_prompt, user_message, max_tokens, cancel_check) -> tuple[str | None, str | None]:
    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=max_tokens,
        temperature=0,
    )
    for attempt in range(_MAX_RETRIES + 1):
        if cancel_check and cancel_check():
            return None, None
        try:
            response = client.models.generate_content(
                model=model, contents=user_message, config=config,
            )
            return response.text, None
        except genai_errors.APIError as exc:
            code = getattr(exc, 'code', None) or 0
            if code in (401, 403):
                return None, "Invalid Gemini API key. Please check your key in Settings → API Keys."
            if code == 429:
                if attempt < _MAX_RETRIES:
                    _sleep(_GEMINI_RETRY_DELAYS[attempt], cancel_check)
                else:
                    return None, "Gemini API rate limit exceeded. Please wait a moment and try again."
            else:
                return None, f"Gemini API error: {exc}"
        except ConnectionError:
            return None, "Network error connecting to Gemini. Check your internet connection."
        except Exception as exc:
            return None, f"Unexpected error: {exc}"
    return None, "Gemini API call failed after retries."


def _sleep(seconds: float, cancel_check: Callable[[], bool] | None) -> None:
    """Interruptible sleep — exits early if cancel_check returns True."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel_check and cancel_check():
            return
        time.sleep(0.1)


def load_ai_api_key(db, model: str) -> tuple[str | None, str | None]:
    """Return ``(api_key, error)`` for the model's provider.

    Reads the global ``api_keys_json`` setting (shared across profiles),
    matching ``verify_worker``.
    """
    import json
    raw = db.get_global_setting('api_keys_json') or '{}'
    try:
        parsed = json.loads(raw)
        key_field = 'gemini' if is_gemini_model(model) else 'anthropic'
        api_key = parsed.get(key_field, '').strip() if isinstance(parsed, dict) else ''
    except (json.JSONDecodeError, AttributeError):
        api_key = ''
    if not api_key:
        provider = 'Gemini' if is_gemini_model(model) else 'Anthropic'
        return None, f"No {provider} API key found. Open Settings → API Keys."
    return api_key, None