"""
Python dependency manager for user custom scripts.
Scans conf/python-requirements/requirements.txt for changes and runs pip install.
"""
import os
import sys
import subprocess
import logging
import hashlib
import threading
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DependencyManager:
    """Manages user Python dependencies via requirements.txt scanning and pip installation."""

    def __init__(
        self,
        requirements_dir: str = "/config/python-requirements",
        scan_interval: int = 30
    ):
        """
        Initialize dependency manager.

        Args:
            requirements_dir: Directory to scan for requirements.txt
            scan_interval: Interval in seconds between scans (default: 30)
        """
        self.requirements_dir = Path(requirements_dir)
        self.requirements_file = self.requirements_dir / "requirements.txt"
        self.log_file = self.requirements_dir / "requirements.log"
        self.scan_interval = scan_interval

        self._file_hash = None
        self._last_scan = datetime.now()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Create directory if it doesn't exist
        self.requirements_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start background scanning thread."""
        if self._running:
            logger.warning("Dependency manager already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()
        logger.info("Dependency manager started")

    def stop(self):
        """Stop background scanning thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Dependency manager stopped")

    def _scan_loop(self):
        """Background thread loop for periodic scanning."""
        while self._running:
            try:
                self.check_and_install()
            except Exception as e:
                logger.error(f"Error in dependency scan loop: {e}")

            # Wait for next scan interval
            for _ in range(self.scan_interval * 10):
                if not self._running:
                    break
                threading.Event().wait(0.1)

    def check_and_install(self) -> bool:
        """
        Check if requirements.txt has changed and install if needed.

        Returns:
            True if installation occurred, False otherwise
        """
        now = datetime.now()
        if now - self._last_scan < timedelta(seconds=self.scan_interval):
            return False

        with self._lock:
            self._last_scan = now

            # Check if requirements.txt exists
            if not self.requirements_file.exists():
                return False

            # Calculate current hash
            try:
                current_hash = self._calculate_file_hash(self.requirements_file)
            except Exception as e:
                logger.error(f"Failed to read requirements.txt: {e}")
                return False

            # Check if hash changed
            if self._file_hash is None or current_hash != self._file_hash:
                # Validate file before installing
                if not self._validate_requirements_file(self.requirements_file):
                    logger.warning("requirements.txt is invalid or incomplete, skipping installation")
                    return False

                logger.info("requirements.txt changed, installing dependencies...")
                success = self._run_pip_install()

                if success:
                    self._file_hash = current_hash
                    logger.info("Dependencies installed successfully")
                    return True
                else:
                    logger.error("Failed to install dependencies")
                    return False

        return False

    def _validate_requirements_file(self, file_path: Path) -> bool:
        """
        Validate requirements.txt before installation.

        Checks:
        - File is readable
        - File is not empty
        - File contains valid requirement lines (not truncated/mid-edit)
        - No obviously incomplete lines

        Args:
            file_path: Path to requirements.txt

        Returns:
            True if file appears valid, False otherwise
        """
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()

            if not lines:
                logger.warning("requirements.txt is empty")
                return False

            # Check last line - if it doesn't end with newline, might be incomplete
            if lines and lines[-1] and not lines[-1].endswith('\n'):
                # Could be incomplete, check if it looks valid
                last_line = lines[-1].strip()
                if not last_line or last_line.startswith('#'):
                    # Empty or comment, OK
                    return True
                # Last line is a requirement without newline - could be mid-edit
                # Simple heuristic: if it contains invalid chars like control chars, likely incomplete
                if any(ord(c) < 32 and c not in '\t\n\r' for c in lines[-1]):
                    logger.warning("requirements.txt appears to be incomplete (last line not terminated)")
                    return False

            # Basic syntax check: each non-comment line should be a valid requirement
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Very basic check: should contain alphanumeric and common requirement chars
                # but not weird control characters
                if any(ord(c) < 32 and c not in '\t' for c in line):
                    logger.warning(f"requirements.txt line {line_num} contains control characters")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating requirements.txt: {e}")
            return False

    def _run_pip_install(self) -> bool:
        """
        Run pip install for requirements.txt.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get pip executable path
            pip_executable = sys.executable.replace("python", "pip")
            if not Path(pip_executable).exists():
                # Fallback: use python -m pip
                cmd = [sys.executable, "-m", "pip", "install", "-r", str(self.requirements_file)]
            else:
                cmd = [pip_executable, "install", "-r", str(self.requirements_file)]

            logger.info(f"Running: {' '.join(cmd)}")

            # Run pip install and capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            # Write log file
            self._write_log_file(result, cmd)

            if result.returncode == 0:
                logger.info("Pip install completed successfully")
                return True
            else:
                logger.error(f"Pip install failed with return code {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Pip install timed out after 5 minutes")
            self._write_log_file_error("Pip install timed out after 5 minutes")
            return False
        except Exception as e:
            logger.error(f"Error running pip install: {e}")
            self._write_log_file_error(str(e))
            return False

    def _write_log_file(self, result: subprocess.CompletedProcess, cmd: list):
        """
        Write installation log file.

        Args:
            result: Result from subprocess.run()
            cmd: Command that was executed
        """
        try:
            with open(self.log_file, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write(f"Timestamp: {datetime.utcnow().isoformat()}Z\n")
                f.write(f"Python: {sys.executable}\n")
                f.write(f"Python Version: {sys.version}\n")
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Return Code: {result.returncode}\n")
                f.write("=" * 80 + "\n\n")

                if result.stdout:
                    f.write("STDOUT:\n")
                    f.write(result.stdout)
                    f.write("\n\n")

                if result.stderr:
                    f.write("STDERR:\n")
                    f.write(result.stderr)
                    f.write("\n\n")

                f.write("=" * 80 + "\n")

            logger.info(f"Installation log written to {self.log_file}")

        except Exception as e:
            logger.error(f"Failed to write log file: {e}")

    def _write_log_file_error(self, error_msg: str):
        """Write error to log file."""
        try:
            with open(self.log_file, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write(f"Timestamp: {datetime.utcnow().isoformat()}Z\n")
                f.write(f"Python: {sys.executable}\n")
                f.write("=" * 80 + "\n\n")
                f.write("ERROR:\n")
                f.write(error_msg)
                f.write("\n\n")
                f.write("=" * 80 + "\n")

        except Exception as e:
            logger.error(f"Failed to write error log: {e}")

    @staticmethod
    def _calculate_file_hash(file_path: Path) -> str:
        """
        Calculate SHA256 hash of file content.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of SHA256 hash
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

