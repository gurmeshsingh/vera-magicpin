# magicpin Vera AI Challenge — Dataset Data Dictionary

Source: `/Users/gurmeshsingh/vera-challenge/pkg/dataset/`
Generated output analyzed: `/Users/gurmeshsingh/vera-challenge/generated/` (freshly run for this doc)

This is the exhaustive input contract: every field, type, enum/cardinality, and
presence guarantee across the four entity types (Merchant, Customer, Trigger,
Category), the trigger taxonomy, category-context differences, generator logic,
run instructions, and real distribution stats from an actual run.

---

## 1. Entity Schemas

### 1.1 Merchant (`MerchantContext`)

Files: `merchants/m_NNN_*.json`, 50 total after generation (10 seeds in
`merchants_seed.json` + 40 generated).

| Field | Type | Example | Cardinality / Enum | Presence |
|---|---|---|---|---|
| `merchant_id` | string | `"m_001_drmeera_dentist_delhi"` | unique, pattern `m_NNN_<slug>` | always |
| `category_slug` | string enum | `"dentists"` | `dentists, salons, restaurants, gyms, pharmacies` (exactly 5) | always |
| `identity.name` | string | `"Dr. Meera's Dental Clinic"` | free text, drawn from an 8-name bank per category (generated ones can repeat business names across merchants) | always |
| `identity.city` | string enum | `"Delhi"` | 10 cities: Delhi, Mumbai, Bangalore, Hyderabad, Chennai, Pune, Chandigarh, Jaipur, Lucknow, Ahmedabad | always |
| `identity.locality` | string | `"Lajpat Nagar"` | 10 localities per city (100 total) | always |
| `identity.place_id` | string | `"ChIJ_LAJPATNAGAR_DENTIST_001"` | synthetic, unique | always |
| `identity.verified` | bool | `true` | seed merchants: fixed per record; generated: `random() > 0.25` → ~75% true | always |
| `identity.languages` | string[] | `["en","hi"]` | always includes `en`,`hi`; generated adds one of `mr`(Mumbai)/`ta`(Chennai)/`te`(Hyderabad)/`kn`(Bangalore) by city | always, len 2-3 |
| `identity.owner_first_name` | string | `"Meera"` or `"Dr. Sameer"` | free text | always |
| `identity.established_year` | int | `2018` | seeds fixed; generated `randint(2010,2023)` | always |
| `subscription.status` | string enum | `"active"` | `active, expired, trial` (generated weights 7:2:1) | always |
| `subscription.plan` | string enum | `"Pro"` | `Pro, Trial, Basic` (Basic only appears in a seed) | always |
| `subscription.days_remaining` | int | `82` | active: seed value or `randint(5,300)`; trial: `randint(1,14)`; expired: `0` | always |
| `subscription.days_since_expiry` | int \| null | `38` | only meaningful when `status=="expired"`; generated formula `randint(7,90)`; **null when not expired** | sometimes null |
| `subscription.renewed_at` | string (date) | `"2026-02-04"` | seed-only field | **only on some seed merchants; absent on generated ones** |
| `performance.window_days` | int | `30` | constant | always |
| `performance.views` | int | `2410` | seeds vary widely; generated `randint(400,6000)` | always |
| `performance.calls` | int | `18` | generated `randint(2, max(3, views//80))` | always |
| `performance.directions` | int | `45` | generated `calls*2 + randint(0,30)` | always |
| `performance.ctr` | float | `0.021` | generated `uniform(0.015,0.060)` rounded 3dp; observed full-dataset range **0.016–0.062** | always |
| `performance.leads` | int | `9` | generated `randint(0, calls)` — **can be 0** | always |
| `performance.delta_7d.views_pct` | float | `0.18` | generated `uniform(-0.30,0.30)` rounded 2dp | always |
| `performance.delta_7d.calls_pct` | float | `-0.05` | same range | always |
| `performance.delta_7d.ctr_pct` | float | `0.02` | **only present on some seed merchants** | sometimes absent |
| `offers` | array of `{id,title,status,started,ended?}` | see below | seed merchants: 0-2 offers; **all 40 generated merchants have `offers: []`** | always present as array, often empty |
| `conversation_history` | array of `{ts,from,body,engagement}` | see below | seeds: 0-2 turns; **all 40 generated merchants have `[]`** | always present as array, often empty |
| `customer_aggregate` | object, free-form per category | `{"total_unique_ytd":540,...}` | seeds carry category-specific extra keys (`lapsed_180d_plus`, `retention_6mo_pct`, `chronic_rx_count`, `delivery_orders_30d`, `total_active_members`, `monthly_churn_pct`, etc. — **not standardized across categories**); generated merchants only carry `{"total_unique_ytd": randint(50,2000)}` | always object, key set varies |
| `signals` | string[] | `["stale_posts:22d","ctr_below_peer_median",...]` | free-text signal tags, sometimes with `:value` suffix; seeds have 0-4; **all generated merchants have `[]`** | always array, often empty |
| `review_themes` | array of `{theme,sentiment,occurrences_30d,common_quote?}` | see below | seeds: 0-2 entries; **all generated merchants have `[]`** | always array, often empty |

Offer object shape: `{id, title, status: "active"|"expired", started: date, ended?: date}` (ended only present when expired).

