## 1. MVP Goal & Demo Narrative

**MVP name:** *Review Intelligence System – LLM + NLP MVP*

**Goal (what it proves):**
Turn 15,000 app reviews into an **executive-ready dashboard** (KPIs + trends + drilldowns) and **GenAI-heavy insight suite** (weekly brief, release comparison, sprint backlog, risk radar, etc.) **without any ML training/fine-tuning**.

**Demo narrative (story you’ll tell):**

1. “Here’s the health of the app this week” → rating trend + % negative trend + critical severity count.
2. “Here’s what’s driving dissatisfaction” → top issue labels + top categories + evidence quotes.
3. “Here’s what changed since last version?” → version comparison + anomalies + likely root causes.
4. “Here’s what we should do next sprint” → auto-generated backlog tickets + PRD snippets + support macros.
5. “Here’s who is at churn risk (heuristic) and why” → churn risk distribution + top risky users + rationale.

---

## 2. Architecture Overview

**Core principle:** deterministic pipeline first, LLM used as **adjudicator + narrator + planner**.

**Flow:**

* **Ingest CSV → normalize → store raw** in DuckDB/SQLite.
* **Enrich reviews** using:

  * rule-based sentiment + LLM adjudication (only where uncertain)
  * rule-based multi-label issues + LLM multi-label classifier (only where uncertain / conflict)
  * severity scoring (deterministic)
  * churn risk scoring per user (deterministic + optional LLM rationale)
* **Aggregate tables** for daily + version + category + issue.
* **LLM insight reports** generated on-demand and cached (weekly brief, release diff, sprint backlog, etc.).
* **Gradio dashboard** reads aggregates + drilldowns + calls insight generators.

**Tech choices (simple MVP):**

* **DuckDB** (recommended) for analytics queries + fast local aggregation.
* **Ollama (Llama 3.2)** for all GenAI features and adjudication.
* **Python** pipeline (pandas + duckdb + pydantic/jsonschema for validation).
* **Gradio** for dashboard.

> Note: I’m borrowing the “MVP blueprint discipline” style you used in your earlier plan doc (clear repo structure, validators, deterministic steps) 

---

## 3. Repo Structure

```
review-intelligence-llm-nlp-mvp/
├── app/
│   ├── gradio_app.py
│   ├── ui/
│   │   ├── components.py
│   │   └── plots.py
│   ├── services/
│   │   ├── insights_service.py
│   │   ├── search_service.py
│   │   └── report_cache.py
│   └── config.py
├── pipeline/
│   ├── 00_ingest.py
│   ├── 01_normalize.py
│   ├── 02_enrich_sentiment.py
│   ├── 03_enrich_issues.py
│   ├── 04_score_severity.py
│   ├── 05_user_churn.py
│   ├── 06_aggregates_daily.py
│   ├── 07_aggregates_version.py
│   ├── 08_trends_anomalies.py
│   └── 09_insight_materialization.py
├── llm/
│   ├── ollama_client.py
│   ├── json_enforcer.py
│   ├── prompts/
│   │   ├── sentiment_adjudicator.md
│   │   ├── issues_multilabel.md
│   │   ├── weekly_exec_brief.md
│   │   ├── release_diff.md
│   │   └── ... (one file per GenAI feature)
│   └── schemas/
│       ├── sentiment.schema.json
│       ├── issues.schema.json
│       ├── insight_report.schema.json
│       └── ... (one schema per feature output)
├── analytics/
│   ├── kpi_definitions.py
│   ├── sql/
│   │   ├── daily_kpis.sql
│   │   ├── version_breakdown.sql
│   │   └── drilldowns.sql
│   └── evidence_quotes.py
├── data/
│   ├── input/
│   │   └── reviews.csv
│   ├── db/
│   │   └── reviews.duckdb
│   └── golden_set/
│       ├── labeled_200.csv
│       └── expected_outputs.json
├── scripts/
│   ├── run_pipeline.sh
│   └── run_app.sh
├── tests/
│   ├── test_schema_validation.py
│   ├── test_kpi_sanity.py
│   └── test_llm_json_retry.py
├── README.md
└── requirements.txt
```

---

## 4. Data Contracts & Schemas

### 4.1 Input schema (CSV → reviews_raw)

