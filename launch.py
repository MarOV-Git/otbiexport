# launch.py
# ---------------------------------------------------------------
# Self-installing launcher:
# - Creates/uses .venv
# - Installs dependencies (requirements.txt or fallback)
# - Runs: streamlit run app.py
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path
import logging

LOG_FORMAT = "[%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("launcher")

REQUIRED_PACKAGES = ["streamlit", "lxml"]  # fallback when requirements.txt is missing


def sh(cmd: list[str]) -> None:
    log.info("$ %s", " ".join(map(str, cmd)))
    subprocess.check_call(cmd)


def ensure_venv(venv_dir: Path) -> None:
    if not venv_dir.exists():
        log.info("Creating virtual environment: %s", venv_dir)
        venv.EnvBuilder(with_pip=True).create(str(venv_dir))
    else:
        log.info("Using existing virtual environment: %s", venv_dir)


def venv_bins(venv_dir: Path) -> tuple[Path, Path, Path]:
    if os.name == "nt":
        py = venv_dir / "Scripts" / "python.exe"
        pip = venv_dir / "Scripts" / "pip.exe"
        streamlit = venv_dir / "Scripts" / "streamlit.exe"
    else:
        py = venv_dir / "bin" / "python"
        pip = venv_dir / "bin" / "pip"
        streamlit = venv_dir / "bin" / "streamlit"
    return py, pip, streamlit


def install_deps(pip_bin: Path, req_file: Path | None) -> None:
    sh([str(pip_bin), "install", "--upgrade", "pip"])
    if req_file and req_file.exists():
        sh([str(pip_bin), "install", "-r", str(req_file)])
    else:
        logging.warning("No requirements.txt found; installing fallback: %s", ", ".join(REQUIRED_PACKAGES))
        sh([str(pip_bin), "install", *REQUIRED_PACKAGES])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Self-installing Streamlit app launcher.")
    p.add_argument("--port", type=int, default=8501, help="Streamlit server port (default 8501)")
    p.add_argument("--address", default="localhost", help="Bind address (default localhost)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    base = Path(__file__).resolve().parent
    venv_dir = base / ".venv"

    ensure_venv(venv_dir)
    _, pip, streamlit = venv_bins(venv_dir)
    install_deps(pip, base / "requirements.txt")

    sh([str(streamlit), "run", str(base / "app.py"),
        "--server.port", str(args.port),
        "--server.address", args.address])


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        logging.error("Command failed with exit code %s", e.returncode)
        sys.exit(e.returncode)
    except Exception as ex:
        logging.exception("Unexpected error: %s", ex)
        sys.exit(1)
