from __future__ import annotations

from importlib import import_module

_EXPORT_TO_MODULE = {
    "GeneratorWizard": ".main_wizard",
    "main": ".main_wizard",
    "ImportFlowWizard": ".import_flow",
    "configure_import_flow_pages": ".import_flow",
}

__all__ = ["GeneratorWizard", "ImportFlowWizard", "configure_import_flow_pages", "main"]


def __getattr__(name: str):
    module_name = _EXPORT_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
