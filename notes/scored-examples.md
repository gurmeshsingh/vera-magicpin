# Scored-Example Intelligence — magicpin Vera AI Challenge

Source files (read in full):
- `pkg/examples/case-studies.md` (338 lines)
- `pkg/examples/api-call-examples.md` (615 lines)
- `pkg/engagement-design.md` (325 lines)
- `pkg/engagement-research.md` (198 lines)

All quoted material below is verbatim from the source files unless explicitly marked as paraphrase.

---

## 1. Every scored case — full tabulation

### Case 1 — Dentists / Research Digest (merchant-facing) — 50/50

**Input**
- Category: `dentists`
- Merchant: Dr. Meera's Dental Clinic, Lajpat Nagar Delhi, CTR 2.1% (below peer 3.0%), 124 high-risk adult patients in roster
- Trigger: `research_digest` — JIDA Oct 2026 paper: 3-month fluoride recall vs 6-month, 38% caries reduction in high-risk adults
- Customer: none

**Message (verbatim)**
```
Dr. Meera, JIDA's Oct issue landed. One item relevant to your high-risk adult
patients — 2,100-patient trial showed 3-month fluoride recall cuts caries
recurrence 38% better than 6-month. Worth a look (2-min abstract). Want me
to pull it + draft a patient-ed WhatsApp you can share?  — JIDA Oct 2026 p.14
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 10

**Judge feedback (verbatim, per dimension)**
- Specificity: "Numbers + source + page reference"
- Category fit: "Clinical vocabulary, peer tone, no overclaim"
- Merchant fit: "\"your high-risk adult patients\" derived from her customer_aggregate"
- Trigger relevance: "Explicitly references the digest as the reason for messaging"
- Engagement compulsion: "Curiosity + reciprocity + clear next step"

---

### Case 2 — Dentists / Recall Reminder (customer-facing) — 49/50

**Input**
- Category: `dentists` (customer-facing voice rules: no medical claims)
- Merchant: Dr. Meera's Dental Clinic — active offer "Dental Cleaning @ ₹299", available slots Wed 5 Nov 6pm + Thu 6 Nov 5pm
- Trigger: `recall_due` — Priya's 6-month cleaning recall window opened
- Customer: Priya — lapsed_soft (5mo since last visit), prefers weekday evenings, hi-en mix

**Message (verbatim, sent as merchant_on_behalf, from Dr. Meera's WA number)**
```
Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit
— your 6-month cleaning recall is due. Apke liye 2 slots ready hain: Wed 5
Nov, 6pm ya Thu 6 Nov, 5pm. ₹299 cleaning + complimentary fluoride. Reply 1
for Wed, 2 for Thu, or tell us a time that works.
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 9

**Judge feedback (verbatim)**
- Specificity: "Real slots + real price + concrete recall window"
- Category fit: "No medical claims; warm-clinical tone"
- Merchant fit: "Real offer from catalog; merchant's actual slots"
- Trigger relevance: "Explicit 6-month recall framing"
- Engagement compulsion: "Strong but Reply 1/2 multi-choice is borderline (binary preferred); the \"or tell us a time that works\" rescues it"

---

### Case 3 — Salons / Bridal Followup (customer-facing, note: doc calls the scoped section merchant-facing header but treats it as customer-facing for variety) — 47/50

**Input**
- Category: `salons`
- Merchant: Studio11 Family Salon, Kapra Hyderabad, calls +20% w/w, retention 62%, peer-leading
- Trigger (as corrected in-doc): `bridal_followup` — Kavya, bride-to-be (wedding 2026-11-08), did Bridal Trial 5 weeks ago, in skin-prep window now. (Note: doc shows an authoring correction mid-case — the original trigger draft `active_planning_intent`/kids yoga camp was struck through as wrong-category and replaced.)
- Customer: Kavya — new state, wedding date 2026-11-08, opted in for bridal followup

**Message (verbatim, sent as merchant_on_behalf)**
```
Hi Kavya 💍 Lakshmi from Studio11 Kapra here. 196 days to your wedding — perfect
window to start the 30-day skin-prep program before serious bridal bookings
roll in. ₹2,499 covers 4 sessions + a take-home kit. Want me to block your
preferred Saturday 4pm slot for the first session next week?
```

**Scores**: Specificity 10, Category fit 9, Merchant fit 9, Trigger relevance 10, Engagement compulsion 9

**Judge feedback (verbatim)**
- Specificity: "Days-to-wedding count, program structure, price"
- Category fit: "Warm-practical tone; emojis used appropriately"
- Merchant fit: "References Lakshmi (owner first name) + Studio11 + her trial"
- Trigger relevance: "Explicitly the bridal followup window"
- Engagement compulsion: "Strong but assumes the program exists in catalog (verify in MerchantContext.offers)"

---

### Case 4 — Salons / Curious Ask (merchant-facing) — 44/50

**Input**
- Category: `salons`
- Merchant: Studio11 Family Salon, growing strongly, last Vera touch 3 days ago
- Trigger: `curious_ask_due` — weekly "what's in demand?" cadence
- Customer: none

**Message (verbatim, sent as Vera)**
```
Hi Lakshmi! Quick check — what service has been most asked-for this week
at Studio11? I'll turn the answer into a Google post + a 4-line WhatsApp
reply you can use when customers ask about pricing. Takes 5 min.
```

**Scores**: Specificity 8, Category fit 9, Merchant fit 8, Trigger relevance 10, Engagement compulsion 9

**Judge feedback (verbatim)**
- Specificity: "\"5 min\" anchor; could be sharper with a guess (\"Is it the keratin treatment?\")"
- Category fit: "Warm tone, fellow-operator register"
- Merchant fit: "Uses owner first name; could reference recent service mix"
- Trigger relevance: "This IS the curious-ask family — exactly the right shape"
- Engagement compulsion: "Asking-the-merchant lever is the strongest Cialdini hook for engaged merchants"

---

### Case 5 — Restaurants / IPL Match Day (merchant-facing) — 50/50

**Input**
- Category: `restaurants`
- Merchant: SK Pizza Junction, Sant Nagar Delhi, trial-tier subscriber, BOGO pizza Tue-Thu active
- Trigger: `ipl_match_today` — DC vs MI at Arun Jaitley Stadium, 7:30pm match today (Sat — *not* a weeknight)
- Customer: none

