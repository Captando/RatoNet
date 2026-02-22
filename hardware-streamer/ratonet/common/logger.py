"""Logging padronizado para todos os módulos RatoNet."""

from __future__ import annotations

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger configurado com formato padronizado."""
    logger = logging.getLogger(f"ratonet.{name}")

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)-8s %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger
