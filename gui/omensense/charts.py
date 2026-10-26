"""Drawn instruments: arc gauges, history traces, and fan rotors.

These are painted rather than assembled from stock widgets because none of them
exists in Qt, and because each one is carrying information that a label cannot:

- ArcGauge puts a reading against its range, so 52 degrees reads as "low" at a
  glance without anyone having to remember what the ceiling is.
- Trace keeps two minutes of history. A temperature's direction and spikiness
  are the useful part; the instantaneous number alone hides both.
- FanRotor turns at the speed the fan is actually turning. That is the one piece
  of motion in this application that carries information rather than decorating
  a transition, which is the bar motion has to clear to exist at all.

Reduced motion is honoured through KDE's own setting rather than a guess: when
animation is switched off in System Settings, the rotor holds still and shows
its RPM as a number like everything else.
"""

from __future__ import annotations

from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

#: One timer drives every rotor in the window. Three or four QTimers ticking
#: independently is three or four wakeups a frame for no benefit.
#:
#: 16 ms rather than 33: at 30 Hz a rotor at speed advances far enough between
#: frames to read as stepping rather than turning.
FRAME_MS = 16


def animation_factor() -> float:
    """KDE's animation setting; 0.0 when the user has turned animation off.

    Qt exposes no cross-platform reduced-motion hint, so read the setting this
    desktop actually has. System Settings writes AnimationDurationFactor into
    kdeglobals, and 0 there is this platform's prefers-reduced-motion.
    """
    config = QtCore.QSettings(
        QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.GenericConfigLocation)
        + "/kdeglobals",
        QtCore.QSettings.Format.IniFormat,
    )
    try:
        return max(0.0, float(config.value("KDE/AnimationDurationFactor", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def tone_colour(tone: str | None) -> QtGui.QColor:
    return QtGui.QColor({"warn": theme.WARN, "alert": theme.ALERT,
                         "ok": theme.OK}.get(tone, theme.get_dynamic_accent()))


class ArcGauge(QtWidgets.QWidget):
    """A reading shown against its range, with the number in the middle."""

    #: 240 degrees leaves a gap at the bottom, so the ends of the range are
    #: visually distinct instead of meeting in a closed ring.
    SPAN = 240
    START = 210

    def __init__(self, caption: str, unit: str, low: float, high: float,
                 diameter: int = 132):
        super().__init__()
        self.caption = caption
        self.unit = unit
        self.low = low
        self.high = high
        self._value = None
        self._tone = None
        self.setFixedSize(diameter, diameter + 18)
        self.setAccessibleName(caption)

    def set(self, value, tone: str | None = None):
        if value != self._value or tone != self._tone:
            self._value, self._tone = value, tone
            self.setAccessibleDescription(
                f"{self.caption}: {'unknown' if value is None else value}"
                f" {self.unit}")
            self.update()

    def _fraction(self) -> float:
        if self._value is None:
            return 0.0
        span = self.high - self.low
        return 0.0 if span <= 0 else max(
            0.0, min(1.0, (float(self._value) - self.low) / span))

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        thickness = 9
        diameter = min(self.width(), self.height() - 18)
        box = QtCore.QRectF((self.width() - diameter) / 2 + thickness / 2,
                            thickness / 2,
                            diameter - thickness, diameter - thickness)

        track = QtGui.QPen(QtGui.QColor(theme.SURFACE_SUNKEN), thickness)
        track.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(box, self.START * 16, -self.SPAN * 16)

        fraction = self._fraction()
        if fraction > 0:
            colour = tone_colour(self._tone)
            # Along the arc the colour lifts slightly, so a nearly-full gauge
            # reads as hotter without introducing a second hue.
            gradient = QtGui.QConicalGradient(box.center(), self.START)
            gradient.setColorAt(0.0, colour.darker(155))
            gradient.setColorAt(min(0.999, self.SPAN / 360.0), colour)
            arc = QtGui.QPen(QtGui.QBrush(gradient), thickness)
            arc.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            painter.drawArc(box, self.START * 16,
                            int(-self.SPAN * fraction * 16))

        centre_y = box.center().y()
        text = "--" if self._value is None else f"{self._value}"
        painter.setPen(QtGui.QColor(theme.TEXT_PRIMARY))
        painter.setFont(theme.numeric_font(26, theme.WEIGHT_REGULAR))
        painter.drawText(
            QtCore.QRectF(0, centre_y - 26, self.width(), 32),
            QtCore.Qt.AlignmentFlag.AlignCenter, text)

        painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
        painter.setFont(theme.ui_font(theme.SIZE_SMALL))
        painter.drawText(
            QtCore.QRectF(0, centre_y + 4, self.width(), 16),
            QtCore.Qt.AlignmentFlag.AlignCenter, self.unit)

        painter.setPen(QtGui.QColor(theme.TEXT_SECONDARY))
        painter.setFont(theme.overline_font())
        painter.drawText(
            QtCore.QRectF(0, self.height() - 16, self.width(), 16),
            QtCore.Qt.AlignmentFlag.AlignCenter, self.caption.upper())


class Trace(QtWidgets.QWidget):
    """Recent history of one value, with its observed range called out.

    Every vendor monitoring app shows this, and it is the single most useful
    element on such a page: whether a temperature is climbing, and whether it is
    spiky or steady, are invisible in a live number no matter how large it is.
    """

    #: Below this many samples the plot would be a sliver at the right edge,
    #: which reads as a broken chart rather than as one still filling up.
    MIN_SAMPLES = 5

    def __init__(self, caption: str, unit: str, samples: int = 120,
                 height: int = 76):
        super().__init__()
        self.caption = caption
        self.unit = unit
        self.history: deque = deque(maxlen=samples)
        self._custom_color: str | None = None
        self._glow: bool = False
        # Fixed, not minimum: a stretched trace leaves the plot floating in
        # empty space between its caption and its range line.
        self.setFixedHeight(height)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{caption} history")

    def set_accent_color(self, color: str | None = None, glow: bool = False):
        if color != self._custom_color or glow != self._glow:
            self._custom_color = color
            self._glow = glow
            self.update()

    def push(self, value):
        if value is not None:
            self.history.append(float(value))
            self.setAccessibleDescription(
                f"{self.caption}: {value} {self.unit}, "
                f"{len(self.history)} samples")
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)

        plot = QtCore.QRectF(0, 17, self.width(), self.height() - 34)
        painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
        painter.setFont(theme.ui_font(theme.SIZE_SMALL))
        painter.drawText(QtCore.QRectF(0, 0, self.width(), 15),
                         QtCore.Qt.AlignmentFlag.AlignLeft
                         | QtCore.Qt.AlignmentFlag.AlignVCenter, self.caption)

        if len(self.history) < self.MIN_SAMPLES:
            painter.drawText(plot, QtCore.Qt.AlignmentFlag.AlignCenter,
                             "collecting…")
            return

        low, high = min(self.history), max(self.history)
        span = max(high - low, 4.0)
        centre = (high + low) / 2
        floor, ceiling = centre - span / 2, centre + span / 2

        step = plot.width() / (self.history.maxlen - 1)
        points = []
        offset = self.history.maxlen - len(self.history)
        for index, value in enumerate(self.history):
            x = plot.left() + (index + offset) * step
            y = plot.bottom() - (value - floor) / (ceiling - floor) * plot.height()
            points.append(QtCore.QPointF(x, y))

        # Construct smooth Catmull-Rom cubic Bézier spline for soft sinusoidal telemetry pulse
        area = QtGui.QPainterPath(QtCore.QPointF(points[0].x(), plot.bottom()))
        area.lineTo(points[0])
        line = QtGui.QPainterPath(points[0])

        if len(points) == 2:
            area.lineTo(points[1])
            line.lineTo(points[1])
        elif len(points) > 2:
            for i in range(len(points) - 1):
                p0 = points[i - 1] if i > 0 else points[i]
                p1 = points[i]
                p2 = points[i + 1]
                p3 = points[i + 2] if i + 2 < len(points) else p2
                cp1 = QtCore.QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                                     p1.y() + (p2.y() - p0.y()) / 6.0)
                cp2 = QtCore.QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                                     p2.y() - (p3.y() - p1.y()) / 6.0)
                area.cubicTo(cp1, cp2, p2)
                line.cubicTo(cp1, cp2, p2)

        area.lineTo(points[-1].x(), plot.bottom())
        area.closeSubpath()

        accent_hex = self._custom_color or theme.get_dynamic_accent()
        base_color = QtGui.QColor(accent_hex)

        fill = QtGui.QLinearGradient(0, plot.top(), 0, plot.bottom())
        tint = QtGui.QColor(base_color)
        tint.setAlpha(90 if not self._glow else 120)
        fill.setColorAt(0.0, tint)
        tint = QtGui.QColor(tint)
        tint.setAlpha(8 if not self._glow else 20)
        fill.setColorAt(1.0, tint)
        painter.fillPath(area, fill)

        # Optimize paint event: enable antialiasing strictly on the vector line curve
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        if self._glow:
            glow_pen = QtGui.QPen(QtGui.QColor(224, 36, 195, 110), 4.5)
            glow_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(glow_pen)
            painter.drawPath(line)

        pen = QtGui.QPen(base_color, 1.8)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(line)

        # Disable antialiasing for text rendering to avoid costly subpixel passes during 1s updates
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
        painter.setFont(theme.numeric_font(theme.SIZE_SMALL,
                                           theme.WEIGHT_REGULAR))
        painter.drawText(
            QtCore.QRectF(0, self.height() - 16, self.width(), 15),
            QtCore.Qt.AlignmentFlag.AlignRight,
            f"min {low:.0f}   max {high:.0f}   now "
            f"{self.history[-1]:.0f} {self.unit}")


