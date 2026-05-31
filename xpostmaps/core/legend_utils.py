"""Legend config serialization helpers."""

from __future__ import annotations

from xpostmaps.core.models import (
    AreaLegendEntry,
    LegendConfig,
    LineStyle,
    NavDataType,
    PostplotLegendEntry,
)


def legend_to_dict(config: LegendConfig) -> dict:
    return {
        "areas": [
            {"name": a.name, "color": a.color, "opacity": a.opacity}
            for a in config.areas
        ],
        "postplot_lines": [
            {
                "name": p.name,
                "line_style": p.line_style.value,
                "color": p.color,
                "opacity": p.opacity,
                "data_type": p.data_type.value,
                "sequence_ids": list(p.sequence_ids),
            }
            for p in config.postplot_lines
        ],
    }


def legend_from_dict(data: dict | None) -> LegendConfig:
    if not data:
        return LegendConfig.default()
    areas = []
    for item in data.get("areas", []):
        areas.append(
            AreaLegendEntry(
                name=item.get("name", ""),
                color=item.get("color", "#60a5fa"),
                opacity=float(item.get("opacity", 1.0)),
            )
        )
    lines = []
    for item in data.get("postplot_lines", []):
        raw_style = item.get("line_style", "solid")
        try:
            line_style = LineStyle(raw_style)
        except ValueError:
            line_style = LineStyle.SOLID
        raw_data_type = item.get("data_type", "source")
        try:
            data_type = NavDataType(raw_data_type)
        except ValueError:
            data_type = NavDataType.SOURCE
        lines.append(
            PostplotLegendEntry(
                name=item.get("name", ""),
                line_style=line_style,
                color=item.get("color", "#ef4444"),
                opacity=float(item.get("opacity", 1.0)),
                data_type=data_type,
                sequence_ids=list(item.get("sequence_ids", [])),
            )
        )
    if not areas and not lines:
        return LegendConfig.default()
    return LegendConfig(
        areas=areas or LegendConfig.default().areas,
        postplot_lines=lines or LegendConfig.default().postplot_lines,
    )
