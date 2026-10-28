# Build log

All code in this repository was written during the Meta Global AI Developer Hackathon (Oct 27 - Nov 4, 2026).

## Oct 27
- Created repo, project structure, CLAUDE.md, PRD.
- Phase 0/1: backend config, /health, disk-cached LLM client (Meta/Baseten), image prep (OpenCV), smoke test; first Muse Spark Open call via Baseten.
- Per-task LLM routing (vision/agent/text): provider, model, reasoning effort, max tokens from .env; reasoning captured in responses.
- Tested reasoning_effort=low on Meta vision (muse-spark-1.1): accepted, completion tokens 1058 -> 409 on SPECIMEN test image.
- Phase 2: synthetic SPECIMEN generator (4 bilingual templates, Playwright render, photo-like augmentation, planted errors, ground truth); 10 households at seed 42; 2x2 vision comparison on a photo-like ration card.
- Phase 3: document reader (one structured-output call per doc: classify + extract, Pydantic validation, one retry, ID masking before cache), reader eval: muse-spark-1.3 99.4% fields correct / 0.6% wrong; 1.1 98.8% / 1.1% wrong; both 58/58 classified.
