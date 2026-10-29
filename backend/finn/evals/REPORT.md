# How we checked FINN's AI output

A language model can give a different answer each time it is asked, and a wrong answer can
read just as well as a right one. So "the output looks good" is not evidence. We asked four
questions of everything the models write, and answered each with a check that does not
depend on trusting the model:

| Question | How it is checked |
|---|---|
| **Is it right?** | Triage labels compared with labels made by hand, by reading 19 full filings. |
| **Is it made up?** | Code looks up every quote, number and name in the source document. Then a second model, from another family, reads source and output side by side. |
| **Is it useful?** | "Why it matters" must add a specific fact, not repeat the summary or say something true of every filing. |
| **Is it repeatable?** | The same prompts are run three times with the cache bypassed, and the answers compared. |

Run it yourself:

```
uv run python -m finn.evals triage      # golden set, 3 fresh runs, code and second-model checks
uv run python -m finn.evals research    # every shipped report and answer: quotes and numbers
uv run python -m finn.evals stability   # the full research pipeline, 3 times
```

Every result, with every flag, is saved in `results/`. The numbers below come from those
files, run on 28 and 29 October 2026.

---

## 1. Push cards: is the label right?

19 filings were drawn at random (seed 7) from the month's filings, with a quota per
category so that rare kinds appear. Each was labelled by reading the whole filing,
annexures included, against FINN's own tier definitions. Where two labels are both
defensible, both count as right; `golden_triage.json` gives the reason for each.

The app's data is written by the scheduled cloud refresh, which keeps its own database.
So we scored three things: what the app shows, what the same code produced in a local
run, and three fresh runs with the cache bypassed.

| Answers | Category right | Tier right | Both right |
|---|---|---|---|
| **Shown in the app** (cloud refresh, 28 Oct 15:02 UTC) | 17 of 19 | 17 of 19 | **15 of 19** |
| Same code, local run | 19 of 19 | 17 of 19 | 17 of 19 |
| Fresh run 1 | 18 of 19 | 18 of 19 | 17 of 19 |
| Fresh run 2 | 18 of 19 | 18 of 19 | 17 of 19 |
| Fresh run 3 | 18 of 19 | 18 of 19 | 17 of 19 |

The misses in the app:

- **Ola Electric's ₹1,000 crore rights issue is shown at "glance".** Its own "why it
  matters" says the raise is over half of annual revenue, so the tier contradicts the
  text. All three fresh runs said must-see.
- **Adani's MoU with Jabil is shown as must-see.** It is a non-binding MoU with no
  amount. This answer came from the Groq fallback, used when Gemini was busy.
- **Two categories are wrong.** Paytm's "board meeting closed at 10:15 pm" is called a
  management change. HDFC Bank's newspaper notice on transferring physical shares is
  called a postal ballot.

The misses elsewhere:

- **Dixon's guarantee** of up to US$7 million for a subsidiary was rated must-see in the
  local run and in all three fresh runs. It is about ₹60 crore against revenue of about
  ₹51,600 crore. The amount sat in an annexure past the 1,800 characters the model reads,
  so it judged blind. Fixed: see section 6.
- **Airtel's two DoT penalties** (₹1.41 lakh and ₹2.12 lakh) were rated must-see in the
  local run, by Flash-Lite standing in while Flash was busy. Flash rated them routine
  every time, which is right.
- **HDFC Bank's quarterly business update** was called "unclassified" in all three fresh
  runs; our label accepts "press release" or "results". Defensible either way, and no label
  was moved after seeing the answers.

## 2. Is it made up?

### Push cards

Code checked every number and name in every AI answer against what the model was given
and the full filing: 125 answers in the app, and 126 from the local run.

| Flag | What it was | Verdict |
|---|---|---|
| Ola "over 50%" / "53%", Sun Pharma "16.7%", eMudhra "4.70%", Mazagon "nearly 10%" of revenue | The model's own division | Correct |
| Maruti production "up about 19.9%" | 242,011 against 201,915 | Correct |
| **Polycab "~0.00008% of revenue"** (local run) | ₹2.79 crore ÷ ₹34,609 crore is **0.008%** | **Wrong by 100×.** Fixed: code now checks every share of revenue |
| **Adani "facilities totalling ₹25,749.96 crore"** (app) | The filing prints no total; no sum of its rows gives this | **Wrong: the model added the rows itself, against the rules** |
| Nazara "Rohit Sharma" | The scanned letter reads "Roh it Shanna" | Correct: the model repaired the OCR |
| "PAT", "MD", "NCD", "Sri Lankan" | Abbreviations, or a word form the source uses ("Sri Lanka") | Checker false alarm |