Conversation history entry shape: `{ts: ISO8601, from: "vera"|"merchant", body: string, engagement: enum}`. Engagement values seen: `merchant_replied, merchant_no_reply, intent_action, intent_question, intent_planning`.

Review theme entry: `{theme: string, sentiment: "pos"|"neg", occurrences_30d: int, common_quote?: string}` (`common_quote` sometimes absent).

Example (seed merchant, full offers/history/signals populated):
```json
{
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "category_slug": "dentists",
  "identity": {
    "name": "Dr. Meera's Dental Clinic", "city": "Delhi", "locality": "Lajpat Nagar",
    "place_id": "ChIJ_LAJPATNAGAR_DENTIST_001", "verified": true,
    "languages": ["en", "hi"], "owner_first_name": "Meera", "established_year": 2018
  },
  "subscription": { "status": "active", "plan": "Pro", "days_remaining": 82, "renewed_at": "2026-02-04" },
  "performance": {
    "window_days": 30, "views": 2410, "calls": 18, "directions": 45, "ctr": 0.021, "leads": 9,
    "delta_7d": { "views_pct": 0.18, "calls_pct": -0.05, "ctr_pct": 0.02 }
  },
  "offers": [
    { "id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active", "started": "2026-03-01" },
    { "id": "o_meera_002", "title": "Deep Cleaning @ ₹499", "status": "expired", "ended": "2026-02-28" }
  ],
  "conversation_history": [
    { "ts": "2026-04-24T10:12:00Z", "from": "vera", "body": "Profile audit done...", "engagement": "merchant_replied" },
    { "ts": "2026-04-24T10:18:00Z", "from": "merchant", "body": "Yes please, focus on whitening and aligners", "engagement": "intent_action" }
  ],
  "customer_aggregate": { "total_unique_ytd": 540, "lapsed_180d_plus": 78, "retention_6mo_pct": 0.38, "high_risk_adult_count": 124 },
  "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort", "engaged_in_last_48h"],
  "review_themes": [
    { "theme": "wait_time", "sentiment": "neg", "occurrences_30d": 3, "common_quote": "had to wait 30 min on Sunday afternoon" },
    { "theme": "doctor_manner", "sentiment": "pos", "occurrences_30d": 5, "common_quote": "Dr. Meera explains everything patiently" }
  ]
}
```

Example (generated merchant — this is the "thin" shape most of the dataset takes):
```json
{
  "merchant_id": "m_011_dr_sameer_dentist_bangalore",
  "category_slug": "dentists",
  "identity": {
    "name": "Bright Smile Dental", "city": "Bangalore", "locality": "Indiranagar",
    "place_id": "ChIJ_INDIRANAGAR_DENTISTS_011", "verified": true,
    "languages": ["en", "hi", "kn"], "owner_first_name": "Dr. Sameer", "established_year": 2013
  },
  "subscription": { "status": "expired", "plan": "Pro", "days_remaining": 0, "days_since_expiry": 28 },
  "performance": {
    "window_days": 30, "views": 4792, "calls": 55, "directions": 138, "ctr": 0.046, "leads": 27,
    "delta_7d": { "views_pct": -0.2, "calls_pct": 0.16 }
  },
  "offers": [],
  "conversation_history": [],
  "customer_aggregate": { "total_unique_ytd": 1905 },
  "signals": [],
  "review_themes": []
}
```

### 1.2 Customer (`CustomerContext`)

Files: `customers/c_NNN_*.json`, 200 total (15 seeds + 185 generated).

