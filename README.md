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

## Try it

- **App:** https://kaagaz-demo.netlify.app (mobile-first; Marathi, Hindi or English). "Try with a sample family" runs a
  bundled sweep video of synthetic SPECIMEN documents; "Record your documents" uses the phone camera (up to 45 s).
- **Backend API:** https://s-dhanushragav--kaagaz-web.us-east.modal.run (`/health`; endpoints in
  [app/api/routes.py](backend/app/api/routes.py)).
- The backend scales to zero when idle: the first request after a pause takes ~30 s to start (run
  `python scripts/warmup.py <backend URL>` before a demo).

## Status

All phases are built, tested and deployed (430 backend tests, no network).

| Phase | What | Status |
|---|---|---|
| 0/1 | Config, `/health`, disk-cached LLM client (Meta Model API + Baseten), per-task model routing | Done |
| 2 | Synthetic SPECIMEN documents (4 types, Marathi + English), photo-like images, planted errors, ground truth | Done |
| 3 | Document reader: one structured-output call per document (classify + extract), validation, retry, ID masking | Done |
| 4 | Document finder: phone-sweep video → SAM 3.1 tracks → best 2–3 upright crops per document → reader | Done |
| 5 | Household builder (name re-read before reporting, adjudicator) + scheme rules engine (5 schemes, deterministic) | Done, evaluated end to end |
| 6a | Fix planner agent (tool loop over a curated fix knowledge base, deterministic verification, retry, fallback) | Done, evaluated (10 households) |
| 6b | Voice: sentences from en/hi/mr templates, numbers spelled out, MMS-TTS out, Muse Voice Transcribe in, numbered spoken answers | Done, round-trip evaluated |
| 7 | LangGraph pipeline (family question as an interrupt), sessions API, mobile web app, Modal + Netlify deployment | Done, deployed |
| 7+ | Close-up loop (a clearer photo of one document re-runs household → rules → plan), "no documents" / "sweep again" stops, issues waiting for a clearer photo, scheme reasons in en/hi/mr, upload progress | Done, deployed |

Remaining phases: see [docs/ROADMAP.md](docs/ROADMAP.md).

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

**Fix planner** (10 EV households with issues, built end to end; a simulated family answers from the ground truth;
`muse-spark-1.3`)
- **10/10 plans passed verification the first time**, 0 retries, 0 fallbacks; 4.0 steps per plan, 3.1 agent turns per
  plan; 85k + 31k tokens, **$0.24** for the 10 households.
- Every mismatch was asked about before any fix, only the document the family's answer showed to be wrong was
  corrected, every Aadhaar change stated its lifetime limit, and wrong documents with no procedure in the knowledge base
  became "ask at the office". All 4 "confirm" spellings were asked as comparisons first (the family said "same").
- Spoken sentences and questions come from templates, not the agent; offices, fees, time limits and documents are
  checked against [data/fixes/](data/fixes/) before a plan is accepted.

**Voice round trip** (MMS-TTS speaks 8 answers + 2 non-answers per language; Muse Voice Transcribe hears them;
answers are matched by number words only, spelling-tolerant). Synthetic speech of isolated words, so a weak proxy
for real voices. **Buttons are the primary way to answer; voice is a bonus.**

| Language | Answers mapped right: default (keywords en only) / keywords / no keywords | Non-answers rejected |
|---|---|---|
| English | 6/8 / 6/8 / 6/8 | 2/2 |
| Hindi | 3/8 / 3/8 / 3/8 | 2/2 |
| Marathi | 4/8 / 0/8 / 4/8 (was 0/8 before spelling-tolerant matching) | 2/2 |

Transcription ~2 s per clip; TTS ~0.6 s per 1 s clip on CPU. Single synthetic Hindi/Marathi words ("दूसरा", "दो",
"दुसरे", "दोन") are still mostly misheard; short phrases ("दूसरा वाला", "नंबर दोन", "मला माहीत नाही") work. Keyword
biasing hurt Marathi, so it is off for Hindi and Marathi by default (`ASR_KEYWORD_LANGUAGES=en`). Interactive
transcription: 10 s timeout, one retry, then buttons. Nothing is ever matched to a wrong option. Spoken questions
name the documents; the numbered options carry the values; in Hindi/Marathi a difference only in English spelling
is not read out: the voice says so and points to the screen, which shows both spellings. Real recordings are next.