Reading the golden set by hand found an error the code check could not: the excerpt was
cut inside a number, so Airtel's "Rs.1,41,000" reached the model as "Rs.1,41". All three
fresh runs wrote "a penalty of Rs.1,41". The app's card says instead that "the full amount
is truncated in the text", which is honest but unhelpful. Code found the figure "in the
source" because the broken figure *was* the source. Fixed: section 6.

The second model (Groq's gpt-oss-120b; FINN writes with Gemini) read the 19 answers shown
in the app against the full filing:

- **Relevant:** 18 of 19 summaries say what happened. The 19th is Airtel's "amount is
  truncated".
- **Why it matters adds a fact:** 6 of the 7 written.
- **Tier fair:** 14 of 19. Ola's rights issue and Dixon's guarantee are FINN's real misses.
  Two disagree with FINN's rule that a results press release is worth a glance, because
  the results statement itself is the must-see. One wants HDFC Bank's business update
  higher.
- **Wrong or unsupported statements:** flagged in 7.
  - Real, both minor: Sun Pharma's title says its NCD ratings were "reaffirmed", but the
    new NCDs were *assigned* a rating. And Airtel's "truncated" line.
  - The checker's own errors: Polycab's 52.8% growth against the press release's rounded
    53% (FINN uses the exact exchange figures); Anup Bagchi's ICICI background (FINN was
    given it from his appointment filing); Sun's Organon acquisition (the filing names it);
    "Q2 FY27" for the quarter ended 30 September 2026, twice.
  - Ola's "over half of annual revenue": correct.

### Research reports and "Was this expected?" answers

All 23 shipped research reports and 12 answers. The reports were checked twice: as first
shipped (28 October), and after 20 of them were rebuilt with the fixes in section 6
(29 October; `results/research-rebuilt.json`).

| | 28 October | 29 October, rebuilt |
|---|---|---|
| Quotes found word for word, on the page cited | **495 of 495** | **472 of 472** |
| Evidence lines that are figures code computed (labelled so; not quotes) | 31 | 30 |
| The same quote cited twice in one point | 5 | 0 |
| Numbers checked | 1,134 | 1,202 |

Where each number was found, on 29 October:

| Where the number was found | Count |
|---|---|
| In the quote it cites, or in figures code computed from the accounts | 1,051 |
| The same, in another unit (₹36,940 crore from "369.4 billion rupees"); all 25 read by hand and correct | 25 |
| Not in the quote it cites, but in the company's own documents | 122 |
| Nowhere; all 4 read by hand and correct | 4 |

The 4 "nowhere" numbers are conversions the checker cannot do: 11 lakh as ₹0.11 crore,
both ends of a 0.60–0.70% range, and HDFC Bank's contingent liabilities as ₹34.17 lakh
crore, from an annual-report table printed in ₹ thousands (34,179,458,972).

Of the 122, 49 are precise figures (100 or more, or with decimals), which are strong
evidence; 73 are small whole numbers such as 2 or 10, which prove little on their own.

The checks start from the quote, not from what the model says about it. A promise's target
is the model's reading of its quote, so the target is checked against the quote too, not
trusted.

The second model read all 455 claims in the 28 October reports with the quotes they cite
(the rebuilt reports were checked by code only). It was run twice; its own
answers changed between runs (324 / 111 / 20 for yes / partly / no, then 318 / 113 / 24).
So its flags are leads for a person, not verdicts. **All 31 different "no" verdicts were
read against the documents:**

- **No false fact was found.**
- 2 points use stronger words than their evidence: Airtel's capex as "multi-year data
  centre expansion", its legal exposure as "significant".
- 7 are true, but the sentence that proves them sits next to the quote rather than in it.
  Polycab's "we have always guided that we will do 1.5x of market growth" comes just
  before the quoted words. eMudhra's ₹75–80 crore capex was an analyst's figure that
  management confirmed with "Right". Eternal's $1 billion target was named in the question,
  and the answer was "We maintain that guidance". Ola's "gross-margin target is around
  30-32%" comes later in the same call.
