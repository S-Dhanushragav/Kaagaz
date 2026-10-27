"""Send one local image + prompt to the configured LLM and print the reply and token usage.

Usage (from backend/):
    python scripts/smoke_test.py path/to/specimen.jpg
    python scripts/smoke_test.py path/to/specimen.jpg --prompt "What document is this?"

Use synthetic SPECIMEN documents only.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients.llm import complete  # noqa: E402
from vision.images import encode_for_llm, read_image  # noqa: E402

DEFAULT_PROMPT = "What kind of document is this? Answer in one sentence."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=2000)  # includes reasoning tokens
    args = parser.parse_args()

    original = read_image(args.image)
    jpeg = encode_for_llm(original)
    print(f"Image: {original.shape[1]}x{original.shape[0]} -> {len(jpeg) / 1024:.0f} KB JPEG")

    resp = complete(args.prompt, image=jpeg, max_tokens=args.max_tokens)

    print(f"Provider: {resp.provider}  Model: {resp.model}  Cached: {resp.cached}")
    print(
        f"Tokens: prompt={resp.usage.prompt_tokens} "
        f"completion={resp.usage.completion_tokens} total={resp.usage.total_tokens}"
    )
    print("--- reply ---")
    print(resp.text)


if __name__ == "__main__":
    main()
