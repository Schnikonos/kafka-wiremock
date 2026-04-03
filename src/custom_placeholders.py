"""
Custom placeholder loader with hot-reload support.
Loads custom placeholder functions from .py files in a configuration directory.
"""

import os
import sys
import logging
import importlib.util
import hashlib
from pathlib import Path
from typing import Dict, Callable, Any, Optional, Tuple, List
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)


def order(priority: int):
    """Decorator to set execution order for a placeholder."""
    def decorator(func):
        func._placeholder_order = priority
        return func
    return decorator


def placeholder(func):
    """Decorator to mark a function as a custom placeholder."""
    func._is_placeholder = True
    if not hasattr(func, '_placeholder_order'):
        func._placeholder_order = None  # Unordered (execute first)
    return func


class CustomPlaceholderRegistry:
    """Registry for custom placeholder functions with hot-reload and pipeline support."""

    def __init__(self, config_dir: str = "/config/custom_placeholders", reload_interval: int = 30):
        """
        Initialize the registry.

        Args:
            config_dir: Directory containing .py files with custom placeholders
            reload_interval: Interval in seconds to check for file changes
        """
        self.config_dir = Path(config_dir)
        self.reload_interval = reload_interval
        self.placeholders: Dict[str, Callable] = {}
        self.placeholder_order: Dict[str, Optional[int]] = {}  # name -> order priority
        self._file_hashes: Dict[Path, str] = {}  # Track file hashes instead of timestamps
        self._lock = threading.Lock()
        self._last_reload = datetime.now()

        # Create directory if it doesn't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Load initial placeholders
        self.reload()

    def get_placeholder(self, name: str) -> Optional[Callable]:
        """Get a custom placeholder function by name."""
        with self._lock:
            return self.placeholders.get(name)

    def get_all_placeholders(self) -> Dict[str, Callable]:
        """Get all registered custom placeholders."""
        with self._lock:
            return dict(self.placeholders)

    def check_and_reload(self) -> bool:
        """
        Check if any custom placeholder files have changed and reload if needed.

        Returns:
            True if reload occurred, False otherwise
        """
        now = datetime.now()
        if now - self._last_reload < timedelta(seconds=self.reload_interval):
            return False

        # Check if any files have been modified
        if self._check_files_changed():
            logger.info("Custom placeholder files changed, reloading...")
            self.reload()
            self._last_reload = now
            return True

        self._last_reload = now
        return False

    def _check_files_changed(self) -> bool:
        """Check if any .py files have been modified by comparing hashes."""
        py_files = list(self.config_dir.rglob("*.py"))
        current_files = set(py_files)
        tracked_files = set(self._file_hashes.keys())
        
        # Check for removed files
        removed_files = tracked_files - current_files
        if removed_files:
            logger.info(f"Custom placeholder files removed: {[f.name for f in removed_files]}")
            # Remove from tracking and clear cache
            for removed_file in removed_files:
                del self._file_hashes[removed_file]
            return True
        
        # Check for new files
        new_files = current_files - tracked_files
        if new_files:
            logger.info(f"Custom placeholder files added: {[f.name for f in new_files]}")
            return True
        
        # Check for modified files by comparing content hashes
        for py_file in py_files:
            try:
                current_hash = self._calculate_file_hash(py_file)
                last_hash = self._file_hashes.get(py_file)
                if last_hash is None or current_hash != last_hash:
                    logger.info(f"Custom placeholder file changed: {py_file.name}")
                    # Update hash so we don't detect this as changed on next check
                    self._file_hashes[py_file] = current_hash
                    return True
            except OSError as e:
                logger.warning(f"Cannot read file {py_file}: {e}")
                return True
        
        return False

    @staticmethod
    def _calculate_file_hash(file_path: Path) -> str:
        """Calculate SHA256 hash of file content."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def reload(self) -> None:
        """Load all custom placeholder .py files and execute in pipeline order."""
        logger.info(f"Loading custom placeholders from {self.config_dir}")

        new_placeholders: Dict[str, Callable] = {}
        new_placeholder_order: Dict[str, Optional[int]] = {}
        new_file_hashes: Dict[Path, str] = {}

        # Get all .py files recursively (supports subdirectories)
        py_files = sorted(self.config_dir.rglob("*.py"))

        if not py_files:
            logger.debug(f"No custom placeholder files found in {self.config_dir}")
            with self._lock:
                self.placeholders = {}
                self.placeholder_order = {}
                self._file_hashes = {}
            return

        # Load all files first, collect placeholders
        all_functions: List[Tuple[str, Callable, Optional[int]]] = []

        for py_file in py_files:
            try:
                # Load the module
                placeholders, functions = self._load_placeholder_file(py_file)

                # Add to collections
                new_placeholders.update(placeholders)

                # Track order for each placeholder
                for name, func in placeholders.items():
                    order_priority = getattr(func, '_placeholder_order', None)
                    new_placeholder_order[name] = order_priority
                    all_functions.append((name, func, order_priority))

                logger.info(f"Loaded {len(placeholders)} placeholders from {py_file.relative_to(self.config_dir)}")

                # Record file hash
                new_file_hashes[py_file] = self._calculate_file_hash(py_file)

            except Exception as e:
                logger.error(f"Failed to load custom placeholder file {py_file}: {e}")

        # Update registry atomically
        with self._lock:
            self.placeholders = new_placeholders
            self.placeholder_order = new_placeholder_order
            self._file_hashes = new_file_hashes  # Replace entire hash tracking

        logger.info(f"Loaded total of {len(new_placeholders)} custom placeholders")
        logger.debug(f"Placeholder execution order: {self._get_execution_order()}")

    def _get_execution_order(self) -> List[str]:
        """Get placeholder names in execution order."""
        items = list(self.placeholder_order.items())
        # Sort: unordered first (None), then by order value
        items.sort(key=lambda x: (x[1] is not None, x[1] or 0))
        return [name for name, _ in items]

    def _load_placeholder_file(self, py_file: Path) -> Tuple[Dict[str, Callable], List[Callable]]:
        """
        Load custom placeholder functions from a .py file.

        Returns:
            Tuple of (placeholders_dict, list_of_functions)
        """
        placeholders: Dict[str, Callable] = {}
        functions: List[Callable] = []

        try:
            # Dynamically import the module
            module_name = f"custom_placeholders_{py_file.stem}"

            # Remove from sys.modules if it exists to force reload
            if module_name in sys.modules:
                del sys.modules[module_name]

            spec = importlib.util.spec_from_file_location(
                module_name,
                py_file
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            # Extract PLACEHOLDERS dict if it exists
            if hasattr(module, "PLACEHOLDERS") and isinstance(module.PLACEHOLDERS, dict):
                for name, func in module.PLACEHOLDERS.items():
                    if callable(func):
                        placeholders[name] = func
                        logger.debug(f"  Loaded placeholder: {name} (order: {getattr(func, '_placeholder_order', 'unordered')})")

            # Also check for functions decorated with @placeholder
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(module, attr_name)
                if callable(attr) and hasattr(attr, "_is_placeholder"):
                    placeholders[attr_name] = attr
                    logger.debug(f"  Loaded placeholder: {attr_name} (order: {getattr(attr, '_placeholder_order', 'unordered')})")
                    functions.append(attr)

        except Exception as e:
            logger.error(f"Error loading placeholders from {py_file}: {e}")
            raise

        return placeholders, functions

    def execute_pipeline(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute all custom placeholders in order, building up context.

        Args:
            context: Initial context with message data

        Returns:
            Enriched context with all placeholder results
        """
        enriched_context = dict(context)

        # Get execution order
        execution_order = self._get_execution_order()

        logger.debug(f"Executing {len(execution_order)} custom placeholders in order")

        for placeholder_name in execution_order:
            func = self.get_placeholder(placeholder_name)
            if not func:
                continue

            try:
                result = func(enriched_context)
                # Add result to context with original function name
                enriched_context[placeholder_name] = result
                logger.debug(f"  {placeholder_name} → {result}")
            except Exception as e:
                logger.error(f"Error executing custom placeholder '{placeholder_name}': {e}")
                # Continue with next placeholder, don't add result to context

        return enriched_context

