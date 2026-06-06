"""Run the SVG Icon Agent Web UI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        os.environ.setdefault(key, _dotenv_value(value))


def _dotenv_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the SVG Icon Agent Web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface.")
    parser.add_argument("--port", type=int, default=7860, help="Port number.")
    parser.add_argument("--out", default="outputs/web", help="Web run output directory.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    args = parser.parse_args()

    _load_dotenv(Path(__file__).resolve().parent / ".env")

    from svg_icon_agent.web_app import create_app

    app = create_app(output_root=Path(args.out))
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
