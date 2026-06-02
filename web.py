"""Run the SVG Icon Agent Web UI."""

from __future__ import annotations

import argparse
from pathlib import Path

from svg_icon_agent.web_app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the SVG Icon Agent Web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface.")
    parser.add_argument("--port", type=int, default=7860, help="Port number.")
    parser.add_argument("--out", default="outputs/web", help="Web run output directory.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    args = parser.parse_args()

    app = create_app(output_root=Path(args.out))
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
