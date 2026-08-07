"""Quick check of the local AI parser. Requires the model pulled + ollama running.

    .venv/bin/python scripts/ai_smoke.py
"""
from shopkeeper.ai import get_provider

SAMPLES = [
    "2 coke, rice 3kg",
    "milk",
    "3 packs of instant noodles and 2 eggs",
    "coca cola x4",
    "half kg sugar, 6 eggs, bread",
]


def main() -> None:
    ai = get_provider()
    if not ai.available():
        print("ollama not available — is the server up and the model pulled?")
        return
    for text in SAMPLES:
        items = ai.parse_items(text)
        print(f"\n{text!r} ->")
        for it in items:
            unit = f" {it.unit}" if it.unit else ""
            print(f"   {it.qty()}{unit}  {it.name}")


if __name__ == "__main__":
    main()
