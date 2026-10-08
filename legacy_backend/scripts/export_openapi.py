import json
from pathlib import Path

from taskiller.main import create_app


def main() -> None:
    output = Path("openapi/current.json")
    output.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