| Field | Type | Example | Cardinality / Enum | Presence |
|---|---|---|---|---|
| `customer_id` | string | `"c_001_priya_for_m001"` | unique; generated pattern `c_NNN_<name>_for_<merchant_id>` | always |
| `merchant_id` | string | `"m_001_drmeera_dentist_delhi"` | FK into merchants; exactly 4 customers per merchant in the fully expanded set | always |
| `identity.name` | string | `"Priya"`, or `"(walk-in, no profile)"`, or `"Aanya (parent: Sneha)"` | one seed customer is a literal walk-in placeholder | always |
| `identity.phone_redacted` | string \| null | `"<phone>"` | always redacted placeholder; **null for the one walk-in/no-profile seed customer** | sometimes null |
| `identity.language_pref` | string | `"hi-en mix"` | seeds use rich values (`"hi-en mix"`, `"te-en mix"`, `"english"`, `"hi"`); generated customers only from `["en","hi-en mix","hi"]` | always |
| `identity.age_band` | string enum-ish | `"25-35"` | seed values include `child_under_12`, `child_7-12`, `65-75`, `unknown`; generated only from `["20-25","25-35","30-40","40-50","50-65"]` | always |
| `identity.senior_citizen` | bool | `true` | **seed-only optional flag**, absent elsewhere | sometimes absent |
| `identity.chronic_conditions` | string[] | `["diabetes_t2","hypertension"]` | **seed-only, pharmacy chronic patient**, absent elsewhere | sometimes absent |
| `relationship.first_visit` | date string | `"2025-11-04"` | seeds vary; **all generated customers hardcode `"2025-09-01"`** | always |
| `relationship.last_visit` | date string | `"2026-05-12"` | seeds vary; **all generated customers hardcode `"2026-04-01"`** | always |
| `relationship.visits_total` | int | `4` | generated `randint(1,12)` | always |
| `relationship.services_received` | string[] | `["cleaning","whitening",...]` | seeds populated with realistic service lists (sometimes containing literal `"..."` as truncation marker); **all generated customers have `[]`** | always array, often empty |
| `relationship.lifetime_value` | int (₹) | `1696` | generated `visits_total * randint(200,1500)` | always |
| `relationship.favourite_dish` | string | `"BBQ Chicken Pizza"` | **restaurant seed customers only** | sometimes absent |
| `state` | string enum | `"lapsed_soft"` | `new, active, lapsed_soft, lapsed_hard, churned` — generated weights 1:4:2:1:1 | always |
| `preferences.channel` | string enum | `"whatsapp"` | seeds: `whatsapp`, `whatsapp_via_parent`, `whatsapp_via_son`, `none_recorded`; generated always `"whatsapp"` | always |
| `preferences.reminder_opt_in` | bool | `true` | generated `random() > 0.2` (~80% true) | always |
| `preferences.preferred_slots` | string | `"weekday_evening"` | **seed-only**, absent on generated | sometimes absent |
| `preferences.preferred_stylist` / `.wedding_date` / `.training_focus` / `.health_focus` / `.household_size` / `.family_size` / `.office_nearby` / `.delivery_address` | mixed | e.g. `"wedding_date": "2026-11-08"` | **seed-only, category-specific extension fields, never on generated customers** | sometimes absent |
| `consent.opted_in_at` | date string \| null | `"2025-09-01"` | null for the walk-in seed customer | sometimes null |
| `consent.scope` | string[] | `["recall_reminders","appointment_reminders"]` | seeds have rich scope lists (`bridal_package_followup`, `refill_reminders`, `winback_offers`, etc.); generated customers always `["promotional_offers"]`; **can be empty `[]`** (walk-in) | always array, sometimes empty |

Example (seed, rich):
```json
{
  "customer_id": "c_001_priya_for_m001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "identity": { "name": "Priya", "phone_redacted": "<phone>", "language_pref": "hi-en mix", "age_band": "25-35" },
  "relationship": { "first_visit": "2025-11-04", "last_visit": "2026-05-12", "visits_total": 4, "services_received": ["cleaning", "cleaning", "whitening", "cleaning"], "lifetime_value": 1696 },
  "state": "lapsed_soft",
  "preferences": { "preferred_slots": "weekday_evening", "channel": "whatsapp", "reminder_opt_in": true },
  "consent": { "opted_in_at": "2025-11-04", "scope": ["recall_reminders", "appointment_reminders"] }
}
```

Example (edge case — walk-in with nulls):
```json
{
  "customer_id": "c_015_anonymous_for_m010",
  "merchant_id": "m_010_sunrisepharm_pharmacy_lucknow",
  "identity": { "name": "(walk-in, no profile)", "phone_redacted": null, "language_pref": "hi", "age_band": "unknown" },
  "relationship": { "first_visit": "2026-04-15", "last_visit": "2026-04-15", "visits_total": 1, "services_received": ["walk_in_otc"], "lifetime_value": 240 },
  "state": "new",
  "preferences": { "channel": "none_recorded", "reminder_opt_in": false },
  "consent": { "opted_in_at": null, "scope": [] }
}
```

Example (generated, thin):
```json
{
  "customer_id": "c_016_tara_for_m_001_drmeera_dentist_delhi",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "identity": { "name": "Tara", "phone_redacted": "<phone>", "language_pref": "en", "age_band": "40-50" },
  "relationship": { "first_visit": "2025-09-01", "last_visit": "2026-04-01", "visits_total": 9, "services_received": [], "lifetime_value": 5220 },
  "state": "lapsed_hard",
  "preferences": { "channel": "whatsapp", "reminder_opt_in": true },
  "consent": { "opted_in_at": "2025-09-01", "scope": ["promotional_offers"] }
}
```

### 1.3 Trigger (`TriggerContext`)

Files: `triggers/trg_NNN_*.json`, 100 total (25 seeds + 75 generated).

| Field | Type | Example | Cardinality / Enum | Presence |
|---|---|---|---|---|
| `id` | string | `"trg_001_research_digest_dentists"` | unique | always |
| `scope` | string enum | `"merchant"` | `merchant, customer` — dataset-wide 70 merchant / 30 customer | always |
| `kind` | string | `"perf_dip"` | 26 distinct kinds observed (see taxonomy §2) | always |
| `source` | string enum | `"internal"` | `internal, external` — dataset-wide 77 internal / 23 external | always |
| `merchant_id` | string | FK | always resolves to an existing merchant | always |
| `customer_id` | string \| null | FK or null | **null whenever `scope=="merchant"`** (70/100 triggers); non-null only for `scope=="customer"` | sometimes null (majority) |
| `payload` | object, kind-specific | see taxonomy | seed triggers: rich, kind-specific keys; **generated triggers (75/100) all use a flat placeholder `{"placeholder": true, "metric_or_topic": "<kind>"}`** — no real numbers/dates | shape varies wildly by kind and seed-vs-generated |
| `urgency` | int | `3` | 1-5 scale; dataset distribution 1:31, 2:32, 3:26, 4:10, 5:1 (5 only for the atorvastatin recall) | always |
| `suppression_key` | string | `"perf_dip:m_002:calls:2026-W17"` | free text, used for de-dup; generated ones look like `"<kind>:<merchant_id>:gen_<idx>"` | always |
| `expires_at` | ISO8601 datetime | `"2026-05-10T00:00:00Z"` | generated triggers all hardcode `"2026-06-30T00:00:00Z"` regardless of kind/urgency | always |