**Deployed app, end to end** (Modal, 1 container, 4 CPU, no GPU; measured 2026-10-29 with `scripts/warmup.py` and a
real upload; target: first spoken sentence within 60 s)

| Run | Find | Read | Household | Plan | First spoken sentence | Plan ready |
|---|---|---|---|---|---|---|
| Sample family (HH009), cached, **cold container** (+29 s until healthy; 2026-10-30) | 9 s | 0 s | 1 s | 1 s | **17 s** (the question) | 22 s |
| Sample family, cached, warm container (2026-10-29) | 8 s | 0 s | 0 s | 0 s | **18 s** (the question) | 30 s |
| Sample close-up ("Use sample close-up" on one listed document), deployed | – | 1 photo | re-run | re-run | – | **4 s** after the tap |
| Real upload, nothing cached, old setting (20 s 720p WebM at 4 Mbps, 10 MB, HH001) | 19 s | 9 s | 0 s | 10 s | 63 s (first plan step) | 63 s |
| **Real upload, nothing cached, current setting** (20 s 1080p WebM at 8 Mbps, 18 MB, HH009) | 29 s | 8 s | 0 s | 11 s | **66 s** (first plan step; upload 12 s) | 64 s |

- The cached sample meets the target; **a real upload misses it: 66 s** at the current 1080p / 8 Mbps setting
  (12 s upload of 18 MB from a desktop line; on slow mobile data the upload alone takes longer, which the app
  now shows as a progress bar). Full-size frames make "find" slower (29 s vs 19 s at 720p): frame sampling and
  mask decoding on CPU. The trade is deliberate: at 720p the ration card often could not be read (see below).
- A cold container adds ~29 s (start + loading three TTS models): run `scripts/warmup.py` 5 minutes before a demo.
- Reading quality on phone-like video: at the current setting HH001 plans exactly its planted error; the HH009 upload
  caught the expired income certificate but not the name mismatch, because one Aadhaar card was unclear. That card is
  put on the close-up list, everything that depends on it (who is on the ration card, a "missing" Aadhaar card) waits
  for the clearer photo, and the close-up re-runs the household, rules and plan. If most documents are unreadable the
  app asks for a new sweep; if no documents are found it says so; in both cases nothing else is shown.
- **Recording size matters more than bitrate.** HH001 as an upload, scored against its ground truth:

  | Upload | Frames the reader saw | Names read right | Ration card read | Plan |
  |---|---|---|---|---|
  | 720p, 4 Mbps (server cap 1080 px) | 608×1080 | 6/6 | no (close-up asked) | 3 "add to ration card" + 1 enrolment (3 false) |
  | 1080p, 8 Mbps (server cap 1080 px) | 608×1080 | 6/6 | no | the same 4 steps |
  | **1080p, 8 Mbps (server keeps 1920 px)** | 1080×1920 | **11/11** | **yes** | **1 "add to ration card" (the planted error)** |
  | 1080p, 4 Mbps (server keeps 1920 px), 10.5 MB | 1080×1920 | 10/10 (one more name unread) | yes | 1 Aadhaar enrolment (false) |

  4 Mbps lost a name and with it the plan, so the app stays at 1080p / 8 Mbps and the server keeps up to 1920 px
  (`UPLOAD_LONG_SIDE`). The cost is upload
  size: ~20 MB for a 20 s sweep (the 63 s timing above was a 10 MB upload).
- Modal cost so far (all deploys, image builds and test runs, month to date 2026-10-30): **$0.41 metered, covered by
  credits** ($0.00 billed). Most of it is the container idling 20 minutes after each test session.

**Rules engine**: 51 hand-written unit tests on every boundary (ages 17/18, 20/21, 64/65/66; incomes 21,000/21,001,
250,000/250,001; each Ramai income band; each ration card colour). These are tests, not an eval: an eval would only
compare the rules with themselves.

## How it works

