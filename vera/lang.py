"""Language handling.

Three output modes:

* "en"      plain English
* "mix"     English core with natural Hindi touches (merchant default when the
            merchant lists Hindi, matching how production Vera writes)
* "hi"      Roman-script Hindi-heavy Hinglish (customers who prefer Hindi, or
            merchants who reply in Hindi)

`pick(mode, en, mix, hi)` returns the phrase for a mode, falling back sensibly.
`detect_reply_language` reads a merchant/customer reply so the bot can mirror
a language switch mid-conversation (open challenge #4 in the brief).
"""

from __future__ import annotations

import re

_HINDI_MARKERS = {
    "hai", "hain", "haan", "ha", "nahi", "nahin", "kya", "kar", "karo", "karna", "karein",
    "kijiye", "mujhe", "aap", "aapka", "aapki", "hum", "humara", "mera", "meri", "bhai",
    "ji", "theek", "thik", "accha", "acha", "chalega", "chalo", "bhej", "bhejo", "dijiye",
    "abhi", "baad", "mein", "se", "ko", "ka", "ki", "ke", "bolo", "batao", "bataiye",
    "kab", "kaise", "kitna", "kitne", "zaroor", "bilkul", "shukriya", "dhanyavaad",
    "samajh", "pata", "wala", "wali", "raha", "rahi", "rahe", "hoga", "hogi", "kyun",
}
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_WORD = re.compile(r"[a-zA-Z']+")


def detect_reply_language(text: str) -> str | None:
    """Return "hi", "mix", "en" or None (too short to tell)."""
    if not text:
        return None
    if _DEVANAGARI.search(text):
        return "hi"
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 2:
        return None
    hits = sum(1 for w in words if w in _HINDI_MARKERS)
    share = hits / len(words)
    if share >= 0.35:
        return "hi"
    if hits >= 2:
        return "mix"
    return "en"


def merchant_mode(merchant: dict, category: dict) -> str:
    langs = [str(x).lower() for x in (merchant.get("identity") or {}).get("languages") or []]
    code_mix = str(((category or {}).get("voice") or {}).get("code_mix") or "")
    if "hi" in langs and "hindi" in code_mix:
        return "mix"
    if langs and langs[0] == "hi":
        return "hi"
    return "en"


def customer_mode(customer: dict) -> str:
    pref = str(((customer or {}).get("identity") or {}).get("language_pref") or "en").lower()
    if pref in ("hi", "hindi"):
        return "hi"
    if pref.startswith("hi") and "en" in pref:
        return "mix"
    return "en"


def pick(mode: str, en: str, mix: str | None = None, hi: str | None = None) -> str:
    if mode == "hi":
        return hi or mix or en
    if mode == "mix":
        return mix or en
    return en