Example (seed, rich payload, urgency 5 — the single highest-urgency trigger in the dataset):
```json
{
  "id": "trg_018_supply_atorvastatin_recall",
  "scope": "merchant", "kind": "supply_alert", "source": "external",
  "merchant_id": "m_009_apollo_pharmacy_jaipur", "customer_id": null,
  "payload": { "alert_id": "d_2026W17_atorvastatin_recall", "molecule": "atorvastatin", "affected_batches": ["AT2024-1102", "AT2024-1108"], "manufacturer": "MfrZ" },
  "urgency": 5, "suppression_key": "alert:atorvastatin:2026-04", "expires_at": "2026-05-30T00:00:00Z"
}
```

Example (generated, placeholder payload — this is what 75% of triggers look like):
```json
{
  "id": "trg_026_research_digest_m_017_dr_rajan_denti",
  "scope": "merchant", "kind": "research_digest", "source": "external",
  "merchant_id": "m_017_dr_rajan_dentist_mumbai", "customer_id": null,
  "payload": { "placeholder": true, "metric_or_topic": "research_digest" },
  "urgency": 1, "suppression_key": "research_digest:m_017_dr_rajan_dentist_mumbai:gen_26",
  "expires_at": "2026-06-30T00:00:00Z"
}
```

### 1.4 Category Context

Files: `categories/{dentists,gyms,pharmacies,restaurants,salons}.json`, copied as-is by the generator (no expansion — exactly 5, static).

| Field | Type | Example | Notes |
|---|---|---|---|
| `slug` | string | `"dentists"` | matches merchant `category_slug` |
| `display_name` | string | `"Dentists"` | |
| `voice.tone` | string | `"peer_clinical"` | one distinct value per category |
| `voice.register` | string | `"respectful_collegial"` | |
| `voice.code_mix` | string | `"hindi_english_natural"` | gyms differ: `"english_primary_some_hindi"` |
| `voice.vocab_allowed` | string[] | clinical/domain jargon list, 11-16 terms | |
| `voice.vocab_taboo` | string[] | banned superlatives/claims, 4-6 terms | all categories ban absolute claims like "guaranteed"/"miracle"/"100% safe", each with category-specific extras (e.g. dentists ban "FDA-approved (use only when actually applicable)") |
| `voice.salutation_examples` | string[] | `["Dr. {first_name}","Doc"]` | template strings with `{placeholder}` |
| `voice.tone_examples` | string[] | 2-3 model utterances | |
| `offer_catalog` | array of `{id,title,value,audience,type}` | 8 offers per category | `audience` ∈ `new_user, repeat_user, senior, all`; `type` ∈ `service_at_price, free_service, membership, free_addon, percentage_discount, free_trial, bogo` |
| `peer_stats` | object | `{scope, avg_rating, avg_review_count, avg_views_30d, avg_calls_30d, avg_directions_30d, avg_ctr, avg_photos, avg_post_freq_days, ...}` | plus category-specific extra keys (`retention_6mo_pct` for dentists, `monthly_churn_pct`+`trial_to_paid_pct` for gyms, `delivery_share_pct`+`repeat_customer_pct` for pharmacies, `retention_30d_pct` for restaurants, `retention_3mo_pct` for salons) — **key set not standardized across categories** |
| `digest` | array of `{id,kind,title,source,summary,actionable,...}` | 5 items | `kind` ∈ `research, compliance, cde, trend, tech, seasonal, compete, supply, alert` (varies by category); optional extra fields per kind: `trial_n`,`patient_segment` (research), `deadline`/`date` (compliance/cde), `credits` (cde) |
| `patient_content_library` | array of `{id,title,channel,length_seconds,body}` | 2-3 items | consumer-facing WhatsApp content snippets, channel always `"whatsapp"` |
| `seasonal_beats` | array of `{month_range,note}` | 3-5 items | category-specific seasonality calendar |
| `trend_signals` | array of `{query,delta_yoy,segment_age,skew}` | 4 items | `skew` ∈ `male, female, balanced` |
| `regulatory_authorities` | string[] | `["Dental Council of India (DCI)","Indian Dental Association (IDA)"]` | 1-3 per category |
| `professional_journals` | string[] | `["JIDA","Indian Journal of Dental Research",...]` | 1-3 per category |

---

## 2. Trigger Taxonomy

26 distinct `kind` values observed across seeds + generator. Grouped by theme; "Seed only" = appears only in the 25 hand-written seeds (rich payload); "Generatable" = also produced by `expand_triggers()` (placeholder payload).

