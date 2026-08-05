import os
import logging
import json
from datetime import datetime
from pathlib import Path

def setup_environment_and_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    configure_log_directory(log_dir)
    os.makedirs("data/processed/input_c_files", exist_ok=True)
    os.makedirs("data/processed/output_rust_files", exist_ok=True)
    return logging.getLogger(name)


def configure_log_directory(log_dir: str) -> None:
    """Route pipeline logs to one directory for the lifetime of a run."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    _replace_handlers(
        root_logger,
        [
            _file_handler(os.path.join(log_dir, "agent.log")),
            logging.StreamHandler(),
        ],
    )

    test_logger = logging.getLogger("tests")
    test_logger.setLevel(logging.INFO)
    test_handler = _file_handler(os.path.join(log_dir, "tests.log"))
    test_logger.propagate = False
    _replace_handlers(test_logger, [test_handler, logging.StreamHandler()])

    compact_logger = logging.getLogger("compact")
    compact_logger.setLevel(logging.INFO)
    compact_handler = _file_handler(os.path.join(log_dir, "compact.log"))
    compact_logger.propagate = False
    _replace_handlers(compact_logger, [compact_handler])


def _file_handler(path: str) -> logging.FileHandler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    return handler


def _replace_handlers(logger: logging.Logger, handlers: list[logging.Handler]) -> None:
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    for handler in handlers:
        logger.addHandler(handler)


def log_compact_compile(file_name: str, repair_count: int, compiler_output: str, success: bool):
    compact_logger = logging.getLogger("compact")
    if success:
        compact_logger.info(f"[{file_name}] Compile attempt #{repair_count+1}: SUCCESS")
    else:
        compact_err = "Unknown error"
        for line in compiler_output.split('\n'):
            if "error" in line.lower() and "[" in line:
                compact_err = line.strip()
                break
        compact_logger.info(f"[{file_name}] Compile attempt #{repair_count+1}: FAIL - {compact_err}")

def log_compact_test(file_name: str, status: str, errors: str):
    compact_logger = logging.getLogger("compact")
    if status == "success":
        compact_logger.info(f"[{file_name}] Test evaluation: PASS")
    elif status == "skipped":
        compact_logger.info(f"[{file_name}] Test evaluation: SKIPPED")
    elif status == "c_failed_compilation":
        compact_logger.info(f"[{file_name}] C Compilation: FAIL")
    else:
        compact_logger.info(f"[{file_name}] Test evaluation: FAIL\n{errors}")


def log_compact_judge(
    file_name: str,
    status: str,
    details: str,
    verdict_counts: dict | None = None,
):
    compact_logger = logging.getLogger("compact")
    counts = ""
    if verdict_counts:
        non_zero_counts = [
            f"{verdict}={count}"
            for verdict, count in verdict_counts.items()
            if count
        ]
        counts = f" ({', '.join(non_zero_counts)})" if non_zero_counts else ""

    if status == "ACCEPTED":
        compact_logger.info(f"[{file_name}] Judge evaluation: ACCEPTED{counts}")
    elif status == "SKIPPED":
        compact_logger.info(f"[{file_name}] Judge evaluation: SKIPPED")
    else:
        compact_logger.info(f"[{file_name}] Judge evaluation: {status}{counts}\n{details}")


class RunRecorder:
    def __init__(self, path: str | None = None):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = path or os.path.join("logs", f"runs-{timestamp}.jsonl")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
