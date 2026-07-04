"""Quick self-tests for formatting + postprocess (run: python test_formatting.py)."""
import formatting as F
import postprocess as P

VITALS = [
    ("blood pressure one twenty over eighty", "blood pressure 120/80"),
    ("bp 120 over 80", "bp 120/80"),
    ("one thirty five over ninety", "135/90"),
    ("one oh five over sixty five", "105/65"),
    ("ninety over sixty", "90/60"),
    ("talk it over with the patient", "talk it over with the patient"),  # no numbers -> untouched
]

UNITS = [
    ("twenty five milligrams", "25 mg"),
    ("take five milligrams daily", "take 5 mg daily"),
    ("give 250 micrograms", "give 250 mcg"),
    ("ninety eight point six", "ninety eight point six"),  # no unit -> untouched here
    ("glucose one hundred ten milligrams per deciliter", "glucose 110 mg/dL"),
    ("weight seventy two kilograms", "weight 72 kg"),
]

NUMBERS = [  # only when formatting.numbers is on
    ("ninety eight point six", "98.6"),
    ("twenty five", "25"),
    ("two thousand twenty four", "2024"),
    ("one hundred and twenty", "120"),
]


def run():
    fails = 0
    s_on = {"formatting": {"vitals": True, "units": True, "numbers": False}}
    for src, want in VITALS + UNITS:
        got = F.apply(src, s_on)
        ok = got == want
        fails += not ok
        print(f"[{'ok' if ok else 'XX'}] {src!r} -> {got!r}" + ("" if ok else f"  (want {want!r})"))

    s_num = {"formatting": {"vitals": False, "units": False, "numbers": True}}
    for src, want in NUMBERS:
        got = F.apply(src, s_num)
        ok = got == want
        fails += not ok
        print(f"[{'ok' if ok else 'XX'}] (num) {src!r} -> {got!r}" + ("" if ok else f"  (want {want!r})"))

    # postprocess integration: substitutions + formatting + strip
    settings = {
        "strip_leading": ["okay", "um"],
        "ignore_if_only": ["thanks"],
        "macros": {"adult checkout": "FULL TEMPLATE TEXT"},
        "substitutions": {"hctz": "hydrochlorothiazide", "b i d": "twice daily"},
        "formatting": {"vitals": True, "units": True, "numbers": False},
        "capitalize_first": True,
    }
    cases = [
        ("okay start hctz twenty five milligrams b i d",
         "Start hydrochlorothiazide 25 mg twice daily"),
        ("thanks", None),
        ("adult checkout", "FULL TEMPLATE TEXT"),
        ("blood pressure one twenty over eighty", "Blood pressure 120/80"),
    ]
    for src, want in cases:
        got = P.apply(src, settings)
        ok = got == want
        fails += not ok
        print(f"[{'ok' if ok else 'XX'}] (pp) {src!r} -> {got!r}" + ("" if ok else f"  (want {want!r})"))

    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURES"))
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