```
phone video ──► find_documents ──► read_documents ──► build_household ──► check_rules ──► plan_fixes ──► speak
               (SAM 3.1, OpenCV)   (Muse Spark)       (deterministic +     (deterministic) (the agent;   (templates,
                                                       name re-read)                        asks family)  MMS-TTS)
                                        │                                       ▲
                                        └── "sweep again" / "no documents": stop │ close-up photo of one document
                                                                                └── re-runs from build_household
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
8. **Run it as a graph** ([graph/build.py](backend/graph/build.py)). The steps above are a LangGraph graph with one shared
   state. When the agent asks the family a question, the graph pauses (an interrupt) and resumes with the answer; the
   answer is remembered if the plan is rebuilt later. A "sweep again" or "no documents found" result stops after reading.
   A close-up photo of a document on the close-up list replaces its reading and re-runs household → rules → plan →
   speak; issues involving a document still waiting for a close-up are listed, not planned.
9. **The app** ([frontend/](frontend/)). Language choice, sample family or camera recording (1080p, up to 45 s, upload
   progress), stage progress, questions as large numbered buttons (plus a mic: answers are matched only by number words),
   the plan grouped by office visit with a play button per sentence, scheme results per member with reasons and
   sources, and the close-up list with "Take a photo". Served from Netlify; the API runs on Modal.

### Meta models used

| Task | Model | How |
|---|---|---|
| Find and track documents in video | **SAM 3.1** (`sam-3.1`) | Meta Model API: Files API + Responses API; masks decoded with Meta's `meta-sam-parser` |
| Read documents (vision) and the agent | **Muse Spark** (`muse-spark-1.3`) | Meta Model API, Chat Completions, structured output, reasoning effort `low` |
| Name adjudication (text) | **Muse Spark Open** (`meta-models/muse-spark-open-1026`) | Baseten (OpenAI-compatible) |
| Speech out | **MMS-TTS** (`facebook/mms-tts-eng`, `-hin`, `-mar`) | Local on CPU via `transformers` (optional `tts` extra); **CC-BY-NC 4.0** |
| Speech in | **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | Meta Model API, `POST /v1/asr/transcribe` |

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
pip install -e ".[tts]" --extra-index-url https://download.pytorch.org/whl/cpu   # only for speech output (~1 GB)
```

Copy `.env.example` to `.env` (repo root) and fill in `META_API_KEY` and `BASETEN_API_KEY`. Model IDs: `muse-spark-1.3`
(vision, agent), `meta-models/muse-spark-open-1026` (text, on Baseten), `sam-3.1` (segmenter), `VISION_REASONING_EFFORT=low`.

## Deploy (Modal + Netlify)

The backend runs on Modal as **one** ASGI container (sessions are paused graphs held in memory); the frontend is a
static Netlify site. Keys live only in a Modal secret.

```bash
pip install -e "backend[deploy]"                      # the Modal CLI
modal token new                                       # once
modal secret create kaagaz-secrets META_API_KEY=... BASETEN_API_KEY=...
KAAGAZ_FRONTEND_ORIGIN=https://<site>.netlify.app modal deploy deploy/modal_app.py
modal volume put kaagaz-cache .cache /                # optional: seed the model-call cache (sample runs free)
python scripts/warmup.py https://<workspace>--kaagaz-web.modal.run   # 5 minutes before any demo
```

- MMS-TTS models are baked into the image at build time; the model-call cache is a Modal Volume.
- `KAAGAZ_KEEP_WARM=1` at deploy keeps one container running (judging window only; it uses credits). Off by default.
- Netlify: base directory `frontend/`, environment variable `VITE_API_URL` = the Modal URL (see `frontend/netlify.toml`).
  CORS on the backend allows only `KAAGAZ_FRONTEND_ORIGIN`.

## Commands

From `backend/` unless noted. Costs are for a cold cache; cached calls are free.

| What | Command | Cost |
|---|---|---|
| All tests (no network) | `pytest -q` | free |
| API server | `uvicorn app.main:app --reload` | free |
| Smoke test one image | `python scripts/smoke_test.py path/to/specimen.jpg` | ~$0.004 |
| Regenerate v1 households (repo root) | `python -m synthetic.generate --n 10 --seed 42` | free |
| Regenerate sweep videos (repo root) | `python -m synthetic.video` (one: `--video HH009`) | free |
| Regenerate EV001–EV030 (repo root) | `python -m synthetic.generate_eval` | free |
| Reader eval (repo root) | `python eval/run_reader_eval.py --model muse-spark-1.3` | ~$0.23 |
| Finder + reader eval (repo root) | `python eval/run_finder_eval.py --prompts document` (`--debug` keeps contact sheets in `tmp/`) | ~$0.40 |
| Household eval, ground truth (repo root) | `python eval/run_household_eval.py --mode truth` | free |
| Household eval, end to end (repo root) | `python eval/run_household_eval.py --mode e2e` (`--dry-run` first) | ~$0.90 |
| Fix planner eval, 10 households (repo root) | `python eval/run_fix_planner_eval.py` (`--dry-run` first) | ~$0.25 |
| Voice round trip (repo root, `tts` extra) | `python eval/run_voice_roundtrip.py` | < $0.01 |
| Warm up / time the deployed app (repo root) | `python scripts/warmup.py <backend URL>` | small |
| Rebuild sample close-ups (repo root) | `python scripts/make_sample_closeups.py` | free (cached) |
| Frontend (from `frontend/`) | `npm run dev` / `npm run build` | free |

