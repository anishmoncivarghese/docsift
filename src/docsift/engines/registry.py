"""Lazy engine registry. Built-in engines are referenced by import-path strings so that
neither engine package is imported until get_engine() is called with its name;
register_engine() overrides built-ins (used by tests and future plugins)."""

import importlib

from docsift.core.exceptions import EngineNotAvailableError
from docsift.engines.base import ConversionEngine

_BUILTIN_PATHS: dict[str, str] = {
    "docling": "docsift.engines.docling_engine:DoclingEngine",
    "markitdown": "docsift.engines.markitdown_engine:MarkItDownEngine",
}
_registered: dict[str, type[ConversionEngine]] = {}


def register_engine(name: str, cls: type[ConversionEngine]) -> None:
    _registered[name] = cls


def unregister_engine(name: str) -> None:
    _registered.pop(name, None)


def available_engines() -> list[str]:
    return sorted(set(_BUILTIN_PATHS) | set(_registered))


def _resolve(name: str) -> type[ConversionEngine]:
    if name in _registered:
        return _registered[name]
    if name in _BUILTIN_PATHS:
        module_path, _, attr = _BUILTIN_PATHS[name].partition(":")
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise EngineNotAvailableError(f"unknown engine '{name}'; expected one of {available_engines()}")


def get_engine(name: str) -> ConversionEngine:
    cls = _resolve(name)
    if not cls.is_available():
        raise EngineNotAvailableError(
            f"engine '{name}' is not installed; install it with: pip install 'docsift[{name}]'"
        )
    return cls()