| Kind | Scope | Source | Seed payload fields | Generatable? | Applies to categories | Correlated merchant/customer state |
|---|---|---|---|---|---|---|
| `research_digest` | merchant | external | `category`, `top_item_id` | yes | all | any; ties to category `digest[]` research items |
| `regulation_change` | merchant | external | `category`, `top_item_id`, `deadline_iso` | seed only | dentists (DCI), pharmacies (FDA/CDSCO), restaurants (GST) | compliance-sensitive categories |
| `recall_due` | customer | internal | `service_due`, `last_service_date`, `due_date`, `available_slots[]` | yes | dentists (6-mo cleaning), salons, gyms | customer with a completed service and a recall interval |
| `perf_dip` | merchant | internal | `metric`, `delta_pct`, `window`, `vs_baseline` | yes | all | merchant with negative `delta_7d` |
| `perf_spike` | merchant | internal | `metric`, `delta_pct`, `window`, `vs_baseline`, `likely_driver` | yes | all | merchant with positive `delta_7d`, often tied to a conversation about a new offer/post |
| `renewal_due` | merchant | internal | `days_remaining`, `plan`, `renewal_amount` | yes | all | `subscription.status in {active near expiry, trial}` |
| `festival_upcoming` | merchant | external | `festival`, `date`, `days_until`, `category_relevance[]` | yes | salons, restaurants, pharmacies primarily | ties to `seasonal_beats` |
| `wedding_package_followup` | customer | internal | `wedding_date`, `trial_completed`, `days_to_wedding`, `next_step_window_open` | seed only | salons | customer with `wedding_date` preference and a bridal trial |
| `curious_ask_due` | merchant | internal | `ask_template`, `last_ask_at` | yes | all | merchant with no recent proactive question from Vera |
| `winback_eligible` | merchant | internal | `days_since_expiry`, `perf_dip_pct`, `lapsed_customers_added_since_expiry` | yes | all | merchant with `subscription.status=="expired"` |
| `ipl_match_today` | merchant | external | `match`, `venue`, `city`, `match_time_iso`, `is_weeknight` | seed only | restaurants | seasonal/sports-linked, city-specific |
| `review_theme_emerged` | merchant | internal | `theme`, `occurrences_30d`, `trend`, `common_quote` | yes | all | ties to merchant `review_themes[]` |
| `milestone_reached` | merchant | internal | `metric`, `value_now`, `milestone_value`, `is_imminent` | yes | all | any merchant approaching a round-number metric |
| `active_planning_intent` | merchant | internal | `intent_topic`, `merchant_last_message` | seed only (also appears among generated `additional_kinds`? no — see note) | all | merchant with `conversation_history` showing `engagement: intent_planning/intent_question` |
| `seasonal_perf_dip` | merchant | internal | `metric`, `delta_pct`, `window`, `is_expected_seasonal`, `season_note` | seed only | gyms (post-resolution dip) | ties to `seasonal_beats` |
| `customer_lapsed_hard` | customer | internal | `days_since_last_visit`, `previous_focus`, `previous_membership_months` | seed only | gyms, dentists, salons | customer `state=="lapsed_hard"` |
| `trial_followup` | customer | internal | `trial_date`, `next_session_options[]` | yes | gyms, dentists | customer `state=="new"` after a trial/consult |
| `supply_alert` | merchant | external | `alert_id`, `molecule`, `affected_batches[]`, `manufacturer` | seed only | pharmacies | highest urgency observed (5) |
| `chronic_refill_due` | customer | internal | `molecule_list[]`, `last_refill`, `stock_runs_out_iso`, `delivery_address_saved` | yes | pharmacies | customer with `chronic_conditions`/chronic Rx |
| `category_seasonal` | merchant | external | `season`, `trends[]`, `shelf_action_recommended` | seed only | pharmacies (summer ORS/sunscreen etc.) | ties to `seasonal_beats` |
| `gbp_unverified` | merchant | internal | `verified`, `verification_path`, `estimated_uplift_pct` | seed only | all | merchant `identity.verified==false` |
| `cde_opportunity` | merchant | external | `digest_item_id`, `credits`, `fee` | seed only | dentists, salons (professional training/CDE events) | ties to category `digest[]` kind `cde` |
| `competitor_opened` | merchant | external | `competitor_name`, `distance_km`, `their_offer`, `opened_date` | yes | all | any merchant, locality-based |
| `dormant_with_vera` | merchant | internal | `days_since_last_merchant_message`, `last_topic` | yes | all | merchant with stale/no `conversation_history` |
| `appointment_tomorrow` | customer | internal | placeholder only (generated-only kind, no seed) | yes | dentists, gyms, salons | scheduled-appointment categories |
| `customer_lapsed_soft` | customer | internal | placeholder only (generated-only) | yes | all | customer `state=="lapsed_soft"` |

Notes on the generator's `additional_kinds` list (`generate_dataset.py` lines 208-224) — this is the authoritative list of what CAN be generated beyond the seeds: `research_digest`(×5), `perf_dip`(×5), `perf_spike`(×5), `milestone_reached`(×5), `dormant_with_vera`(×5), `review_theme_emerged`(×5), `competitor_opened`(×5), `festival_upcoming`(×5), `recall_due`(×5, customer-scoped), `customer_lapsed_soft`(×5, customer-scoped), `appointment_tomorrow`(×5, customer-scoped), `chronic_refill_due`(×5, customer-scoped), `trial_followup`(×5, customer-scoped), `renewal_due`(×5), `curious_ask_due`(×5) — 15 kinds × 5 = 75 generated triggers exactly filling the gap from 25 seeds to 100. **All generated triggers, regardless of kind, get the same flat placeholder payload** `{"placeholder": true, "metric_or_topic": kind}` and the same `expires_at` (`2026-06-30T00:00:00Z`) — real numeric/date payload richness exists ONLY in the 25 seed triggers.