**CSV fields (given):**

* `reviewId` (string)
* `userName` (string)
* `content` (string)
* `score` (int 1–5)
* `thumbsUpCount` (int)
* `reviewCreatedVersion` (string)
* `at` (date or datetime string)
* `appVersion` (string)
* `category` (string)  ← “already categorised data”

### 4.2 DuckDB tables (exact)

#### `reviews_raw`

| column                 |      type | notes                |
| ---------------------- | --------: | -------------------- |
| review_id              |   VARCHAR | from reviewId        |
| user_name              |   VARCHAR | from userName        |
| content                |   VARCHAR | raw text             |
| score                  |   INTEGER | 1–5                  |
| thumbs_up              |   INTEGER | thumbsUpCount        |
| review_created_version |   VARCHAR | reviewCreatedVersion |
| at_ts                  | TIMESTAMP | parsed from at       |
| app_version            |   VARCHAR | appVersion           |
| category_raw           |   VARCHAR | category             |

Primary key: `review_id`

#### `reviews_enriched`

| column               |      type | notes                                         |
| -------------------- | --------: | --------------------------------------------- |
| review_id            |   VARCHAR | FK to raw                                     |
| category_taxonomy    |   VARCHAR | mapped taxonomy name                          |
| sentiment_label      |   VARCHAR | positive/neutral/negative                     |
| sentiment_confidence |    DOUBLE | 0–1                                           |
| sentiment_method     |   VARCHAR | rule / llm / hybrid                           |
| issues_json          |   VARCHAR | JSON string (array of labels with confidence) |
| issues_method        |   VARCHAR | rule / llm / hybrid                           |
| severity_score       |    DOUBLE | 0–1                                           |
| severity_band        |   VARCHAR | low/med/high/critical                         |
| churn_user_score     |    DOUBLE | 0–1 (nullable)                                |
| churn_user_tier      |   VARCHAR | low/med/high (nullable)                       |
| churn_user_rationale |   VARCHAR | short text (nullable)                         |
| processed_at         | TIMESTAMP | pipeline timestamp                            |

Primary key: `review_id`

#### `daily_aggregates`

| column             |    type |
| ------------------ | ------: |
| day                |    DATE |
| total_reviews      | INTEGER |
| avg_rating         |  DOUBLE |
| pct_negative       |  DOUBLE |
| pct_positive       |  DOUBLE |
| critical_count     | INTEGER |
| top_issues_json    | VARCHAR |
| churn_high_users   | INTEGER |
| anomaly_flags_json | VARCHAR |

Primary key: `day`

#### `version_aggregates`

| column                  |    type |
| ----------------------- | ------: |
| app_version             | VARCHAR |
| first_seen_day          |    DATE |
| last_seen_day           |    DATE |
| total_reviews           | INTEGER |
| avg_rating              |  DOUBLE |
| pct_negative            |  DOUBLE |
| critical_count          | INTEGER |
| issue_breakdown_json    | VARCHAR |
| category_breakdown_json | VARCHAR |

Primary key: `app_version`

#### `insight_reports`

| column       |      type |                                              |
| ------------ | --------: | -------------------------------------------- |
| report_id    |   VARCHAR |                                              |
| report_type  |   VARCHAR |                                              |
| scope_json   |   VARCHAR | filters used (date range, version, category) |
| content_json |   VARCHAR | strict JSON output of the feature            |
| created_at   | TIMESTAMP |                                              |
| model        |   VARCHAR | llama3.2                                     |
| hash_key     |   VARCHAR | for caching                                  |

Primary key: `report_id`, unique: `hash_key`

### 4.3 Taxonomy mapping file

`analytics/taxonomy_map.json` (example)

```json
{
  "account_balance": "Account & Balance",
  "card_management": "Card Management",
  "money_transfers": "Payments & Transfers",
  "login": "Login & Authentication"
}
```

---

## 5. Step-by-Step Pipeline (Ingestion → Storage → Processing → Analytics → LLM Insights)

### 5.1 Pipeline step 00: Ingest CSV → `reviews_raw`

* Read `data/input/reviews.csv`
* Standardize column names
* Parse `at` into `at_ts` (timezone-naive OK)
* Deduplicate by `reviewId` (keep latest `at` if duplicates)
* Write to DuckDB: `reviews_raw`

