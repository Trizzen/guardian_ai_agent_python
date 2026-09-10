"""Safe, single-line Begin diagnostics, also visible in the normal launcher log."""

import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())


def log_begin(key: str, **fields: object) -> None:
    # JSON encoding prevents user-controlled IDs from injecting log lines.
    logger.info("BEGIN %s %s", json.dumps(key), " ".join(
        f"{name}={json.dumps(value)}" for name, value in fields.items()
    ))