Kinds appearing ONLY among the 25 seeds and never regenerated (i.e. exactly 1 instance each in the full 100-trigger dataset): `regulation_change, wedding_package_followup, ipl_match_today, active_planning_intent (×2 in seeds), seasonal_perf_dip, customer_lapsed_hard, supply_alert, category_seasonal, gbp_unverified, cde_opportunity`. These are rare/high-signal one-offs an engine must still handle correctly even though they're statistically underrepresented.

---

## 3. Category Contexts — What Each Provides & How They Differ

All 5 categories share the same top-level schema (§1.4) but differ substantially in content, which is exactly what "category fit" scoring should key off:

- **Voice/tone**: dentists = `peer_clinical`/`respectful_collegial` (clinical jargon: OPG, IOPA, RCT, zirconia); gyms = `energetic_disciplined`/`coach_to_member`, English-primary (only category where `code_mix` isn't "hindi_english_natural"); pharmacies = `trustworthy_precise`/`neighbourhood_pharmacist`; restaurants = `warm_busy_practical`/`fellow_operator`; salons = `warm_practical`/`approachable_expert`.
- **Taboo vocabulary** differs per category's regulatory sensitivity: dentists/pharmacies ban unsupported clinical/efficacy claims ("100% safe", "doctor recommended without disclosure"); restaurants/gyms ban hype ("viral guarantee", "shred in 7 days", "miracle transformation").
- **Offer catalog** types differ by business model: dentists/salons/pharmacies lean `service_at_price` + `membership`; restaurants add `bogo` and `percentage_discount`; gyms add `free_trial`; pharmacies uniquely have `senior`-audience and `percentage_discount` offers tied to Schedule H/OTC economics.
- **peer_stats** extra fields are category-specific and NOT standardized: dentists track `retention_6mo_pct`; gyms track `monthly_churn_pct`+`trial_to_paid_pct`; pharmacies track `delivery_share_pct`+`repeat_customer_pct`; restaurants track `retention_30d_pct`; salons track `retention_3mo_pct`. An engine comparing merchant performance to peers must look up the right key per category — there's no universal "retention" field.
- **Digest kinds** vary: dentists/gyms have `research` (clinical trial-style, with `trial_n`); pharmacies have `alert`/`supply`/`compliance` (recall/regulatory, highest real-world urgency); restaurants have `compliance` (GST) and `tech` (delivery-platform features); salons have `tech` (product launches) and `cde` (training).
- **Seasonality** is category-specific and sometimes conflicting: gyms see April-June as their *lowest* acquisition window while dentists/salons see April-May as a *secondary* opportunity (pediatric/bridal); restaurants peg IPL season (Mar-Apr) and warn Saturday matches actually underperform weeknights — a subtlety an engine must respect, not just "IPL = good".
- **Compliance/regulatory bodies** differ: dentists → DCI/IDA; pharmacies → CDSCO/State FDA/DCGI (heaviest regulatory burden, matches the `supply_alert`/`regulation_change` triggers being pharmacy/dentist-heavy); restaurants → FSSAI/GST Council; salons → FDA India (cosmetic ingredients, lightest); gyms → FSSAI (supplements only)/Municipal Corp.
- **Trend signals** carry `skew` (gender lean) and `segment_age`, letting an engine target messaging demographically (e.g. salon "bridal makeup artist" skews female 22-32; gym "personal trainer cost" is balanced 30-50).

---

## 4. Generator Logic (`generate_dataset.py`)

- **Determinism**: `SEED = 20260426` fixed at module level; a single `random.Random(SEED)` instance threads through all three expand functions in a fixed call order (`expand_merchants` → `expand_customers` → `expand_triggers`). Same seed dir in → byte-identical output every run (verified: reran locally, category files are copied verbatim, and console output matches expected counts exactly).
- **Categories**: not expanded at all — the 5 files in `categories/*.json` are copied as-is into `expanded/categories/`.
- **Merchants** (`expand_merchants`, lines 118-164): starts from the 10 seeds, then tops up each of the 5 categories to exactly 10 merchants (8 generated per category × 5 = 40, total 50). For each generated merchant: business name + owner drawn (with replacement) from an 8-entry `NAME_BANKS[category]` list (so name collisions across generated merchants are possible/expected), city/locality randomly drawn from the 10-city × 10-locality grid, `views` uniform 400-6000, `calls` derived from views, `ctr` uniform 0.015-0.060, `verified` ~75% true, `subscription.status` weighted 7:2:1 active:expired:trial. **Generated merchants always get empty `offers`, `conversation_history`, `signals`, `review_themes`, and a minimal single-key `customer_aggregate`** — this is a structural simplification, not noise.
- **Customers** (`expand_customers`, lines 167-201): for each of the 50 merchants, tops up to a flat `target_per_merchant = 4`, subtracting any seeds already attached to that merchant. Global cap enforced via `next_idx > 200 + len(seeds)` break (in practice this exactly reaches 200). Name drawn (with replacement) from an 18-name Sanskrit/Hindi first-name pool — no surnames, so generated customer names collide often. `visits_total` uniform 1-12; `state` weighted 1:4:2:1:1 for new:active:lapsed_soft:lapsed_hard:churned; `lifetime_value = visits_total * randint(200,1500)`. All generated customers get identical hardcoded `first_visit`/`last_visit` dates, empty `services_received`, and no category-specific preference/consent extensions — only the 15 seed customers carry those richer fields.
- **Triggers** (`expand_triggers`, lines 204-244): iterates a fixed list of 15 `(kind, source, scope, urgency)` tuples (`additional_kinds`), generating exactly 5 of each (75 total, capped at 100 combined with seeds via `expanded[:100]`). Merchant chosen uniformly at random from all 50; for `scope=="customer"` kinds, a customer is chosen uniformly at random from that merchant's customers — **if a merchant happens to have zero customers, the generator silently `continue`s and produces fewer than 5 for that kind** (not observed in practice since every merchant gets ≥4 customers, but it's a latent edge case in the code). Every generated trigger gets the same flat placeholder payload and a fixed `expires_at`.
- **Test pairs** (`write_test_pairs`, lines 267-283): groups all 100 triggers by `kind` (26 kinds), takes up to 2 per kind in sorted-kind order, stops at 30. Because some kinds have only 1 instance (the seed-only ones), the 30 pairs end up covering only 18 of the 26 kinds with a mix of 1x and 2x representation — **not 26 kinds × 2 as one might assume**; verified by rerun (see §6).