### 5.2 Step 01: Normalize + cleaning

* `content_clean = strip + normalize whitespace`
* Drop rows with empty content (or keep but mark `content_empty=1`)
* Create derived columns:

  * `day = DATE(at_ts)`
  * `week = ISO week` (optional)
* Store in DuckDB as views or computed in queries.

### 5.3 Step 02: Sentiment Classification (rule-based + LLM adjudication)

**Rule score (deterministic):**

* Start from rating:

  * if score in {1,2} → negative prior
  * if score == 3 → neutral prior
  * if score in {4,5} → positive prior
* Lexicon hits:

  * negative words (e.g., “terrible”, “doesn’t work”, “failed”, “worst”, “scam”, “uninstall”)
  * positive words (e.g., “great”, “love”, “smooth”, “fast”, “amazing”)
* Negation handling: “not good”, “never works”
* Output:

  * `sent_rule_label`
  * `sent_rule_confidence` based on margin

**LLM adjudication trigger (only when needed):**

* If rule confidence < 0.70 OR rating conflicts with text signal OR content very short but extreme rating.
* Call Llama to return strict JSON sentiment.
* Combine:

  * if LLM called: `sentiment_method=hybrid`, final confidence = max(rule, llm) but penalize if disagreement.

**Example output JSON (sentiment):**

```json
{
  "sentiment_label": "negative",
  "confidence": 0.86,
  "reasons": ["Mentions failures", "Strong negative language"],
  "signals": {"rating_prior": 0.2, "lexicon_score": -0.7}
}
```

### 5.4 Step 03: Issue Classification (multi-label, hybrid)

**Rule pass:**

* For each issue label, maintain a keyword/regex set (+ synonyms).
* Produce candidates with base confidence:

  * 0.60 if direct keyword match
  * +0.10 if multiple matches
  * +0.10 if “can’t / failed / error” occurs near keyword
  * cap at 0.85

**LLM pass trigger:**

* If no labels found OR too many (>4) OR content ambiguous OR conflicts with `category_raw`.
* LLM returns labels with confidence + evidence spans (quotes).

**Store** `issues_json` as array:

```json
[
  {"label":"Transaction Failure","confidence":0.91,"evidence":["payment failed","transfer not going through"]},
  {"label":"Customer Support","confidence":0.63,"evidence":["support never responds"]}
]
```

### 5.5 Step 04: Severity Scoring (0–1)

Deterministic formula (see Section 6).
Also store bands:

* 0.00–0.29 = low
* 0.30–0.59 = medium
* 0.60–0.79 = high
* 0.80–1.00 = critical

### 5.6 Step 05: Churn Risk (user-level heuristic + optional LLM rationale)

Aggregate per `user_name`:

* Count reviews
* % negative
* avg severity
* repeat transaction failures count
* churn intent mentions (“uninstall”, “cancel”, “close account”, “switching”)
  Compute churn risk score (deterministic).
  Optionally LLM produces short rationale for top N risky users (to keep compute low).

### 5.7 Step 06: Aggregates (daily)

Compute:

* totals, avg rating, sentiment mix
* critical_count
* top issues (by weighted severity)
* churn high users count
  Store into `daily_aggregates`.

### 5.8 Step 07: Aggregates (version-wise)

For each `app_version`:

* first_seen_day, last_seen_day
* avg rating, pct negative, critical_count
* issue breakdown JSON
  Store into `version_aggregates`.

### 5.9 Step 08: Trend detection + anomalies

* Rolling 7-day moving average for key KPIs
* z-score spikes on:

  * pct_negative
  * critical_count
  * Transaction Failure count
* Version comparison (release-to-release deltas)
  Store anomaly flags in `daily_aggregates.anomaly_flags_json`.

### 5.10 Step 09: Insight materialization + caching

* Generate scheduled reports:

  * Weekly Executive Brief (every run)
  * Weekly Top Issues (every run)
* Cache everything in `insight_reports` keyed by `(type + scope hash)`.

---

## 6. KPI Definitions (exact formulas)

Let:

