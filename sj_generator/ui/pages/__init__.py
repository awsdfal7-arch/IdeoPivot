__all__ = [
    "IntroPage",
    "WelcomePage",
    "AiSelectFilesPage",
    "AiImportPage",
    "DedupeResultPage",
    "AiAnalysisPage",
    "ImportSuccessPage",
]


def __getattr__(name: str):
    if name == "IntroPage":
        from .intro_pages import IntroPage

        return IntroPage
    if name == "WelcomePage":
        from .welcome_pages import WelcomePage

        return WelcomePage
    if name == "AiSelectFilesPage":
        from .import_pages import AiSelectFilesPage

        return AiSelectFilesPage
    if name == "AiImportPage":
        from .import_pages import AiImportPage

        return AiImportPage
    if name == "DedupeResultPage":
        from .dedupe_pages import DedupeResultPage

        return DedupeResultPage
    if name == "AiAnalysisPage":
        from .analysis_pages import AiAnalysisPage

        return AiAnalysisPage
    if name == "ImportSuccessPage":
        from .export_pages import ImportSuccessPage

        return ImportSuccessPage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