**Message (verbatim, sent as Vera)**
```
Quick heads-up Suresh — DC vs MI at Arun Jaitley tonight, 7:30pm. Important:
Saturday IPL matches usually shift -12% restaurant covers (people watch at
home). Skip the match-night promo today; instead push your BOGO pizza
(already active) as a delivery-only Saturday special. Want me to draft the
Swiggy banner + an Insta story? Live in 10 min.
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 10

**Judge feedback (verbatim)**
- Specificity: "Match details, percentage delta, time-bound"
- Category fit: "Operator-to-operator voice (\"covers\", \"match-night\")"
- Merchant fit: "Existing BOGO referenced; Swiggy/Insta channels appropriate"
- Trigger relevance: "Direct response to IPL trigger with informed nuance"
- Engagement compulsion: "Loss aversion (-12%) + existing-offer leverage + 10-min effort cap"
- Doc's own note: "This case is illustrative because it shows the bot **adding value beyond the trigger itself** — the trigger said \"IPL match today\"; the bot interpreted it correctly and gave a contrarian recommendation."

---

### Case 6 — Restaurants / Active Planning Intent (merchant-facing) — 49/50

**Input**
- Category: `restaurants`
- Merchant: Mylari South Indian Cafe, Indiranagar Bangalore — high-volume, weekday lunch thali doing 18 orders/day
- Trigger: `active_planning_intent` — merchant asked about a corporate-bulk thali package; explicitly said "yes good idea, what would it look like"
- Customer: none

**Message (verbatim, sent as Vera, in direct conversation)**
```
Suresh, here's a starter version — you can edit:

Mylari Corporate Thali — for offices in Indiranagar
- 10 thalis @ ₹125 each (₹25 off retail) + free delivery
- 25 thalis @ ₹115 each + 2 free filter coffees
- 50+: ₹105 each + 1 free dosa platter
- WhatsApp the day-before by 5pm; we deliver between 12:30-1pm

3 offices in Indiranagar are in your delivery radius (Embassy Tech, RMZ Eco,
Sigma Soft). Want me to draft a 3-line WhatsApp to send their facilities
managers?
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 9

**Judge feedback (verbatim)**
- Specificity: "Tier prices, radius, building names, time windows"
- Category fit: "Operator language (\"delivery radius\", \"facilities managers\")"
- Merchant fit: "Indiranagar locality + filter-coffee dosa nods to South Indian cafe identity"
- Trigger relevance: "Direct continuation of merchant's planning intent"
- Engagement compulsion: "Strong but assumes building data is in MerchantContext or fabricates — judge will check"

---

### Case 7 — Gyms / Seasonal Dip Reframe (merchant-facing) — 48/50

**Input**
- Category: `gyms`
- Merchant: PowerHouse Fitness, HSR Layout Bangalore, views -30% w/w (April seasonal drop), 245 active members
- Trigger: `seasonal_perf_dip` — expected April-June low; flagged as not-a-problem
- Customer: none

**Message (verbatim, sent as Vera)**
```
Karthik, your views are down 30% this week — but I want to flag this is the
normal April-June acquisition lull (every metro gym sees -25 to -35% in this
window). Action: skip ad spend now, save it for Sept-Oct when conversion is
2x. For now, focus retention on your 245 members. Want me to draft a "summer
attendance challenge" to keep them through the dip?
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 8

**Judge feedback (verbatim)**
- Specificity: "Percentage range, months, member count"
- Category fit: "Coach-to-operator tone; uses \"ad spend\", \"conversion\" correctly"
- Merchant fit: "His exact dip number + his member count + HSR locality (peer benchmark)"
- Trigger relevance: "Directly addresses the seasonal dip with reframe"
- Engagement compulsion: "Could be sharper — \"save it for Sept-Oct\" is a bit hand-wavy without numbers"

---

### Case 8 — Gyms / Customer Lapse Winback (customer-facing) — 50/50

**Input**
- Category: `gyms` (customer-facing voice: warm, no-shame, no guilt-trip)
- Merchant: PowerHouse Fitness — first month @ ₹499 offer active
- Trigger: `customer_lapsed_hard` — Rashmi, 57 days since last visit, previous focus was weight loss, was a 5-month member
- Customer: Rashmi

**Message (verbatim, sent as merchant_on_behalf)**
```
Hi Rashmi 👋 Karthik from PowerHouse here. It's been about 8 weeks — happens
to most members at some point, no judgment. We've added a Tue/Thu evening
HIIT class that fits weight-loss goals well (45 min, 6:30pm). Want me to
hold a free trial spot for you next Tue, 30 Apr? Reply YES — no commitment,
no auto-charge.
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 10

**Judge feedback (verbatim)**
- Specificity: "Class name, time, day, date, duration"
- Category fit: "Coach voice, no shame, evidence-based"
- Merchant fit: "Karthik (owner first name), PowerHouse, real new class"
- Trigger relevance: "Explicitly addresses lapse without being needy"
- Engagement compulsion: "\"no judgment\" + \"no commitment, no auto-charge\" removes 2 common barriers in one line"

---

### Case 9 — Pharmacies / Compliance Alert (merchant-facing) — 50/50

**Input**
- Category: `pharmacies`
- Merchant: Apollo Health Plus Pharmacy, Malviya Nagar Jaipur — engaged, has 240 chronic-Rx customers
- Trigger: `supply_alert` — voluntary recall on atorvastatin batches AT2024-1102 + AT2024-1108 by Mfr Z
- Customer: none

