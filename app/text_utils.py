import unicodedata


def sanitize_text(text: str) -> str:
    """Strips lone UTF-16 surrogate codepoints (U+D800-U+DFFF) and normalizes
    to NFC.

    Surrogates end up in a `str` when something decodes bytes with
    errors="surrogateescape" (e.g. a terminal/stdin encoding mismatch) —
    each undecodable byte becomes one lone surrogate. Such a string looks
    fine in Python but isn't valid UTF-8: asyncpg encodes query parameters
    as UTF-8 before sending them to PostgreSQL, and encoding a lone
    surrogate raises UnicodeEncodeError deep in the driver, crashing the
    whole request. This must run on any user-supplied text before it can
    reach SQLAlchemy/asyncpg or an LLM API call.
    """
    cleaned = text.encode("utf-8", errors="replace").decode("utf-8")
    return unicodedata.normalize("NFC", cleaned)
