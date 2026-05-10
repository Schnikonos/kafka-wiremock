"""
Application Settings Management.
Loads and manages application-wide UI and behavior settings from JSON file.
Automatically reloads settings when file changes.
"""
import logging
import json
import threading
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class UISettings:
    """UI-specific settings."""
    test_recap_threshold: int = 100  # Show recap popup if total runs > this value


@dataclass
class AppSettings:
    """Root application settings."""
    ui: UISettings = field(default_factory=UISettings)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class AppSettingsLoader:
    """Loads and manages application settings from JSON file with hot-reload."""

    def __init__(self, config_dir: str = "/config", scan_interval: int = 30):
        """
        Initialize the app settings loader.

        Args:
            config_dir: Base config directory path
            scan_interval: How often to scan for config changes (seconds)
        """
        self.config_dir = Path(config_dir)
        self.settings_file = self.config_dir / "app-settings.json"
        self.scan_interval = scan_interval
        self.settings = self._load_default_settings()
        self._lock = threading.Lock()
        self._running = False
        self._scan_thread: Optional[threading.Thread] = None
        self._file_hash: Optional[str] = None

    def start(self) -> None:
        """Start background scanning thread."""
        if not self._running:
            self._running = True
            self._scan_thread = threading.Thread(
                target=self._scan_loop,
                daemon=True,
                name="app-settings-scanner"
            )
            self._scan_thread.start()
            logger.info(f"App settings scanner started (scan interval: {self.scan_interval}s)")

    def stop(self) -> None:
        """Stop background scanning thread."""
        self._running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=5)

    def _scan_loop(self) -> None:
        """Background loop that periodically scans for settings changes."""
        import time
        while self._running:
            try:
                self._load_settings()
            except Exception as e:
                logger.error(f"Error loading app settings: {e}")
            time.sleep(self.scan_interval)

    def _load_default_settings(self) -> AppSettings:
        """Create default settings."""
        return AppSettings(
            ui=UISettings(test_recap_threshold=100)
        )

    def _load_settings(self) -> None:
        """Load settings from JSON file if it exists and has changed."""
        if not self.settings_file.exists():
            logger.debug(f"App settings file does not exist: {self.settings_file}")
            with self._lock:
                self.settings = self._load_default_settings()
                self._file_hash = None
            return

        try:
            # Check if file has changed
            with open(self.settings_file, 'rb') as f:
                content = f.read()
                file_hash = hashlib.md5(content).hexdigest()

            if self._file_hash == file_hash:
                # File hasn't changed
                return

            # File is new or changed - load it
            with open(self.settings_file, 'r') as f:
                data = json.load(f)

            # Parse settings with validation
            settings = self._parse_settings(data)

            with self._lock:
                self.settings = settings
                self._file_hash = file_hash
                logger.info(f"Loaded app settings from {self.settings_file}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in app settings file: {e}")
        except Exception as e:
            logger.error(f"Failed to load app settings: {e}")

    def _parse_settings(self, data: Dict[str, Any]) -> AppSettings:
        """Parse and validate settings from dictionary."""
        # Get UI settings
        ui_data = data.get("ui", {})
        ui_settings = UISettings(
            test_recap_threshold=ui_data.get("test_recap_threshold", 100)
        )

        # Validate threshold
        if not isinstance(ui_settings.test_recap_threshold, int) or ui_settings.test_recap_threshold < 0:
            logger.warning(f"Invalid test_recap_threshold: {ui_settings.test_recap_threshold}, using default 100")
            ui_settings.test_recap_threshold = 100

        return AppSettings(ui=ui_settings)

    def get_settings(self) -> AppSettings:
        """Get current settings (thread-safe)."""
        with self._lock:
            return self.settings

    def update_settings(self, settings: AppSettings) -> None:
        """Update and save settings to file."""
        try:
            # Ensure config dir exists
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Write to file
            with open(self.settings_file, 'w') as f:
                json.dump(settings.to_dict(), f, indent=2)

            # Update in-memory settings
            with self._lock:
                self.settings = settings
                # Recalculate hash
                with open(self.settings_file, 'rb') as f:
                    self._file_hash = hashlib.md5(f.read()).hexdigest()

            logger.info(f"Updated app settings: {self.settings_file}")
        except Exception as e:
            logger.error(f"Failed to update app settings: {e}")
            raise

