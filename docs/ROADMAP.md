# Roadmap (Phases 8-12)

Submission deadline: Wed 5 Nov, 7:30 AM IST. Judging weights: Impact 30% (I), Use of Meta AI
tooling 25% (M), Technical depth 20% (T), Demo 25% (D). Bonus prizes: Best Agentic (Ag), Best
Build on Meta Open Weight Models (OW), Most Viral (V), Community Vote (CV).

Cut order if late: cross-model verification and video cross-check, then Malayalam and Punjabi,
then the re-check comparison. Login, history, Ask Kaagaz and the UI redesign stay.

## Phase 8: UI redesign (Sat 1 Nov)
- [x] Chat layout: sidebar, conversation, household panel; phone and laptop (I, D, CV)
- [x] Live document thumbnails as SAM 3.1 finds each one, labelled with the owner (M, D, V)
- [x] Household matrix: members x 5 schemes, tap for reasons (I, D)
- [x] Result cards: What to do with Listen/Stop and Listen to all; Problems found;
      collapsible Your family (I, D)
- [x] Scheme catalog from verified YAML with sources, GET /schemes (I, T)
- [x] Feedback on answers and plans (I) (on the plan now; the component takes `answer:<id>` for Phase 10)
- [x] Layout ready for login and history (T) ("Your checks" placeholder in the sidebar)
Status: deployed 2026-10-30 (Modal backend, then Netlify); live site checked in Marathi at 360 and 1440 px.
Warm-up on the deployed backend: question spoken at 12.4 s, plan at 17.0 s (cached sample, warm container).
Commits: 0a7af4c, 06fbdc5, a035d08, 083f376, cf5de94; review fixes d311233, 95f9419, 1aa698f.
Changed: the catalog's rule lines are new wording in data/templates/reasons/*.yaml (`catalog`); the Marathi lines
are machine-drafted (added after the native-speaker review). Added after review: Aadhaar numbers blurred on
identity-card thumbnails (vision model boxes the number; no box -> icon; unread documents only as a coarse preview);
full and short scheme names in en/hi/mr and a one-line benefit per scheme in the YAML (only Ladki Bahin's is
verified; hi/mr benefit text machine-translated); quiet 'not eligible' cells; model caption under progress;
'How Kaagaz works' before a check.
Also fixed: age limits in scheme reasons were shown as rupees ("minimum age of ₹65").

## Phase 9: Login and case file (Sun 2 Nov, morning)
- [x] Phone login, demo-code mode, pluggable SMS adapter; Continue as guest (I, T, D)
- [x] Case file history in Neon Postgres (DATABASE_URL); storage behind an interface with an
      in-memory version for tests (I, T)
- [x] Returning-user welcome with pending office visits (I, D, V)
- [x] Tick off plan steps as done (I, D)
- [x] Re-check after fixing, compared with the last check (I, T, D, V)
- [x] Privacy: hashed phone numbers, no images or full ID numbers stored, consent line,
      Delete my data, retention limit (I, T)
- [x] Feedback moved into the database
Status: built and tested (490 offline tests; live Postgres round trip with `pytest -m live_db`; Playwright in
mr/hi/en at 360 and 1440 px against Neon); deployed 2026-11-01.
Commits: e26264c, df4c1ed, bd4807b, abfed8f, 61e7584, 0083612; review fixes dcf8588 and the frontend/docs commits after it.
Changed after review: login is not the front door (the app opens into the chat as a guest; returning users with a
token land on welcome back; a "Save this check" card after a guest check logs in and keeps that check via
POST /sessions/{id}/claim while the session is in memory); rate limits use the proxy-added client IP (last
X-Forwarded-For entry), 30 codes per IP per hour; the live-database test deletes its own feedback row and never
runs the broad retention purge on the real database.
Follow-up before deploy (750b4e1, 1cb9fd3, bf6daef, and the docs commit): honest demo-login text and notice; one
plural helper for every count; guests keep working when the database is down (fast 503s for login and saving);
a guest secret is needed to claim a session; production refuses to start without 32-byte login keys
(KAAGAZ_ENV=local for development keys); masked client IPs in logs; live database tests only with KAAGAZ_LIVE_DB=1;
Could-not-read lines name the person; ask-at-the-office sentences say what the problem is.
Changed: stored checks keep no ID numbers at all (not even the last 4 digits); tokens are signed with the standard
library (no JWT dependency); login codes and rate limits live in memory (one container), so a redeploy clears
pending codes. Added dependency: psycopg[binary] 3. PHONE_HASH_KEY and TOKEN_SIGNING_KEY are in the Modal secret.

