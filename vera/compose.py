"""Composer: Draft -> final message, with a guard and optional LLM polish.

Pipeline for one trigger:

    contexts -> Ctx (facts) -> playbook -> Draft -> render -> guard
                                                     |
                                    (optional) LLM polish -> guard again
                                                     |
                               polished text if it passed, else the draft

The guard is strict on what the judge punishes hardest:
  * every number must exist in the contexts (or be derived on purpose)
  * no taboo vocabulary, no URLs, no raw internal codes like ctr_below_peer
  * exactly one call-to-action, placed last
  * not identical to something already sent to this person
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .facts import Ctx, numbers_in
from .lang import merchant_mode
from .llm import LLM
from .playbooks import Draft, choose_playbook, consent_ok

_URL = re.compile(r"https?://\S+|www\.\S+")
_CODE_TOKEN = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


@dataclass
class Composed:
    body: str
    cta: str
    send_as: str
    suppression_key: str
    rationale: str
    template_name: str
    template_params: list
    family: str
    strength: float
    draft: Draft
    polished: bool = False
    skip: str = ""


# ------------------------------------------------------------------ rendering
def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def _end(s: str) -> str:
    s = s.strip()
    return s if not s or s[-1] in ".!?:" else s + "."


def render(d: Draft, ctx: Ctx) -> str:
    if d.body:  # customer drafts are written whole
        return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", d.body)).strip()
    hook = d.hook.strip()
    first = f"{ctx.salutation}, {hook}" if hook else ctx.salutation + ","
    parts = [_end(first)]
    for piece in (d.insight, d.action):
        if piece and piece.strip():
            parts.append(_end(_cap(piece.strip())))
    if d.cta:
        parts.append(d.cta.strip())
    text = " ".join(parts)
    if "\n•" in hook:  # a bulleted plan: put the call-to-action on its own line
        text = text.replace(" " + d.cta.strip(), "\n\n" + d.cta.strip()) if d.cta else text
    text = re.sub(r"\.\.+", ".", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r" *\n *", "\n", text).strip()


# ------------------------------------------------------------------ guard
def ungrounded_numbers(text: str, ctx: Ctx) -> list[float]:
    allowed = ctx.allowed_numbers
    bad = []
    for n in numbers_in(text):
        if round(n, 2) in allowed or float(round(n)) in allowed and abs(n - round(n)) < 1e-9:
            continue
        if n in (0, 1):  # "1 for Wed", "one" style ordinals are harmless
            continue
        bad.append(n)
    return bad


def guard_issues(text: str, ctx: Ctx, d: Draft, sent_before: set | None = None) -> list[str]:
    issues = []
    if not text or len(text.strip()) < 15:
        issues.append("empty")
        return issues
    if _URL.search(text):
        issues.append("url")
    low = text.lower()
    for t in ctx.taboos:
        core = re.sub(r"\(.*?\)", "", t).strip().lower()
        if core and core in low:
            issues.append(f"taboo:{core}")
    bad = ungrounded_numbers(text, ctx)
    if bad:
        issues.append("ungrounded:" + ",".join(str(b) for b in bad[:5]))
    if _CODE_TOKEN.search(text):
        issues.append("internal_code:" + _CODE_TOKEN.search(text).group())
    if len(re.findall(r"\breply\b", low)) > 1 and d.cta_type != "multi_choice_slot":
        issues.append("multiple_cta")
    if d.cta_type != "none":
        tail = re.split(r"(?<=[.!?])\s+", text.strip())[-1].lower()
        if not ("?" in tail or "reply" in tail or "yes" in tail or "likhiye" in tail or "bhej" in tail):
            issues.append("cta_not_last")
    if sent_before and text.strip() in sent_before:
        issues.append("repeat")
    if len(text) > 1100:
        issues.append("too_long")
    return issues


def repair(text: str, ctx: Ctx) -> str:
    text = _URL.sub("", text)
    for t in ctx.taboos:
        core = re.sub(r"\(.*?\)", "", t).strip()
        if core:
            text = re.sub(re.escape(core), "", text, flags=re.I)
    text = _CODE_TOKEN.sub(lambda m: m.group().replace("_", " "), text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ------------------------------------------------------------------ LLM polish
_POLISH_SYSTEM = """You edit WhatsApp messages that magicpin's assistant Vera sends to Indian business owners (or, on their behalf, to their customers).
Rewrite the DRAFT so it reads like a sharp, warm human colleague wrote it. Rules, all mandatory:
1. Keep EVERY number, price, date, percentage, name, quote and source exactly as in the draft. Add NO new numbers, facts, names, offers or claims.
2. Keep the opening salutation and the final call-to-action; the call-to-action stays the last sentence, and there is only one.
3. Keep the same language mix (English / Hinglish in Roman script). Do not translate.
4. Tone: {tone}. Category: {category}. Never use these words: {taboos}.
5. No greetings like "hope you are well", no emojis unless the draft has them, no URLs, no hashtags.
6. Similar length or shorter (max {max_words} words). Bullet lines starting with "•" must stay as bullets.
Return JSON: {{"body": "<rewritten message>"}}"""


def _polish_prompt(text: str, ctx: Ctx) -> tuple[str, str]:
    voice = ctx.category.get("voice") or {}
    tone = humanize_tone(voice.get("tone", "professional")) + (
        f", register {humanize_tone(voice.get('register', ''))}" if voice.get("register") else "")
    words = len(text.split())
    system = _POLISH_SYSTEM.format(tone=tone, category=ctx.slug, taboos=", ".join(ctx.taboos) or "none",
                                   max_words=max(25, int(words * 1.1)))
    return system, "DRAFT:\n" + text


def humanize_tone(s: str) -> str:
    return str(s).replace("_", " ")


def polish_ok(new: str, old: str, ctx: Ctx, d: Draft, sent_before: set | None) -> bool:
    if not new or not isinstance(new, str):
        return False
    old_nums = sorted(numbers_in(old))
    new_nums = sorted(numbers_in(new))
    if old_nums != new_nums:  # same numbers, no more, no fewer
        return False
    if guard_issues(new, ctx, d, sent_before):
        return False
    if not (0.55 * len(old) <= len(new) <= 1.25 * len(old)):
        return False
    first_word = old.split(",")[0].strip().split(" ")[0]
    if first_word and first_word.lower() not in new[:60].lower():
        return False
    for q in re.findall(r"\"([^\"]{6,})\"|'([^']{6,})'", old):
        quote = q[0] or q[1]
        if quote and quote not in new:
            return False
    return True


# ------------------------------------------------------------------ public API
def plan(ctx: Ctx, suppression_key: str = "") -> Composed:
    """Decide and render deterministically (fast, no network)."""
    fn, needs, how = choose_playbook(ctx)
    if needs is not None:
        if not ctx.customer:
            return _skipped("customer context missing for a customer-facing trigger", suppression_key)
        if not consent_ok(ctx, needs):
            return _skipped(f"customer consent scope {ctx.consent_scope or '[]'} does not cover this message",
                            suppression_key)
    try:
        d = fn(ctx)
    except Exception as exc:  # a playbook bug must never take the bot down
        from .playbooks import pb_generic
        d = pb_generic(ctx)
        d.reasons.append(f"playbook error fallback ({type(exc).__name__})")
    if d.skip:
        return _skipped(d.skip, suppression_key)
    if how != "known":
        d.reasons.append(f"routing: {how}")
    body = render(d, ctx)
    issues = guard_issues(body, ctx, d)
    if issues:
        body = repair(body, ctx)
        if any(i.startswith("ungrounded") for i in guard_issues(body, ctx, d)):
            # last line of defence: strip the offending sentence(s)
            body = _drop_ungrounded_sentences(body, ctx)
    return Composed(body=body, cta=d.cta_type, send_as=d.send_as, suppression_key=suppression_key,
                    rationale=rationale(d, ctx), template_name=template_name(d), template_params=template_params(d, ctx),
                    family=d.family, strength=d.strength, draft=d)


def polish(c: Composed, ctx: Ctx, llm: LLM, deadline: float | None, sent_before: set | None = None) -> Composed:
    if c.skip or llm is None:
        return c
    system, user = _polish_prompt(c.body, ctx)
    out = llm.chat_json(system, user, max_tokens=500, deadline=deadline)
    new = (out or {}).get("body") if isinstance(out, dict) else None
    if isinstance(new, str):
        new = new.strip()
        if polish_ok(new, c.body, ctx, c.draft, sent_before):
            c.body = new
            c.polished = True
    return c


def _drop_ungrounded_sentences(text: str, ctx: Ctx) -> str:
    sents = re.split(r"(?<=[.!?])\s+", text)
    keep = [s for i, s in enumerate(sents) if i == len(sents) - 1 or i == 0 or not ungrounded_numbers(s, ctx)]
    return " ".join(keep)


def _skipped(reason: str, key: str) -> Composed:
    return Composed(body="", cta="none", send_as="vera", suppression_key=key, rationale=reason,
                    template_name="", template_params=[], family="skip", strength=0, draft=Draft("skip"),
                    skip=reason)


def rationale(d: Draft, ctx: Ctx) -> str:
    why = d.reasons[0] if d.reasons else d.family
    extra = "; ".join(d.reasons[1:3])
    who = "customer " + ctx.cust_name if d.send_as == "merchant_on_behalf" else ctx.name
    mode = d.mode if d.send_as == "merchant_on_behalf" else merchant_mode(ctx.merchant, ctx.category)
    lang = {"en": "English", "mix": "Hindi-English mix", "hi": "Hindi (Roman)"}[mode]
    return (f"Why now: {why}." + (f" Decision: {extra}." if extra else "") +
            f" For {who}, in {lang}. Levers: {', '.join(d.levers[:3])}. One CTA ({d.cta_type}) as the last line.")


def template_name(d: Draft) -> str:
    return f"{'merchant' if d.send_as == 'merchant_on_behalf' else 'vera'}_{d.family}_v1"


def template_params(d: Draft, ctx: Ctx) -> list[str]:
    first = ctx.cust_name if d.send_as == "merchant_on_behalf" else ctx.salutation
    anchor = re.sub(r"\s+", " ", d.anchor or d.family)[:80]
    return [first, anchor, d.deliverable[:60] if d.deliverable else d.cta_type]
