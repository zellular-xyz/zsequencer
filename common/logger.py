import logging
from logging import FileHandler, Logger, StreamHandler

zlogger: Logger = logging.getLogger("zellular_logger")
zlogger.setLevel(logging.DEBUG)

LOG_COLORS = {
    "DEBUG": "\033[94m",  # Blue
    "INFO": "\033[92m",  # Green
    "WARNING": "\033[93m",  # Yellow
    "ERROR": "\033[91m",  # Red
    "CRITICAL": "\033[41m" + "\033[97m",  # Red background with white text
    "RESET": "\033[0m",  # Reset to default
}

str_formatter: logging.Formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s - %(filename)s(%(lineno)d) - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        log_level = record.levelname
        record.msg = (
            LOG_COLORS[log_level] + str_formatter.format(record) + LOG_COLORS["RESET"]
        )
        return record.msg


file_handler: FileHandler = logging.FileHandler(filename="zellular.log", mode="w")
file_handler.setFormatter(str_formatter)

console_handler: StreamHandler = logging.StreamHandler()
console_handler.setFormatter(ColoredFormatter())

zlogger.addHandler(file_handler)
zlogger.addHandler(console_handler)


if __name__ == "__main__":
    zlogger.debug("Debug message")
    zlogger.info("Info message")
    zlogger.warning("Warning message")
    zlogger.error("Error message")
    zlogger.critical("Critical message")
