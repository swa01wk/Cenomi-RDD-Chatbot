"""Structured logging setup."""

import logging
import sys


def configure_logging() -> None:
    """Configure structlog or stdlib logging; extend with JSON exporters in production."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
