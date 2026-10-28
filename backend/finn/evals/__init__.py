"""Evaluation of FINN's AI output: is it right, is it grounded, is it useful, is it stable?

A language model answers differently from run to run, so one good-looking answer proves
little. Each check here asks a question a code test cannot settle by itself:

- Right: triage labels against a hand-labelled set of filings (golden_triage.json).
- Grounded: every number, name and quote FINN writes must be found in the source it was
  given. Code checks this for every output; a model from another family (Groq's
  gpt-oss-120b, while FINN writes with Gemini) then reads source and output side by side
  for what code cannot see, such as a wrong date or a claim the quote does not make.
- Useful: "why it matters" must add a fact, not repeat the summary or say something true
  of every filing of that kind.
- Stable: the same prompt run three times, with the cache bypassed, should give the same
  labels and the same verdicts.

uv run python -m finn.evals triage      # golden set, 3 fresh runs, code + second-model checks
uv run python -m finn.evals research    # every shipped report and answer: quotes and numbers
uv run python -m finn.evals stability   # research re-run 3 times on two companies
"""
