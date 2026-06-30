"""Persist survey plot aggregates in the project database for fast reload."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import PlotKind
from xpostmaps.core.postplot_4d_survey_plot_data import (
    AerialHeatmapData,
    CumulativeHistogram,
    SurveyPlotsLoadResult,
    SurveySpecPieData,
    SurveySpecPieStats,
    PieSlice,
)
from xpostmaps.core.postplot_4d_plot_settings import load_survey_specs
from xpostmaps.core.postplot_4d_survey_spec import Severity, StatType, SurveySpecRow

SURVEY_PLOT_CACHE_VERSION = 3
_MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class SurveyPlotCacheRecord:
    """Deserialized survey plot cache payload."""

    fingerprint: str
    streamers_detected: bool
    available_kinds: list[PlotKind]
    metric_values: dict[PlotKind, list[float]]
    heatmap_cache: dict[PlotKind, AerialHeatmapData]
    histogram_cache: dict[PlotKind, CumulativeHistogram]
    pie_charts: list[SurveySpecPieData]
    sequence_count: int
    shotpoint_count: int


def survey_specs_fingerprint() -> str:
    specs = load_survey_specs()
    payload = [
        {
            "metric": row.metric,
            "statistic": row.statistic.value,
            "reference_value": row.reference_value,
            "stat_value": row.stat_value,
            "absolute": row.absolute,
            "severity": row.severity.value,
        }
        for row in specs
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def match_rows_fingerprint(match_rows: list[Postplot4DMatchRow]) -> str:
    parts = sorted(
        (
            row.sequence_id,
            row.baseline_name,
            row.line_name,
            row.subline,
            row.sequence_no,
            row.first_sp,
            row.last_sp,
            row.baseline_file_name,
        )
        for row in match_rows
        if row.has_match and row.sequence_id
    )
    return hashlib.sha256(
        json.dumps(parts, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def compute_source_fingerprint(
    *,
    baseline_kind: str,
    match_rows: list[Postplot4DMatchRow],
    diff_signature: str,
) -> str:
    """Composite fingerprint for cache invalidation."""
    match_fp = match_rows_fingerprint(match_rows)
    specs_fp = survey_specs_fingerprint()
    payload = (
        f"v{SURVEY_PLOT_CACHE_VERSION}|{baseline_kind}|{match_fp}|"
        f"{diff_signature}|{specs_fp}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _spec_row_to_dict(row: SurveySpecRow) -> dict[str, Any]:
    return {
        "metric": row.metric,
        "statistic": row.statistic.value,
        "reference_value": row.reference_value,
        "stat_value": row.stat_value,
        "absolute": row.absolute,
        "severity": row.severity.value,
    }


def _spec_row_from_dict(data: dict[str, Any]) -> SurveySpecRow:
    return SurveySpecRow(
        metric=data.get("metric", "crossline"),
        statistic=StatType(data.get("statistic", StatType.MAX_VALUE.value)),
        reference_value=float(data.get("reference_value", 0.0)),
        stat_value=float(data.get("stat_value", 0.0)),
        absolute=bool(data.get("absolute", True)),
        severity=Severity(data.get("severity", Severity.ERROR.value)),
    )


def _pie_stats_to_dict(stats: SurveySpecPieStats | None) -> dict[str, Any] | None:
    if stats is None:
        return None
    return asdict(stats)


def _pie_stats_from_dict(data: dict[str, Any] | None) -> SurveySpecPieStats | None:
    if not data:
        return None
    return SurveySpecPieStats(
        total_shotpoints=int(data["total_shotpoints"]),
        pass_count=int(data["pass_count"]),
        fail_count=int(data["fail_count"]),
        pass_pct=float(data["pass_pct"]),
        fail_pct=float(data["fail_pct"]),
        average=data.get("average"),
        maximum=data.get("maximum"),
        minimum=data.get("minimum"),
        unit=str(data.get("unit", "")),
    )


def _heatmap_to_dict(data: AerialHeatmapData) -> dict[str, Any]:
    return {
        "sequence_labels": list(data.sequence_labels),
        "sequence_min": int(data.sequence_min),
        "sequence_max": int(data.sequence_max),
        "shot_min": int(data.shot_min),
        "shot_max": int(data.shot_max),
        "value_limit": float(data.value_limit),
        "source_no": str(data.source_no),
        "kind": data.kind,
        "header_title": data.header_title,
        "survey_label": data.survey_label,
        "map_label": data.map_label,
    }


def _heatmap_from_dict(kind: str, meta: dict[str, Any], image: np.ndarray) -> AerialHeatmapData:
    return AerialHeatmapData(
        image=image,
        sequence_labels=list(meta.get("sequence_labels") or []),
        sequence_min=int(meta.get("sequence_min", 0)),
        sequence_max=int(meta.get("sequence_max", 0)),
        shot_min=int(meta.get("shot_min", 0)),
        shot_max=int(meta.get("shot_max", 0)),
        value_limit=float(meta.get("value_limit", 15.0)),
        source_no=str(meta.get("source_no", "")),
        kind=kind,  # type: ignore[assignment]
        header_title=str(meta.get("header_title", "Aerial View")),
        survey_label=str(meta.get("survey_label", "Survey: Monitor")),
        map_label=str(meta.get("map_label", "")),
    )


def _histogram_to_dict(data: CumulativeHistogram) -> dict[str, Any]:
    return {
        "bucket_labels": list(data.bucket_labels),
        "cumulative_pct": list(data.cumulative_pct),
        "sample_count": int(data.sample_count),
        "x_axis_unit": data.x_axis_unit,
        "x_positions": list(data.x_positions) if data.x_positions is not None else None,
    }


def _histogram_from_dict(data: dict[str, Any]) -> CumulativeHistogram:
    positions = data.get("x_positions")
    return CumulativeHistogram(
        bucket_labels=list(data.get("bucket_labels") or []),
        cumulative_pct=[float(value) for value in data.get("cumulative_pct") or []],
        sample_count=int(data.get("sample_count", 0)),
        x_axis_unit=str(data.get("x_axis_unit", "meter")),
        x_positions=[float(value) for value in positions] if positions else None,
    )


def _pie_chart_to_dict(chart: SurveySpecPieData) -> dict[str, Any]:
    return {
        "spec": _spec_row_to_dict(chart.spec),
        "headline": chart.headline,
        "title": chart.title,
        "tab_label": chart.tab_label,
        "slices": [asdict(slice_) for slice_ in chart.slices],
        "subtitle": chart.subtitle,
        "stats": _pie_stats_to_dict(chart.stats),
        "spec_passed": chart.spec_passed,
        "fail_color": chart.fail_color,
        "severity": chart.severity.value,
    }


def _pie_chart_from_dict(data: dict[str, Any]) -> SurveySpecPieData:
    slices = [
        PieSlice(
            label=str(item.get("label", "")),
            value=float(item.get("value", 0.0)),
            color=str(item.get("color", "")),
        )
        for item in data.get("slices") or []
    ]
    return SurveySpecPieData(
        spec=_spec_row_from_dict(data.get("spec") or {}),
        headline=str(data.get("headline", "")),
        title=str(data.get("title", "")),
        tab_label=str(data.get("tab_label", "")),
        slices=slices,
        subtitle=str(data.get("subtitle", "")),
        stats=_pie_stats_from_dict(data.get("stats")),
        spec_passed=bool(data.get("spec_passed", True)),
        fail_color=str(data.get("fail_color", "#ef4444")),
        severity=Severity(data.get("severity", Severity.ERROR.value)),
    )


def serialize_survey_plot_cache(
    result: SurveyPlotsLoadResult,
    *,
    fingerprint: str,
) -> bytes:
    """Pack computed survey plot aggregates into a compressed blob."""
    manifest: dict[str, Any] = {
        "version": SURVEY_PLOT_CACHE_VERSION,
        "fingerprint": fingerprint,
        "streamers_detected": result.streamers_detected,
        "available_kinds": list(result.available_kinds),
        "metric_values": {
            kind: [float(value) for value in values]
            for kind, values in result.metric_values.items()
        },
        "heatmap_meta": {
            kind: _heatmap_to_dict(data)
            for kind, data in result.heatmap_cache.items()
        },
        "histogram_cache": {
            kind: _histogram_to_dict(data)
            for kind, data in result.histogram_cache.items()
        },
        "pie_charts": [_pie_chart_to_dict(chart) for chart in result.pie_charts],
        "sequence_count": int(result.sequence_count),
        "shotpoint_count": int(result.shotpoint_count),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            _MANIFEST_NAME,
            json.dumps(manifest, separators=(",", ":")),
        )
        for kind, data in result.heatmap_cache.items():
            array = np.asarray(data.image, dtype=np.float64)
            npy_buffer = io.BytesIO()
            np.save(npy_buffer, array, allow_pickle=False)
            archive.writestr(f"heatmap_{kind}.npy", npy_buffer.getvalue())
    return buffer.getvalue()


def deserialize_survey_plot_cache(payload: bytes) -> SurveyPlotCacheRecord | None:
    """Restore cached aggregates from a database blob."""
    if not payload:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            manifest = json.loads(archive.read(_MANIFEST_NAME).decode())
            if int(manifest.get("version", 0)) != SURVEY_PLOT_CACHE_VERSION:
                return None
            heatmap_cache: dict[PlotKind, AerialHeatmapData] = {}
            for kind, meta in (manifest.get("heatmap_meta") or {}).items():
                name = f"heatmap_{kind}.npy"
                if name not in archive.namelist():
                    continue
                image = np.load(io.BytesIO(archive.read(name)), allow_pickle=False)
                heatmap_cache[kind] = _heatmap_from_dict(kind, meta, image)
            histogram_cache = {
                kind: _histogram_from_dict(data)
                for kind, data in (manifest.get("histogram_cache") or {}).items()
            }
            pie_charts = [
                _pie_chart_from_dict(item) for item in (manifest.get("pie_charts") or [])
            ]
            metric_values = {
                kind: [float(value) for value in values]
                for kind, values in (manifest.get("metric_values") or {}).items()
            }
            return SurveyPlotCacheRecord(
                fingerprint=str(manifest.get("fingerprint", "")),
                streamers_detected=bool(manifest.get("streamers_detected", False)),
                available_kinds=list(manifest.get("available_kinds") or []),
                metric_values=metric_values,
                heatmap_cache=heatmap_cache,
                histogram_cache=histogram_cache,
                pie_charts=pie_charts,
                sequence_count=int(manifest.get("sequence_count", 0)),
                shotpoint_count=int(manifest.get("shotpoint_count", 0)),
            )
    except (KeyError, json.JSONDecodeError, OSError, ValueError, zipfile.BadZipFile):
        return None


def merge_cache_with_sets(
    cached: SurveyPlotCacheRecord,
    result: SurveyPlotsLoadResult,
) -> SurveyPlotsLoadResult:
    """Attach freshly loaded diff sets to cached plot aggregates."""
    return SurveyPlotsLoadResult(
        sets=list(result.sets),
        streamers_detected=cached.streamers_detected,
        available_kinds=list(cached.available_kinds),
        metric_values=dict(cached.metric_values),
        heatmap_cache=dict(cached.heatmap_cache),
        histogram_cache=dict(cached.histogram_cache),
        pie_charts=list(cached.pie_charts),
        sequence_count=len(result.sets),
        shotpoint_count=result.shotpoint_count,
    )