## Phase 9b: Layout pass
- [x] Two-column layout: schemes matrix and office visits inline in the result (replaces the household panel) (I, D)
- [x] Centred reading column, composer lined up with it and clear of the home bar and keyboard (D)
- [x] How Kaagaz works in the welcome; light neutral palette in CSS variables (D, CV)
- [x] Cell detail names whose document could not be read (I)
Status: built and tested (12 frontend tests); deployed 2026-11-01. Commits: dcba1fb, e4821b5.

## Phase 9c: Real-input rescue (before Phase 10)
Why: a manual phone test (documents on a laptop screen, filmed with a phone) failed 9 of 9 videos with "Many
documents were not clear" or "no documents found"; showing documents one at a time stuck on the first one; upload
took 10-60 s, about 2 minutes in total. SAM found the documents, but every crop thumbnail was rotated 90°.
Not deployed or pushed until reviewed.
- [x] Part A, diagnose: per-stage dump for each real video (scripts/diagnose_video.py), compared with HH009
- [x] Part A, fix: upright crops (frame-aligned corners + text orientation, tests at 0°, ±30°, ±45°, ±90°, 180°,
      portrait, landscape and table), tracks split where the document in the box is swapped (one-at-a-time), cut-off
      documents read instead of dropped. Rotation metadata and variable frame rate: already handled by the upload
      normalization (frames checked upright, 24.93 s of 24.96 s kept); no change needed.
- [x] Part A: recorder asks for the camera's highest resolution at 10 Mbps and shows what the camera delivers
- [x] Part A: gates. Edge-contact gate recalibrated on data (4 of 4 cut-off documents in the real video read every
      key field right); frame agreement unchanged. Finder eval misreads before/after: 0/0/2/0 and 0/0/2/0.
- [x] Part B: triage after reading (duplicates merged, background dropped, unidentified listed), "Read clearly" /
      "Need a clearer photo" with Take photo and Upload, 'hold' when more than half are unclear (continues once
      clearer photos bring it to half), "Add photos" / "Record again" on the no-documents stop
- [x] Part C: photo mode (Add photos, camera or gallery, up to 12; Record also takes a gallery video), browser resize to
      2000 px JPEG without EXIF, SAM 3.1 per photo (inline image), two reads per document that must agree, "Uploading
      3 of 5" progress. Photo eval EV001-EV010: 73/74 documents right (1 wrong value), two per photo 72/74.
- [x] New en/hi/mr strings (Marathi and Hindi machine-drafted, listed for review)
- [x] Tests: orientation, appearance split, triage, photo finder, photo sessions and API; Playwright on the real
      videos, real-video frames as photos, HH009 photos and the sample in mr/hi/en at 360 and 1440 px (30 runs)
Status: built and tested; deployed 2026-11-01. Commits: 86beb78.
Open: the household builder flags a missing ration-card colour as "could not read" while the card is not on the
clearer-photo list (decision field, not a key field), so the sample shows the card under "Read clearly" and in
Problems found; the 720p sweep (video 728) still holds with many unclear documents and one agreed wrong digit.

## Phase 10: Live voice and Ask Kaagaz (Sun 2 Nov afternoon to Mon 3 Nov morning)
- [x] Spoken questions, push-to-talk (changed from a realtime live transcript): tap to start and stop (30 s at most,
      timer and level meter), the clip (WebM/Opus or MP4/AAC) converted by ffmpeg and transcribed with Muse Voice
      Transcribe (file endpoint, language bias) into the text box to check before sending; the answer to a spoken
      question plays by itself (I, M, T, D)
- [x] Ask Kaagaz agent on Muse Spark Open (Baseten): questions about the 5 schemes and the
      family's check (live or saved), answered through 8 read-only tools (I, M, D, Ag, OW)
- [x] Every fact in an answer checked against verified data before it is shown: numbers, schemes, offices, fees,
      eligibility (rules engine only), language, length; one retry, then "not sure" with the check's own line (M, T, Ag)
- [x] Answers spoken with MMS-TTS (Listen on every answer) (I, M, D)
- [x] Suggested questions from the family's own problems; "Add a photo" chips open the close-up flow (I, D)
Status: built, tested and deployed 2026-11-01 (Modal backend). Ask eval: 30 questions, 26/26 answered correctly, 4/4 refused,
0 wrong answers shown (eval/results/ask_20261101-030333.json). Speech: synthetic MMS-TTS clips only so far (WER en 0.06,
hi 0.19, mr 0.25; 11/12 transcripts still get the right answer; eval/results/asr_20261101-033631.json); stop to text
2.4-3.9 s locally, 2.9-3.7 s on throttled Slow 4G. The owner's own recordings are still to be run
(`python eval/run_asr_eval.py --clips <folder>`).
Commits: part 1 63165bf; part 2 1458f3e.
Production check: /ask answers in 8 s from a cold container; spoken question to text 2.3-4.7 s from India to
Modal us-east (server share 1.3-1.9 s); the sample family's plan at 23 s.
Changed: spoken questions' transcripts are never written to the disk cache (privacy; transcription costs $0.18 an hour).
Open: scheme YAML has no verified "where to apply" yet (the agent says to ask at the office; TODO for the developer).