* `N = total reviews in scope`
* `neg = count(sentiment_label='negative')`
* `pos = count(sentiment_label='positive')`
* `crit = count(severity_score >= 0.80)`
* `rating_avg = avg(score)`
* `issue_count(label) = number of reviews where issues_json contains label`
* `issue_weighted(label) = sum(severity_score for reviews containing label)`

### Required KPIs

1. **% Negative Reviews (weekly trend)**
   For each day `d`:

* `pct_negative_d = neg_d / N_d`
  Weekly view uses 7-day MA:
* `pct_negative_7dma(d) = mean(pct_negative_{d-6..d})`

2. **Top 5 issue categories (issue labels)**
   Rank labels by `issue_weighted(label)` descending. Return top 5.

3. **Critical severity count**

* `critical_count = count(severity_score >= 0.80)`

4. **Churn risk distribution**
   For users in scope:

* `churn_risk_score_u ∈ [0,1]`
  Buckets:
* low: <0.33
* medium: 0.33–0.66
* high: >0.66
  Display histogram: `% users in each bucket`.

5. **App rating trend**
   Daily avg:

* `avg_rating_d = avg(score for day d)`
  7DMA similarly.

6. **Version-wise issue breakdown**
   For each app_version `v`, for each issue label `L`:

* `pct_issue(v, L) = issue_count(v,L) / N_v`
  Also show delta vs previous version:
* `delta_pct_issue = pct_issue(v,L) - pct_issue(prev_v,L)`

7. **Bug-to-release resolution lag (approximate)**
   For each issue label `L`:

* `first_seen_day(L) = min(day where issue_count(day,L)>0)`
* `last_seen_day(L) = max(day where issue_count(day,L)>0)`
* `resolution_lag_days(L) = last_seen_day - first_seen_day`
  **Limitation note in UI:** this is “observed in reviews”, not true fix date.

### Severity formula (exact)

Define components:

* `r = (5 - score) / 4`  (score=1 → 1.0, score=5 → 0.0)
* `s = sentiment_component`:

  * negative → 1.0
  * neutral → 0.4
  * positive → 0.1
* `f = failure_component`:

  * 1.0 if any of {“failed”, “error”, “declined”, “not working”, “stuck”, “crash”, “can’t”, “unable”}
  * else 0.0
* `t = thumbs_component = min(1.0, log(1 + thumbsUpCount) / log(1 + 50))`
* `c = critical_issue_component`:

  * 1.0 if labels include Transaction Failure or Login/Auth Issues
  * 0.5 if Performance Issues or Glitches/Bugs
  * 0.3 otherwise

Final:

* `severity_score = clamp(0,1, 0.35*r + 0.25*s + 0.15*f + 0.15*c + 0.10*t )`

---

## 7. GenAI Features (at least 12)

### Shared: Ollama wrapper + JSON enforcement (required)

**Pseudo-code:**

```python
# llm/ollama_client.py
import json, time, requests

def call_ollama(model: str, system: str, user: str, temperature: float = 0.2) -> str:
    payload = {
        "model": model,
        "messages": [{"role":"system","content":system},{"role":"user","content":user}],
        "stream": False,
        "options": {"temperature": temperature}
    }
    r = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"]

# llm/json_enforcer.py
def call_json_with_retry(schema_validator, *args, max_retries=3):
    last = None
    for attempt in range(max_retries):
        txt = call_ollama(*args)
        try:
            obj = json.loads(txt)
            schema_validator(obj)   # pydantic or jsonschema validate
            return obj
        except Exception as e:
            last = (txt, str(e))
            # add repair instruction on retry
            args = (args[0], args[1], args[2] + f"\n\nRETRY: Return ONLY valid JSON. Error: {e}")
            time.sleep(0.2)
    raise ValueError(f"Invalid JSON after retries: {last}")
```

**Model:** `llama3.2` (via Ollama)

---

Below, each feature includes: what/why/UI + prompt templates + output schema.

---

### 7.1 Weekly Executive Brief

**What:** C-level narrative summary of the last 7 days with KPIs, drivers, risks, and recommended actions.
**Why valuable:** instantly “executive-looking” output.
**UI:** Tab “Executive Brief” + button “Generate”.

**SYSTEM prompt (template):**

* Role: Executive analyst. Output strict JSON only. No markdown. Cite evidence by quoting short snippets.

