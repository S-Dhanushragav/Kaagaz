from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="Kaagaz")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm_provider": get_settings().llm_provider}
