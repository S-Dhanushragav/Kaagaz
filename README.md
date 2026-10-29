# Kaagaz

**Kaagaz** (कागज़, "paper") is a voice-first agent that checks a family's welfare documents before they apply for a scheme.
A family member sweeps a phone camera once across the family's papers. Kaagaz finds each document, reads it, links the
documents to household members, checks them against each other and against scheme rules, and explains what to fix, by
voice, in Marathi or Hindi.

Built for the **Meta Global AI Developer Hackathon**, Indie Developer track, theme "Build for Your World".
All code in this repository was written during the hackathon (from Oct 27, 2026); see [docs/BUILD_LOG.md](docs/BUILD_LOG.md).

> **Synthetic data only.** Every document in this repository is generated, bilingual, and watermarked **SPECIMEN**.
> Identity numbers are 12 digits starting with 0 or 1, so they can never be valid real numbers. No real person's documents
> are used anywhere.

---

## Why

Many families who qualify for welfare schemes lose them because of paperwork: a name spelled differently on two
documents, an expired income certificate, a missing identity card. Nobody catches it at application time; the rejection
arrives weeks later. Most of the people affected can't easily read forms, so Kaagaz works by camera and voice.

## Status

| Phase | What | Status |
|---|---|---|
| 0/1 | Config, `/health`, disk-cached LLM client (Meta Model API + Baseten), per-task model routing | Done |
| 2 | Synthetic SPECIMEN documents (4 types, Marathi + English), photo-like images, planted errors, ground truth | Done |
| 3 | Document reader: one structured-output call per document (classify + extract), validation, retry, ID masking | Done |
| 4 | Document finder: phone-sweep video → SAM 3.1 tracks → best 2–3 upright crops per document → reader | Done |
| 5 | Household builder + scheme rules engine (5 schemes, deterministic) | Done (end-to-end eval done) |
| 6 | Fix planner agent (tool loop over a curated fix knowledge base), voice sentences from templates | 6a done |
| 7 | Mobile web app, voice in (Muse Voice Transcribe) and out (MMS-TTS), recapture flow | Not started |

Full product spec: [docs/PRD.md](docs/PRD.md). Working rules for this repo (architecture, hard rules): [CLAUDE.md](CLAUDE.md).

## Results so far

All numbers are on synthetic SPECIMEN data; result files are in [eval/results/](eval/results/).

**Reader** (58 photo-like documents, one photo each, `muse-spark-1.3`, reasoning effort low)
- 58/58 documents classified; 641/645 fields correct (99.4%), 4 wrong values, 0 nulls; ~3.8 s per document.
- The remaining errors are rare place names "corrected" to familiar words (e.g. चाचणीनगर → चांदणीनगर).
- `muse-spark-1.1` at the same settings: 98.8% correct, 7 wrong values, about 1.8× the completion tokens.

**Finder + reader end to end** (4 synthetic phone-sweep videos, 29 documents)
- Documents found: 29/29, crop accuracy (IoU with true corners) ≈ 0.96, 0 false detections, 1 duplicate (fast, blurry video).
- Decision fields (names, date of birth, gender, ID last 4, income, category, card colour, issue dates): **0 wrong values**.
  Each is accepted only if at least 2 frames read it the same way; otherwise it is left empty and the document is
  flagged for a close-up.
- Display-only fields (address, certificate number, relation; read from one frame): 4 wrong values.
- 28/29 documents classified; 50 empty fields; 13 documents flagged `needs_retake`.
- **Upload to answer: 28–31 s per video** (target: under 60 s). Cost ≈ $0.10 per video.

**Household builder** (EV001–EV030, documents taken from ground truth, i.e. a perfect reader)
- **32/32 planted errors caught, 0 false alarms**, 0 name-adjudicator calls.

**Household builder, end to end** (EV001–EV030, 226 photo-like documents read by `muse-spark-1.3`, effort low)

| | No re-read | Re-read may delete (previous) | Re-read confirms, never deletes (now) |
|---|---|---|---|
| Planted errors caught | 32/32 | 32/32 | 32/32 (all 7 name mismatches as blockers) |
| False alarms, blocker | 12 | 6 | **6** (4 name, 1 not on card, 1 missing) |
| False alarms, confirm | – | – (6 hidden as info) | 7 (name spellings for the family to compare) |
| Name re-reads (vision, effort medium) | 0 | 47, $0.20 | 48, $0.21 |
| Adjudicator calls (Baseten) | 0 | 1 | 1 |

