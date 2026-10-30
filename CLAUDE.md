# Kaagaz — project context for Claude Code

## What this is
Kaagaz is a voice-first agent for the Meta Global AI Developer Hackathon (Indie track, "Build for Your World").
A family sweeps a phone camera across their welfare documents. Kaagaz finds each document, reads it,
links documents to household members, checks them against each other and against scheme rules,
and an agent produces a fix plan, spoken back in Marathi or Hindi.

Full spec: `docs/PRD.md`. Read it before large changes.

## Hackathon rules that affect code
- The repo is public. Never commit secrets. Keys live in `.env` only (see `.env.example`).
- New work only: everything here is built during the hackathon (from Oct 27, 2026).
- The project must use Meta models (Meta Model API and/or Meta open-weights models).
- Never use real personal documents. Only synthetic documents watermarked "SPECIMEN".

## Architecture (do not change without asking)
Pipeline as a LangGraph graph; one shared state (`graph/state.py`):
1. `find_documents`: video frames → segmenter (SAM 3.1 API or SAM 3 on Modal) → track → sharpest 2–3 frames per document → deskew
2. `read_documents`: crops → LLM classify → LLM structured extraction (Pydantic-validated, one retry on validation error)
3. `build_household`: deterministic. Ration card members → link documents by name + DOB. Names: transliterate, then rapidfuzz.
   Score ≥ 90 match; 70–90 ask the LLM (log the reason); < 70 no match.
4. `check_rules`: deterministic. YAML rules in `data/schemes/`. Consistency, validity, eligibility → `list[Issue]`. NO LLM calls.
5. `plan_fixes`: the one true agent. LLM tool loop with tools in `agents/tools.py`.
   Fixes must come from `data/fixes/`. If nothing matches, say so. Never invent procedures, offices, or rules.
6. `speak`: MMS-TTS for Marathi/Hindi output.

## Hard rules
- No RAG, no vector database, no embeddings. Rules are YAML checked by code; scheme descriptions go in a cached prompt.
- The LLM never decides eligibility. Only `rules/engine.py` does.
- Never write scheme eligibility values, document validity periods, or office procedures from memory.
  Those come from official government sources and are filled in by the developer. Leave clear TODO placeholders instead.
- All model calls go through `clients/` (one place each). No direct SDK calls elsewhere.
- Every model call goes through `clients/cache.py` (disk cache keyed by a hash of model + input). Credits are limited.
- Send only cropped, resized document images (about 1024 px long side) to the LLM. Never full videos or full frames.
- Mask ID numbers (e.g. Aadhaar digits) in extracted text before storing. Do not persist raw frames; `tmp/` is cleaned after each run.
- Log token usage per request into state `usage`.

## Model providers
Both are OpenAI-compatible; use the `openai` Python SDK with a custom `base_url`.
- `LLM_PROVIDER=meta`: Meta Model API, Muse Spark (model ID from Meta docs; set via env)
- `LLM_PROVIDER=baseten`: Muse Spark Open, model `meta-models/muse-spark-open-1026`
- Segmenter: `SEGMENTER=sam31_api` or `sam3_modal`
- Speech in: Muse Voice Transcribe. Speech out: MMS-TTS (`facebook/mms-tts-mar`, `facebook/mms-tts-hin`)
Base URLs and model IDs always come from env/config, never hardcoded.

## Stack
- Backend: Python 3.11, FastAPI, LangGraph, Pydantic v2, OpenCV, ffmpeg, rapidfuzz, an Indic transliteration library
- Storage: SQLite (LangGraph checkpointer), YAML/JSON in `data/`
- Frontend: Vite + React + TypeScript, mobile-first web app, browser camera API
- Hosting: frontend on Netlify (static build); backend on Modal as one ASGI container (`deploy/modal_app.py`)

## Scope (current)
- 5 schemes, 4 document types: ration card, Aadhaar, income certificate, caste certificate
- Expand to 10 schemes + bank passbook only if on schedule

## How to work
- Make small, focused changes. Explain the plan before editing more than 3 files.
- Write or update a test in `backend/tests/` for every deterministic module (rules, matching, vision utils).
- Use type hints everywhere; Pydantic models for all data crossing module boundaries.
- Keep prompts in `backend/prompts/*.md`, not inline strings.
- After finishing a task, suggest a one-line entry for `docs/BUILD_LOG.md` and a commit message.
- After each phase, update `docs/ROADMAP.md`: tick finished items, add the commit hashes, note anything cut or changed and why, and keep the README Status table in sync.
- Ask before adding any new dependency.

## Commands
- Backend dev: `cd backend && uvicorn app.main:app --reload`
- Tests: `cd backend && pytest -q`
- Eval: `python eval/run_eval.py --subset 5` (daily) / `--all` (full run, max twice)
- Frontend: `cd frontend && npm run dev`
