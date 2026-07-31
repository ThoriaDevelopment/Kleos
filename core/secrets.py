"""DPAPI-backed secret encryption for Windows at-rest storage.

Kleos stores API keys (YouTube, Twitch, Anthropic, Gemini) in the shared
``api_keys_json`` global setting.  On Windows they are encrypted with DPAPI
(``CryptProtectData``) so the credential blob on disk is bound to the current
Windows user account and unreadable to other accounts or offline scavengers.

The token format is ``dpapi:<base64(blob)>``.  ``decrypt`` recognises the
``dpapi:`` prefix and returns the plaintext; any other string is treated as a
legacy plaintext value (returned as-is) so older databases migrate seamlessly.

If ``win32crypt`` cannot be imported (e.g. a non-Windows dev box), both
functions fall back to plaintext and a single warning is logged.  Callers
never need to branch on availability — ``encrypt``/``decrypt`` always return a
usable string.
"""
from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

_PREFIX = "dpapi:"

try:
    import win32crypt
    _DPAPI_AVAILABLE = True
except ImportError:
    _DPAPI_AVAILABLE = False
    logger.warning(
        "win32crypt unavailable — API keys will be stored in plaintext. "
        "Install pywin32 on Windows to enable DPAPI encryption."
    )


def encrypt(plaintext: str) -> str:
    """Return a DPAPI-encrypted token for *plaintext*.

    Falls back to returning *plaintext* unchanged when DPAPI is not available
    so the app still runs (keys are simply stored unencrypted in that case).
    """
    if not _DPAPI_AVAILABLE or not plaintext:
        return plaintext
    try:
        blob = win32crypt.CryptProtectData(
            plaintext.encode("utf-8"), "Kleos API keys", None, None, None, 0
        )
        return _PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception as exc:  # pragma: no cover — DPAPI failure is unusual
        logger.warning("DPAPI encryption failed; storing value in plaintext: %s", type(exc).__name__)
        return plaintext


def decrypt(token: str) -> str | None:
    """Return the plaintext for a *token* produced by :func:`encrypt`.

    A non-``dpapi:`` value is treated as legacy plaintext and returned as-is
    (so older databases migrate without a separate step).  Returns ``None`` if
    the token is ``None``.  On DPAPI decryption failure (e.g. a different
    Windows user account), returns an empty string so the caller can prompt the
    user to re-enter their keys rather than crash.
    """
    if token is None:
        return None
    if not isinstance(token, str) or not token:
        return ""
    if not token.startswith(_PREFIX):
        # Legacy plaintext value — return unchanged.
        return token
    if not _DPAPI_AVAILABLE:
        # Encrypted token but no DPAPI to decrypt it — can't recover.
        logger.warning("Encrypted token present but win32crypt unavailable; cannot decrypt.")
        return ""
    try:
        blob = base64.b64decode(token[len(_PREFIX):])
        _desc, plaintext_bytes = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return plaintext_bytes.decode("utf-8")
    except Exception as exc:  # pragma: no cover — wrong user / corrupted blob
        logger.warning("DPAPI decryption failed; the stored key may be unreadable: %s", type(exc).__name__)
        return ""