**Message (verbatim, sent as Vera)**
```
Ramesh, urgent: voluntary recall on 2 atorvastatin batches (AT2024-1102,
AT2024-1108) by Mfr Z — sub-potency, no safety risk, but customers should be
informed for replacement. Pulled your repeat-Rx list: 22 of your chronic-Rx
customers were dispensed these batches in last 90 days. Want me to draft
their WhatsApp note + the replacement-pickup workflow?
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 10

**Judge feedback (verbatim)**
- Specificity: "Batch numbers, manufacturer, count of affected customers"
- Category fit: "Trustworthy-precise tone; correct use of \"sub-potency\" without alarming"
- Merchant fit: "Pulls from his customer aggregate; uses his name"
- Trigger relevance: "Direct compliance action"
- Engagement compulsion: "Urgency + clear offer of complete artifact"

---

### Case 10 — Pharmacies / Chronic Refill Reminder (customer-facing) — 49/50

**Input**
- Category: `pharmacies` (customer-facing voice: trustworthy, precise, respectful of senior)
- Merchant: Apollo Health Plus Pharmacy — free home delivery >₹499, senior 15% off active
- Trigger: `chronic_refill_due` — Mr. Sharma's metformin/atorvastatin/telmisartan run out 2026-04-28
- Customer: Mr. Sharma — 65-75 age band, senior citizen, channel via son's WhatsApp, address saved, opted in

**Message (verbatim, sent as merchant_on_behalf, addressed to son)**
```
Namaste — Apollo Health Plus Malviya Nagar yahan. Sharma ji ki 3 monthly
medicines (metformin, atorvastatin, telmisartan) 28 April ko khatam hongi.
Same dose, same brand pack ready hai. Senior discount 15% applied — total
₹1,420 (₹240 saved). Free home delivery to saved address by 5pm tomorrow.
Reply CONFIRM to dispatch, or call 9876543210 if any change in dosage.
```

**Scores**: Specificity 10, Category fit 10, Merchant fit 10, Trigger relevance 10, Engagement compulsion 9

**Judge feedback (verbatim)**
- Specificity: "Three molecule names, exact date, total + savings, time window"
- Category fit: "Trustworthy-precise voice; namaste salutation appropriate"
- Merchant fit: "Apollo's actual offers (free delivery, senior 15%); Malviya Nagar locality"
- Trigger relevance: "Refill due date is the central anchor"
- Engagement compulsion: "Strong; could nudge with \"stocks may take 24h\" if scarcity were real"

---

## 2. Score-delta analysis: high scorers vs. low scorers

Scores range 44–50/50 (all cases are near-ceiling "north star" examples — there is no genuinely bad case in this file; the deltas below are extracted from the *relative* gaps the judge calls out, since the package doesn't include a scored ≤5 example). The lowest of the 10 (Case 4, 44/50, and Case 3, 47/50) are the closest thing to "low scorers" here; contrast against the four perfect 50/50s (Cases 1, 5, 8, 9).

**Message length**
- All 10 messages are short — roughly 35–75 words, 2–5 sentences. Case 6 (49/50) is the longest because it's a drafted artifact (tiered price list), and it still scores 9-10 across dimensions — length is not penalized when every line adds a concrete fact. Case 4 (44/50, the lowest score) is also short but its content density is lower (see numbers below), suggesting length isn't the driver — density is.

**Numbers/dates/offer names — the strongest quantitative signal**
- 50/50 and 49/50 cases each contain 3+ hard facts: Case 1 (2,100-patient / 38% / p.14), Case 5 (7:30pm / -12% / 10-min), Case 8 (45 min / 6:30pm / 30 Apr), Case 9 (2 batch numbers / 22 of 240 / 90 days), Case 10 (3 molecule names / exact date / ₹1,420 / ₹240 saved), Case 2 (2 slots / ₹299), Case 6 (3 pricing tiers / 3 building names / delivery windows).
- Case 4 (44/50, the worst score) contains only one soft anchor — "5 min" — and the judge explicitly penalizes this under Specificity (8/10): "could be sharper with a guess (\"Is it the keratin treatment?\")." This is the cleanest number-density-to-score correlation in the set: **the lowest-scored case is also the case with the fewest concrete numbers.**
- Cross-case pattern doc states directly: "Numbers from the contexts, not invented" and warns "Numbers without provenance get scored as fabrication" (line 316) — i.e., quantity alone isn't enough; every number must be traceable to a context field (`customer_aggregate`, `MerchantContext.performance`, etc.).

**CTA phrasing**
- Highest scorers use a single, low-friction, ideally binary ask: "Reply YES — no commitment, no auto-charge" (Case 8, 10/10 compulsion), "Want me to draft the Swiggy banner + an Insta story? Live in 10 min." (Case 5, 10/10).
- Case 2 loses exactly 1 point on Engagement compulsion specifically because of CTA phrasing: "Reply 1 for Wed, 2 for Thu" is flagged as "borderline (binary preferred)" — multi-choice numbered replies are a soft penalty vs. strict binary.
- Cross-case doc rule #4: "Single most important next step framed as low-friction commitment... Multi-action asks dilute" (line 318).
- Case 7's compulsion score (8/10, the single lowest compulsion score across all 10 cases) is explicitly because the recommended action lacks a number: "'save it for Sept-Oct' is a bit hand-wavy without numbers" — i.e., even the CTA/action language needs quantification, not just the setup.

**Opening line style**
- Every perfect/near-perfect case opens with the merchant's or customer's first name directly, with zero greeting-word throat-clearing: "Dr. Meera, JIDA's..." / "Quick heads-up Suresh —" / "Karthik, your views..." / "Ramesh, urgent:..." / "Hi Rashmi 👋 Karthik from PowerHouse here." / "Hi Priya, Dr. Meera's clinic here 🦷"
- Cross-case rule #3 (line 317): "Owner/merchant first name when present ... Generic 'Hi' loses 1 point on merchant fit." Case 4 opens with "Hi Lakshmi!" (a generic-feeling greeting, though it does include the name) and scores merchant-fit 8/10 — the lowest merchant-fit score in the set — with the explicit note "could reference recent service mix," meaning the greeting alone doesn't pull enough merchant-specific data forward.

**Use of the merchant's own data / personalization depth**
- Top scorers pull a computed or roster-derived number specific to that merchant: "your high-risk adult patients" (from `customer_aggregate`), "22 of your chronic-Rx customers" (computed: subset of 240), "245 active members," "196 days to your wedding" (computed from wedding date), "18 orders/day" implied via corporate tier design.
- Case 4 and Case 3 are the two sub-49 cases, and both carry an explicit judge caveat about unverified/assumed data: Case 3 — "assumes the program exists in catalog (verify in MerchantContext.offers)"; Case 6's near-perfect score (49/50) still docks a point for the same reason: "assumes building data is in MerchantContext or fabricates — judge will check." **Pattern: any claim of merchant-specific fact whose provenance the judge cannot verify against a context field caps engagement-compulsion at 9, never 10, even when everything else is excellent.**

**Formatting (emoji, line breaks, greeting)**
- Emoji used only in customer-facing, warm-register cases, and sparingly (max one per message): 🦷 (Case 2), 💍 (Case 3), 👋 (Case 8). Merchant-facing operator-tone cases (Cases 1, 5, 6, 7, 9) use zero emoji.
- Line breaks / structured lists appear only when the content is itself a structured artifact being drafted (Case 6's tiered price list uses `-` bullets and bold-free line breaks). Every other case is a single flowing paragraph, 2-5 sentences, no line breaks.
- Bold markdown (`**Wed 5 Nov, 6pm**`) appears in the *API example* version of the recall message (api-call-examples.md, Example 2.9) but not in the case-study body text of Case 2 — suggesting bold-highlighting of slot times is an acceptable but not scored-as-necessary enhancement.

**Language/register matching (customer-facing only)**
- Hindi-English code-mixing matched to the customer's actual stated preference: "Apke liye 2 slots ready hain" (Priya, hi-en mix). Full Hindi-first register for a senior-citizen-via-son channel: "Namaste — Apollo Health Plus Malviya Nagar yahan... Sharma ji ki 3 monthly medicines... khatam hongi." Cross-case rule #5 (line 319): "Customer-facing messages honor language preference + relationship state ... Treating every customer the same loses 2 points on customer fit" — the single largest named point-penalty in the cross-case list.

**Domain vocabulary**
- Rule #6 (line 320): "Domain-specific vocabulary used correctly — 'covers', 'AOV', 'sub-potency', 'fluoride varnish', 'ad spend', 'conversion'. Wrong vocabulary or absent vocabulary signals the bot didn't actually use the CategoryContext.voice."

**The single highest-signal differentiator called out in the doc**
- Rule #7 (line 321): "The bot adds judgment, not just templating" — Case 5 (the IPL case, 50/50) is held up as the exemplar: the bot was told "IPL match today" and independently concluded the merchant should *skip* the expected promo because Saturday matches suppress dine-out. This contrarian, data-informed override is called "the highest signal of category understanding" — i.e., pure trigger-echoing (templating the trigger back into prose) is explicitly a lower tier of performance than a message that reasons past the trigger using merchant+category data.

**Quantitative summary**

| Metric | 50/50 cases (1,5,8,9) | Sub-48 cases (3,4,7) |
|---|---|---|
| Concrete numbers/dates/names per message | 3–5 each | 1 (#4: "5 min" only); #7 has 3 numbers but its *action* clause is unquantified; #3 has numbers but an unverified catalog claim |
| First-name-direct opening | Yes, all 4 | Yes, but #4's is judged as still too generic in overall merchant-fit |
| CTA form | Single binary or fully open-ended with capped effort ("10 min", "no commitment") | #7's CTA is a question (fine) but the *preceding recommendation* is qualitative not quantitative |
| Provenance-checkable merchant fact | Always (customer_aggregate/performance fields) | #3 and #6 flagged as assumed/unverified — this is the specific 1-point tax |

---

## 3. Named failure modes (quoted verbatim, with source case/section)

From the case studies and cross-case section:

1. **Missing source citation on research/compliance claims** — "Source citation when claiming research/compliance — JIDA p.14, DCI circular, batch numbers. **No citation = score capped at 7.**" (Cross-case pattern #1, line 315)
2. **Fabricated or unprovenanced numbers** — "Numbers from the contexts, not invented ... Numbers without provenance get scored as fabrication." (Cross-case pattern #2, line 316)
3. **Generic greeting instead of owner/merchant first name** — "Generic 'Hi' loses 1 point on merchant fit." (Cross-case pattern #3, line 317)
4. **Multi-action / diluted CTA** — "Multi-action asks dilute." (Cross-case pattern #4, line 318)
5. **Numbered multi-choice CTA treated as suboptimal vs. binary** — Case 2 judge note: "Strong but Reply 1/2 multi-choice is borderline (binary preferred); the 'or tell us a time that works' rescues it." (Case 2)
6. **Treating every customer identically regardless of language/relationship state** — "Treating every customer the same loses 2 points on customer fit." (Cross-case pattern #5, line 319)
7. **Wrong or absent domain vocabulary** — "Wrong vocabulary or absent vocabulary signals the bot didn't actually use the CategoryContext.voice." (Cross-case pattern #6, line 320)
8. **Unverified/fabricated merchant-specific facts (catalog or third-party data)** — Case 3: "assumes the program exists in catalog (verify in MerchantContext.offers)"; Case 6: "assumes building data is in MerchantContext or fabricates — judge will check."
9. **Hand-wavy action without numbers** — Case 7: "'save it for Sept-Oct' is a bit hand-wavy without numbers." (Case 7, engagement compulsion note)
10. **Rationale/message mismatch** — "The rationale field is concise and reflects actual reasoning — judge cross-checks rationale against the message; mismatch = penalty." (Cross-case pattern #9, line 323)
11. **Repetition or fabrication as an operational floor violation** — "No repetition, no fabrication — these are the operational floor. Any of them in the message and the case is capped at 5/dimension regardless of quality." (Cross-case pattern #10, line 324)
12. **Direct copying of case-study body text** — "direct copying the body text of a case study counts as plagiarism — the judge runs a similarity check on submissions vs the case studies and penalizes near-duplicates." (closing section)
13. **Ignoring an explicit intent transition (from api-call-examples.md, Example 4.2)** — bad response continues qualifying after merchant said "Ok, let's do it. What's next?": `"rationale": "Continuing qualification..."  // ← penalty: ignored explicit intent transition"`
14. **Malformed / missing required fields in API response** — "Missing required fields (`conversation_id`, `send_as`, `trigger_id`, `cta`, `suppression_key`, `rationale`) → action scored as 0, -2 penalty." (Example F.2)
15. **URL in message body** — "Hard fail for that action — Meta would reject. Penalty: -3 per URL." (Example F.4)
16. **Repeated identical body in same conversation** — "Same `body` text sent twice in the same `conversation_id` → -2 anti-repetition penalty per repeat." (Example F.5)
17. **Not detecting auto-reply / continuing to push after canned response** — implicit failure mode contrasted against the "good bot" backoff behavior in Examples 2.5 and 4.1 (bot must detect canned "Thank you for contacting..." text and back off, not treat it as real engagement).
18. **Continuing to message after explicit opt-out/hostility** — contrasted against "good" graceful-exit behavior in Examples 2.6 and 4.3; the bad-path implication is any further send after "Stop messaging me" / hostile turns.

