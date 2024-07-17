"""This module configures and sets up logging for the zellular application."""

import logging
from logging import FileHandler, Logger, StreamHandler

# Set up the logger
zlogger: Logger = logging.getLogger("zellular_logger")
zlogger.setLevel(logging.DEBUG)

# Define log colors for different levels
LOG_COLORS: dict = {
    "DEBUG": "\033[94m",  # Blue
    "INFO": "\033[92m",  # Green
    "WARNING": "\033[93m",  # Yellow
    "ERROR": "\033[91m",  # Red
    "CRITICAL": "\033[41m" + "\033[97m",  # Red background with white text
    "RESET": "\033[0m",  # Reset to default
}

# Define the standard formatter
str_formatter: logging.Formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s - %(filename)s(%(lineno)d) - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to the log output based on the log level."""

    def format(self, record: logging.LogRecord) -> str:
        log_level: str = record.levelname
        record.msg = LOG_COLORS[log_level] + str(record.msg) + LOG_COLORS["RESET"]
        return super().format(record)


# Set up file handler
file_handler: FileHandler = logging.FileHandler(filename="zellular.log", mode="w")
file_handler.setFormatter(str_formatter)

# Set up console handler with colored formatter
console_handler: StreamHandler = logging.StreamHandler()
console_handler.setFormatter(ColoredFormatter())

# Add handlers to the logger
zlogger.addHandler(file_handler)
zlogger.addHandler(console_handler)

if __name__ == "__main__":
    zlogger.debug("Debug message")
    zlogger.info("Info message")
    zlogger.warning("Warning message")
    zlogger.error("Error message")
    zlogger.critical("Critical message")
