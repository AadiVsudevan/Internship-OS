"""Validate Google credentials without exposing secret values in errors."""
from __future__ import annotations

import json
from typing import Any


class CredentialConfigurationError(ValueError):
    """An actionable, credential-safe configuration failure."""


def parse_service_account(raw: str) -> dict[str, Any]:
    """Accept a complete JSON key, optionally JSON-string-encoded once."""
    help_text = ('GOOGLE_SERVICE_ACCOUNT_JSON must contain the complete downloaded Google '
                 'service-account JSON file, including its opening { and closing }. '
                 'Paste file contents, not the Sheet ID, filename or an individual field.')
    if not raw.strip():
        raise CredentialConfigurationError('Set GOOGLE_SERVICE_ACCOUNT_JSON in GitHub Actions secrets.')
    try:
        info = json.loads(raw.lstrip('\ufeff').strip())
        if isinstance(info, str):
            info = json.loads(info.lstrip('\ufeff').strip())
    except (json.JSONDecodeError, RecursionError):
        raise CredentialConfigurationError(help_text) from None
    if not isinstance(info, dict):
        raise CredentialConfigurationError(help_text)
    if info.get('type') != 'service_account':
        raise CredentialConfigurationError('GOOGLE_SERVICE_ACCOUNT_JSON must be a service-account key, not an OAuth client configuration.')
    required = ('client_email', 'private_key', 'token_uri')
    if any(not isinstance(info.get(k), str) or not info[k].strip() for k in required):
        raise CredentialConfigurationError('GOOGLE_SERVICE_ACCOUNT_JSON is incomplete: client_email, private_key and token_uri are required. Copy the entire downloaded file.')
    return info
