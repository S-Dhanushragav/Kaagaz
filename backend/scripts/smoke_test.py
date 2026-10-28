"""Send one prompt (optionally with a local image) for a task and print the reply and token usage.

Usage (from backend/):
    python scripts/smoke_test.py --task text --prompt "Say hello in Marathi."
    python scripts/smoke_test.py path/to/specimen.jpg
    python scripts/smoke_test.py path/to/specimen.jpg --task vision --prompt "What document is this?"

Use synthetic SPECIMEN documents only.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from clients.llm import complete  # noqa: E402
from vision.images import encode_for_llm, read_image  # noqa: E402

DEFAULT_IMAGE_PROMPT = "What kind of document is this? Answer in one sentence."
DEFAULT_TEXT_PROMPT = "Say hello in Marathi, in one short sentence."


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252; replies are Devanagari
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, nargs="?")
    parser.add_argument("--task", choices=["vision", "agent", "text"], default="vision")
    parser.add_argument("--prompt")
    parser.add_argument("--max-tokens", type=int, help="override the task's configured budget")
    args = parser.parse_args()

    resolved = get_settings().resolve(args.task)
    print(
        f"Task: {args.task}  Provider: {resolved.provider}  Model: {resolved.model}  "
        f"Effort: {resolved.reasoning_effort or '-'}  "
        f"Max tokens: {args.max_tokens or resolved.max_tokens}"
    )

    jpeg = None
    if args.image is not None:
        original = read_image(args.image)
        jpeg = encode_for_llm(original)
        print(f"Image: {original.shape[1]}x{original.shape[0]} -> {len(jpeg) / 1024:.0f} KB JPEG")
    prompt = args.prompt or (DEFAULT_IMAGE_PROMPT if jpeg else DEFAULT_TEXT_PROMPT)

    resp = complete(prompt, task=args.task, images=[jpeg] if jpeg else (), max_tokens=args.max_tokens)

    print(
        f"Cached: {resp.cached}  Tokens: prompt={resp.usage.prompt_tokens} "
        f"completion={resp.usage.completion_tokens} total={resp.usage.total_tokens}  "
        f"Reasoning: {len(resp.reasoning) if resp.reasoning else 0} chars"
    )
    print("--- reply ---")
    print(resp.text)


if __name__ == "__main__":
    main()
