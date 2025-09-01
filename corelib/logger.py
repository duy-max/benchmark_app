# python
import logging
from pathlib import Path

class Logger:
    def __init__(self, name="benchmark_app", level=logging.INFO, filename="benchmark.log", dir_name="logs"):
        project_root = Path(__file__).resolve().parent.parent
        logs_dir = project_root / dir_name
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / filename
        self.logger = logging.getLogger(name)
        if self.logger.handlers:
            self.logger.handlers.clear()
        self.logger.setLevel(level)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        self.logger.addHandler(fh)
        self.logger.propagate = False
        self.log_path = log_path

    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)

    def debug(self, msg, exc_info=False):
        self.logger.debug(msg, exc_info=exc_info)

    def exception(self, msg):
        self.logger.exception(msg)