---

## 4. Worked API examples (verbatim JSON/HTTP, canonical per endpoint)

### `GET /v1/healthz` (pre-warmup)
```http
GET /v1/healthz HTTP/1.1
Host: bot.candidate-team-alpha.example.com
Accept: application/json
```
```json
{
  "status": "ok",
  "uptime_seconds": 124,
  "contexts_loaded": { "category": 0, "merchant": 0, "customer": 0, "trigger": 0 }
}
```

### `GET /v1/healthz` (post-warmup)
```json
{
  "status": "ok",
  "uptime_seconds": 1024,
  "contexts_loaded": { "category": 5, "merchant": 50, "customer": 200, "trigger": 0 }
}
```
"If counts don't match what the judge pushed, warmup fails and the bot is disqualified for that test slot."

### `GET /v1/metadata`
```json
{
  "team_name": "Team Alpha",
  "team_members": ["Alice", "Bob"],
  "model": "claude-opus-4-7",
  "approach": "single-prompt composer with retrieval over digest items + dispatch by trigger.kind",
  "contact_email": "team@example.com",
  "version": "1.2.0",
  "submitted_at": "2026-04-26T08:00:00Z"
}
```

### `POST /v1/context` — push CategoryContext
```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 1,
  "delivered_at": "2026-04-26T09:45:00Z",
  "payload": {
    "slug": "dentists",
    "voice": { "tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe"] },
    "offer_catalog": [
      { "id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299", "audience": "new_user", "type": "service_at_price" }
    ],
    "peer_stats": { "avg_rating": 4.4, "avg_ctr": 0.030 },
    "digest": [{ "id": "d_2026W17_jida_fluoride", "kind": "research", "title": "3-month fluoride recall cuts caries 38% better", "source": "JIDA Oct 2026, p.14" }],
    "patient_content_library": [],
    "seasonal_beats": [{ "month_range": "Nov-Feb", "note": "exam-stress bruxism spike" }],
    "trend_signals": [{ "query": "clear aligners delhi", "delta_yoy": 0.62 }]
  }
}
```
Response:
```json
{ "accepted": true, "ack_id": "ack_dentists_v1", "stored_at": "2026-04-26T09:45:00.123Z" }
```
Note: "For the actual test the full category JSON (`dataset/categories/dentists.json`) goes in `payload`, not the abbreviated form above."

