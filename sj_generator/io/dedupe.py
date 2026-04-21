from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import jieba

from sj_generator.models import Question
from sj_generator.io.excel_repo import load_questions
from sj_generator.io.sqlite_repo import load_all_questions


_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
_JIEBA_READY = False


@dataclass(frozen=True)
class DedupeHit:
    left_file: Path
    left_number: str
    left_stem: str
    right_file: Path
    right_number: str
    right_stem: str
    similarity: float
    right_level_path: str = ""


def list_xlsx_in_folder(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted([p for p in folder.rglob("*.xlsx") if p.is_file()])


def dedupe_between_repos(
    *,
    left_repo: Path,
    other_repos: list[Path],
    threshold: float,
    limit: int = 200,
) -> list[DedupeHit]:
    left_questions = [q for q in load_questions(left_repo) if q.stem.strip()]
    other_files = [p for p in other_repos if p.resolve() != left_repo.resolve()]

    right_questions_by_file: list[tuple[Path, list]] = []
    for repo in other_files:
        qs = [q for q in load_questions(repo) if q.stem.strip()]
        if qs:
            right_questions_by_file.append((repo, qs))

    corpus: list[str] = []
    corpus.extend([q.stem for q in left_questions])
    for _, qs in right_questions_by_file:
        corpus.extend([q.stem for q in qs])

    tfidf, norms = _build_tfidf(corpus)

    left_count = len(left_questions)
    idx = 0
    left_vecs = tfidf[:left_count]
    left_norms = norms[:left_count]
    idx += left_count

    hits: list[DedupeHit] = []
    for file_path, qs in right_questions_by_file:
        right_vecs = tfidf[idx : idx + len(qs)]
        right_norms = norms[idx : idx + len(qs)]
        idx += len(qs)

        for li, lq in enumerate(left_questions):
            for ri, rq in enumerate(qs):
                sim = _cosine(left_vecs[li], left_norms[li], right_vecs[ri], right_norms[ri])
                if sim >= threshold:
                    hits.append(
                        DedupeHit(
                            left_file=left_repo,
                            left_number=lq.number,
                            left_stem=lq.stem,
                            right_file=file_path,
                            right_number=rq.number,
                            right_stem=rq.stem,
                            similarity=sim,
                        )
                    )

    hits.sort(key=lambda x: x.similarity, reverse=True)
    if limit > 0:
        hits = hits[:limit]
    return hits


def dedupe_between_questions_and_repos(
    *,
    left_questions: list[Question],
    left_file: Path,
    other_repos: list[Path],
    threshold: float,
    limit: int = 200,
) -> list[DedupeHit]:
    filtered_left_questions = [q for q in left_questions if q.stem.strip()]
    other_files = [p for p in other_repos if p.resolve() != left_file.resolve()]

    right_questions_by_file: list[tuple[Path, list[Question]]] = []
    for repo in other_files:
        qs = [q for q in load_questions(repo) if q.stem.strip()]
        if qs:
            right_questions_by_file.append((repo, qs))

    corpus: list[str] = []
    corpus.extend([q.stem for q in filtered_left_questions])
    for _, qs in right_questions_by_file:
        corpus.extend([q.stem for q in qs])

    tfidf, norms = _build_tfidf(corpus)

    left_count = len(filtered_left_questions)
    idx = 0
    left_vecs = tfidf[:left_count]
    left_norms = norms[:left_count]
    idx += left_count

    hits: list[DedupeHit] = []
    for file_path, qs in right_questions_by_file:
        right_vecs = tfidf[idx : idx + len(qs)]
        right_norms = norms[idx : idx + len(qs)]
        idx += len(qs)

        for li, lq in enumerate(filtered_left_questions):
            for ri, rq in enumerate(qs):
                sim = _cosine(left_vecs[li], left_norms[li], right_vecs[ri], right_norms[ri])
                if sim >= threshold:
                    hits.append(
                        DedupeHit(
                            left_file=left_file,
                            left_number=lq.number,
                            left_stem=lq.stem,
                            right_file=file_path,
                            right_number=rq.number,
                            right_stem=rq.stem,
                            similarity=sim,
                        )
                    )

    hits.sort(key=lambda x: x.similarity, reverse=True)
    if limit > 0:
        hits = hits[:limit]
    return hits


def dedupe_between_questions_and_db(
    *,
    left_questions: list[Question],
    left_file: Path,
    db_path: Path,
    threshold: float,
    limit: int = 200,
) -> list[DedupeHit]:
    filtered_left_questions = [q for q in left_questions if q.stem.strip()]
    db_questions = [q for q in load_all_questions(db_path) if q.stem.strip()]

    corpus: list[str] = []
    corpus.extend([q.stem for q in filtered_left_questions])
    corpus.extend([q.stem for q in db_questions])

    tfidf, norms = _build_tfidf(corpus)

    left_count = len(filtered_left_questions)
    left_vecs = tfidf[:left_count]
    left_norms = norms[:left_count]
    right_vecs = tfidf[left_count:]
    right_norms = norms[left_count:]

    hits: list[DedupeHit] = []
    for li, lq in enumerate(filtered_left_questions):
        for ri, rq in enumerate(db_questions):
            sim = _cosine(left_vecs[li], left_norms[li], right_vecs[ri], right_norms[ri])
            if sim >= threshold:
                hits.append(
                    DedupeHit(
                        left_file=left_file,
                        left_number=lq.number,
                        left_stem=lq.stem,
                        right_file=db_path,
                        right_number=rq.id,
                        right_stem=rq.stem,
                        right_level_path=rq.level_path,
                        similarity=sim,
                    )
                )

    hits.sort(key=lambda x: x.similarity, reverse=True)
    if limit > 0:
        hits = hits[:limit]
    return hits


def _normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()

def _tokenize(text: str) -> list[str]:
    global _JIEBA_READY
    if not _JIEBA_READY:
        jieba.setLogLevel(20)
        jieba.initialize()
        _JIEBA_READY = True
    text = _normalize_text(text)
    if not text:
        return []
    cleaned = " ".join(_TOKEN_RE.findall(text))
    if not cleaned:
        return []
    tokens = [t.strip() for t in jieba.cut(cleaned) if t.strip()]
    return [t for t in tokens if len(t) > 1]


def _build_tfidf(texts: list[str]) -> tuple[list[dict[str, float]], list[float]]:
    docs = [_tokenize(t) for t in texts]

    df: dict[str, int] = {}
    for tokens in docs:
        seen = set(tokens)
        for tok in seen:
            df[tok] = df.get(tok, 0) + 1

    n = max(1, len(docs))
    idf: dict[str, float] = {}
    for tok, d in df.items():
        idf[tok] = math.log((1 + n) / (1 + d)) + 1.0

    vectors: list[dict[str, float]] = []
    norms: list[float] = []
    for tokens in docs:
        if not tokens:
            vectors.append({})
            norms.append(0.0)
            continue

        tf: dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1

        total = sum(tf.values())
        vec: dict[str, float] = {}
        for tok, c in tf.items():
            vec[tok] = (c / total) * idf.get(tok, 0.0)

        vectors.append(vec)
        norms.append(math.sqrt(sum(v * v for v in vec.values())))

    return vectors, norms


def _cosine(
    a: dict[str, float],
    a_norm: float,
    b: dict[str, float],
    b_norm: float,
) -> float:
    if a_norm <= 0 or b_norm <= 0:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
        a_norm, b_norm = b_norm, a_norm
    dot = 0.0
    for k, v in a.items():
        dot += v * b.get(k, 0.0)
    return dot / (a_norm * b_norm)
