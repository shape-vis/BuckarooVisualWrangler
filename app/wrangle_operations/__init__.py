"""Public entry point for looking up wrangle operation implementations."""

from app.wrangle_operations.registry import get_operation

__all__ = ["get_operation"]
