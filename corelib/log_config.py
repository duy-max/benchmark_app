import logging
import os
import pathlib

def _ensure_logs_dir(dir_name: str="logs"):
    project_root = pathlib.Path(__file__).resolve().parents[1]
    logs_dir = project_root / f"{dir_name}"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return str(logs_dir)

def get_logger(name="benchmark_app", level=logging.INFO, filename="benchmark.log", dir_name="logs"):
    """
    Simple logger factory:
    - creates logs/ if missing
    - clears existing handlers for the named logger (simple behavior)
    - writes to logs/<filename> and to console
    - sets logger._log_path to file path
    """
    logs_dir = _ensure_logs_dir(dir_name)
    log_path = os.path.join(logs_dir, filename)

    logger = logging.getLogger(name)
    # simple: remove existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()

    logger.setLevel(level)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(fh)

    # ch = logging.StreamHandler()
    # ch.setLevel(logging.INFO)
    # ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    # logger.addHandler(ch)

    # Prevent messages from propagating to root logger (so no console output)
    logger.propagate = False

    # convenience attribute
    logger._log_path = log_path
    return logger