## Phase 11: More Indian languages (Mon 3 Nov afternoon)
Before it, four fixes from the Phase 10 test (commit c38e2d7):
- [x] Spoken answers on phones: one audio element for the app, unlocked inside the mic and Send taps; "Tap to listen"
      if the browser still refuses; answer speech made on the server as soon as the answer exists (the ~5 s Listen delay)
- [x] New check / Start over keeps the check on screen, with its answers and Ask thread, under "Earlier in this visit"
- [x] Baseten daily token budget (BASETEN_DAILY_TOKENS, default 2M, all tasks; counts kept on disk, in /health); Ask
      says "unavailable" when it is used up; vision and agent calls routed to Baseten fall back to Muse Spark when it
      fails or the budget is used up (PHOTO_SECOND_READ_PROVIDER=baseten makes photo mode's second read a Muse Spark Open
      read with that fallback; default: both reads by Muse Spark, as before)
- [x] The app's name in Ask answers is the UI's own spelling (कागज, not कागद), checked per language
Phase 11 (commit 685671a):
- [x] Tamil, Telugu, Kannada: UI, plan, problems, Ask, chips, suggested questions, counts; voice in (ASR_LANGUAGES) and
      out (MMS-TTS tam/tel/kan); names shown in Latin letters as on the documents, said in each script (I, M, D, CV)
- [x] Translation pipeline (scripts/translate.py): Muse Spark translates with a glossary, Muse Spark Open
      back-translates and compares meaning, code checks placeholders, numbers, the app's name, punctuation and script;
      reviewed fixes in data/translations/fixes.yaml; report in docs/TRANSLATION_REPORT.md (M, T, OW)
- [x] Unreviewed languages labelled machine-translated (in their own script, with a tooltip and a note in the chat) (I, T)
- [x] Ask in ta/te/kn: answers in the UI language, fact check for their digits, number words, eligibility, fees,
      offices and schemes; questions in another script refused by code (I, T, Ag)
- [ ] Malayalam, Punjabi: skipped (several Phase 11 items needed rework; see below)
Status: built, tested and deployed 2026-11-01 (Modal backend with six TTS models, Netlify frontend). 752 backend tests,
32 frontend tests. Production check: healthy from cold in 16 s (six TTS models loaded in the background); sample family
in Tamil: first spoken sentence 22.7 s, plan 29.3 s (Marathi 15.6 s / 19.8 s); a Tamil Ask answer in 11 s, its speech
~13 s after the answer for a ~30 s answer (made ahead, so Listen waits only if tapped at once); the live site finishes the
sample check in Tamil and Kannada at 360 px (Playwright). Commits: c38e2d7, 685671a, 4c85f72, dcbecdb, and the deploy notes.
Translation: 362 strings per language; first pass ta 0/10, te 1/5, kn 1/3 (code failures / meaning mismatches); 26
strings fixed on review (8 of them not flagged by any check); final ta 0/6 (5 are the back-translator reading காகஸ் as
"Caucus"), te 1/1, kn 0/0 (docs/TRANSLATION_REPORT.md).
Ask eval (49 questions, 18 new in ta/te/kn): 48 handled right, 1 "not sure" (the model returned an empty reply twice),
0 wrong answers shown (eval/results/ask_20261101-134752.json). Speech (synthetic MMS-TTS clips, 3 per language): WER
ta 0.30 / te 0.50 / kn 0.18, CER 0.19 / 0.29 / 0.07, right answers 2/3, 3/3, 3/3 (eval/results/asr_20261101-134935.json).
Playwright (local): sample check, one Ask question, Save this check (demo login), saved check, tick, Check again and
the comparison in ta/te/kn at 360 and 1440 px: no overflow after two CSS fixes (big buttons wrap, matrix scheme names
break between letters).
Changed: rework was needed for the first translation prompt (spoken templates lost their punctuation), the brand rule
(कागद and ಕಾಗದ also mean "paper"; now rejected only where they name the app), the fact check (zero-width joiners, near
spellings of scheme names, Tamil "அல்ல"), a Bengali question answered in Tamil (now refused by code) and a Tamil question
refused as "other language" (now sent back). Scheme names: official names transliterated by Muse Spark, with the
English name in brackets. Kannada TTS reads "ಕಾಗದ" fine; the Telugu voice is the least clear in the ASR round trip.
Deploy note: TTS_MODEL_TA/TE/KN and ASR_LANGUAGES come from .env.example into the Modal image (models baked at build).