- A name difference the re-read confirms is a **blocker**; one it doesn't confirm stays as `name_mismatch` with severity
  **confirm**: shown to the family with both spellings and the document crops, never hidden, never blocking
  eligibility. The re-read can't delete a mismatch because it shares the reader's habit of writing familiar spellings:
  in EV002 and EV013 it read **every** document as प्रियंका, so the reads agreed without being right.
- All false alarms come from a misread name (प्रियांका → प्रियंका, ठोंबरे → ठॉंबरे, ढमढेरे → धमधेरे, Kshitij → Kohitij).
  The report lists, for every false alarm, the misread field (document, field, expected, read), and splits false alarms
  by severity. When one script is confirmed and the other isn't (EV015), the member gets one issue of each.
- One misread on a ration card (ज्ञानदा → शयनदा) still causes 2 blocker false alarms: before the secondary link the
  row is re-read, but the re-read repeats "Shyanada" (score stays 67) and the adjudicator answers "different first names".

**Rules engine**: 51 hand-written unit tests on every boundary (ages 17/18, 20/21, 64/65/66; incomes 21,000/21,001,
250,000/250,001; each Ramai income band; each ration card colour). These are tests, not an eval: an eval would only
compare the rules with themselves.

## How it works

```
phone video ──► find_documents ──► read_documents ──► build_household ──► rules engine ──► fix planner ──► voice
               (SAM 3.1, OpenCV)   (Muse Spark)       (deterministic)      (deterministic)   (agent, Phase 6) (Phase 7)
```

1. **Find** ([graph/nodes/find_documents.py](backend/graph/nodes/find_documents.py)). The video is resampled to 5 fps at
   720p and sent to **SAM 3.1** (Files API + Responses API) with the prompt "document". Tracks are cleaned (split at time
   gaps, tiny/short/duplicate tracks dropped, tracks never fully in view dropped). For each document the sharpest 2–3
   frames, at least 0.5 s apart (0.2 s fallback), are chosen; only those masks are decoded, then each crop is cut from the
   full-resolution frame and straightened (mask → 4 corners → perspective warp). Frames live in `tmp/` and are deleted
   after the run.
2. **Read** ([graph/nodes/read_documents.py](backend/graph/nodes/read_documents.py)). One structured-output call per frame
   classifies and extracts with a JSON schema generated from Pydantic models. Output is normalized, validated, and retried
   once with the errors; if it still fails, the document is marked unreadable. For video, decision fields need 2 frames
   that agree. Documents start reading as soon as their crops are ready (8 calls in parallel).
3. **Build the household** ([graph/nodes/build_household.py](backend/graph/nodes/build_household.py)). The ration card's
   member list defines the household. Other documents are linked by name across scripts (Devanagari transliteration +
   rapidfuzz): score ≥ 90 links, 70–90 asks the text model and logs its reason, < 70 means the person is not on the ration
   card. Secondary link: 50–70 still asks the model if the document's age (±1 year) and gender fit exactly one member
   without a document of that type (that member's ration-card row is re-read first, and the re-read name is what the
   model sees). Spelling and date-of-birth checks are separate exact comparisons, so "Suneel" is
   linked to Sunil *and* reported as a mismatch. Before a name mismatch is reported, the name is re-read on each involved
   document (name only, letter by letter, effort medium): if the re-read still differs, it is a blocker; if not, it stays
   with severity `confirm` for the family to compare (the re-read can confirm a mismatch, never delete one). Both reads
   are in the evidence. An empty field is never a mismatch.
4. **Check the rules** ([rules/engine.py](backend/rules/engine.py)). For each member and scheme, the result is
   `not_eligible`, `blocked_by_issues` (fix these first), `check_at_office`, or `eligible_on_documents`, plus the rules
   used (value, status, source), the reasons, and what the documents can't show (`needs_other_proof`). **No LLM call
   decides eligibility.** `confirm` issues are listed with the result (`to_confirm`, and in `warnings`), never blocking.
5. **Recapture plan.** If more than half the documents need a retake: "sweep again"; otherwise a list of documents to
   photograph close up.
6. **Plan the fixes** ([agents/fix_planner.py](backend/agents/fix_planner.py)). The one agent: Muse Spark in a tool loop
   (`lookup_fix_procedure`, `get_office_info`, `ask_family`, `draft_declaration`, `submit_plan`) over the fix knowledge
   base in [data/fixes/](data/fixes/) (8 procedures; every fact has its own status and source). Code verifies every
   office, fee, time limit, document and caution against the knowledge base, checks that mismatches were asked about
   first and only the wrong document is corrected, retries once, then falls back to a plain list of procedures. Code
   also orders the plan: questions first, the slowest fix (caste certificate) next, then one visit per office.
