from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path

    @property
    def doc_dir(self) -> Path:
        return self.base_dir / "doc"

    @property
    def docs_dir(self) -> Path:
        return self.base_dir / "docs"

    @property
    def reference_dir(self) -> Path:
        return self.base_dir / "reference"

    @property
    def reference_resource_dir(self) -> Path:
        return self.reference_dir / "resource"

    @property
    def reference_mistakes_dir(self) -> Path:
        return self.reference_dir / "mistakes"

    @property
    def reference_quotation_dir(self) -> Path:
        return self.reference_dir / "quotation"

    @property
    def reference_picture_dir(self) -> Path:
        return self.reference_dir / "picture"


def app_paths(base_dir: Path | None = None) -> AppPaths:
    return AppPaths(base_dir=base_dir or Path(__file__).resolve().parents[1])


def common_mistakes_md_path(base_dir: Path | None = None) -> Path:
    return app_paths(base_dir).reference_mistakes_dir / "选择题常见错题归因与答题策略分析.md"