### `POST /v1/context` — push MerchantContext
```json
{
  "scope": "merchant",
  "context_id": "m_001_drmeera_dentist_delhi",
  "version": 1,
  "delivered_at": "2026-04-26T09:45:30Z",
  "payload": {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": { "name": "Dr. Meera's Dental Clinic", "city": "Delhi", "locality": "Lajpat Nagar",
                  "verified": true, "languages": ["en", "hi"], "owner_first_name": "Meera" },
    "subscription": { "status": "active", "plan": "Pro", "days_remaining": 82 },
    "performance": { "window_days": 30, "views": 2410, "calls": 18, "directions": 45,
                     "ctr": 0.021, "delta_7d": { "views_pct": 0.18, "calls_pct": -0.05 } },
    "offers": [{ "id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active" }],
    "conversation_history": [],
    "customer_aggregate": { "total_unique_ytd": 540, "lapsed_180d_plus": 78,
                            "retention_6mo_pct": 0.38, "high_risk_adult_count": 124 },
    "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort"]
  }
}
```
Response:
```json
{ "accepted": true, "ack_id": "ack_m_001_drmeera_v1", "stored_at": "2026-04-26T09:45:30.456Z" }
```

### `POST /v1/context` — idempotency check (same version re-pushed)
Response (409):
```json
{ "accepted": false, "reason": "stale_version", "current_version": 1 }
```

### `POST /v1/context` — version bump
Request: same as MerchantContext push but `version: 2`, `performance.views: 2580`.
Response:
```json
{ "accepted": true, "ack_id": "ack_m_001_drmeera_v2", "stored_at": "2026-04-26T10:30:00.789Z" }
```

### `POST /v1/context` — trigger push (research digest)
```json
{
  "scope": "trigger",
  "context_id": "trg_001_research_digest_dentists",
  "version": 1,
  "delivered_at": "2026-04-26T10:32:00Z",
  "payload": {
    "id": "trg_001_research_digest_dentists",
    "scope": "merchant",
    "kind": "research_digest",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "category": "dentists",
      "top_item_id": "d_2026W17_jida_fluoride"
    },
    "urgency": 2,
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2026-05-03T00:00:00Z"
  }
}
```
Response:
```json
{ "accepted": true, "ack_id": "ack_trg_001_v1", "stored_at": "2026-04-26T10:32:00.150Z" }
```

### `POST /v1/tick` — bot decides to send
Request:
```json
{
  "now": "2026-04-26T10:35:00Z",
  "available_triggers": ["trg_001_research_digest_dentists"]
}
```
Response:
```json
{
  "actions": [
    {
      "conversation_id": "conv_m_001_drmeera_research_W17",
      "merchant_id": "m_001_drmeera_dentist_delhi",
      "customer_id": null,
      "send_as": "vera",
      "trigger_id": "trg_001_research_digest_dentists",
      "template_name": "vera_research_digest_v1",
      "template_params": [
        "Dr. Meera",
        "JIDA Oct issue landed. One item relevant to your high-risk adult patients — 2,100-patient trial showed 3-month fluoride recall cuts caries recurrence 38% better than 6-month",
        "Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share?"
      ],
      "body": "Dr. Meera, JIDA's Oct issue landed. One item relevant to your high-risk adult patients — 2,100-patient trial showed 3-month fluoride recall cuts caries recurrence 38% better than 6-month. Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share? — JIDA Oct 2026 p.14",
      "cta": "open_ended",
      "suppression_key": "research:dentists:2026-W17",
      "rationale": "External research digest with merchant-relevant clinical anchor (high-risk-adult cohort matches signal). Source citation at end maintains credibility. Open-ended CTA invites continuation without forcing a binary choice."
    }
  ]
}
```

### `POST /v1/tick` — bot decides NOT to send
```json
{ "actions": [] }
```
"Empty `actions` is valid. Restraint is rewarded; spam is penalized."

### `POST /v1/reply` — merchant engaged response
Request:
```json
{
  "conversation_id": "conv_m_001_drmeera_research_W17",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Yes please send the abstract. Also draft the patient WhatsApp.",
  "received_at": "2026-04-26T10:42:00Z",
  "turn_number": 2
}
```
Response:
```json
{
  "action": "send",
  "body": "Sending the abstract now (PDF, 2 pages). Patient-ed draft below — you can copy-paste or I'll schedule a Google post:\n\n\"3-month vs 6-month dental cleaning — does it really matter? New research shows yes, especially if you've had cavities recently. Drop us a note for a quick check.\"\n\nWant me to schedule the post for tomorrow 10am?",
  "cta": "binary_yes_no",
  "rationale": "Honoring both asks (abstract + draft) in one turn. Draft is at patient-reading level. Final question is a binary yes/no to lower friction."
}
```

### `POST /v1/reply` — merchant auto-reply (bot must back off)
Request:
```json
{
  "conversation_id": "conv_m_001_drmeera_research_W17",
  "from_role": "merchant",
  "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
  "received_at": "2026-04-26T10:42:00Z",
  "turn_number": 2
}
```
Response:
```json
{
  "action": "wait",
  "wait_seconds": 14400,
  "rationale": "Detected merchant auto-reply (canned 'Thank you for contacting' phrasing). Backing off 4 hours to wait for owner."
}
```

### `POST /v1/reply` — merchant hard "no"
Request:
```json
{
  "conversation_id": "conv_m_001_drmeera_research_W17",
  "from_role": "merchant",
  "message": "Not interested. Stop messaging me.",
  "received_at": "2026-04-26T10:42:00Z",
  "turn_number": 2
}
```
Response:
```json
{
  "action": "end",
  "rationale": "Merchant explicitly opted out. Closing conversation; suppressing this conversation_id for future ticks."
}
```
"The bot must not send any further messages on this `conversation_id`."

### `POST /v1/reply` — curveball off-topic ask
Request:
```json
{
  "conversation_id": "conv_m_001_drmeera_research_W17",
  "from_role": "merchant",
  "message": "Btw can you also help me with my GST filing this month?",
  "received_at": "2026-04-26T10:42:00Z",
  "turn_number": 2
}
```
Response:
```json
{
  "action": "send",
  "body": "I'll have to leave GST filing to your CA — that's outside what I can help with directly. Coming back to the JIDA piece — want me to draft the patient post first, or send the abstract?",
  "cta": "open_ended",
  "rationale": "Out-of-scope ask politely declined; redirects back to the original trigger without losing thread."
}
```

