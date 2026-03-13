import logging
import sys


def setup_logging(level: int = logging.INFO):
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s user_id=%(user_id)s endpoint=%(endpoint)s latency=%(latency)s error=%(error)s message="%(message)s"'
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str):
    return logging.getLogger(name)
