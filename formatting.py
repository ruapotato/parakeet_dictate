"""
Medical / numeric formatting (a small, local "inverse text normalization").

Parakeet already punctuates and capitalizes well, so this module deliberately
does NOT try to reformat prose. It targets the few dictation patterns clinicians
say out loud that look wrong when written literally:

  - Vitals:   "one twenty over eighty"      -> "120/80"
  - Dosages:  "twenty five milligrams"      -> "25 mg"
  - Numbers:  "ninety eight point six"      -> "98.6"   (only next to a unit,
              or everywhere if format_numbers is turned on)

Every transform is individually toggleable in settings and each one is written
to be a no-op when it isn't confident, so it can never mangle ordinary prose.
Pure-Python, no platform deps, so it is unit-tested directly on any OS.
"""

import re

# --- spoken-number vocabulary ---------------------------------------------
_ONES = {
    "zero": 0, "oh": 0, "o": 0,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}

_NUM_WORDS = set(_ONES) | set(_TENS) | set(_SCALES) | {"and", "point"}

# unit phrase (as spoken, longest first) -> written abbreviation
_UNITS = [
    ("milligrams per deciliter", "mg/dL"),
    ("millimeters of mercury", "mmHg"),
    ("milliliters", "mL"), ("milliliter", "mL"), ("millilitres", "mL"),
    ("micrograms", "mcg"), ("microgram", "mcg"),
    ("milligrams", "mg"), ("milligram", "mg"),
    ("kilograms", "kg"), ("kilogram", "kg"),
    ("centimeters", "cm"), ("centimeter", "cm"),
    ("millimeters", "mm"), ("millimeter", "mm"),
    ("grams", "g"), ("gram", "g"),
    ("liters", "L"), ("liter", "L"),
    ("units", "units"),
    ("percent", "%"),
]


def _standard_int(tokens):
    """Parse a run of number words with normal English multiplication.

    "twenty five" -> 25, "one hundred and twenty" -> 120,
    "two thousand twenty four" -> 2024. Returns None if nothing parseable.
    """
    total = current = 0
    got = False
    for t in tokens:
        if t == "and":
            continue
        if t in _SCALES:
            scale = _SCALES[t]
            if scale >= 1000:
                total += (current or 1) * scale
                current = 0
            else:  # hundred
                current = (current or 1) * scale
            got = True
        elif t in _TENS:
            current += _TENS[t]
            got = True
        elif t in _ONES:
            current += _ONES[t]
            got = True
        else:
            return None
    return (total + current) if got else None


def _colloquial_int(tokens):
    """Vitals-style parse where a lone leading digit means "hundreds".

    "one twenty" -> 120, "one oh five" -> 105, "one thirty five" -> 135.
    Falls back to the standard parse for everything else ("ninety" -> 90).
    """
    toks = [t for t in tokens if t != "and"]
    if not toks:
        return None
    if not any(t in _SCALES for t in toks) and len(toks) > 1:
        head = _ONES.get(toks[0])
        if head is not None and 1 <= head <= 9:
            tail = _standard_int(toks[1:])
            if tail is not None and tail < 100:
                return head * 100 + tail
    return _standard_int(toks)


def _run_to_number(text, colloquial=False):
    """Convert a whitespace string of number words (or digits) to a numeric
    string, honouring a decimal 'point'. Returns None if not fully numeric."""
    text = text.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return text  # already digits
    tokens = text.lower().split()
    if "point" in tokens:
        i = tokens.index("point")
        whole = _int_run(tokens[:i], colloquial)
        frac_digits = [str(_ONES[t]) for t in tokens[i + 1:] if t in _ONES]
        if whole is None or len(frac_digits) != len(tokens[i + 1:]):
            return None
        return f"{whole}.{''.join(frac_digits)}"
    return _int_run(tokens, colloquial)


def _int_run(tokens, colloquial):
    if not tokens:
        return None
    val = _colloquial_int(tokens) if colloquial else _standard_int(tokens)
    return None if val is None else str(val)


_NUM_RUN = r"(?:{})".format("|".join(sorted(_NUM_WORDS, key=len, reverse=True)))
# one or more number words (word-bounded), or a literal digit string
_RUN_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?|{w}(?:\s+{w})*)\b".format(w=_NUM_RUN), re.IGNORECASE)


def format_vitals(text):
    """'one twenty over eighty' / '120 over 80' -> '120/80'."""
    pat = re.compile(
        r"\b((?:\d+|{w})(?:\s+{w})*)\s+over\s+((?:\d+|{w})(?:\s+{w})*)\b".format(
            w=_NUM_RUN), re.IGNORECASE)

    def repl(m):
        a = _run_to_number(m.group(1), colloquial=True)
        b = _run_to_number(m.group(2), colloquial=True)
        if a is None or b is None:
            return m.group(0)
        return f"{a}/{b}"

    return pat.sub(repl, text)


def format_units(text):
    """'twenty five milligrams' -> '25 mg' (only when a number precedes)."""
    for phrase, abbr in _UNITS:
        pat = re.compile(
            r"\b((?:\d+(?:\.\d+)?|{w})(?:\s+{w})*)\s+{p}\b".format(
                w=_NUM_RUN, p=re.escape(phrase)), re.IGNORECASE)

        def repl(m, abbr=abbr):
            num = _run_to_number(m.group(1), colloquial=False)
            if num is None:
                return m.group(0)
            return f"{num} {abbr}"

        text = pat.sub(repl, text)
    return text


def format_numbers(text):
    """Convert every standalone spoken number to digits. Off by default because
    it will also rewrite prose ('one of them' -> '1 of them')."""
    def repl(m):
        num = _run_to_number(m.group(0), colloquial=False)
        return num if num is not None else m.group(0)

    return _RUN_RE.sub(repl, text)


def apply(text, settings):
    fmt = settings.get("formatting", {})
    if not text:
        return text
    if fmt.get("vitals", True):
        text = format_vitals(text)
    if fmt.get("units", True):
        text = format_units(text)
    if fmt.get("numbers", False):
        text = format_numbers(text)
    return text
