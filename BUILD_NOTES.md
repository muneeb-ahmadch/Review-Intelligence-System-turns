# Build notes — pairing with AI on this project

Honest notes on where working with an AI agent changed how I built this. Written
for myself, to talk through in a live conversation. Every bullet maps to
something actually in the repo.

- **I started by having the model audit my own repo, and it caught me
  over-claiming.** `PLAN.md` described 15 GenAI features; the code wired 2. The
  committed database also disagreed with the committed SQL — the DB had
  `churn_high_users = 4669` while `daily_kpis.sql` literally returned `0`. Left
  alone I'd probably have written a README around the *plan*. Instead I cut the
  "what it does" list down to what runs, moved the rest to a clearly-labelled
  Roadmap, and re-ran the pipeline so the DB matches the code. The honesty
  constraint changed the shape of the whole submission.

- **The grounding guardrail is the idea I'm proudest of, and it came out of a
  "how do I make this claim literally true?" conversation.** I wanted to say
  "insights cite real reviews, not hallucinations" and have it survive scrutiny.
  So `llm/grounding.py` does two concrete things after every generation:
  overwrites the KPI numbers in the model's output with the figures I computed in
  DuckDB, and drops any cited quote that isn't a substring of a real review I
  passed in. The model writes prose; it is not allowed to author a number or a
  quote.

- **I deliberately kept the LLM out of the data path, and overrode the easy
  "make it AI-powered" framing.** Sentiment, issues, severity, churn, and
  anomalies are all plain rules/formulas/SQL. It would have been a flashier pitch
  to call sentiment "LLM-powered," but then I couldn't reproduce or test it. The
  split I landed on — deterministic code owns every number, the model only
  narrates and prioritises — is the architectural decision the project is built
  around.

- **The model pushed me to make the LLM layer provider-agnostic; I took the idea
  but made it degrade safely.** Original code was Ollama-only. The brief said
  "read any API key from env," so I added a Claude path (`claude-opus-4-8`) that
  activates on `ANTHROPIC_API_KEY`, falling back to local Ollama, then to a
  deterministic grounded fallback. I couldn't test the Claude path without a key,
  so I made the whole chain fail soft and serve the cached outputs — and I kept
  the README honest that the committed cache was generated with Llama 3.2, not
  Claude.

- **"Run it and look" caught a bug that reading the code didn't.** The dashboard
  defaulted to a 7-day window, but the sample data's last week (Feb 2026) is
  nearly empty, so the app opened on a blank dashboard. I only saw it by
  launching and screenshotting. I changed the default to the full data range so
  the first thing a reviewer sees is populated.

- **A passing test suite still left the database broken — a genuinely surprising
  gotcha.** After `pytest` went green, the churn KPI showed 0. The tests re-run
  early pipeline steps (00,01,02,04) against the shared DuckDB, wiping the issue
  and churn columns that steps 03 and 05 produce. The fix wasn't code — it was
  ordering: re-run the full pipeline as the last step before committing, and I
  documented the trap in the README so the next person isn't fooled by green
  tests.

- **I reasoned my way out of a double-counting trap in the churn KPI.** Summing
  `churn_high_users` across days over the full-range default would count a user
  once per day they reviewed. I switched the tile to `COUNT(DISTINCT user_name)`
  from the enriched table over the window. Small, but it's the difference between
  a number that means something and one that just looks big.

- **The anomaly detector needed a volume guard to not be noise.** A raw 7-day
  z-score over eight years of mostly low-traffic days flags every blip. Requiring
  at least 8 reviews on a day before it can be flagged turned a useless wall of
  alerts into a short, sorted list worth reading (120 days, top deviations
  first). I'd have shipped the noisy version if I hadn't looked at the output.

- **Smallest but realest:** the churn SQL crashed on the word `can't` because the
  apostrophe broke the string literal. Doubling the quote fixed it. Worth
  remembering that the messy real-world data — not the architecture — is usually
  what bites.
