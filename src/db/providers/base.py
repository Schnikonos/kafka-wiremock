"""
Abstract base class and shared types for DB providers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------

@dataclass
class DBResult:
    """Result returned by every DB provider operation."""
    rows: List[Dict[str, Any]] = field(default_factory=list)
    """Rows returned by a SELECT (list of column→value dicts)."""

    generated_key: Optional[Any] = None
    """Auto-generated primary key from INSERT (None if not applicable)."""

    rows_affected: int = 0
    """Number of rows affected by INSERT / UPDATE / DELETE."""

    raw: Any = None
    """Provider-specific raw result object (for advanced use)."""


class NotSupportedError(Exception):
    """Raised when a DB provider does not support a specific operation."""


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------

class DBProvider(ABC):
    """
    Abstract base class for database providers.

    Each built-in or custom provider implements this interface.
    All four DML methods accept a raw SQL / CQL query string plus an optional
    named-parameter dict.  Providers should raise NotSupportedError for
    operations they cannot handle (e.g. Cassandra does not return generated keys).
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """
        Open the connection (or pool) to the database.

        Raises:
            ConnectionError: if connection cannot be established.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection (or pool) gracefully."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the connection is currently open."""

    @abstractmethod
    def validate_connection(self) -> bool:
        """
        Send a lightweight probe (e.g. SELECT 1) to confirm liveness.

        Returns:
            True if the connection is alive and responsive.
        """

    # ------------------------------------------------------------------
    # DML operations  (all accept raw query + optional named params)
    # ------------------------------------------------------------------

    @abstractmethod
    def select(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> DBResult:
        """
        Execute a SELECT query and return rows.

        Args:
            query:  Raw SQL / CQL string.  Template placeholders are rendered
                    by DBExecutor *before* this method is called.
            params: Optional named bind parameters (provider-specific format).

        Returns:
            DBResult with ``rows`` populated.
        """

    @abstractmethod
    def insert(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> DBResult:
        """
        Execute an INSERT statement.

        Args:
            query:  Raw SQL / CQL INSERT string.
            params: Optional named bind parameters.

        Returns:
            DBResult with ``generated_key`` set if the engine supports it,
            and ``rows_affected`` set to 1 on success.
        """

    @abstractmethod
    def update(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> DBResult:
        """
        Execute an UPDATE statement.

        Args:
            query:  Raw SQL / CQL UPDATE string.
            params: Optional named bind parameters.

        Returns:
            DBResult with ``rows_affected`` set.

        Raises:
            NotSupportedError: if the provider does not support UPDATE.
        """

    @abstractmethod
    def delete(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> DBResult:
        """
        Execute a DELETE statement.

        Args:
            query:  Raw SQL / CQL DELETE string.
            params: Optional named bind parameters.

        Returns:
            DBResult with ``rows_affected`` set.

        Raises:
            NotSupportedError: if the provider does not support DELETE.
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_provider_type(self) -> str:
        """Return snake_case provider identifier derived from the class name."""
        import re
        class_name = self.__class__.__name__
        s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", class_name)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
        return name.replace("_db_provider", "").replace("_provider", "")