### What is in the space of generated inputs (edge cases an engine must survive)

1. **Merchants with zero offers, zero conversation history, zero signals, zero review themes** — this is 40-43 of 50 merchants (86%), i.e. the *typical* case, not an edge case. Any engine assuming "merchants usually have an offer to reference" is wrong.
2. **Merchants with `subscription.status=="expired"`** and `days_since_expiry` populated but `days_remaining==0` — must not be treated as "renewal upcoming."
3. **Merchants with 0 leads** despite nonzero views/calls (4 merchants).
4. **Customers with null `phone_redacted`, null `consent.opted_in_at`, and empty `consent.scope`** simultaneously (the walk-in customer) — an engine must handle a customer it effectively cannot legally message.
5. **Customer `age_band` values that aren't ranges** (`child_under_12`, `child_7-12`, `unknown`) mixed in with the normal decade-bucket format — string parsing that assumes `"NN-NN"` will break.
6. **Trigger `customer_id` is null for 70% of triggers** (all merchant-scoped ones) — any code path assuming a customer is always attached will NPE.
7. **75% of triggers carry a non-informative placeholder payload** (`{"placeholder": true, "metric_or_topic": kind}`) with no real numbers, dates, or entities — an engine that tries to extract e.g. `delta_pct` or `molecule` from a generated `perf_dip`/`chronic_refill_due` trigger will find nothing there, even though the seed version of that same kind has rich data. Message-generation logic must degrade gracefully when payload is a placeholder.
8. **Same generated `expires_at` (`2026-06-30T00:00:00Z`) regardless of urgency** — a generated urgency-4 trigger can have the identical, fairly distant expiry as a placeholder urgency-1 trigger; expiry cannot be used as a proxy for urgency.
9. **Duplicate business/owner names across generated merchants** (8-entry name bank reused up to 10x per category) and **duplicate customer first names with no surnames** — entity resolution by name alone is unsafe.
10. **`customer_aggregate` key sets differ between seed and generated merchants, and across categories** — no fixed schema; code must treat it as a loose bag of optional stats.
11. **Rare, high-urgency, seed-only kinds** (`supply_alert` urgency 5, the atorvastatin recall) exist exactly once in the whole 100-trigger set — statistically negligible but operationally the most safety-critical case; an engine tuned on the generated bulk (all urgency 1-4, generic) could systematically underweight it.
12. **`performance.delta_7d.ctr_pct` present on some seed merchants but absent on all others** — optional/inconsistent nested-key presence.
13. **`subscription.plan == "Basic"`** appears exactly once (seed `m_010`) vs the otherwise-universal `Pro`/`Trial` — a third enum value that's easy to miss if only skimming a few examples.
14. **Trigger scope/customer mismatch risk in the generator**: for customer-scoped kinds, if a randomly chosen merchant has no customers the code `continue`s silently, meaning kind counts are not strictly guaranteed to hit exactly 5 (didn't manifest in this run because minimum customers-per-merchant is 4, but a downstream engine should not hard-assume exact-5 counts per generated kind).

---

## 5. How to Run It

```bash
cd /Users/gurmeshsingh/vera-challenge/pkg/dataset
python3 generate_dataset.py --seed-dir . --out /Users/gurmeshsingh/vera-challenge/generated
```

- `--seed-dir` (default `.`): directory containing `categories/`, `merchants_seed.json`, `customers_seed.json`, `triggers_seed.json`.
- `--out` (default `./expanded`): output directory; created if missing, with subfolders `categories/`, `merchants/`, `customers/`, `triggers/`, plus a top-level `test_pairs.json`.
- **Dependencies**: none beyond the Python 3 standard library (`argparse`, `json`, `os`, `random`, `pathlib`). No `requirements.txt` needed; ran successfully on system Python 3.
- **Output files written** (all under `--out`):
  - `categories/{dentists,gyms,pharmacies,restaurants,salons}.json` (5 files, verbatim copies)
  - `merchants/m_NNN_*.json` (50 files)
  - `customers/c_NNN_*.json` (200 files)
  - `triggers/trg_NNN_*.json` (100 files)
  - `test_pairs.json` (1 file, `{"pairs": [{test_id, trigger_id, merchant_id, customer_id}, ...]}`, 30 entries)
- Deterministic: reran during this task and got identical counts (50/200/100/30) each time.

For this task, output was written to `/Users/gurmeshsingh/vera-challenge/generated/`.

---

## 6. Real Distribution Stats (from the actual run)

**Merchants (50 total)**
- Category distribution: exactly 10 each — dentists, salons, restaurants, gyms, pharmacies (perfectly balanced by construction).
- Subscription status: `active` 36, `expired` 9, `trial` 5.
- `verified`: `true` 40, `false` 10.
- **Merchants with empty `offers`: 43/50 (86%)**
- **Merchants with empty `conversation_history`: 42/50 (84%)**
- **Merchants with empty `signals`: 40/50 (80%)**
- **Merchants with empty `review_themes`: 43/50 (86%)**
- `performance.views` range: 720 – 12,400
- `performance.calls` range: 2 – 88
- `performance.ctr` range: 0.016 – 0.062
- `performance.delta_7d.views_pct` range: -0.30 – 0.26
- Merchants with 0 leads: 4/50
- City distribution: Chandigarh 7, Mumbai 6, Bangalore 6, Ahmedabad 6, Pune 5, Chennai 5, Lucknow 5, Jaipur 4, Delhi 4, Hyderabad 2 (uneven — random draw, not uniform by construction since seeds pin some cities).

**Customers (200 total)**
- State distribution: `active` 98, `lapsed_soft` 48, `new` 19, `lapsed_hard` 19, `churned` 16.
- Customers per merchant: exactly 4 for all 50 merchants (flat target hit exactly).
- Customers with empty `consent.scope`: 1 (the walk-in).
- Customers with null `phone_redacted`: 1 (the same walk-in).
- Age bands: dominated by the 5 generated buckets (`25-35`:45, `40-50`:47, `20-25`:41, `30-40`:38, `50-65`:23) with the seed-only oddballs (`45-55`, `child_7-12`, `unknown`, `65-75`, `child_under_12`) each appearing exactly once.

**Triggers (100 total)**
- Scope: `merchant` 70, `customer` 30.
- Source: `internal` 77, `external` 23.
- Urgency: 1→31, 2→32, 3→26, 4→10, 5→1.
- Kind counts: the 15 generatable kinds each land at 5-6 (5 generated + 0-1 seed overlap): `curious_ask_due` 6, `festival_upcoming` 6, `competitor_opened` 6, `appointment_tomorrow` 5, `customer_lapsed_soft` 5, `research_digest` 6, `recall_due` 6, `chronic_refill_due` 6, `dormant_with_vera` 6, `perf_dip` 6, `perf_spike` 6, `renewal_due` 6, `trial_followup` 6, `milestone_reached` 6, `review_theme_emerged` 6. The 10 seed-only kinds sit at 1 each (`customer_lapsed_hard`, `cde_opportunity`, `supply_alert`, `seasonal_perf_dip`, `winback_eligible`, `ipl_match_today`, `regulation_change`, `gbp_unverified`, `wedding_package_followup`, `category_seasonal`), except `active_planning_intent` which has 2 (both seeds).
- Triggers with `customer_id == null`: 70/100 (matches merchant-scope count exactly).
- **Triggers with placeholder payload: 75/100 (exactly the generated set).**

**Test pairs (30 total)**
- Covers 18 of the 26 distinct kinds (not all 26 — the `sorted(by_kind.items())` + "up to 2 per kind, stop at 30" logic exhausts the 30-slot budget partway through the alphabetically-sorted kind list, so kinds later than `~"i"` alphabetically or with low counts get excluded this run: covered kinds are `active_planning_intent`(2), `appointment_tomorrow`(2), `category_seasonal`(1), `cde_opportunity`(1), `chronic_refill_due`(2), `competitor_opened`(2), `curious_ask_due`(2), `customer_lapsed_hard`(1), `customer_lapsed_soft`(2), `dormant_with_vera`(2), `festival_upcoming`(2), `gbp_unverified`(1), `ipl_match_today`(1), `milestone_reached`(2), `perf_dip`(2), `perf_spike`(2), `recall_due`(2), `regulation_change`(1)`. Kinds like `renewal_due`, `research_digest`, `review_theme_emerged`, `seasonal_perf_dip`, `supply_alert`, `trial_followup`, `winback_eligible`, `wedding_package_followup` are NOT in the 30 canonical test pairs despite existing in the trigger set — an engine evaluated only against `test_pairs.json` will never be scored on these 8 kinds.