class DualSplineTrace(QtWidgets.QWidget):
    """Dual-Spline Live Graph (QPainterPath cubic bezier) showing CPU vs GPU temperatures simultaneously.

    Renders two smooth Catmull-Rom cubic Bézier splines with semi-transparent alpha gradient fills:
    - CPU: Balanced Cyan (#00B4D8)
    - GPU: High-Performance Crimson (#FF1A35)
    """

    MIN_SAMPLES = 4

    def __init__(self, caption: str = "Thermal Pulse Heartbeat (Dual-Spline)", unit: str = "°C",
                 samples: int = 120, height: int = 86):
        super().__init__()
        self.caption = caption
        self.unit = unit
        self.cpu_history: deque = deque(maxlen=samples)
        self.gpu_history: deque = deque(maxlen=samples)
        self._glow: bool = False
        self._custom_color: str | None = None
        self.setFixedHeight(height)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setAccessibleName("CPU and GPU thermal trace")

    def set_accent_color(self, color: str | None = None, glow: bool = False):
        self._custom_color = color
        self._glow = glow
        self.update()

    def push(self, cpu_val, gpu_val=None):
        if gpu_val is None and isinstance(cpu_val, (tuple, list)):
            if len(cpu_val) >= 2:
                cpu_val, gpu_val = cpu_val[0], cpu_val[1]
            elif len(cpu_val) == 1:
                cpu_val, gpu_val = cpu_val[0], None

        if cpu_val is not None:
            self.cpu_history.append(float(cpu_val))
        elif self.cpu_history:
            self.cpu_history.append(self.cpu_history[-1])

        if gpu_val is not None:
            self.gpu_history.append(float(gpu_val))
        elif self.gpu_history:
            self.gpu_history.append(self.gpu_history[-1])

        self.update()

    @staticmethod
    def _build_spline(points: list[QtCore.QPointF], plot_bottom: float):
        area = QtGui.QPainterPath(QtCore.QPointF(points[0].x(), plot_bottom))
        area.lineTo(points[0])
        line = QtGui.QPainterPath(points[0])

        if len(points) == 2:
            area.lineTo(points[1])
            line.lineTo(points[1])
        elif len(points) > 2:
            for i in range(len(points) - 1):
                p0 = points[i - 1] if i > 0 else points[i]
                p1 = points[i]
                p2 = points[i + 1]
                p3 = points[i + 2] if i + 2 < len(points) else p2
                cp1 = QtCore.QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                                     p1.y() + (p2.y() - p0.y()) / 6.0)
                cp2 = QtCore.QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                                     p2.y() - (p3.y() - p1.y()) / 6.0)
                area.cubicTo(cp1, cp2, p2)
                line.cubicTo(cp1, cp2, p2)

        area.lineTo(points[-1].x(), plot_bottom)
        area.closeSubpath()
        return area, line

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        top_h = 18
        bot_h = 16
        plot = QtCore.QRectF(0, top_h, self.width(), self.height() - top_h - bot_h)

        # Header with Caption & Live Legend
        painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
        painter.setFont(theme.ui_font(theme.SIZE_SMALL))
        painter.drawText(QtCore.QRectF(0, 0, 240, 16),
                         QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                         self.caption)

        cpu_now = f"{self.cpu_history[-1]:.0f} °C" if self.cpu_history else "-- °C"
        gpu_now = f"{self.gpu_history[-1]:.0f} °C" if self.gpu_history else "-- °C"

        painter.setFont(theme.numeric_font(theme.SIZE_SMALL, theme.WEIGHT_BOLD))
        painter.setPen(QtGui.QColor(theme.ACCENT_ICE))
        painter.drawText(QtCore.QRectF(self.width() - 250, 0, 115, 16),
                         QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                         f"● CPU: {cpu_now}")
        painter.setPen(QtGui.QColor(theme.ACCENT_SPOTIFY))
        painter.drawText(QtCore.QRectF(self.width() - 130, 0, 130, 16),
                         QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                         f"● GPU: {gpu_now}")

        if max(len(self.cpu_history), len(self.gpu_history)) < self.MIN_SAMPLES:
            painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
            painter.setFont(theme.ui_font(theme.SIZE_SMALL))
            painter.drawText(plot, QtCore.Qt.AlignmentFlag.AlignCenter, "Collecting thermal telemetry…")
            return

        all_vals = list(self.cpu_history) + list(self.gpu_history)
        if not all_vals:
            return
        low, high = min(all_vals), max(all_vals)
        span = max(high - low, 6.0)
        centre = (high + low) / 2.0
        floor, ceiling = centre - span / 2.0, centre + span / 2.0

        max_len = self.cpu_history.maxlen or 120
        step = plot.width() / (max_len - 1)

        def _calc_points(hist):
            pts = []
            offset = max_len - len(hist)
            for idx, val in enumerate(hist):
                x = plot.left() + (idx + offset) * step
                y = plot.bottom() - (val - floor) / (ceiling - floor) * plot.height()
                pts.append(QtCore.QPointF(x, y))
            return pts

        # Render Splines with Vector Antialiasing
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        # 1. CPU Spline (Ice #00D2FF)
        if len(self.cpu_history) >= 2:
            cpu_pts = _calc_points(self.cpu_history)
            cpu_area, cpu_line = self._build_spline(cpu_pts, plot.bottom())

            cpu_fill = QtGui.QLinearGradient(0, plot.top(), 0, plot.bottom())
            c_tint = QtGui.QColor(theme.ACCENT_ICE)
            c_tint.setAlpha(75 if not self._glow else 110)
            cpu_fill.setColorAt(0.0, c_tint)
            c_tint.setAlpha(6)
            cpu_fill.setColorAt(1.0, c_tint)
            painter.fillPath(cpu_area, cpu_fill)

            cpu_pen = QtGui.QPen(QtGui.QColor(theme.ACCENT_ICE), 2.0)
            cpu_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(cpu_pen)
            painter.drawPath(cpu_line)

        # 2. GPU Spline (Spotify Emerald #1DB954)
        if len(self.gpu_history) >= 2:
            gpu_pts = _calc_points(self.gpu_history)
            gpu_area, gpu_line = self._build_spline(gpu_pts, plot.bottom())

            gpu_fill = QtGui.QLinearGradient(0, plot.top(), 0, plot.bottom())
            g_tint = QtGui.QColor(theme.ACCENT_SPOTIFY)
            g_tint.setAlpha(65 if not self._glow else 100)
            gpu_fill.setColorAt(0.0, g_tint)
            g_tint.setAlpha(6)
            gpu_fill.setColorAt(1.0, g_tint)
            painter.fillPath(gpu_area, gpu_fill)

            gpu_pen = QtGui.QPen(QtGui.QColor(theme.ACCENT_SPOTIFY), 2.0)
            gpu_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(gpu_pen)
            painter.drawPath(gpu_line)

        # Bottom stats
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
        painter.setFont(theme.numeric_font(theme.SIZE_SMALL, theme.WEIGHT_REGULAR))
        painter.drawText(
            QtCore.QRectF(0, self.height() - 15, self.width(), 15),
            QtCore.Qt.AlignmentFlag.AlignRight,
            f"min {low:.0f} °C   max {high:.0f} °C   samples {len(all_vals) // 2}"
        )


