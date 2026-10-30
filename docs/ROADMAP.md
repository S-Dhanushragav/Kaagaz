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
mr/hi/en at 360 and 1440 px against Neon); awaiting review; not deployed.
Commits: e26264c, df4c1ed, bd4807b, abfed8f, 61e7584, 0083612; review fixes dcf8588 and the frontend/docs commits after it.
Changed after review: login is not the front door (the app opens into the chat as a guest; returning users with a
token land on welcome back; a "Save this check" card after a guest check logs in and keeps that check via
POST /sessions/{id}/claim while the session is in memory); rate limits use the proxy-added client IP (last
X-Forwarded-For entry), 30 codes per IP per hour; the live-database test deletes its own feedback row and never
runs the broad retention purge on the real database.
Changed: stored checks keep no ID numbers at all (not even the last 4 digits); tokens are signed with the standard
library (no JWT dependency); login codes and rate limits live in memory (one container), so a redeploy clears
pending codes. Added dependency: psycopg[binary] 3. PHONE_HASH_KEY and TOKEN_SIGNING_KEY are in the Modal secret.

## Phase 10: Live voice and Ask Kaagaz (Sun 2 Nov afternoon to Mon 3 Nov morning)
- [ ] Live transcript in the text box while speaking (Muse Voice Transcribe realtime),
      editable before sending; backend relays audio so the key never reaches the browser
      (I, M, T, D)
- [ ] Ask Kaagaz agent on Muse Spark Open (Baseten): questions about the 5 schemes and the
      family's case file, answered through tools (I, M, D, Ag, OW)
- [ ] Every fact in an answer checked against verified data before it is shown (M, T, Ag)
- [ ] Answers spoken with MMS-TTS (I, M, D)
Status: not started. Commits: -

## Phase 11: More Indian languages (Mon 3 Nov afternoon)
- [ ] Tamil, Telugu, Kannada: voice in and out (I, M, D, CV)
- [ ] Malayalam, Punjabi: text, buttons and speech out only (Muse Voice Transcribe does not
      support them) (I, CV)
- [ ] Translation pipeline: Muse Spark translates, Muse Spark Open back-translates, code checks
      meaning, numbers and placeholders (M, T, OW)
- [ ] Unreviewed languages labelled machine-translated in the app (I, T)
Status: not started. Commits: -

## Phase 12: Freeze and submit (Tue 4 - Wed 5 Nov)
- [ ] Final evals re-run; README numbers final (T)
- [ ] Final deploy, then freeze: no redeploys during judging (T, D)
- [ ] Demo video: problem, sweep, thumbnails, question, plan in Marathi, close-up, returning
      user, Ask Kaagaz (I, M, D)
- [ ] Writeup mapped to the rubric (I, M, T)
- [ ] X post and gallery link shared (V, CV)
Status: not started. Commits: -

## Only if time allows
- [ ] Cross-model name verification: Muse Spark Open re-reads disputed names; kept only if the
      eval improves (M, T, OW)
- [ ] Video cross-check: Muse Spark watches the whole sweep to confirm SAM's document count (M, T)

## Meta models: before and after
| Model | Before Phase 8 | After Phase 12 |
|---|---|---|
| Muse Spark 1.3 | Reader, name verifier, fix planner | Same, plus translation |
| Muse Spark Open (Baseten) | Borderline same-person calls | Ask Kaagaz agent, back-translation |
| SAM 3.1 | Finding documents (hidden) | Same, visible in the UI |
| Muse Voice Transcribe | File mode for answers | Plus live mode in the chat box |
| MMS-TTS | 3 languages | 8 languages |

## Owner tasks (not for Claude Code)
- [x] Marathi templates reviewed by a native speaker
- [ ] Real phone test with printed HH009 documents
- [ ] Demo script (Mon), demo video (Tue), X post and submission (Wed)