### `POST /v1/context` — mid-test adaptive injection (category v2)
```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 2,
  "delivered_at": "2026-04-26T10:50:00Z",
  "payload": {
    "slug": "dentists",
    "voice": { "tone": "peer_clinical" },
    "digest": [
      { "id": "d_2026W17_jida_fluoride", "kind": "research", "title": "3-month fluoride recall cuts caries 38% better", "source": "JIDA Oct 2026, p.14" },
      { "id": "d_2026W17_dci_radiograph_NEW", "kind": "compliance", "title": "DCI revised radiograph dose limits effective 2026-12-15",
        "source": "DCI circular 2026-11-04", "summary": "Max dose drops 1.5→1.0 mSv per IOPA. E-speed film passes; D-speed does not." }
    ],
    "// other fields": "..."
  }
}
```
Response:
```json
{ "accepted": true, "ack_id": "ack_dentists_v2", "stored_at": "2026-04-26T10:50:00.110Z" }
```
"The bot must replace the old version atomically and use the new digest item if relevant in the next send."

### `POST /v1/tick` — customer-scoped trigger (recall_due)
Context pushes:
```json
{ "scope": "customer", "context_id": "c_001_priya_for_m001", "version": 1, "payload": { "...": "Priya's CustomerContext from dataset/customers_seed.json" } }
```
```json
{ "scope": "trigger", "context_id": "trg_003_recall_due_priya", "version": 1, "payload": { "...": "the recall trigger from dataset/triggers_seed.json" } }
```
Tick request:
```json
{
  "now": "2026-04-26T11:00:00Z",
  "available_triggers": ["trg_003_recall_due_priya"]
}
```
Response:
```json
{
  "actions": [
    {
      "conversation_id": "conv_priya_recall_2026_11",
      "merchant_id": "m_001_drmeera_dentist_delhi",
      "customer_id": "c_001_priya_for_m001",
      "send_as": "merchant_on_behalf",
      "trigger_id": "trg_003_recall_due_priya",
      "template_name": "merchant_recall_reminder_v1",
      "template_params": [
        "Priya",
        "Dr. Meera's clinic",
        "It's been 5 months since your last visit",
        "Wed 5 Nov, 6pm or Thu 6 Nov, 5pm",
        "₹299 cleaning + complimentary fluoride"
      ],
      "body": "Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is due. Apke liye 2 slots ready hain: **Wed 5 Nov, 6pm** ya **Thu 6 Nov, 5pm**. ₹299 cleaning + complimentary fluoride. Reply 1 for Wed, 2 for Thu, or tell us a time that works.",
      "cta": "multi_choice_slot",
      "suppression_key": "recall:c_001_priya_for_m001:6mo",
      "rationale": "Customer-scoped recall, sending via merchant's number (send_as=merchant_on_behalf). Honoring Priya's hi-en mix language pref + weekday-evening preference (both slots offered are weekday evenings). Multi-choice slot CTA is appropriate for booking flows."
    }
  ]
}
```

### Phase 4 replay scenario — auto-reply hell (4 turns)
Turn 1: `POST /v1/tick { "now": "...", "available_triggers": ["trg_022_cde_webinar_dentists"] }` → `{ "actions": [{ "/* CDE webinar invite */": "" }] }`

Turn 2 (auto-reply): request `{ "from_role": "merchant", "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.", "turn_number": 2 }`
Good response:
```json
{ "action": "send",
  "body": "Looks like an auto-reply 😊 When the owner sees this, just reply 'Yes' for the webinar invite.",
  "cta": "binary_yes_no",
  "rationale": "Detected auto-reply; one explicit prompt to flag it for the owner." }
```

Turn 3 (same auto-reply again):
```json
{ "action": "wait", "wait_seconds": 86400,
  "rationale": "Same auto-reply twice in a row → owner not at phone. Wait 24h before retry." }
```

Turn 4 (same auto-reply yet again):
```json
{ "action": "end",
  "rationale": "Auto-reply 3x in a row, no real reply. Conversation has zero engagement signal; closing." }
```

### Phase 4 replay scenario — intent transition
Turn 3 request: `{ "from_role": "merchant", "message": "Ok, let's do it. What's next?", "turn_number": 3 }`

Good response:
```json
{ "action": "send",
  "body": "Great. Drafting your patient WhatsApp now — 90 seconds. I'll also pre-fill the GBP post for tomorrow 10am. Reply CONFIRM to send the WhatsApp draft to your patient list (40 high-risk adult patients).",
  "cta": "binary_confirm_cancel",
  "rationale": "Merchant explicitly committed; switching from question-asking to action-execution. Concrete next step + measurable scope (40 patients)." }
```

Bad response (loses points):
```json
{ "action": "send",
  "body": "Excellent! Just to plan well — would you say most of your high-risk patients are diabetic, or is there another common factor?",
  "rationale": "Continuing qualification..."  // ← penalty: ignored explicit intent transition
}
```

### Phase 4 replay scenario — hostile/off-topic
Turn 2 request: `{ "from_role": "merchant", "message": "Why are you bothering me. This is useless. Stop sending these.", "turn_number": 2 }`

Good response (graceful exit):
```json
{ "action": "end",
  "rationale": "Merchant frustration explicit; closing without further engagement. Suppressing all triggers for this merchant for 30 days." }
```

Acceptable alternative (short apology + exit):
```json
{ "action": "send",
  "body": "Apologies — I won't message again. If anything changes, you can always restart with 'Hi Vera'. 🙏",
  "cta": "none",
  "rationale": "One-line acknowledgment + opt-out path; conversation will close after this send." }
```

### Failure-mode examples (verbatim)
- F.1 Timeout: "If `/v1/tick` doesn't respond within 30s, the judge logs a timeout and continues. No retries."
- F.2 Malformed response:
```json
{ "actions": [{ "merchant_id": "m_001", "body": "..." }] }
```
"Missing required fields (`conversation_id`, `send_as`, `trigger_id`, `cta`, `suppression_key`, `rationale`) → action scored as 0, -2 penalty."
- F.3 Body too long: "No hard body-length cap. Messages are judged on quality, specificity, and relevance."
- F.4 URL in body:
```json
{ "body": "Read more: https://magicpin.com/blog" }
```
"Hard fail for that action — Meta would reject. Penalty: -3 per URL."
- F.5 Repetition: "Same `body` text sent twice in the same `conversation_id` → -2 anti-repetition penalty per repeat."