## Phase 12: Freeze and submit (Tue 4 - Wed 5 Nov)
Prep (commit 86e6fc0 and the docs commit after it; built and tested locally, not deployed or pushed):
- [x] Sample family switched to EV012's seven SPECIMEN photos through the real photo pipeline (no fixtures): one photo
      (Dattatray's caste certificate) is motion-blurred on purpose so the close-up loop shows; its clean render is the
      bundled close-up (clear, re-plan in ~4 s). The HH009 sweep video stays reachable (`?sample=video`, API
      `{"source": "video"}`). EV012's matrix as read covers all four outcomes, so EV022 was not needed.
- [x] EV012 held out of the evaluation set (eval/eval_set.py). Only the household eval ever scored it: truth 32/32 ->
      31/31, 0 false alarms; e2e 32/32 -> 31/31, 13 false alarms (6 blocker, 7 confirm) before and after (all reads
      cached). Fix planner, photo and Ask evals never used EV012 (unchanged).
- [x] Capacity: a FIFO line for running checks (MAX_RUNNING_CHECKS=4) and "Kaagaz is busy, you're next in line" /
      "number {n} in line" in the app; decoded SAM masks cached on disk (Meta's pure-Python decoder: ~5.5 s per
      document -> 0.02 s); load test (scripts/load_test.py) on a local copy pinned to 4 cores: 1/3/5/10 sample checks
      plan median 13.3/18.4/21.1/30.2 s, 0 errors (before the mask cache 44.0/92.8/122.9/209.9 s); 10 Ask questions at
      once 6.5-10.0 s, 0 errors. BASETEN_DAILY_TOKENS default 5M.
- [x] Freeze checklist script (scripts/freeze_check.py): /health, secrets and settings, Modal secret, the sample end to
      end with the close-up loop and the four outcomes, Ask in mr, a voice question from a fixture clip, login -> save
      -> delete, no Netlify badge and no third-party requests. Local copy: 12 passed, 0 failed, 1 skipped (Modal secret).
- [x] Writeup draft (docs/WRITEUP.md) and demo script (docs/DEMO_SCRIPT.md), with placeholders for the owner
- [ ] Final evals re-run; README numbers final (T)
- [ ] Final deploy, then freeze: no redeploys during judging (T, D). Before it: seed the cache volume with the EV012
      entries, deploy with KAAGAZ_KEEP_WARM=1, `warmup.py --language mr hi en ta te kn`, `freeze_check.py`
- [ ] Demo video: problem, sweep, thumbnails, question, plan in Marathi, close-up, returning
      user, Ask Kaagaz (I, M, D)
- [ ] Writeup mapped to the rubric (I, M, T): draft done, placeholders open
- [ ] X post and gallery link shared (V, CV)
Status: prep built and tested locally (756 backend tests, 32 frontend tests); not deployed.
Changed: ta/te/kn for the two busy strings came from scripts/translate.py (0 code failures, back-translations matched);
only those lines were kept, because a full re-run re-translated ~500 reviewed strings (chunk boundaries moved).
Open: Modal timings for the EV012 sample (local only so far); the busy strings in hi/mr are machine-drafted.

## Only if time allows
- [ ] Cross-model name verification: Muse Spark Open re-reads disputed names; kept only if the
      eval improves (M, T, OW)
- [ ] Video cross-check: Muse Spark watches the whole sweep to confirm SAM's document count (M, T)

## Meta models: before and after
| Model | Before Phase 8 | After Phase 12 |
|---|---|---|
| Muse Spark 1.3 | Reader, name verifier, fix planner | Same, plus translation (and the fallback for Baseten) |
| Muse Spark Open (Baseten) | Borderline same-person calls | Ask Kaagaz agent, back-translation |
| SAM 3.1 | Finding documents (hidden) | Same, visible in the UI |
| Muse Voice Transcribe | File mode for answers | Plus live mode in the chat box |
| MMS-TTS | 3 languages | 6 languages (Malayalam, Punjabi skipped) |

## Owner tasks (not for Claude Code)
- [x] Marathi templates reviewed by a native speaker
- [ ] Real phone test with printed HH009 documents
- [ ] Demo script (Mon; draft in docs/DEMO_SCRIPT.md), demo video (Tue), X post and submission (Wed)