**USER prompt (template):**

* Provide KPI snapshot JSON + top issues + anomaly flags + 10 evidence reviews.

**Expected output JSON schema:**

```json
{
  "week_range": "YYYY-MM-DD..YYYY-MM-DD",
  "headline": "string",
  "kpi_summary": {
    "avg_rating": 0.0,
    "pct_negative": 0.0,
    "critical_count": 0
  },
  "drivers": [{"title":"string","impact":"high|med|low","evidence_quotes":["..."]}],
  "risks": [{"risk":"string","signal":"string","severity":"high|med|low"}],
  "recommendations": [{"action":"string","owner":"PM|Eng|Support","expected_impact":"string"}]
}
```

---

### 7.2 “What changed since last version?” (Release Comparison)

**What:** Compare two versions’ KPI + issue deltas; explain likely causes.
**UI:** Tab “Release Diff” → dropdown version A/B.

**Output schema:**

```json
{
  "version_a":"string",
  "version_b":"string",
  "kpi_delta":{"avg_rating":0.0,"pct_negative":0.0,"critical_count":0},
  "issue_deltas":[{"label":"string","delta_pct":0.0,"interpretation":"string","evidence_quotes":["..."]}],
  "top_regressions":["string"],
  "top_improvements":["string"]
}
```

---

### 7.3 Top Customer Pain Points (with evidence)

**What:** Top pain points ranked by weighted severity, with quotes + affected areas.
**UI:** Tab “Pain Points” with table + “Generate narrative”.

Schema:

```json
{
  "pain_points":[
    {"rank":1,"pain_point":"string","labels":["..."],"estimated_impact":"string","evidence_quotes":["..."]}
  ]
}
```

---

### 7.4 Suggested Sprint Backlog Generator

**What:** Converts insights into ticket list with titles, acceptance criteria, severity, and evidence.
**UI:** Tab “Sprint Planner” with export JSON.

Schema:

```json
{
  "tickets":[
    {
      "title":"string",
      "type":"bug|improvement|feature",
      "priority":"P0|P1|P2|P3",
      "severity_score":0.0,
      "impact_notes":"string",
      "acceptance_criteria":["string"],
      "evidence_quotes":["string"],
      "related_labels":["string"],
      "related_versions":["string"]
    }
  ]
}
```

---

### 7.5 Root-Cause Hypothesis Generator

**What:** LLM proposes plausible technical root causes (no hallucinated certainty), suggests instrumentation.
**UI:** Inside “Sprint Planner” as “Root cause hints”.

Schema:

```json
{
  "hypotheses":[
    {"hypothesis":"string","confidence":"low|med|high","why":"string","suggested_logs":["string"],"suggested_metrics":["string"]}
  ]
}
```

---

### 7.6 Auto PRD Snippet Generator

**What:** Produces PM-ready PRD bullets for top issues/features.
**UI:** Tab “PRD Builder”.

Schema:

```json
{
  "prd_items":[
    {"problem":"string","user_story":"string","success_metrics":["string"],"scope":["string"],"out_of_scope":["string"]}
  ]
}
```

---

### 7.7 Support Macro Drafts

**What:** Drafts support replies per top complaint type with empathy + steps.
**UI:** Tab “Support Tools”.

Schema:

```json
{
  "macros":[
    {"scenario":"string","macro_text":"string","dos":["string"],"donts":["string"]}
  ]
}
```

---

### 7.8 Bug Reproduction Hints

**What:** Extracts steps-to-repro from reviews and groups them.
**UI:** Tab “Engineering Tools”.

Schema:

```json
{
  "repro_groups":[
    {"label":"string","steps":["string"],"devices_or_context":["string"],"evidence_quotes":["string"]}
  ]
}
```

---

### 7.9 Risk Radar (Emerging issues)

**What:** Detects emerging spikes/anomalies and narrates risk outlook.
**UI:** Tab “Risk Radar” with anomaly list + “Generate”.

Schema:

```json
{
  "emerging_risks":[
    {"risk":"string","signal":"string","trend":"rising|stable|falling","recommended_action":"string","evidence_quotes":["string"]}
  ]
}
```

---

### 7.10 Feature Request Summarizer + Priority

