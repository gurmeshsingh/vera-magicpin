"""The pre-registered composer bake-off.

All three architects independently proposed this experiment and fixed the
decision rule in advance, so that whoever loses cannot move the threshold
afterwards. Their three rules were close; the reconciled version is:

    measured gap < 4 points   ship the deterministic composer alone;
                              the LLM moves to authoring time and leaves
                              the runtime entirely
    gap 4 - 8 points          ship the synthesis: deterministic primary with
                              a validated LLM upgrade path
    gap > 8 points            promote the LLM composer to primary

Method:
  * the same (merchant, category, trigger) inputs to both composers
  * the same judge, the same window, scored blind to which side produced what
  * N repetitions per message, because the judge's own noise floor is
    SD 1.3 / range 3 on an identical input -- a single-run gap under 3 points
    carries no information
  * Gemini writes, Claude judges, so no model grades its own output
  * fabrication is reported separately: the deterministic side cannot
    fabricate by construction, and if the LLM buys quality with invented
    facts the rule should see that cost

Run:  PYTHONPATH=src:. python -m harness.bakeoff [n_pairs] [n_reps]
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys
from typing import Any

sys.path.insert(0, "src")

from vera.compose.engine import compose as compose_det  # noqa: E402
from vera.compose.facts import FactLedger  # noqa: E402
from vera.grounding.verify import Severity, verify  # noqa: E402

from .judge.scorer import DIMENSIONS, JudgeError, score  # noqa: E402
from .llm_composer import compose_llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "generated"
CATS = ROOT / "pkg" / "dataset" / "categories"


def load_pairs(n: int) -> list[dict[str, Any]]:
    """A spread across categories and across rich/thin merchants.

    Sampling only rich merchants would flatter both composers; sampling only
    thin ones would flatter the engine, which was built for them.
    """
    cats = {p.stem: json.loads(p.read_text()) for p in CATS.glob("*.json")}
    merchants = [json.loads(p.read_text())
                 for p in sorted(GEN.glob("merchants/*.json"))]

    def richness(m: dict) -> int:
        return (len(m.get("offers") or []) + len(m.get("signals") or [])
                + len(m.get("conversation_history") or []))

    by_cat: dict[str, list[dict]] = {}
    for m in merchants:
        by_cat.setdefault(m.get("category_slug", ""), []).append(m)

    picked: list[dict[str, Any]] = []
    slugs = sorted(by_cat)
    while len(picked) < n and slugs:
        for slug in slugs:
            if len(picked) >= n:
                break
            pool = by_cat.get(slug) or []
            if not pool:
                continue
            pool.sort(key=richness, reverse=(len(picked) % 2 == 0))
            m = pool.pop(0)
            picked.append({
                "merchant": m,
                "category": cats[m["category_slug"]],
                "trigger": {"id": f"trg_bake_{m['merchant_id']}",
                            "kind": "perf_dip", "scope": "merchant",
                            "merchant_id": m["merchant_id"], "urgency": 3,
                            "payload": {}},
            })
    return picked


def fabrications(body: str, pair: dict[str, Any]) -> int:
    ledger = FactLedger.build(pair["merchant"], pair["category"], pair["trigger"])
    return sum(1 for v in verify(body, ledger)
               if v.severity is Severity.ERROR)


def main(n_pairs: int = 8, n_reps: int = 2) -> None:
    pairs = load_pairs(n_pairs)
    print(f"bake-off: {len(pairs)} pairs x {n_reps} reps x 2 composers "
          f"= {len(pairs) * n_reps * 2} judge calls\n")

    rows: list[dict[str, Any]] = []
    for i, pair in enumerate(pairs, 1):
        name = pair["merchant"]["identity"]["name"]
        slug = pair["merchant"]["category_slug"]

        det = compose_det(pair["merchant"], pair["category"], pair["trigger"])
        llm = compose_llm(pair["merchant"], pair["category"], pair["trigger"])

        print(f"[{i}/{len(pairs)}] {name} ({slug})")
        if det is None:
            print("   DET: silent")
        if llm is None:
            print("   LLM: composer failed")

        bundle = {"category": pair["category"], "merchant": pair["merchant"],
                  "trigger": pair["trigger"], "customer": None}

        for label, msg in (("det", det), ("llm", llm)):
            if msg is None:
                continue
            action = (
                {"body": msg.body, "cta": msg.cta, "send_as": msg.send_as,
                 "suppression_key": msg.suppression_key,
                 "rationale": msg.rationale}
                if label == "det" else msg
            )
            fab = fabrications(action["body"], pair)
            totals = []
            dims: dict[str, list[int]] = {d: [] for d in DIMENSIONS}
            for _ in range(n_reps):
                try:
                    r = score(action, bundle, window="full", backend="claude")
                except JudgeError as exc:
                    print(f"   {label.upper()}: judge error {exc}")
                    continue
                totals.append(r.total)
                for d in DIMENSIONS:
                    dims[d].append(r.scores[d])
            if not totals:
                continue
            mean = statistics.mean(totals)
            rows.append({"pair": name, "side": label, "mean": mean,
                         "fab": fab,
                         "dims": {d: statistics.mean(v) for d, v in dims.items()
                                  if v}})
            print(f"   {label.upper()}: {mean:5.1f}/50  runs={totals}  "
                  f"fabrications={fab}")
            print(f"        {action['body'][:105]}")
        print()

    _report(rows, n_reps)


def _report(rows: list[dict[str, Any]], n_reps: int) -> None:
    det = [r for r in rows if r["side"] == "det"]
    llm = [r for r in rows if r["side"] == "llm"]
    paired = [(d, l) for d in det for l in llm if d["pair"] == l["pair"]]

    print("=" * 66)
    if not paired:
        print("no paired results; nothing decided")
        return

    d_mean = statistics.mean(d["mean"] for d, _ in paired)
    l_mean = statistics.mean(l["mean"] for _, l in paired)
    diffs = [l["mean"] - d["mean"] for d, l in paired]
    gap = statistics.mean(diffs)

    print(f"pairs scored          : {len(paired)}  ({n_reps} reps each)")
    print(f"deterministic mean    : {d_mean:5.2f}/50")
    print(f"LLM mean              : {l_mean:5.2f}/50")
    print(f"gap (LLM - det)       : {gap:+5.2f}")
    if len(diffs) > 1:
        sd = statistics.pstdev(diffs)
        print(f"per-pair diff sd      : {sd:5.2f}   "
              f"se of gap {sd / (len(diffs) ** 0.5):.2f}")
    print(f"LLM wins / ties / losses: "
          f"{sum(1 for x in diffs if x > 0)} / {sum(1 for x in diffs if x == 0)} "
          f"/ {sum(1 for x in diffs if x < 0)}")

    print("\nper dimension (det -> llm):")
    for dim in DIMENSIONS:
        dv = [d["dims"].get(dim) for d, _ in paired if d["dims"].get(dim)]
        lv = [l["dims"].get(dim) for _, l in paired if l["dims"].get(dim)]
        if dv and lv:
            print(f"  {dim:<24} {statistics.mean(dv):4.1f} -> "
                  f"{statistics.mean(lv):4.1f}")

    d_fab = sum(d["fab"] for d, _ in paired)
    l_fab = sum(l["fab"] for _, l in paired)
    print(f"\nungrounded claims     : det {d_fab}   llm {l_fab}")

    print("\n" + "-" * 66)
    abs_gap = abs(gap)
    if abs_gap < 4:
        verdict = ("GAP < 4 -> ship the deterministic composer alone. "
                   "The LLM leaves the runtime.")
    elif abs_gap <= 8:
        verdict = ("GAP 4-8 -> ship the synthesis: deterministic primary, "
                   "validated LLM upgrade path.")
    else:
        verdict = "GAP > 8 -> promote the LLM composer to primary."
    print(f"PRE-REGISTERED RULE: {verdict}")
    if gap < 0:
        print("(the gap favours the deterministic side)")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    main(n, reps)
