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
_TRINAV_LINE_SUFFIX_RE = re.compile(r"^(?P<root>\d+)113\d+$")
_TRINAV_LINE_L_SUFFIX_RE = re.compile(r"^(?P<root>\d+)[1-9]L\d+$", re.IGNORECASE)
_TRINAV_EMBEDDED_SUFFIX_RE = re.compile(r"^(?:113|[1-9]L|[1-9]\d+)\d+$", re.IGNORECASE)
_PREPLOT_ACQUIRED_SUFFIX_RE = re.compile(r"^[A-Z]+\d+[A-Z0-9_-]*$", re.IGNORECASE)
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
    baseline_file_name: str = ""

    @property
    def has_match(self) -> bool:
        return bool(self.sequence_id)


def sequence_sort_key(row: Postplot4DMatchRow) -> tuple[int | str, ...]:
    """Stable natural ordering for sequences ('3' < '20'), text fallback."""
    try:
        return (int(row.sequence_no), row.sequence_no.upper())
    except ValueError:
        return (-1, row.sequence_no.upper())


def find_match_by_sequence_no(
    rows: list[Postplot4DMatchRow],
    sequence_text: str,
) -> Postplot4DMatchRow | None:
    """Find a match by sequence number, tolerant of leading zeros / case."""
    query = (sequence_text or "").strip()
    if not query:
        return None
    query_upper = query.upper()
    query_stripped = query.lstrip("0") or "0"
    for row in rows:
        if row.sequence_no == query or row.sequence_no.upper() == query_upper:
            return row
        if (row.sequence_no.lstrip("0") or "0") == query_stripped:
            return row
    return None


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


def _reverse_leading_prefix_alias_forms(text: str) -> set[str]:
    """Map baseline names like 0114451U to common acquired prefixes 8114451U, 5114451U, …"""
    forms: set[str] = set()
    for raw in (text or "", *_tokens(text), *_line_family_forms(text)):
        value = raw.strip().upper().strip("/\\ .:")
        if not value.startswith("0") or len(value) < 4:
            continue
        rest = value[1:]
        if not rest or not rest[0].isdigit():
            continue
        for prefix in "123456789":
            forms.add(f"{prefix}{rest}")
    return forms


def _preplot_line_root_forms(text: str) -> set[str]:
    """Extract embedded preplot line ids from acquired names like 51892113001."""
    forms: set[str] = set()
    for raw in (text or "", *_tokens(text)):
        value = raw.strip().upper().strip("/\\ .:")
        if not value:
            continue
        for pattern in (_TRINAV_LINE_SUFFIX_RE, _TRINAV_LINE_L_SUFFIX_RE):
            match = pattern.match(value)
            if match:
                root = match.group("root")
                if len(root) >= 3:
                    forms.add(root)
    return forms


def _preplot_prefix_root_forms(text: str, preplot_names: set[str]) -> set[str]:
    """Match acquired names to catalog preplot ids by longest valid prefix."""
    if not text or not preplot_names:
        return set()
    matches: list[str] = []
    values = [
        value.strip().upper().strip("/\\ .:")
        for value in (text, *_tokens(text))
        if value.strip().upper().strip("/\\ .:")
    ]
    for value in values:
        for name in preplot_names:
            candidate = (name or "").strip().upper()
            if not candidate or not value.startswith(candidate) or len(value) <= len(candidate):
                continue
            rest = value[len(candidate):]
            if _TRINAV_EMBEDDED_SUFFIX_RE.match(rest) or _PREPLOT_ACQUIRED_SUFFIX_RE.match(rest):
                matches.append(candidate)
    if not matches:
        return set()
    return {max(matches, key=len)}


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


def _sequence_forms(
    seq: LineSequence,
    *,
    include_context: bool = True,
    include_file_name: bool = False,
    preplot_names: set[str] | None = None,
) -> set[str]:
    forms = set()
    texts = [seq.line_name]
    if include_context:
        texts.extend([seq.sequence_no, seq.file_name, Path(seq.file_name).stem])
    elif include_file_name:
        texts.extend([seq.file_name, Path(seq.file_name).stem])
    for text in texts:
        forms.update(_text_forms(text))
        forms.update(_parent_line_forms(text))
        forms.update(_leading_prefix_alias_forms(text))
        forms.update(_preplot_line_root_forms(text))
        if preplot_names:
            forms.update(_preplot_prefix_root_forms(text, preplot_names))
    return forms


def _candidate_forms(candidate: BaselineCandidate) -> set[str]:
    forms = set()
    for text in candidate.candidate_texts:
        forms.update(_text_forms(text))
        forms.update(_line_family_forms(text))
        forms.update(_parent_line_forms(text))
        forms.update(_leading_prefix_alias_forms(text))
        forms.update(_reverse_leading_prefix_alias_forms(text))
        forms.update(_preplot_line_root_forms(text))
    return forms


def _is_match(candidate: BaselineCandidate, seq: LineSequence) -> bool:
    candidate_forms = _candidate_forms(candidate)
    seq_forms = _sequence_forms(seq)
    if not candidate_forms or not seq_forms:
        return False
    return bool(candidate_forms.intersection(seq_forms))


def _sequence_form_index(
    sequences: list[LineSequence],
    *,
    include_context: bool = True,
    include_file_name: bool = False,
    preplot_names: set[str] | None = None,
) -> tuple[list[LineSequence], dict[str, list[LineSequence]]]:
    """Index imported sequences once so large preplot sets do not hang the UI."""
    ordered = sorted(sequences, key=lambda seq: (_sort_key(seq.line_name), seq.sequence_no))
    index: dict[str, list[LineSequence]] = {}
    for seq in ordered:
        for form in _sequence_forms(
            seq,
            include_context=include_context,
            include_file_name=include_file_name,
            preplot_names=preplot_names,
        ):
            index.setdefault(form, []).append(seq)
    return ordered, index


def _matching_sequences(
    candidate: BaselineCandidate,
    ordered_sequences: list[LineSequence],
    indexed_sequences: dict[str, list[LineSequence]],
) -> list[LineSequence]:
    forms = _candidate_forms(candidate)
    if not forms:
        return []
    matched_ids = {
        id(seq)
        for form in forms
        for seq in indexed_sequences.get(form, [])
    }
    if not matched_ids:
        return []
    return [seq for seq in ordered_sequences if id(seq) in matched_ids]


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
                candidate_texts=tuple(text for text in (name,) if text),
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
    preplot_names = None
    if baseline_kind == "preplot":
        preplot_names = {
            form
            for candidate in candidates
            for form in _candidate_forms(candidate)
            if len(form) >= 3 and form not in _STOP_TOKENS
        }
    sequences, sequence_index = _sequence_form_index(
        map_data.sequences,
        include_context=baseline_kind == "navplan",
        include_file_name=baseline_kind == "preplot",
        preplot_names=preplot_names,
    )

    rows: list[Postplot4DMatchRow] = []
    for candidate in candidates:
        matches = _matching_sequences(candidate, sequences, sequence_index)
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
                    baseline_file_name=candidate.file_name,
                )
            )
    return rows