**What:** Summarizes feature requests and prioritizes by severity-weighted demand + thumbsUp.
**UI:** Tab “Feature Requests”.

Schema:

```json
{
  "requests":[
    {"request":"string","priority":"high|med|low","why":"string","evidence_quotes":["string"],"related_categories":["string"]}
  ]
}
```

---

### 7.11 Policy Complaint Analyzer

**What:** Finds policy-related complaints (fees, pricing, verification), suggests policy copy improvements.
**UI:** Tab “Policy & Trust”.

Schema:

```json
{
  "policy_issues":[
    {"theme":"string","what_users_say":"string","risk":"string","copy_suggestion":"string","evidence_quotes":["string"]}
  ]
}
```

---

### 7.12 Competitor Mention Extraction

**What:** Extract competitor names + comparisons (better/worse) and what users value.
**UI:** Tab “Competitive Intel”.

Schema:

```json
{
  "competitors":[
    {"name":"string","mentions":0,"sentiment":"positive|neutral|negative","why_users_compare":["string"],"evidence_quotes":["string"]}
  ]
}
```

---

### 7.13 Persona-based Summaries (CEO vs PM vs Eng)

**What:** Same data, three different narratives.
**UI:** Tab “Persona View” with selector.

Schema:

```json
{
  "persona":"CEO|PM|Eng|Support",
  "summary":"string",
  "top_actions":[{"action":"string","owner":"string"}]
}
```

---

### 7.14 “Explain this spike” (Anomaly explainer)

**What:** When z-score anomaly triggers, explain likely drivers using evidence reviews.
**UI:** click anomaly → “Explain”.

Schema:

```json
{
  "anomaly_date":"YYYY-MM-DD",
  "metric":"string",
  "z_score":0.0,
  "likely_drivers":[{"driver":"string","evidence_quotes":["string"]}],
  "recommended_next_steps":["string"]
}
```

---

### 7.15 “Board Slide Ready” Summary (1-page)

**What:** Generates a concise, slide-like JSON structure you can paste into slides.
**UI:** Tab “Export”.

Schema:

```json
{
  "title":"string",
  "bullets":["string"],
  "kpi_tiles":[{"label":"string","value":"string","delta":"string"}],
  "top_risks":["string"],
  "top_actions":["string"]
}
```

> Implementation note: each of the above features is a **prompt file + JSON schema file + service function** in `app/services/insights_service.py`.

---

## 8. Gradio Dashboard Spec (tabs, components, user flows)

### 8.1 Layout (tabs)

1. **Overview**

* KPI tiles: avg rating, % negative, critical count, churn high users
* Line charts: rating trend, % negative trend, critical count trend
* Table: Top 5 issues (weighted)

2. **Trends & Anomalies**

* anomaly list (date, metric, z-score)
* click → “Explain spike” (GenAI)

3. **Issues Drilldown**

* filters: date range, category_taxonomy, issue label, version
* table: reviews with sentiment, severity, issues, thumbsUp
* “Evidence quotes” panel (top N excerpts)

4. **Release Diff**

* version A/B dropdown
* delta table + “Generate release narrative”

5. **Sprint Planner**

* “Generate backlog” button
* ticket table + export JSON
* root-cause hypotheses panel

6. **Executive Brief**

* weekly brief generator
* persona selector (CEO/PM/Eng/Support)

7. **Support Tools**

* support macros
* policy complaint analyzer

8. **Competitive Intel**

* competitor extraction + summary

9. **Feature Requests**

* feature request summary + priority list

### 8.2 User flow (fast)

* Open Overview → pick last 7 days
* Click Top Issue → jump to Issues Drilldown
* Click Anomaly → get explanation
* Go to Sprint Planner → generate tickets
* Go to Executive Brief → generate narrative

---

## 9. Implementation Plan (sequenced tasks with time estimates per step removed; just ordered steps)

### Day 1 — Data foundation + KPIs

1. Create repo structure + requirements
2. Implement DuckDB connection + migrations (create tables)
3. Build `00_ingest.py` (CSV → reviews_raw) + dedupe + date parsing
4. Build `01_normalize.py` (basic cleaning)
5. Implement taxonomy mapping + populate `category_taxonomy`
6. Implement KPI SQL queries + write to `daily_aggregates`, `version_aggregates`
7. Basic Gradio “Overview” tab reading from aggregates

