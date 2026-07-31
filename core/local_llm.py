"""Local LLM support via Ollama.

Kleos talks to a locally-running `Ollama`_ instance over its HTTP API
(default ``http://localhost:11434``) using ``requests`` — no new pip
dependency, no bundled model.  Ollama is a free desktop app the user installs
separately from https://ollama.com.

Model IDs are prefixed ``ollama:`` (e.g. ``ollama:gemma3:270m``); the bare
Ollama tag is the part after the prefix.  This prefix never collides with the
``gemini-`` prefix used by the Gemini provider.

.. _Ollama: https://ollama.com
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import requests
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
_REQUEST_TIMEOUT = 10          # seconds — for /api/tags and short probes
_CHAT_TIMEOUT = 120            # local first-load inference can be slow
_LIST_TIMEOUT = 3              # short, UI-facing probe for installed models
# The four local models offered in the install dialog, ordered lightest to
# heaviest. All are instruct/chat-tuned and non-thinking so they follow
# Kleos's evaluate/verify rubric and YES/NO-on-the-final-line output format;
# thinking-mode models (qwen3 default tags, deepseek-r1) are deliberately
# excluded because their 1980 reasoning traces break that format. Per-tag
# category hints (Best Availability / Balance / Value / Performance) live in
# ui/install_local_models_dialog.py.
_CANDIDATE_TAGS = (
    "gemma3:1b",
    "qwen2.5:3b-instruct",
    "gemma3:4b",
    "qwen2.5:7b-instruct",
)

_LOCAL_PREFIX = "ollama:"


def is_local_model(model: str) -> bool:
    """True if *model* is a local (Ollama) model id."""
    return model.startswith(_LOCAL_PREFIX)


def ollama_model_name(model: str) -> str:
    """Return the bare Ollama tag for *model* (strips the ``ollama:`` prefix)."""
    if not is_local_model(model):
        return model
    return model[len(_LOCAL_PREFIX):]


def get_ollama_host(db: Any | None = None) -> str:
    """Resolve the Ollama host: the ``ollama_host`` global setting if set,
    otherwise :data:`DEFAULT_HOST`.  Never raises.

    Safe to call on the GUI thread — it only reads an in-memory setting, no
    network.  Pass the result into :class:`ListLocalModelsWorker` so the worker
    thread never touches the database.

    The stored value is normalized: trailing slashes are stripped and a bare
    ``host:port`` (no scheme) gets ``http://`` prepended so every call site can
    build URLs without re-checking.
    """
    if db is not None:
        try:
            host = (db.get_global_setting("ollama_host") or "").strip()
        except Exception:
            host = ""
        if host:
            host = host.rstrip("/")
            if "://" not in host:
                host = f"http://{host}"
            return host
    return DEFAULT_HOST


def ollama_reachable(db: Any | None = None) -> bool:
    """True if the Ollama API responds at the configured host.  Never raises."""
    try:
        resp = requests.get(f"{get_ollama_host(db)}/api/tags", timeout=_REQUEST_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False


def ollama_list_installed(db: Any | None = None) -> tuple[list[str], str | None]:
    """Return ``(model_tags, error)`` for every model installed in Ollama.

    On success ``error`` is None and ``model_tags`` is the list of bare tags
    (e.g. ``["gemma3:270m", "smollm2:360m"]``).  On connection failure returns
    ``([], "Ollama is not running…")``.
    """
    try:
        resp = requests.get(f"{get_ollama_host(db)}/api/tags", timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return [], "Ollama is not running. Start the Ollama app and try again."
    models = data.get("models") or []
    tags = [m.get("name") for m in models if m.get("name")]
    return tags, None


def ollama_chat(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 512,
    cancel_check: Callable[[], bool] | None = None,
    db: Any | None = None,
) -> tuple[str | None, str | None]:
    """Send a single prompt to the local Ollama model.

    Returns ``(text, error)`` mirroring :func:`core.ai_client.call_ai`:
    ``(text, None)`` on success, ``(None, error)`` on failure, ``(None, None)``
    if cancelled before the request is issued.
    """
    if cancel_check and cancel_check():
        return None, None
    tag = ollama_model_name(model)
    payload = {
        "model": tag,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
        "options": {"num_predict": max_tokens, "temperature": 0},
    }
    try:
        resp = requests.post(
            f"{get_ollama_host(db)}/api/chat", json=payload,
            stream=True, timeout=(5, _CHAT_TIMEOUT),
        )
    except requests.exceptions.ConnectionError:
        return None, "Ollama is not running. Start the Ollama app and try again."
    except requests.exceptions.Timeout:
        return None, "Ollama request timed out. Check your local setup and try again."

    # A 404 with {"error": "model '...' not found"} means the model isn't
    # installed (e.g. a stale saved setting).  Surface a clear message that
    # includes the server's reason (fixes dead err_msg).
    if resp.status_code == 404:
        try:
            err_msg = (resp.json().get("error") or "").strip()
        except (ValueError, json.JSONDecodeError):
            err_msg = ""
        extra = f" ({err_msg})" if err_msg else ""
        return None, (
            f"Local model '{tag}' is not installed. "
            f"Install it via Settings → Verify → Install Local AI Models.{extra}"
        )

    try:
        resp.raise_for_status()
    except Exception as exc:
        return None, f"Ollama error: {exc}"

    # Stream the NDJSON response so a mid-inference cancel is honored between
    # chunks instead of blocking for up to _CHAT_TIMEOUT seconds.
    parts: list[str] = []
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if cancel_check and cancel_check():
                return None, None
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            msg = chunk.get("message") or {}
            content = msg.get("content")
            if content:
                parts.append(content)
            if chunk.get("done"):
                break
    except requests.exceptions.ConnectionError:
        return None, "Ollama is not running. Start the Ollama app and try again."
    except requests.exceptions.Timeout:
        return None, "Ollama request timed out. Check your local setup and try again."
    finally:
        resp.close()

    text = "".join(parts)
    if not text:
        return None, "Ollama returned an empty response."
    return text, None


class PullModelWorker(QThread):
    """Background thread that pulls (installs) a model into Ollama.

    Ollama's ``/api/pull`` streams NDJSON progress lines; we parse them and
    emit Qt signals so the GUI can show a progress bar without blocking.

    Pulls are resumable — Ollama caches downloaded blobs, so re-pulling a
    partially-pulled model continues from where it left off.

    Signals
    -------
    progress(str, int)
        ``(status_text, percent)``; ``percent`` is 0..100, or -1 for
        indeterminate phases (e.g. "pulling manifest", "verifying").
    done(str)
        The model tag on success.
    error(str)
        Human-readable error message.
    aborted()
        Emitted when the user cancelled the pull.
    """

    progress = pyqtSignal(str, int)
    done = pyqtSignal(str)
    error = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, model_tag: str, db: Any | None = None, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._tag = model_tag
        self._db = db
        self._host = get_ollama_host(db)
        self._cancel = threading.Event()
        self._response: Any | None = None

    def cancel(self) -> None:
        """Request the pull to stop promptly.

        Sets the cancel flag and closes the in-flight response stream so
        ``iter_lines`` returns immediately instead of blocking on a read gap.
        """
        self._cancel.set()
        resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def run(self) -> None:
        emitted = False
        try:
            with requests.post(
                f"{self._host}/api/pull",
                json={"name": self._tag, "stream": True},
                stream=True,
                timeout=(5, 120),
            ) as resp:
                self._response = resp
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if self._cancel.is_set():
                        resp.close()
                        self.aborted.emit()
                        emitted = True
                        return
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    # Ollama reports pull failures as an "error" field on a
                    # status chunk (e.g. disk full mid-pull) — surface it.
                    if chunk.get("error"):
                        if self._cancel.is_set():
                            self.aborted.emit()
                        else:
                            self.error.emit(f"Failed to pull {self._tag}: {chunk['error']}")
                        emitted = True
                        return
                    status = str(chunk.get("status", "") or "")
                    if status == "success":
                        self.done.emit(self._tag)
                        emitted = True
                        return
                    if status == "downloading":
                        total = chunk.get("total") or 0
                        completed = chunk.get("completed") or 0
                        if total > 0:
                            percent = int(completed * 100 / total)
                        else:
                            percent = -1
                        self.progress.emit(status, percent)
                    else:
                        self.progress.emit(status, -1)
        except requests.exceptions.ConnectionError:
            if self._cancel.is_set():
                self.aborted.emit()
            else:
                self.error.emit("Ollama is not running. Start the Ollama app and try again.")
            emitted = True
        except Exception as exc:
            if self._cancel.is_set():
                self.aborted.emit()
            else:
                self.error.emit(f"Failed to pull {self._tag}: {exc}")
            emitted = True
        finally:
            self._response = None
        # The stream ended without a success/error/cancel signal (e.g. the
        # connection dropped or Ollama exited without a final status line).
        # Emit a fallback so the dialog doesn't wait on a signal that never comes.
        if not emitted and not self._cancel.is_set():
            self.error.emit(f"Pull ended unexpectedly for {self._tag}.")


# Holds references to in-flight ListLocalModelsWorker instances so they are
# not garbage-collected (and thus destroyed by Qt) while still running — even
# if the UI that started one has already closed.  Each worker removes itself
# and self-deletes on ``finished``.
_LIVE_LIST_WORKERS: set = set()


class ListLocalModelsWorker(QThread):
    """Fetch the list of installed Ollama models off the GUI thread.

    Used by the Settings Verify tab, the Verify dialog Local page, and the
    Discover Evaluate combo so opening those UIs never blocks on a network
    round-trip.  Does only HTTP — the host is resolved on the GUI thread and
    passed in, so the worker never touches the database.

    Signals
    -------
    done(list)
        The list of bare installed model tags on success.
    error(str)
        A human-readable message on failure (e.g. Ollama not running).
    """

    done = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, host: str, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._host = host

    def run(self) -> None:
        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=_LIST_TIMEOUT)
            resp.raise_for_status()
            tags = [m.get("name") for m in (resp.json().get("models") or []) if m.get("name")]
            self.done.emit(tags)
        except Exception:
            self.error.emit("Ollama is not running. Start the Ollama app and try again.")

    def start(self) -> None:  # type: ignore[override]
        # Register before starting so the registry holds a ref for the worker's
        # whole lifetime; ``finished`` removes it and schedules deletion.
        _LIVE_LIST_WORKERS.add(self)
        self.finished.connect(
            lambda *_: (_LIVE_LIST_WORKERS.discard(self), self.deleteLater())
        )
        super().start()