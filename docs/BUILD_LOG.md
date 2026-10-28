# Build log

All code in this repository was written during the Meta Global AI Developer Hackathon (Oct 27 - Nov 4, 2026).

## Oct 27
- Created repo, project structure, CLAUDE.md, PRD.
- Phase 0/1: backend config, /health, disk-cached LLM client (Meta/Baseten), image prep (OpenCV), smoke test; first Muse Spark Open call via Baseten.
- Per-task LLM routing (vision/agent/text): provider, model, reasoning effort, max tokens from .env; reasoning captured in responses.
- Tested reasoning_effort=low on Meta vision (muse-spark-1.1): accepted, completion tokens 1058 -> 409 on SPECIMEN test image.
- Phase 2: synthetic SPECIMEN generator (4 bilingual templates, Playwright render, photo-like augmentation, planted errors, ground truth); 10 households at seed 42; 2x2 vision comparison on a photo-like ration card.
- Phase 3: document reader (one structured-output call per doc: classify + extract, Pydantic validation, one retry, ID masking before cache), reader eval: muse-spark-1.3 99.4% fields correct / 0.6% wrong; 1.1 98.8% / 1.1% wrong; both 58/58 classified.
- Reader schema: doc_type paired with its own fields (wrapped in "document"; Meta rejects top-level anyOf). 1.3 re-run: retries 4 -> 0, wrong values 4 -> 4 (place-name "corrections" persist), worst time 9.0 -> 8.9 s.
- Phase 4A: synthetic hand-held sweep videos (1080x1920, 30 fps, ~20 s) with per-frame document corners and visibility truth; HH001, HH008, HH009, HH008_hard (1.6x faster, two documents touching).
- Phase 4C (offline): segmenter interface, frame resampling (H.264/HEVC), sharpness/edge checks, mask->quad deskew with min-area-rect fallback, track cleanup, find_documents with tmp cleanup and --debug contact sheet.
- Phase 4B: SAM 3.1 client (Files API upload, Responses API, meta-sam-parser, cached, uploaded file deleted after). Probe: 50 frames 720p, upload 4.9 s + segment 6.8 s, $0.01.
- Phase 4D: finder eval on 4 sweep videos: 29/29 documents found, crop IoU ~0.96, 1 duplicate (hard video), 1 false detection; end to end 284/318 fields correct, 11 wrong, 23 null; upload-to-answer 33-41 s, $0.22 total. Lazy SAM mask decoding (parse 123 s -> 0.004 s).
- Frame agreement for decision fields (2 of 2-3 frames must agree), needs_retake flag, streaming reads (8 parallel), HH009 phantom fixed (texture beyond table edge). Wrong values 11 -> 1, nulls 23 -> 127 (8/29 documents had only 1 usable frame), needs_retake 20/29, upload-to-answer 29-37 s.
- Frame-selection fallback (0.2 s gap, 80% visible) when <2 frames, agreement_strength (strong >= 0.5 s), recapture plan (close_ups / sweep_again). Classified 20/29 -> 28/29, nulls 127 -> 50, wrong 1 -> 4 (all display-only fields; 0 wrong decision fields), weak agreements 5, upload-to-answer 28-31 s.
- Phase 5A: evaluation set v2 EV001-EV030 (quota schedule, card colours with PHH stamp, Neo-Buddhist, rare names, boundary ages and incomes); card_colour in the reader schema; fixed null income/age crashing validation.
- Phase 5B/D: scheme rules in data/schemes (developer-provided values, status, sources, interpretations), YAML loader, deterministic rules engine with outcome order not_eligible > blocked > check_at_office > eligible; 51 boundary unit tests.
- Phase 5C: household builder (ration-card members, cross-script name linking with rapidfuzz + transliteration, LLM adjudicator for 70-90, tie-break by gender/age, separate exact spelling and DOB checks, duplicate merge, missing/expired/unreadable issues). Truth mode: 32/32 planted errors caught, 0 false alarms, 0 model calls.
