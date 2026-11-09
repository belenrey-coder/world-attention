"""Shared text normalization used by steps 2 and 3."""
import re
import unicodedata

from unidecode import unidecode

_SPACE = re.compile(r"\s+")
_ARABIC_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ֑-ׇ]")
# alef variants -> ا ; alef maqsura and Persian yeh -> Arabic yeh ; Persian keheh -> Arabic kaf
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ی": "ي",
                              "ک": "ك", "ؤ": "و", "ئ": "ي"})


def _is_latin(ch: str) -> bool:
    try:
        return unicodedata.name(ch).startswith("LATIN")
    except ValueError:
        return False


def norm(s: str) -> str:
    """Lowercase, strip accents, replace punctuation/symbols with spaces, collapse spaces.

    Accent stripping is script-aware: Latin letters are transliterated to ASCII
    (é->e, ø->o, ß->ss) and Greek tonos marks are dropped, but combining marks in
    other scripts (Devanagari, Thai, Arabic, Hebrew...) are kept, because there
    they are vowels, not accents. Cyrillic is left intact (й is a letter, not и+accent).
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    out = []
    for ch in s:
        if ord(ch) < 128:
            out.append(ch)
        elif _is_latin(ch):
            out.append(unidecode(ch))
        else:
            out.append(ch)
    s = "".join(out)
    # Drop Greek accents: decompose, remove combining marks that follow a Greek base.
    if any("Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿" for c in s):
        d = unicodedata.normalize("NFD", s)
        kept, prev_greek = [], False
        for c in d:
            if unicodedata.combining(c) and prev_greek:
                continue
            prev_greek = "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿"
            kept.append(c)
        s = unicodedata.normalize("NFC", "".join(kept))
    # Arabic/Persian/Hebrew: optional diacritics (harakat, niqqud) and hamza/alef-maqsura
    # spelling variants are the equivalent of accents -> fold them.
    s = _ARABIC_DIACRITICS.sub("", s).translate(_ARABIC_FOLD)
    s = "".join(" " if unicodedata.category(c)[0] in "PSZC" else c for c in s)
    return _SPACE.sub(" ", s).strip()