- 16 rest on the annual-report page around the quote. 13 attribute a point to the auditors
  ("a key audit matter", "an emphasis of matter", CARO remarks), and in each the cited page
  is in the auditor's report and uses those words. 3 name what the page names: the
  Competition Commission, the subsidiaries in a related-party resolution, the
  contingent-liability note.
- 2 are unit errors by the checker: annual-report tables printed in ₹ thousands.
- 1 is checked against figures code computed: Mazagon Dock's FY26 revenue against its
  targets.
- 3 are answers whose numbers come from the Push card's results (code confirms them), or
  that say management did *not* discuss something, which no quote can show.

Most "partly" verdicts (58 of 113) say the quote does not name the period ("FY26"). That is
by design: code assigns the period from the call's date.

## 3. Is it useful?

On the 19 golden filings, "why it matters" was left empty in 12 of the answers in the app
(11 in the local run). That is the prompt working: it must be left empty rather than say
something generic. Where it was written, 6 of 7 in the app carried a specific figure or
name (7 of 7 locally), and none repeated the summary. In the fresh runs, 0 to 2 per run
repeated the summary.

## 4. Is it repeatable?

**Triage**, three fresh runs of the same batches:

- 16 of 19 filings got the same category and tier all three times.
- All 3 that moved stayed inside the labels counted right: Polycab's court-hearing notice
  and Sun Pharma's professorship press release moved between routine and glance, and
  Paytm's board-meeting notice between "unclassified" and "results".
- No run changed whether an answer was right.

**Production is less steady than that.** The app's answers and the local run's answers
come from the same prompt (version 7), but they were made on different days, and
different models answered: Flash, Flash-Lite standing in when Flash was busy, or the Groq
fallback. They disagree on **8 of the 19** filings:

| Which answer was right | Filings |
|---|---|
| The app's, not the local run's | 2: Dixon, Airtel |
| The local run's, not the app's | 4: Ola's rights issue, Adani's MoU, Paytm, HDFC's notice |
| Both acceptable | 2 |

The controlled test gives each filing the same model three times. Production does not,
so which model answered matters more than the run-to-run noise of any one model. Two
things follow from this:

1. An important filing answered by Flash-Lite standing in is already asked again until
   Flash answers. The Groq fallback's answers are not: they are cached as final. Treating
   them as stand-ins too is the next step. The cache already marks them as degraded, so
   this means re-asking past those rows.
2. Re-scoring the app after the version 8 re-read (section 6) tells us whether the fixes
   helped, measured on what users actually see.

