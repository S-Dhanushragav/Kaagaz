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
Status: built and tested with Playwright at 360 and 1440 px in mr/hi/en; awaiting screenshot review; not deployed.
Commits: 0a7af4c, 06fbdc5, a035d08, 083f376, and the docs commit.
Changed: the catalog's rule lines are new wording in data/templates/reasons/*.yaml (`catalog`); the Marathi lines
are machine-drafted (added after the native-speaker review). Scheme names stay English (the YAML has `en` only).
Also fixed: age limits in scheme reasons were shown as rupees ("minimum age of ₹65").

## Phase 9: Login and case file (Sun 2 Nov, morning)
- [ ] Phone login, demo-code mode, pluggable SMS adapter; Continue as guest (I, T, D)
- [ ] Case file history in Neon Postgres (DATABASE_URL); storage behind an interface with an
      in-memory version for tests (I, T)
- [ ] Returning-user welcome with pending office visits (I, D, V)
- [ ] Tick off plan steps as done (I, D)
- [ ] Re-check after fixing, compared with the last check (I, T, D, V)
- [ ] Privacy: hashed phone numbers, no images or full ID numbers stored, consent line,
      Delete my data, retention limit (I, T)
- [ ] Feedback moved into the database
Status: not started. Commits: -

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
