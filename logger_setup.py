import os
import logging

def setup_environment_and_logger(name: str) -> logging.Logger:
    """Creates required directories and configures the logger."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("input_c_files", exist_ok=True)
    os.makedirs("output_rust_files", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/agent.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(name)