Every eval script has `--dry-run` (or prints its call count) and saves a summary to `eval/results/` and per-document
details to `eval/results/raw/` (gitignored).

## Next steps

1. **Real Hindi recordings** for the spoken-answer round trip (synthetic single words are a weak proxy; short phrases
   such as "नंबर दो" already work far better).
2. **Native-speaker review** of every Hindi and Marathi text: voice templates, number words, answer words, scheme
   reasons, UI strings.
3. **Upload time:** the real uncached upload is at 66 s against a 60 s target; the largest parts are the upload itself
   and CPU frame sampling / mask decoding in "find".
4. The `needs_other_proof` scheme items stay `unverified` until the developer adds sources.
5. Re-running the evals: `python eval/run_household_eval.py --mode e2e` and `python eval/run_fix_planner_eval.py`
   (cached calls cost nothing).

## Future work
- **Voice front agent** (free spoken questions about schemes and issues, routed to the pipeline or answered from the
  cached scheme descriptions): not built. Phase 6b covers only fixed questions with numbered spoken answers.

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
- The backend is one container with sessions held in memory: a restart or redeploy drops open sessions (don't redeploy
  during a demo). Session data is deleted after an hour anyway.
- Spoken answers: single Hindi/Marathi words are often misheard by speech recognition in our synthetic tests; buttons
  are the primary way to answer.
- MMS-TTS is CC-BY-NC 4.0 (non-commercial): a commercial deployment needs a different TTS.

## Repository layout

```
backend/
  app/            FastAPI app, settings, sessions (pipeline runs, answers, close-ups, cleanup, rate limit), API routes
  agents/         fix planner (the agent), its tools, voice templates, speech text, spoken answers, scheme reasons
  clients/        the only place model calls happen: llm.py (chat + tools), segmenter.py (SAM 3.1), tts.py (MMS-TTS),
                  transcribe.py (Muse Voice Transcribe), cache.py
  graph/          LangGraph pipeline: state.py, build.py, closeup.py, runtime.py, nodes/ (find_documents,
                  read_documents, build_household, check_rules, plan_fixes, speak)
  vision/         frames (incl. upload normalization), quality, deskew, tracks, images, text normalization and ID masking
  matching/       cross-script name matching
  rules/          YAML loader and deterministic rules engine
  schemas/        Pydantic models: documents, issues, household, fixes
  prompts/        all prompts (extract, retry, name adjudicator, name re-read, fix planner)
  tests/          430 tests, no network
data/
  schemes/        scheme rules (YAML, with sources)
  fixes/          fix procedures (YAML, status and source per fact)
  templates/      voice sentences (en/hi/mr), scheme reasons (en/hi/mr), declaration draft
  sample/         bundled close-up photos for the sample family
deploy/           Modal app (backend container)
scripts/          warm-up / timing check, sample close-up builder
synthetic/        document templates, generators (v1, v2), photo-like and video simulators, ground-truth helpers
eval/             eval scripts and results (reader, finder, household, fix planner, voice round trip)
docs/             PRD and build log
frontend/         Vite + React + TypeScript mobile web app (Netlify)
```

## License

See [LICENSE](LICENSE). The bundled Noto Sans Devanagari font is under the SIL Open Font License
([synthetic/templates/fonts/OFL.txt](synthetic/templates/fonts/OFL.txt)). `meta-sam-parser` is distributed by Meta under the SAM License.

**Speech output models are non-commercial.** Meta's MMS-TTS models used here are licensed **CC-BY-NC 4.0** ("The model
is licensed as CC-BY-NC 4.0." on each model card: [facebook/mms-tts-mar](https://huggingface.co/facebook/mms-tts-mar),
[facebook/mms-tts-hin](https://huggingface.co/facebook/mms-tts-hin), [facebook/mms-tts-eng](https://huggingface.co/facebook/mms-tts-eng);
checked 2026-10-29). That is fine for this hackathon demo; a commercial deployment needs a different TTS. The models
are downloaded at run time and not redistributed in this repository.
