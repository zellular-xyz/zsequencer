import logging
from logging import FileHandler, Logger, StreamHandler

zellular_logger: Logger = logging.getLogger("zellular_logger")
zellular_logger.setLevel(logging.DEBUG)

formatter: logging.Formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s - %(filename)s(%(lineno)d) - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

file_handler: FileHandler = logging.FileHandler(filename="zellular.log", mode="w")
file_handler.setFormatter(formatter)

console_handler: StreamHandler = logging.StreamHandler()
console_handler.setFormatter(formatter)

zellular_logger.addHandler(file_handler)
zellular_logger.addHandler(console_handler)


if __name__ == "__main__":
    zellular_logger.debug("Debug message")
    zellular_logger.info("Info message")
    zellular_logger.warning("Warning message")
    zellular_logger.error("Error message")
    zellular_logger.critical("Critical message")
