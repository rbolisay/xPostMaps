"""Match imported postplot lines against preplot or navplan baselines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from xpostmaps.core.models import LineSegment, LineSequence, MapData, ProjectSettings

BaselineKind = Literal["navplan", "preplot"]

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_KNOWN_EXTENSION_RE = re.compile(
    r"\.(?:p111|p190|190|txt|navplan|nav|plan)\b",
    re.IGNORECASE,
)
_LINE_FAMILY_WITH_SEQ_RE = re.compile(
    r"^(?P<base>\d{3,8}[A-Z]\d?)[A-Z]*[-_]\d{1,4}[A-Z]*$",
    re.IGNORECASE,
)
_LINE_FAMILY_COMPACT_RE = re.compile(
    r"^(?P<base>\d{3,8}[A-Z]\d?)[A-Z]+\d{1,4}[A-Z]*$",
    re.IGNORECASE,
)
_LEADING_PREFIX_LINE_RE = re.compile(r"^[1-9](?P<rest>\d{6}[A-Z]\d?)$", re.IGNORECASE)
_STOP_TOKENS = {
    "H",
    "LINE",
    "LINENAME",
    "NAME",
    "NAVPLAN",
    "NUMBER",
    "P111",
    "P190",
    "PREPLOT",
    "SUBLINE",
    "TXT",
}


@dataclass(frozen=True)
class BaselineCandidate:
    name: str
    kind: BaselineKind
    file_name: str = ""
    candidate_texts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Postplot4DMatchRow:
    baseline_name: str
    baseline_kind: BaselineKind
    line_name: str
    subline: str
    sequence_no: str
    first_sp: int
    last_sp: int
    line_direction: str
    sequence_id: str = ""

    @property
    def has_match(self) -> bool:
        return bool(self.sequence_id)


def _tokens(text: str) -> list[str]:
    cleaned = _KNOWN_EXTENSION_RE.sub(" ", text or "")
    return [token.upper() for token in _TOKEN_RE.findall(cleaned)]


def _compact(text: str) -> str:
    return "".join(_tokens(text))


def _line_family_forms(text: str) -> set[str]:
    """Return baseline-level names for acquired lines like 1065P1A-070."""
    forms: set[str] = set()
    for raw in (text or "", *_tokens(text)):
        value = raw.strip().upper().strip("/\\ .:")
        if not value:
            continue
        match = _LINE_FAMILY_WITH_SEQ_RE.match(value)
        if match:
            forms.add(match.group("base").upper())
            continue
        match = _LINE_FAMILY_COMPACT_RE.match(value)
        if match:
            forms.add(match.group("base").upper())
    return forms


def _parent_line_forms(text: str) -> set[str]:
    """Return parent names like 1065P for sequence names like 1065P1A-070."""
    forms: set[str] = set()
    for family in _line_family_forms(text):
        parent = re.sub(r"(?<=[A-Z])\d$", "", family)
        if parent and parent != family and len(parent) >= 4:
            forms.add(parent)
    return forms


def _leading_prefix_alias_forms(text: str) -> set[str]:
    """Map acquired variants like 8114451U to baseline names like 0114451U."""
    forms: set[str] = set()
    for raw in (text or "", *_tokens(text), *_line_family_forms(text)):
        value = raw.strip().upper().strip("/\\ .:")
        match = _LEADING_PREFIX_LINE_RE.match(value)
        if match:
            forms.add(f"0{match.group('rest').upper()}")
    return forms


def _text_forms(text: str) -> set[str]:
    """Build robust match keys from noisy headers, names, and filenames."""
    forms: set[str] = set()
    compact = _compact(text)
    if compact:
        forms.add(compact)
    forms.update(_line_family_forms(text))
    for token in _tokens(text):
        if token in _STOP_TOKENS:
            continue
        # Ignore bare H-record numbers but keep real mixed line names like 0103643A.
        if token.startswith("H") and token[1:].isdigit():
            continue
        forms.update(_line_family_forms(token))
        if len(token) >= 2:
            forms.add(token)
    return forms


def _sequence_forms(seq: LineSequence) -> set[str]:
    forms = set()
    for text in (seq.line_name, seq.sequence_no, seq.file_name, Path(seq.file_name).stem):
        forms.update(_text_forms(text))
        forms.update(_parent_line_forms(text))
        forms.update(_leading_prefix_alias_forms(text))
    return forms


def _candidate_forms(candidate: BaselineCandidate) -> set[str]:
    forms = set()
    for text in candidate.candidate_texts:
        forms.update(_text_forms(text))
    return forms


def _is_match(candidate: BaselineCandidate, seq: LineSequence) -> bool:
    candidate_forms = _candidate_forms(candidate)
    seq_forms = _sequence_forms(seq)
    if not candidate_forms or not seq_forms:
        return False
    return bool(candidate_forms.intersection(seq_forms))


def _sort_key(text: str) -> tuple[str, int, str]:
    forms = sorted(_text_forms(text))
    primary = forms[0] if forms else text.upper()
    digits = re.sub(r"\D+", "", primary)
    return primary, int(digits) if digits else -1, text.upper()


def _segment_point_range(segment: LineSegment) -> tuple[int, int]:
    count = len(segment.xs)
    if count <= 0:
        return 0, 0
    try:
        first = int(float(segment.sequence_no))
    except (TypeError, ValueError):
        first = 0
    if first:
        return first, first + count - 1
    return 0, count - 1


def _unique_candidates(candidates: list[BaselineCandidate]) -> list[BaselineCandidate]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[BaselineCandidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.file_name, _compact(candidate.name))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return sorted(unique, key=lambda item: (_sort_key(item.name), item.file_name))


def _segments_by_file(segments: list[LineSegment]) -> dict[str, list[LineSegment]]:
    grouped: dict[str, list[LineSegment]] = {}
    for segment in segments:
        if not segment.file_name:
            continue
        grouped.setdefault(Path(segment.file_name).name, []).append(segment)
    return grouped


def build_navplan_candidates(
    map_data: MapData | None,
    settings: ProjectSettings | None,
) -> list[BaselineCandidate]:
    if map_data is None:
        return []
    candidates: list[BaselineCandidate] = []
    by_file = _segments_by_file(map_data.navplan_segments)

    for entry in (settings.navplan_catalog if settings else []):
        path = Path(entry.file_path)
        file_segments = by_file.get(path.name, [])
        texts = [
            entry.navplan_name,
            path.stem,
            path.name,
            *(segment.line_name for segment in file_segments),
        ]
        candidates.append(
            BaselineCandidate(
                name=entry.navplan_name or path.stem,
                kind="navplan",
                file_name=path.name,
                candidate_texts=tuple(text for text in texts if text),
            )
        )

    catalog_files = {Path(entry.file_path).name for entry in (settings.navplan_catalog if settings else [])}
    for segment in map_data.navplan_segments:
        file_name = Path(segment.file_name).name if segment.file_name else ""
        if file_name in catalog_files:
            continue
        name = segment.line_name or Path(file_name).stem
        candidates.append(
            BaselineCandidate(
                name=name,
                kind="navplan",
                file_name=file_name,
                candidate_texts=tuple(text for text in (name, file_name, Path(file_name).stem) if text),
            )
        )

    return _unique_candidates(candidates)


def build_preplot_candidates(map_data: MapData | None) -> list[BaselineCandidate]:
    if map_data is None:
        return []
    candidates: list[BaselineCandidate] = []
    for segment in map_data.preplot_segments:
        file_name = Path(segment.file_name).name if segment.file_name else ""
        name = segment.line_name or Path(file_name).stem
        candidates.append(
            BaselineCandidate(
                name=name,
                kind="preplot",
                file_name=file_name,
                candidate_texts=tuple(text for text in (name, file_name, Path(file_name).stem) if text),
            )
        )
    return _unique_candidates(candidates)


def build_postplot_4d_rows(
    map_data: MapData | None,
    settings: ProjectSettings | None,
    baseline_kind: BaselineKind,
) -> list[Postplot4DMatchRow]:
    if map_data is None:
        return []

    candidates = (
        build_navplan_candidates(map_data, settings)
        if baseline_kind == "navplan"
        else build_preplot_candidates(map_data)
    )
    sequences = sorted(map_data.sequences, key=lambda seq: (_sort_key(seq.line_name), seq.sequence_no))

    rows: list[Postplot4DMatchRow] = []
    for candidate in candidates:
        matches = [seq for seq in sequences if _is_match(candidate, seq)]
        if not matches:
            rows.append(
                Postplot4DMatchRow(
                    baseline_name=candidate.name,
                    baseline_kind=baseline_kind,
                    line_name="No match",
                    subline="",
                    sequence_no="",
                    first_sp=0,
                    last_sp=0,
                    line_direction="",
                )
            )
            continue
        for seq in matches:
            rows.append(
                Postplot4DMatchRow(
                    baseline_name=candidate.name,
                    baseline_kind=baseline_kind,
                    line_name=seq.line_name,
                    subline=seq.subline,
                    sequence_no=seq.sequence_no,
                    first_sp=seq.first_sp,
                    last_sp=seq.last_sp,
                    line_direction=seq.line_direction,
                    sequence_id=seq.seq_id,
                )
            )
    return rows