class FanRotor(QtWidgets.QWidget):
    """An impeller turning at the speed the tachometer reports.

    Seven blades, and the rotation rate is scaled down from the real one -
    a fan at 1200 rpm is 20 revolutions a second, which past about 3 would
    strobe against the frame rate and read as standing still or running
    backwards. The point is to show that it is spinning and roughly how hard,
    not to be a stroboscope.

    Two things keep it smooth. The angle advances by measured elapsed time
    rather than by the timer's nominal interval, so a late frame does not also
    become a short one. And the speed eases toward the tachometer's figure
    instead of snapping to it: readings arrive once a second and jitter by tens
    of RPM, which applied directly would make the rotor visibly stutter every
    poll.
    """

    BLADES = 7
    #: Revolutions per second on screen at the top of the range.
    MAX_VISUAL_RPS = 1.6
    #: Seconds to cover most of the gap to a new reading.
    EASE_SECONDS = 0.6

    def __init__(self, diameter: int = 96, full_scale_rpm: int = 4500):
        super().__init__()
        self.full_scale = full_scale_rpm
        self._target_rpm = 0.0
        self._rpm = 0.0
        self._angle = 0.0
        self.setFixedSize(diameter, diameter)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_rpm(self, rpm):
        self._target_rpm = float(rpm or 0)

    def advance(self, seconds: float):
        """Called by the shared frame timer. True if anything is still moving."""
        # Exponential approach: fast enough to track a real change within about
        # a second, slow enough that sample-to-sample jitter does not show.
        if self._rpm != self._target_rpm:
            blend = min(1.0, seconds / self.EASE_SECONDS)
            self._rpm += (self._target_rpm - self._rpm) * blend
            if abs(self._target_rpm - self._rpm) < 0.5:
                self._rpm = self._target_rpm

        if self._rpm <= 0:
            return False
        fraction = min(1.0, self._rpm / self.full_scale)
        self._angle = (self._angle
                       + fraction * self.MAX_VISUAL_RPS * 360 * seconds) % 360
        self.update()
        return True

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        radius = side / 2

        painter.translate(self.width() / 2, self.height() / 2)

        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER_QUIET), 1))
        painter.setBrush(QtGui.QColor(theme.SURFACE_SUNKEN))
        painter.drawEllipse(QtCore.QPointF(0, 0), radius - 1, radius - 1)

        painter.rotate(self._angle)
        hub = radius * 0.26
        blade = QtGui.QColor(theme.BORDER_CONTROL if self._rpm
                             else theme.BORDER_QUIET)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(blade)

        for index in range(self.BLADES):
            path = QtGui.QPainterPath()
            path.moveTo(hub * 0.9, 0)
            # Two arcs of differing curvature give the blade a swept edge
            # without needing a bitmap.
            path.quadTo(radius * 0.72, -radius * 0.30,
                        radius * 0.90, -radius * 0.06)
            path.quadTo(radius * 0.70, radius * 0.16, hub * 0.9, hub * 0.62)
            path.closeSubpath()
            painter.save()
            painter.rotate(index * 360 / self.BLADES)
            painter.drawPath(path)
            painter.restore()

        painter.setBrush(QtGui.QColor(theme.SURFACE_RAISED))
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER_CONTROL), 1))
        painter.drawEllipse(QtCore.QPointF(0, 0), hub, hub)