**Measured directly: which model answers decides the score.** On the night of 28 October,
Flash's free daily quota ran out, so the golden set ran with only the stand-ins answering
(Flash-Lite and Groq's gpt-oss):

| Who answered | Both labels right | Same answer in all 3 runs |
|---|---|---|
| Flash (28 Oct, afternoon) | 17 of 19 | 16 of 19 |
| Flash-Lite and Groq only (28 Oct, night) | 10 to 12 of 19 | 9 of 19 |

Groq's answers over-rated: it made results press releases, a court-date notice, an MoU
and a credit rating must-see. Flash-Lite again rated Dixon's US$7 million guarantee
must-see. This is why, from version 10, important filings answered by a stand-in are
asked again, of Flash only, until Flash answers. A stand-in's answer stays meanwhile;
an empty card would be worse.

**Research:** the full pipeline (every call read afresh, then judged afresh) was started on
Kaynes and Asian Paints, three runs each. It stopped when the free tier's daily quota ran
out, and was not run again. A full run reads every call afresh, and it draws on the same
free daily quota that the live refresh needs to re-ask Flash about cards a stand-in
answered. On 29 October that quota went to the app and to the rebuild of the 20 reports
above. So research repeatability is **not measured**. What is measured: every quote and
number in every report, as shipped, after each rebuild.

## 5. The checker was checked

A check that is wrong is worse than no check. The first pass flagged 48 numbers as
unsupported. Every one was the checker's fault:

- It missed figures glued to a prefix ("INR1,350", "Rs.594").
- It read "FY27" as the number 27.
- It did not know ₹ thousands.
- It trusted targets the model wrote.

Each fix has a test in `tests/test_evals.py`.

## 6. What the checks found, and what changed

| Found | Change |
|---|---|
| 5 bull or bear points cited the same quote twice (two claims read from one sentence) | Points drop repeats; reports corrected |
| Counts shown as rupees: "100 million passengers" became "₹10 crore", and the same for Dixon's phone volumes | A unit naming a counted thing is not money; 3 targets corrected |
| The excerpt cut inside numbers, and missed amounts in annexures | It ends on a word and adds the passages around later amounts. Airtel's card now sees both penalties, Dixon's the US$7,000,000 |
| A share of revenue 100 times too small | Code recomputes every "% of revenue" the model writes; a wrong one is replaced |
| The refresh schedule had silently stopped | Re-registered, and moved to minutes 7 and 37, off the busy top of the hour |
| A 13 October MoU press release was given the results filed on 28 October | Results figures go only to results filings, and only once the results are out (v9) |
| A share count shown as an amount: the Jio IPO's "27,00,00,000 equity shares" became ₹270,000,000 crore | Code drops an amount over three times annual revenue (v10) |
| An invented total (Adani's ₹25,749.96 crore) | Code drops a "why it matters" line with a figure that is not in the filing, a unit conversion of one, or a sum of two (v10) |
| Ola's ₹1,000 crore raise, 53% of revenue, once rated "glance" | A deal or claim of 5% of revenue or more is at least must-see, whichever model answered (v10) |
| Stand-in answers stuck on important cards | Re-asked of Flash only until Flash answers (v10) |
| A bull point cited a deadline already past as a catalyst | The judge is told today's date; a passed deadline is not a catalyst (judge v3) |
| A guidance revised on a later call showed as two promises | Merged into one, graded on the latest figure, with "Revised from" and both quotes |
| Nothing on screen said when the data stopped updating | Today shows "Updated 19m ago", and an amber line when the data is stale |

All of code's checks on a triage answer now sit in one function, `review()` in
`finn/enrich/triage.py`, which production and this evaluation both call, so the evaluation
scores exactly what production stores. The grounding checks live in `finn/grounding.py`.

**The golden set on version 10** (29 October, 07:20 UTC; `results/triage-v10-flash.json`).
Flash's quota had only partly reset, so in each run Flash answered 6 of its 12 important
filings and Groq stood in for the rest. Split by who answered, across all three runs:

| Who answered | Answers | Both labels right |
|---|---|---|
| Flash | 18 | **16 (89%)** |
| Flash-Lite (routine filings, its own job) | 21 | 13 (62%) |
| Groq, standing in for Flash | 17 | 10 (59%) |

All 7 of Groq's misses are the same mistake: a glance filing rated must-see. That is the
case for the version 10 re-ask, and the reason an answer counts as final only once Flash
gives it. Flash-Lite's misses are mostly one filing: HDFC Bank's business update, called
"investor meetings" every time.

What the version 8 to 10 fixes changed, against version 7:

- **"Why it matters" now says something.** It was left empty in 2 to 5 answers per run,
  down from 11, because the model now sees the amounts later in the filing. It carried a
  specific figure or name in 10 to 13, up from 7.
- **Numbers not in the filing:** 0 or 1 per run, as before.
- **Second model, on 18 shipped answers:** 17 relevant; "why it matters" adds a fact in
  13 of 13. It flagged 3 statements as wrong. Read against the filings, one is real:
  Flash-Lite dated HDFC Bank's figures 30 September 2025 instead of 2026. A year that
  appears elsewhere in the filing passes code's number check, so this one needs the
  second reader. The other two are the checker's errors: Adani's "$100 billion, 5 GW"
  and Sun Pharma's reaffirmed ICRA AAA are both in the filing.

## Limits

- 19 labelled filings is a small set. It catches systematic errors, not rare ones.
- The labels were made by one reader. Where a label could be argued, both answers count.
- Recall was not measured: nobody listed by hand every promise in a transcript, so we know
  the promises FINN found are real, not that it found them all.
- Research repeatability was not measured (section 4).
- LT, Indian Hotels and Reliance kept their 28 October reports: when the rebuild reached
  them, the judge model was at its daily cap, and an incomplete report never replaces a
  complete one.
- The second model is a model. Its flags were read by a person before any was counted.
