import os
import logging

def setup_environment_and_logger(name: str) -> logging.Logger:
    """Creates required directories and configures the logger."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data/processed/input_c_files", exist_ok=True)
    os.makedirs("data/processed/output_rust_files", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/agent.log"),
            logging.StreamHandler()
        ]
    )
    
    test_logger = logging.getLogger("tests")
    test_logger.setLevel(logging.INFO)
    test_handler = logging.FileHandler("logs/tests.log")
    test_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    test_logger.propagate = False
    test_logger.addHandler(test_handler)
    test_logger.addHandler(logging.StreamHandler())

    compact_logger = logging.getLogger("compact")
    compact_logger.setLevel(logging.INFO)
    compact_handler = logging.FileHandler("logs/compact.log")
    compact_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    compact_logger.propagate = False
    compact_logger.addHandler(compact_handler)

    return logging.getLogger(name)


def log_compact_compile(file_name: str, repair_count: int, compiler_output: str, success: bool):
    """Helper to keep parsing logic out of the main agent file."""
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
    """Helper to keep parsing logic out of the main agent file."""
    compact_logger = logging.getLogger("compact")
    if status == "success":
        compact_logger.info(f"[{file_name}] Test evaluation: PASS")
    elif status == "skipped":
        compact_logger.info(f"[{file_name}] Test evaluation: SKIPPED")
    elif status == "c_failed_compilation":
        compact_logger.info(f"[{file_name}] C Compilation: FAIL")
    else:
        compact_logger.info(f"[{file_name}] Test evaluation: FAIL\n{errors}")