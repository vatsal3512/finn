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
files, run on 28 October 2026.

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

All 23 shipped research reports and 12 answers:

- **Quotes:** 495 of 495 were found again, word for word, in the source document, on the
  page cited. A further 31 evidence lines are figures code computed from the accounts and
  label as such; they are not quotes.
- **Numbers:** 1,134 numbers in promises, targets, bull and bear points and summaries.

| Where the number was found | Count |
|---|---|
| In the quote it cites, or in figures code computed from the accounts | 994 |
| The same, in another unit (₹713.2 crore from "INR 7,132 million"); all 24 read by hand and correct | 24 |
| Not in the quote it cites, but in the company's own documents | 113 |
| Nowhere; all 3 read by hand: correct conversions (11 lakh = ₹0.11 crore; a 0.60–0.70% range) | 3 |

Of the 113, 42 are precise figures (100 or more, or with decimals), which are strong
evidence; 71 are small whole numbers such as 2 or 10, which prove little on their own.

The checks start from the quote, not from what the model says about it. A promise's target
is the model's reading of its quote, so the target is checked against the quote too, not
trusted.

The second model read all 455 claims with the quotes they cite. It was run twice; its own
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

**Research:** the full pipeline (every call read afresh, then judged afresh) was started on
Kaynes and Asian Paints, three runs each. It stopped when the free tier's daily quota ran
out. *[Results to be added after the quota resets.]*

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
| The refresh schedule had silently stopped | Restored; the workflow file explains why it stopped |

Triage moved to version 8 with these changes, so every card is being re-read.
*[Golden set on version 8: to be added.]*

## Limits

- 19 labelled filings is a small set. It catches systematic errors, not rare ones.
- The labels were made by one reader. Where a label could be argued, both answers count.
- Recall was not measured: nobody listed by hand every promise in a transcript, so we know
  the promises FINN found are real, not that it found them all. The research stability run
  measures part of this: a promise found in one run and not another was missed once.
- The second model is a model. Its flags were read by a person before any was counted.