### Day 2 — Enrichment (sentiment/issues/severity/churn)

8. Implement rule-based sentiment + triggers
9. Implement Ollama wrapper + JSON enforcer + schema validation
10. Implement sentiment LLM adjudication + store in `reviews_enriched`
11. Implement rule-based issue labeling + triggers
12. Implement issue LLM multi-label classifier + store `issues_json`
13. Implement severity scoring formula + bands
14. Implement churn heuristic per user + store fields

### Day 3 — GenAI “feature-rich” dashboard

15. Implement insight caching table + hash key
16. Implement core GenAI features: Weekly Brief, Release Diff, Sprint Backlog, Spike Explainer
17. Implement remaining GenAI tabs (Support, Competitive, Feature Requests, Policy)
18. Add drilldowns with evidence quotes + filters
19. Add export buttons (JSON download / copy-to-clipboard text)
20. Final pass: golden set evaluation + sanity tests + demo rehearsal

---

## 10. Testing & Evaluation (quick checks + golden set)

### 10.1 Golden set (manual labels)

* Create `data/golden_set/labeled_200.csv` with columns:

  * `review_id`, `gold_sentiment`, `gold_issue_labels` (comma-separated), `gold_severity_band`
* Sample stratified by score and category.

### 10.2 Checks (no model training; just quality validation)

1. **Schema validation**: every enriched row has valid JSON in `issues_json` and expected enums
2. **Sentiment sanity**:

   * score=1 should be negative ≥ 85% of time (rule+llm)
   * score=5 should be positive ≥ 85% of time
3. **Issue label sanity**:

   * Transaction Failure label should correlate with low scores & high severity
4. **Severity monotonicity**:

   * average severity(score=1) > average severity(score=5)
5. **Golden set spot metrics** (simple):

   * sentiment accuracy on 200 labeled
   * issue label precision@k (k=2) on 200 labeled (manual review)
6. **LLM JSON retry test**:

   * inject invalid JSON response mock; ensure retry repairs

---

## 11. Risks & Mitigations

1. **LLM outputs invalid JSON**
   Mitigation: strict JSON schema validation + retry + “repair” instruction.

2. **Cost/latency too high if LLM called for every review**
   Mitigation: LLM only on **uncertain/conflict** cases; cache adjudication; batch processing.

3. **Keyword rules miss slang/typos**
   Mitigation: expand lexicons iteratively using “unknown bucket” reviews + LLM suggested synonyms (offline, curated).

4. **Churn risk is weak due to limited user signal**
   Mitigation: clearly label as *heuristic*; focus on explainability (rationale + evidence).

5. **Version comparison unreliable if versions missing/dirty**
   Mitigation: normalize version strings; provide “insufficient data” fallback in UI.

6. **Insights feel generic**
   Mitigation: always include **KPI deltas + evidence quotes + recommended actions with owners**.

---

## 12. Demo Script (5–7 minutes)

1. **(0:00–0:45) Overview**
   “Last 7 days: avg rating, % negative, critical count, churn high users. Here are the trends.”

2. **(0:45–1:45) What’s driving it**
   “Top issues by weighted severity. Click ‘Transaction Failure’ → see evidence quotes + severity distribution.”

3. **(1:45–2:45) Spike explanation**
   “Here’s an anomaly on Feb X: click ‘Explain spike’ → drivers + quotes + next steps.”

4. **(2:45–4:00) Release Diff**
   “Compare version A vs B → issue deltas + regressions + improvements + narrative.”

5. **(4:00–5:30) Sprint Planner**
   “Generate backlog → shows P0/P1 tickets, acceptance criteria, evidence, root-cause hypotheses.”

6. **(5:30–6:30) Executive Brief + Persona view**
   “Weekly Executive Brief for CEO; switch persona to Engineering for action-focused summary.”

7. **(6:30–7:00) Close**
   “This MVP is pipeline-first, KPI-first, and GenAI-heavy—ready to expand into Phase 2 clustering/semantic search.”

---

If you want, I can also generate **starter prompt files + JSON schemas** (one per feature) in a copy-paste-ready format for your repo.
