import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()

    path = Path("data/input/sample_batch.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        file.write("[\n")

        for index in range(args.count):
            json.dump(
                {"prompt": f"Explain asynchronous systems briefly. #{index}"},
                file,
            )
            if index != args.count - 1:
                file.write(",")
            file.write("\n")

        file.write("]\n")

    print(f"wrote {args.count} prompts to {path}")


if __name__ == "__main__":
    main()