class RotorDriver(QtCore.QObject):
    """The single frame timer shared by every rotor on screen.

    Stops itself when nothing is turning, and never starts at all when the
    desktop has animation switched off - a still rotor beside a live RPM
    number is a perfectly good instrument, and a spinning one the user asked
    not to see is not.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rotors: list[FanRotor] = []
        self.enabled = animation_factor() > 0
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._clock = QtCore.QElapsedTimer()

    def add(self, rotor: FanRotor):
        self.rotors.append(rotor)

    def sync(self):
        """Start or stop the timer to match whether anything is turning."""
        if not self.enabled:
            return
        # Do not spin the 16ms timer if rotors are not visible (e.g. minimized to tray)
        if not any(rotor.isVisible() for rotor in self.rotors):
            if self._timer.isActive():
                self._timer.stop()
            return
        # Also keep running while a rotor is still easing down to zero, or it
        # would freeze mid-slowdown and jump to a stop.
        moving = any(rotor._rpm or rotor._target_rpm for rotor in self.rotors)
        if moving and not self._timer.isActive():
            self._clock.restart()
            self._timer.start()
        elif not moving and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        # Measured, not nominal: a frame delayed by a repaint elsewhere would
        # otherwise advance the angle as though it had been on time, which is
        # exactly what reads as stutter.
        elapsed = self._clock.restart() / 1000.0
        if elapsed <= 0 or elapsed > 0.25:
            elapsed = FRAME_MS / 1000.0
        for rotor in self.rotors:
            if rotor.isVisible():
                rotor.advance(elapsed)
