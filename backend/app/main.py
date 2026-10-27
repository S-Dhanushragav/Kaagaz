from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="Kaagaz")


@app.get("/health")
def health() -> dict[str, object]:
    s = get_settings()
    return {
        "status": "ok",
        "providers": {"vision": s.vision_provider, "agent": s.agent_provider, "text": s.text_provider},
    }
