from __future__ import annotations

from importlib import import_module

_MODULE_EXPORTS = {
    "intro_pages": ["IntroPage"],
    "welcome_pages": ["WelcomePage"],
    "import_flow": [
        "AiSelectFilesPage",
        "AiImportPage",
        "AiImportContentPage",
        "DedupeResultPage",
        "AiAnalysisPage",
        "ImportSuccessPage",
    ],
}

_EXPORT_TO_MODULE = {
    name: module_name
    for module_name, names in _MODULE_EXPORTS.items()
    for name in names
}

__all__ = [
    "IntroPage",
    "WelcomePage",
    "AiSelectFilesPage",
    "AiImportPage",
    "AiImportContentPage",
    "DedupeResultPage",
    "AiAnalysisPage",
    "ImportSuccessPage",
]


def __getattr__(name: str):
    module_name = _EXPORT_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
