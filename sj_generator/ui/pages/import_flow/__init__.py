__all__ = ["AiSelectFilesPage", "AiImportPage", "AiImportContentPage"]


def __getattr__(name: str):
    if name == "AiSelectFilesPage":
        from .select_page import AiSelectFilesPage

        return AiSelectFilesPage
    if name == "AiImportPage":
        from .question_ref_page import AiImportPage

        return AiImportPage
    if name == "AiImportContentPage":
        from .content_page import AiImportContentPage

        return AiImportContentPage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