### Endpoint summary table (verbatim)
| Endpoint | Method | Body | Latency budget | Retried? |
|---|---|---|---|---|
| `/v1/healthz` | GET | none | 2 s | yes (×3) |
| `/v1/metadata` | GET | none | 2 s | no |
| `/v1/context` | POST | full payload | 5 s | no |
| `/v1/tick` | POST | `{now, available_triggers}` | 10 s | no |
| `/v1/reply` | POST | reply turn | 10 s | no |

---

## 5. Engagement doctrine (from engagement-design.md and engagement-research.md)

### Core theory: the 4-context composition framework
Every message = `compose(category, merchant, trigger, customer?)`. The four inputs:

| Context | Question it answers | Refresh cadence | Shared across |
|---|---|---|---|
| Category | "How do we talk to *this type* of business? What do they know, care about, offer, get regulated on?" | Weekly (digest), monthly (voice/catalog) | All merchants in the vertical |
| Merchant | "Who is this specific business, how are they doing, what's in their history with us?" | Daily (perf), real-time (conversation) | Just this merchant |
| Trigger | "Why am I messaging *right now*? What specific event prompts this?" | Per-event | This one send |
| Customer | "Who is the merchant's customer, and what's their state with this merchant?" | Per-visit / per-interaction | Just this customer |

Same composer drives both merchant-facing and customer-facing (`merchant_on_behalf`) sends — "Build once, ship twice."

### Cadence / frequency doctrine
Stated business problem: "Functional nudges are inherently low-frequency. A merchant only has a handful of 'broken things' or 'events' per month. To engage them 3-5×/week, we need a framework that supports curiosity-driven, knowledge-driven, and customer-driven conversations — not just 'fix-this' reminders." **This is an implicit scoring signal**: bots that only fire on hard "broken thing" events will under-engage relative to what the design intends; curiosity/knowledge loops (e.g., `curious_ask_due`, `research_digest`) are treated as first-class, not filler.

### Offer design doctrine
"Prefer 'Dental Cleaning @ ₹299' over 'Flat 20% OFF'. Service+price is more compelling than discount." — Implicit scoring criterion: named service-at-price offers should be favored over generic percentage-discount framing.

### Voice doctrine (category-specific)
"For dentists: technical terms welcome ('fluoride varnish at 3-month recall'), legal taboos ('cure', 'guaranteed'), peer tone not hype." CategoryContext carries an explicit `vocab_taboo` list (e.g. `["guaranteed", "100% safe"]` in the API example) — using a taboo word should be treated as a hard category-fit violation.

### Timing / seasonality doctrine
`seasonal_beats` field exists specifically to "cue category-specific timing" (e.g., "exam-stress bruxism spikes Nov-Feb" for dentists). Trend_signals (Google Trends/Practo-style) surface what customers are currently searching. Together these argue that a top message should reflect *current* seasonal/trend context, not generic evergreen copy — mirrored directly in Case 5 (IPL) and Case 7 (seasonal dip).

### Trigger typology
Two families: **External** (news, weather, festival, regulation change, competitor-opens, category-trend movement, weekly research digest) and **Internal** (performance dip/spike, milestone, dormancy threshold, customer lapse threshold, appointment due, review pattern, scheduled-recurring nudge). Each trigger carries `urgency` (1-5, ranks against other queued triggers) and a `suppression_key` (Redis dedup) plus `expires_at` (staleness). This maps directly onto the "restraint is rewarded; spam is penalized" doctrine in the API examples — the composer is expected to prioritize by urgency and suppress duplicates, not fire on everything available.

### Suppression / dedup doctrine
`suppression_key` is used "to prevent re-sends" — seen operationally in the API examples as `"research:dentists:2026-W17"` (category+week-scoped) and `"recall:c_001_priya_for_m001:6mo"` (customer+cycle-scoped). Good keys are legible and reflect the natural recurrence period of the underlying trigger (weekly digest → week-scoped key; 6-month recall → 6mo-scoped key). This is echoed by cross-case pattern #8 in case-studies.md: "The `conversation_id` is meaningful — `conv_priya_recall_2026_11` is good (decodable, resumable). `conv_001` is acceptable. UUIDs without context lose nothing but help nothing."