7. **Say it** ([agents/voice.py](backend/agents/voice.py)). The agent never writes what the family hears. Every
   sentence and question is a template from [data/templates/voice/](data/templates/voice/) (English, Hindi, Marathi),
   filled only with knowledge-base facts, member names and document display names; unverified facts are followed by
   "confirm at the office"; a time limit is only ever said as "the law sets ... for this office".
   **The Hindi and Marathi templates are machine-drafted and need review by a native speaker.**

### Meta models used

| Task | Model | How |
|---|---|---|
| Find and track documents in video | **SAM 3.1** (`sam-3.1`) | Meta Model API: Files API + Responses API; masks decoded with Meta's `meta-sam-parser` |
| Read documents (vision) and the agent | **Muse Spark** (`muse-spark-1.3`) | Meta Model API, Chat Completions, structured output, reasoning effort `low` |
| Name adjudication (text) | **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | Baseten (OpenAI-compatible) |
| Speech in / out (Phase 7) | Muse Voice Transcribe / MMS-TTS | planned |

Model IDs and base URLs come from `.env`, never from code. Every model call goes through [backend/clients/](backend/clients/)
and a disk cache keyed by a hash of the full request, so re-running an eval costs nothing for unchanged calls.

### Privacy and safety
- Identity numbers: the model is asked for the last 4 digits only, and the LLM client masks any 12-digit number
  (plain, spaced, dashed, or in Devanagari digits) **before** the reply is cached or returned.
- Only cropped, resized document images (~1024 px long side) are sent to the reader; never whole videos or frames.
- Uploaded videos are deleted from the Files API after segmentation. Raw frames in `tmp/` are deleted after each run.
- No secrets in the repo: keys live in `.env` (gitignored); see [.env.example](.env.example).

## Scheme rules

Rules are YAML in [data/schemes/](data/schemes/). **Every value was provided by the developer from official sources**; none
was written from memory. Each rule records `value`, `status` (`verified` | `conflict` | `unverified`), `source`,
`source_url`, `last_checked`. Where the source's text doesn't settle a case, an `interpretation` field states our reading.

| Scheme | Rules (summary) |
|---|---|
| PM Ujjwala | Female, 18+; SC/ST caste certificate of any household member (otherwise needs other proof); ration card + identity card of every adult on it; no LPG connection (other proof) |
| Ladki Bahin | Female, 21–65; family income ≤ 2,50,000; no income certificate needed with a Yellow/Orange card (our reading), but a certificate above the limit means not eligible |
| Sanjay Gandhi Niradhar | Age < 65; income ≤ 21,000; covered group (other proof) |
| Shravanbal | Age ≥ 65; income ≤ 21,000 |
| Ramai Awas | Applicant's own SC/Neo-Buddhist certificate (another member's only → check at office); income limit **conflict**: ≤ 1,00,000 passes, > 1,50,000 fails, between → check at office |
| Shared | Income certificate issued before 1 April of the current financial year → warning "may need renewal, check at the office" (unverified; never a blocker) |

Every rule links to the exact source page. **Open TODO for the developer:** the `needs_other_proof` items stay
`unverified` (source `developer`) for now.

## Synthetic data

| Set | Where | Purpose |
|---|---|---|
| HH001–HH010 (v1, seed 42) | `synthetic/households/` | Reader eval and the sweep videos. **Do not change**: a test checks they regenerate identically. |
| Sweep videos | `synthetic/videos/` | HH001, HH008, HH009, HH008_hard (faster, two documents touching). 1080×1920, 30 fps, ~20 s, per-frame truth (`video_truth.json`). |
| EV001–EV030 (v2, seed 2029) | `synthetic/eval_households/` | Household + rules eval: ≥ 6 of each planted error, 6 clean households, 5–6 member households, every income/age boundary, card colours, Neo-Buddhist, rare names. |

Each household folder has `ground_truth.json` (committed) plus clean renders and photo-like images (gitignored except
HH001; regenerate them with the commands below). Planted error types: `name_mismatch`, `dob_mismatch`, `expired`,
`missing_document`, `not_on_ration_card`.

## Setup

