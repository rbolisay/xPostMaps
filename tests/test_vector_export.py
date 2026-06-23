"""Vector PDF geometry optimization tests."""

from __future__ import annotations

import numpy as np

from xpostmaps.utils.vector_export import (
    VectorExportContext,
    prepare_vector_line_geometry,
    prepare_vector_scatter_geometry,
    reduce_coordinate_precision,
)


def _ctx(
    *,
    view_span: float = 10_000.0,
    device_w: float = 2000.0,
    device_h: float = 1500.0,
) -> VectorExportContext:
    view_bbox = (0.0, view_span, 0.0, view_span)
    clip_bbox = (-500.0, view_span + 500.0, -500.0, view_span + 500.0)
    return VectorExportContext.from_view(
        view_bbox=view_bbox,
        clip_bbox=clip_bbox,
        view_w=1000,
        view_h=750,
        device_w=device_w,
        device_h=device_h,
    )


def test_scatter_removes_hidden_points() -> None:
    ctx = _ctx()
    xs = np.array([100.0, 5000.0, 20_000.0], dtype=np.float64)
    ys = np.array([100.0, 5000.0, 5000.0], dtype=np.float64)
    cx, cy = prepare_vector_scatter_geometry(xs, ys, ctx, symbol_px=4.0)
    assert cx.size == 2
    assert 20_000.0 not in cx


def test_scatter_grid_deduplication() -> None:
    ctx = _ctx(view_span=1000.0, device_w=500.0, device_h=500.0)
    xs = np.linspace(100.0, 900.0, 50_000, dtype=np.float64)
    ys = np.full(50_000, 500.0, dtype=np.float64)
    cx, cy = prepare_vector_scatter_geometry(xs, ys, ctx, symbol_px=4.0)
    assert cx.size < 500
    assert cx.size > 50


def test_line_detail_increases_vertex_count() -> None:
    xs = np.linspace(0.0, 1000.0, 100_000, dtype=np.float64)
    ys = np.sin(xs * 0.05) * 100.0 + 500.0
    low = _ctx(view_span=1000.0, device_w=800.0, device_h=600.0)
    low = VectorExportContext.from_view(
        view_bbox=low.view_bbox,
        clip_bbox=low.clip_bbox,
        view_w=low.view_w,
        view_h=low.view_h,
        device_w=low.device_w,
        device_h=low.device_h,
        line_detail_percent=0,
    )
    high = VectorExportContext.from_view(
        view_bbox=low.view_bbox,
        clip_bbox=low.clip_bbox,
        view_w=low.view_w,
        view_h=low.view_h,
        device_w=low.device_w,
        device_h=low.device_h,
        line_detail_percent=100,
    )
    cx_low, _ = prepare_vector_line_geometry(xs, ys, low)
    cx_high, _ = prepare_vector_line_geometry(xs, ys, high)
    assert cx_high.size > cx_low.size


def test_line_pixel_decimation_reduces_vertices() -> None:
    ctx = _ctx(view_span=1000.0, device_w=800.0, device_h=600.0)
    xs = np.linspace(0.0, 1000.0, 100_000, dtype=np.float64)
    ys = np.sin(xs * 0.05) * 100.0 + 500.0
    cx, cy = prepare_vector_line_geometry(xs, ys, ctx)
    assert cx.size < 5000
    assert cx.size > 100


def test_coordinate_precision_snaps_to_pixel_grid() -> None:
    ctx = _ctx(view_span=1000.0, device_w=100.0, device_h=100.0)
    xs = np.array([123.456789], dtype=np.float64)
    ys = np.array([987.654321], dtype=np.float64)
    rx, ry = reduce_coordinate_precision(xs, ys, ctx)
    quantum = ctx.world_quantum
    assert abs((rx[0] - ctx.view_bbox[0]) / quantum - round((xs[0] - ctx.view_bbox[0]) / quantum)) < 1e-9
    assert abs((ry[0] - ctx.view_bbox[2]) / quantum - round((ys[0] - ctx.view_bbox[2]) / quantum)) < 1e-9
