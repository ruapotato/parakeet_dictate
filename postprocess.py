"""
Transcript post-processing.

Order of operations:
  1. Strip configured filler words from the START of the utterance
     (handles the "Okay ..." / "Mm-hmm ..." prepend problem).
  2. If nothing meaningful remains, or the whole thing is an ignore-only
     word, return None (inject nothing).
  3. If the cleaned phrase exactly matches a macro trigger, return the
     macro's expansion verbatim (paragraph templates, etc.).
  4. Apply inline substitutions (spoken abbreviation -> written form, anywhere
     in the sentence) and medical/numeric formatting.
  5. Capitalize the first letter if requested.
"""

import re

import formatting

_PUNCT = " .,!?;:\"'"


def _norm(s):
    """Lowercase, collapse whitespace, trim surrounding punctuation."""
    return re.sub(r"\s+", " ", s.strip().lower()).strip(_PUNCT)


def _apply_substitutions(text, subs):
    """Whole-word/phrase replacement anywhere in the text, case-insensitive.
    Longer triggers are applied first so 'blood pressure' wins over 'pressure'.
    """
    if not subs:
        return text
    for key in sorted(subs, key=len, reverse=True):
        if not key.strip():
            continue
        val = subs[key]
        pat = re.compile(r"\b" + re.escape(key) + r"\b", re.IGNORECASE)
        text = pat.sub(lambda m, v=val: v, text)
    return text


def apply(text, settings, mid_sentence=False):
    """mid_sentence=True marks a continuation of a segment that was force-cut
    mid-sentence, so the first letter is not capitalized."""
    if not text:
        return None
    original = text.strip()

    # 1. strip leading filler words (repeatedly)
    strip_set = {w.strip(_PUNCT).lower() for w in settings.get("strip_leading", [])}
    words = original.split()
    while words:
        first = words[0].strip(_PUNCT).lower()
        if first in strip_set:
            words.pop(0)
        else:
            break
    cleaned = " ".join(words).strip()
    if not cleaned:
        return None

    # 2. ignore-if-only (whole utterance is a throwaway word/phrase)
    ignore_set = {_norm(w) for w in settings.get("ignore_if_only", [])}
    if _norm(cleaned) in ignore_set:
        return None

    # 3. macro expansion (exact normalized match) -> returned verbatim
    macros = settings.get("macros", {})
    norm_macros = {_norm(k): v for k, v in macros.items()}
    if _norm(cleaned) in norm_macros:
        return norm_macros[_norm(cleaned)]

    # 4. inline substitutions, then medical/numeric formatting
    cleaned = _apply_substitutions(cleaned, settings.get("substitutions", {}))
    cleaned = formatting.apply(cleaned, settings)

    # 5. capitalize first letter if requested (not applied to macros, and not
    #    when continuing a mid-sentence forced cut)
    if settings.get("capitalize_first", True) and not mid_sentence:
        for i, ch in enumerate(cleaned):
            if ch.isalpha():
                cleaned = cleaned[:i] + ch.upper() + cleaned[i + 1:]
                break

    return cleaned
