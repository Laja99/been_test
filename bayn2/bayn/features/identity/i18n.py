"""
1. see in Accept-Language header: "ar" or "en"
2. get_locale()reed the Accept-Language header and return the appropriate locale
3. t() returns the translated message for the given key and locale

translations:
    locales/ar.json
    locales/en.json

"""

import json
from functools import lru_cache #Least Recently Used
from pathlib import Path

from fastapi import Header


# Constants
SUPPORTED_LOCALES = {"ar", "en"}
DEFAULT_LOCALE = "en"

BAYN_DIR = Path(__file__).parent.parent


# Loader
@lru_cache(maxsize=None)
def _load_locale(feature_name: str, locale: str) -> dict:
    """
    Loads the translation JSON file for the given feature and locale.
    Caches the result to avoid repeated file reads.
    """
    locale_file = BAYN_DIR / "features" / feature_name / "locales" / f"{locale}.json"

    if not locale_file.exists():
        return {}

    with open(locale_file, encoding="utf-8") as f:
        return json.load(f)



# Core Translation Function
def t(feature_name: str, key: str, locale: str = DEFAULT_LOCALE) -> str:
    """
    Returns the translated string for the given feature, key, and locale.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = DEFAULT_LOCALE

    translations = _load_locale(feature_name, locale)

    value = _get_nested(translations, key)

    if value is None and locale != DEFAULT_LOCALE:
        fallback_translations = _load_locale(feature_name, DEFAULT_LOCALE)
        value = _get_nested(fallback_translations, key)

    return value if value is not None else key


def _get_nested(data: dict, key: str) -> str | None:
    """
    Retrieves a nested value from a dictionary using dot notation keys.
    """
    keys = key.split(".")
    current = data

    for k in keys:
        if not isinstance(current, dict) or k not in current:
            return None
        current = current[k]

    return current if isinstance(current, str) else None


# FastAPI Dependency
def get_locale(
    accept_language: str = Header(default="en", alias="Accept-Language"),
) -> str:
    """
    Determines the best locale based on the Accept-Language header.
    Returns the locale code (e.g., "en" or "ar").
    If the header is missing or unsupported, defaults to DEFAULT_LOCALE.
    """
    if not accept_language:
        return DEFAULT_LOCALE

    primary = accept_language.split(",")[0].strip()

    lang_code = primary.split("-")[0].strip().lower()

    return lang_code if lang_code in SUPPORTED_LOCALES else DEFAULT_LOCALE
