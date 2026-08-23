"""Local entrypoint for the Jaza Sentinel control center."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

from jaza_sentinel import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Jaza Sentinel API")
    parser.add_argument("--host", default=os.environ.get("JAZA_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        default=int(os.environ.get("PORT", os.environ.get("JAZA_PORT", "5000"))),
        type=int,
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Optional runtime JSON directory (defaults to data/runtime)",
    )
    parser.add_argument(
        "--codex-config",
        type=Path,
        default=None,
        help="Optional Codex config.toml path (defaults to ~/.codex/config.toml)",
    )
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app(data_dir=args.data_dir, codex_config_path=args.codex_config)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
