# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Tiny QWidget that paints a rolling-hashrate polyline.

No PyQt6-Charts dependency: just a QPainter polyline over a (t, rate)
sequence. The widget owns no data; the dashboard pushes samples via
`set_samples()` whenever the underlying HashrateRing changes.
"""

from __future__ import annotations

from typing import List, Tuple

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_rate(hps: float) -> str:
    if hps <= 0:
        return "0 H/s"
    if hps >= 1e9:
        return f"{hps / 1e9:.2f} GH/s"
    if hps >= 1e6:
        return f"{hps / 1e6:.2f} MH/s"
    if hps >= 1e3:
        return f"{hps / 1e3:.1f} kH/s"
    return f"{hps:.0f} H/s"


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class HashrateChart(QWidget):
    """Polyline chart of hashrate over time.

    Samples are (t_seconds, rate_hps). The widget computes its own
    bounds: x = first..last sample time, y = 0..max(rate). On empty
    samples it shows a placeholder message.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._samples: List[Tuple[float, float]] = []
        self._window_seconds: float = 300.0
        self.setMinimumHeight(140)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_samples(self, samples: List[Tuple[float, float]]) -> None:
        self._samples = samples
        self.update()

    def set_window_seconds(self, seconds: float) -> None:
        self._window_seconds = max(seconds, 1.0)
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg = self.palette().window().color().darker(110)
        p.fillRect(self.rect(), bg)

        margin_l = 56
        margin_r = 12
        margin_t = 18
        margin_b = 22
        w = self.width()
        h = self.height()
        plot_w = max(w - margin_l - margin_r, 10)
        plot_h = max(h - margin_t - margin_b, 10)
        plot_x0 = margin_l
        plot_y0 = margin_t

        grid_pen = QPen(QColor(255, 255, 255, 30))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for i in range(0, 5):
            yy = plot_y0 + plot_h * i / 4
            p.drawLine(int(plot_x0), int(yy),
                       int(plot_x0 + plot_w), int(yy))

        axis_font = QFont(self.font())
        axis_font.setPointSizeF(max(self.font().pointSizeF() - 1.0, 7.0))
        p.setFont(axis_font)
        fm = QFontMetrics(axis_font)

        if not self._samples:
            p.setPen(QColor(180, 180, 180))
            text = "no data yet"
            tw = fm.horizontalAdvance(text)
            p.drawText(int(plot_x0 + (plot_w - tw) / 2),
                       int(plot_y0 + plot_h / 2 + fm.ascent() / 2),
                       text)
            p.end()
            return

        first_t = self._samples[0][0]
        last_t = self._samples[-1][0]
        # Anchor x-window to the configured size so a short session doesn't
        # scale up. Use whichever is larger (actual span vs. min window).
        actual_span = max(last_t - first_t, 1e-3)
        span = max(self._window_seconds, actual_span)
        x_origin = last_t - span

        max_rate = max((r for _, r in self._samples), default=1.0)
        if max_rate <= 0:
            max_rate = 1.0
        # Round y-axis up to a "nice" upper bound.
        y_max = _nice_ceiling(max_rate)

        def to_px(t: float, r: float) -> QPointF:
            x = plot_x0 + plot_w * (t - x_origin) / span
            y = plot_y0 + plot_h * (1.0 - r / y_max)
            return QPointF(x, y)

        # Y-axis labels.
        p.setPen(QColor(180, 180, 180))
        for i in range(0, 5):
            yy = plot_y0 + plot_h * i / 4
            label_rate = y_max * (1.0 - i / 4)
            label = _fmt_rate(label_rate)
            tw = fm.horizontalAdvance(label)
            p.drawText(int(plot_x0 - tw - 6),
                       int(yy + fm.ascent() / 2 - 1), label)

        # X-axis labels: show how far back (now-Ns).
        for i in range(0, 5):
            xx = plot_x0 + plot_w * i / 4
            seconds_ago = int(span * (1.0 - i / 4))
            label = "now" if seconds_ago == 0 else f"-{seconds_ago}s"
            tw = fm.horizontalAdvance(label)
            p.drawText(int(xx - tw / 2), int(plot_y0 + plot_h + 14), label)

        # Polyline of samples.
        line_pen = QPen(QColor(80, 180, 220))
        line_pen.setWidthF(1.6)
        p.setPen(line_pen)
        poly = QPolygonF()
        for t, r in self._samples:
            poly.append(to_px(t, r))
        if poly.size() >= 2:
            p.drawPolyline(poly)

        # Filled area under the line for a softer look.
        if poly.size() >= 2:
            area = QPolygonF(poly)
            area.append(QPointF(plot_x0 + plot_w, plot_y0 + plot_h))
            area.append(QPointF(plot_x0, plot_y0 + plot_h))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(80, 180, 220, 40)))
            p.drawPolygon(area)

        # Last-sample marker + label.
        last_t, last_r = self._samples[-1]
        last_pt = to_px(last_t, last_r)
        marker_pen = QPen(QColor(240, 240, 240))
        marker_pen.setWidthF(1.0)
        p.setPen(marker_pen)
        p.setBrush(QBrush(QColor(80, 180, 220)))
        p.drawEllipse(last_pt, 3.0, 3.0)
        label = _fmt_rate(last_r)
        p.setPen(QColor(220, 220, 220))
        tx = min(last_pt.x() + 6,
                 plot_x0 + plot_w - fm.horizontalAdvance(label) - 2)
        ty = max(last_pt.y() - 4, plot_y0 + fm.ascent() + 2)
        p.drawText(int(tx), int(ty), label)

        p.end()


# ---------------------------------------------------------------------------
# Y-axis ceiling helpers
# ---------------------------------------------------------------------------


def _nice_ceiling(v: float) -> float:
    """Round v up to a 'nice' value for a chart y-axis."""
    if v <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    frac = v / base
    if frac <= 1.0:
        return 1.0 * base
    if frac <= 2.0:
        return 2.0 * base
    if frac <= 5.0:
        return 5.0 * base
    return 10.0 * base