### send_as / attribution doctrine
`send_as: "vera"` for merchant-facing; `send_as: "merchant_on_behalf"` for customer-facing (sent from the merchant's own WhatsApp number/identity). engagement-research.md's open question #3 flags this as unresolved in production: "Does the patient see 'Dr. Meera's clinic' or 'Vera on behalf of Dr. Meera's clinic'? Trust + legal implications either way. Probably category-dependent (regulated verticals need clearer attribution)." — implies attribution correctness (using the right `send_as` per scope) is itself a scoring dimension baked into merchant/trigger relevance and category fit.

### CTA design doctrine
Design doc doesn't state CTA rules explicitly beyond the `cta` field existing (`binary_yes_no`, `open_ended`, `multi_choice_slot`, `binary_confirm_cancel`, `none`), but the case studies (see Section 2 above) make clear binary/low-friction is preferred, and the API examples show CTA types are scoped to the send's purpose (booking flows get `multi_choice_slot`, action-commitments get `binary_confirm_cancel`, conversational continuations get `open_ended`).

### Channel norms — WhatsApp / Kaleyra templates
`template_params` fill "an approved Kaleyra template (used only for the first touch in a session window)" — implying the composer must produce both a free-form `body` and structured `template_params` because WhatsApp Business API requires an approved template for the first message outside a 24h session window, then allows free-form within the window. This is an Indian-market WhatsApp Business API constraint baked directly into the schema (see `template_registry.py` reference in the appendix: "will continue to host the Kaleyra-approved template names (used for the first-touch send before the 24h session window opens)").

### Indian-market specifics
- Code-mixed Hindi-English ("Apke liye 2 slots ready hain") matched to a customer's stated language preference.
- "Namaste" salutation for a senior-citizen-adjacent, respectful register (Case 10).
- ₹ currency throughout, no USD.
- IPL cricket as a merchant-relevant external event category (Case 5) — sports-calendar awareness is a first-class external trigger source.
- Festival/weather/monsoon/heatwave/fuel-price triggers listed as an already-built news/weather scanner source (`agents/vera/followup/event_sources.py`).

### Consent / regulatory doctrine (open question, but load-bearing for scoring)
"Consent architecture. Can Vera message a patient directly, or must every outbound require merchant approval before send? Recommendation: templated auto-sends with merchant override available, switching to fully-auto after the merchant has approved N consecutive sends." — Every customer-facing case in the case studies explicitly states the customer "opted in" (Priya, Kavya, Rashmi, Mr. Sharma) — implying consent-gating is a background requirement the composer should never violate even though it isn't a named scoring dimension per se; it undergirds trigger-relevance/merchant-fit legitimacy.

### Rationale/audit doctrine
"The composer prompt is the single point of failure. It must be: Versioned ... A/B-testable ... Auditable (we can replay any past message and see all 4 input contexts)." Every API action includes a `rationale` field, and case-studies.md cross-case pattern #9 states the judge "cross-checks rationale against the message; mismatch = penalty" — rationale is a first-class graded artifact, not a throwaway log line.

### Implicit scoring criteria flagged in the design docs (not explicit in case-studies.md but consistent with it)
- Favor named service+price offers over blanket discounts.
- Never use a `vocab_taboo` word.
- Reflect current `seasonal_beats`/`trend_signals` when relevant instead of generic timing.
- Respect `urgency` ranking — don't fire low-urgency triggers over high-urgency ones, and don't fire when nothing meets the bar (`{"actions": []}` is a valid, rewarded output).
- Use meaningful, legible `suppression_key` / `conversation_id` values.
- Match `send_as` to scope correctly and correctly attribute the sender identity in the message body itself.

---

## 6. Distilled message spec — checklist to plausibly score 9+/10 per dimension

Each item cites the case or doctrine section it's derived from.

**A. Specificity (target: 10/10)**
1. Include at least 2–3 concrete numbers, dates, or names that are directly traceable to a context field (not invented). [Cases 1, 5, 8, 9, 10; cross-case rule #2, line 316]
2. If citing external research/compliance, name the source and a locatable reference (journal + date + page, or circular number). Absence caps the whole case at 7. [Case 1; cross-case rule #1, line 315]
3. Prefer a computed/derived number over a raw one when possible (e.g., "22 of your 240" rather than just "240") — shows the bot did work, not just recall. [Case 9]
4. Avoid vague effort/time anchors ("takes a while") in favor of exact ones ("5 min", "10 min", "90 seconds"). [Cases 4, 5, F.2 intent-transition example]

**B. Category fit (target: 10/10)**
5. Use at least one piece of correct domain vocabulary from `CategoryContext.voice` (e.g., "covers", "ad spend", "sub-potency", "fluoride varnish", "delivery radius", "facilities managers"). [Cross-case rule #6, line 320; engagement-design.md voice doctrine]
6. Never use a word on `vocab_taboo` (e.g., "guaranteed", "100% safe", "cure"). [engagement-design.md]
7. Match register to scope: operator-to-operator/peer tone for merchant-facing; warm/no-shame/no-guilt for customer-facing lapse messages; trustworthy-precise + respectful-of-senior for pharmacy-to-elder. [Cases 1,5,6,7,9 vs 2,8,10]
8. Use emoji sparingly and only in warm customer-facing registers (max 1–2); zero emoji in operator-tone merchant-facing sends. [Cases 2,3,8 vs 1,5,6,7,9]

**C. Merchant/customer fit (target: 10/10)**
9. Open with the owner's or customer's first name directly (not a generic "Hi") — generic greeting costs 1 point. [Cross-case rule #3, line 317; Case 4's 8/10 merchant-fit]
10. Every merchant-specific claim (offer, building name, catalog item, price) must be verifiable against `MerchantContext.offers`/`customer_aggregate`/`performance` — an unverifiable claim caps engagement-compulsion at 9 even if everything else is perfect. [Cases 3, 6]
11. For customer-facing sends, match the customer's actual language preference (code-mixed Hindi-English, full Hindi, or English) and relationship state (lapsed_soft vs. lapsed_hard vs. senior/via-proxy-channel) — treating all customers identically costs 2 points. [Cross-case rule #5, line 319; Cases 2, 10]
12. Reference locality/peer context when it strengthens credibility (e.g., "HSR Layout," "South-Delhi solo CTR median"). [Cases 1, 3, 6, 7, 10]

**D. Trigger relevance (target: 10/10)**
13. Explicitly name the trigger event as the reason for messaging (the digest, the recall window, the match, the recall due-date) rather than a generic pretext. [All 10 cases score 10/10 here when this is true]
14. When the trigger is ambiguous or could suggest a bad tactical move, reason past it with category+merchant data rather than templating it literally — the single highest-signal differentiator in the whole set. [Case 5 IPL; cross-case rule #7, line 321]
15. Respect trigger `urgency` and suppression state — don't act on stale/suppressed/low-priority triggers; sending nothing (`actions: []`) is valid and rewarded over a low-value send. [api-call-examples.md Example 2.3; engagement-design.md TriggerContext]

**E. Engagement compulsion (target: 10/10)**
16. End with exactly one low-friction next step, ideally strict binary ("Reply YES", "Want me to draft X?") — multi-choice numbered replies are borderline/penalized relative to binary. [Case 2; cross-case rule #4, line 318]
17. Quantify the ask's effort or bound its risk explicitly: "Live in 10 min," "no commitment, no auto-charge," "90 seconds." Removing 2 objections in one line is called out as ideal. [Cases 5, 8; api F.2 "40 high-risk adult patients" scope]
18. Never leave the recommended action itself unquantified — even a good idea loses a point if phrased hand-wavily ("save it for Sept-Oct") without a number attached. [Case 7]
19. Offer reciprocity/effort-externalization ("I'll turn the answer into...", "I'll pull it for you") rather than just asking for something. [Cases 1, 4, 6]

**F. Structural / operational floor (all dimensions, hard caps)**
20. No repetition of identical `body` in the same `conversation_id` (−2 penalty/repeat; operational floor caps case at 5/dimension). [F.5; cross-case rule #10, line 324]
21. No fabricated facts, no plagiarized/near-duplicate case-study body text. [Cross-case rule #10; closing plagiarism note]
22. No URLs in body (hard fail, −3 per URL — Meta/WhatsApp policy). [F.4]
23. All required response fields present (`conversation_id`, `send_as`, `trigger_id`, `cta`, `suppression_key`, `rationale`); missing any → action scored 0, −2 penalty. [F.2]
24. `rationale` must accurately reflect the actual composition logic — judge cross-checks rationale vs. message; mismatch penalized. [Cross-case rule #9, line 323]
25. `conversation_id`/`suppression_key` should be legible and decodable (e.g., `conv_priya_recall_2026_11`, `recall:c_001_priya_for_m001:6mo`) rather than a bare UUID. [Cross-case rule #8, line 322; api-call-examples.md throughout]
26. Correct `send_as` for scope (`vera` merchant-facing / `merchant_on_behalf` customer-facing), with attribution reflected in the message body itself ("Karthik from PowerHouse here", "Dr. Meera's clinic here"). [engagement-design.md Composer section; engagement-research.md open question #3]
27. Detect and correctly handle non-substantive turns: auto-reply (back off, don't treat as engagement — escalating wait→wait→end on repeats), hostile/opt-out (end gracefully or one-line apology + stop), off-topic curveball (politely decline + redirect to original trigger without losing thread), explicit intent transition (switch immediately from qualifying to executing — continuing to qualify after "let's do it" is explicitly penalized). [api-call-examples.md Examples 2.5–2.7, 4.1–4.3]