Requirements: Python 3.11+ (developed on 3.13), Windows/macOS/Linux. Optional: `ffmpeg` (only for the HEVC test).

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev,synthetic]"
python -m playwright install chromium   # only needed to render synthetic documents
```

Copy `.env.example` to `.env` (repo root) and fill in `META_API_KEY` and `BASETEN_API_KEY`. Model IDs: `muse-spark-1.3`
(vision, agent), `meta-models/muse-spark-open-1026` (text, on Baseten), `sam-3.1` (segmenter), `VISION_REASONING_EFFORT=low`.

## Commands

From `backend/` unless noted. Costs are for a cold cache; cached calls are free.

| What | Command | Cost |
|---|---|---|
| All tests (209, no network) | `pytest -q` | free |
| API server | `uvicorn app.main:app --reload` | free |
| Smoke test one image | `python scripts/smoke_test.py path/to/specimen.jpg` | ~$0.004 |
| Regenerate v1 households (repo root) | `python -m synthetic.generate --n 10 --seed 42` | free |
| Regenerate sweep videos (repo root) | `python -m synthetic.video` (one: `--video HH009`) | free |
| Regenerate EV001–EV030 (repo root) | `python -m synthetic.generate_eval` | free |
| Reader eval (repo root) | `python eval/run_reader_eval.py --model muse-spark-1.3` | ~$0.23 |
| Finder + reader eval (repo root) | `python eval/run_finder_eval.py --prompts document` (`--debug` keeps contact sheets in `tmp/`) | ~$0.40 |
| Household eval, ground truth (repo root) | `python eval/run_household_eval.py --mode truth` | free |
| Household eval, end to end (repo root) | `python eval/run_household_eval.py --mode e2e` (`--dry-run` first) | ~$0.90 |

Every eval script has `--dry-run` (or prints its call count) and saves a summary to `eval/results/` and per-document
details to `eval/results/raw/` (gitignored).

## Continuing the evals (where we stopped)

1. **Household eval, end to end: done** (results above). Re-run with
   `python eval/run_household_eval.py --mode e2e` (cached calls cost nothing; `--no-verify` for the run without name
   re-reads). The 6 blocker false alarms left are misread names that the re-read repeats; in the app, frame agreement
   over 2–3 frames also applies to names. `TEXT_MAX_TOKENS` now defaults to 4000 (1,500 was too few for the
   adjudicator's reasoning).
2. **Before the final eval run:** the eval-phase notes say to keep ≥ 4 of each error type over 30 households (done in v2),
   include 5–6 member households (done), and rare names and unusual spellings to measure "correction" errors (done in v2).

## Known limitations
- The reader sometimes "corrects" rare names and place names to familiar words. The prompt asks it not to, and this
  remains the most common error. Frame agreement keeps these out of decision fields when frames disagree.
- Display-only fields (addresses, office names, certificate numbers, relation) are read from one frame and can be wrong.
- Mask decoding with Meta's pure-Python parser is the slowest local step (~10 s per video, run in parallel processes).
- A document seen only briefly in a video may get two frames very close together; its agreement is marked `weak`.
- Duplicates of the same document across two tracks are kept in the finder output; merging happens in the household
  builder (same ID last 4 + same date of birth).
- Synthetic documents follow simplified layouts; real documents will need schema adjustments.
- Hindi and Marathi voice templates (their wording of offices, documents and cautions, and the number words used for speech) are machine-drafted and
  have not been reviewed by a native speaker.

## Repository layout

```
backend/
  app/            FastAPI app and settings (per-task model routing)
  clients/        the only place model calls happen: llm.py, segmenter.py (SAM 3.1), cache.py
  graph/nodes/    pipeline steps: find_documents, read_documents, build_household (+ later: check_rules, plan_fixes, speak)
  vision/         frames, quality, deskew, tracks, images, text normalization and ID masking
  matching/       cross-script name matching
  rules/          YAML loader and deterministic rules engine
  schemas/        Pydantic models: documents, issues, household
  prompts/        all prompts (extract, retry, name adjudicator)
  scripts/        smoke test, SAM probe, 2x2 vision comparison
  tests/          209 tests, no network
data/schemes/     scheme rules (YAML)
synthetic/        document templates, generators (v1, v2), photo-like and video simulators, ground-truth helpers
eval/             eval scripts and results
docs/             PRD and build log
frontend/         Vite + React + TypeScript app (Phase 7)
```

## License

See [LICENSE](LICENSE). The bundled Noto Sans Devanagari font is under the SIL Open Font License
([synthetic/templates/fonts/OFL.txt](synthetic/templates/fonts/OFL.txt)). `meta-sam-parser` is distributed by Meta under the SAM License.
