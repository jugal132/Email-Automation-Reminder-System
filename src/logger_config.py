"""
Logger Configuration Module.

Provides centralized logging configuration for the Email Automation &
Reminder System with structured formatters and console/file handlers.
"""

import logging
from typing import Optional


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Retrieve or configure a standardized logger instance.

    Args:
        name: The name of the logger, typically __name__.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name or "email_automation")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
