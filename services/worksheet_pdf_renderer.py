"""
Converts a WORKSHEET_SCHEMA JSON dict into a print-ready A4 PDF.

Usage:
    from services.worksheet_pdf_renderer import render_worksheet_pdf
    render_worksheet_pdf(worksheet_dict, "output/my_worksheet.pdf")

Section types supported: mcq, fill_blank, true_false, short_answer, match.
Includes a detachable answer-key page at the end.
"""

import math
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, PageBreak, KeepTogether,
    Image as RLImage,
)
from reportlab.platypus.flowables import Flowable


# ── Custom flowables ──────────────────────────────────────────────────────────

class BubbleOption(Flowable):
    """A small circle + label on one line, used for MCQ options."""
    HEIGHT = 0.45 * cm

    def __init__(self, label: str, text: str, width: float):
        Flowable.__init__(self)
        self.label = label
        self.text = text
        self.width = width
        self.height = self.HEIGHT

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.circle(0.25 * cm, self.HEIGHT / 2, 0.20 * cm, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(0.25 * cm, self.HEIGHT / 2 - 3, self.label)
        c.setFont("Helvetica", 10)
        c.drawString(0.6 * cm, self.HEIGHT / 2 - 3.5, self.text)


class CheckBox(Flowable):
    """A labelled checkbox for True/False questions."""
    HEIGHT = 0.5 * cm

    def __init__(self, label: str, width: float):
        Flowable.__init__(self)
        self.label = label
        self.width = width
        self.height = self.HEIGHT

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.rect(0, self.HEIGHT / 4, 0.4 * cm, 0.4 * cm, stroke=1, fill=0)
        c.setFont("Helvetica", 10)
        c.drawString(0.55 * cm, self.HEIGHT / 4 + 2, self.label)


class RuledLines(Flowable):
    """Horizontal ruled lines for short-answer responses."""

    def __init__(self, num_lines: int = 3, width: float = 15 * cm):
        Flowable.__init__(self)
        self.num_lines = num_lines
        self.line_spacing = 0.7 * cm
        self.width = width
        self.height = num_lines * self.line_spacing + 0.2 * cm

    def draw(self):
        c = self.canv
        c.setLineWidth(0.4)
        c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
        for i in range(self.num_lines):
            y = self.height - (i + 1) * self.line_spacing
            c.line(0, y, self.width, y)


class WorksheetDiagram(Flowable):
    """
    Renders real educational vector diagrams inline with worksheet questions.

    Diagram types (set via the 'type' key in the spec dict):
        shapes_2d        — labeled 2-D shapes: circle, square, triangle, rectangle,
                           pentagon, hexagon, diamond, star
        shapes_3d        — isometric 3-D shapes: cube, sphere, cylinder, cone
        spatial_position — two labeled objects in a positional relationship
                           (above, below, inside, next to, left of, in front, behind)
        object_row       — a left-to-right row of labeled boxes for ordering/position
                           questions; pass highlight="<label>" to outline one in red
        number_line      — a graduated number line with optional red marker dots
        direction_turn   — a path-and-arc diagram for turning/direction questions
    """

    _TYPE_HEIGHT = {
        "shapes_2d": 4.2,
        "shapes_3d": 4.4,
        "spatial_position": 4.8,
        "object_row": 3.4,
        "number_line": 2.6,
        "direction_turn": 4.4,
    }

    _PALETTE = [
        colors.HexColor("#4a90d9"),  # blue
        colors.HexColor("#e67e22"),  # orange
        colors.HexColor("#27ae60"),  # green
        colors.HexColor("#e74c3c"),  # red
        colors.HexColor("#9b59b6"),  # purple
        colors.HexColor("#16a085"),  # teal
    ]

    def __init__(self, spec: dict, avail_width: float):
        Flowable.__init__(self)
        self._spec = spec
        self._dtype = spec.get("type", "")
        self.width = min(avail_width * 0.72, 11.5 * cm)
        self.height = self._TYPE_HEIGHT.get(self._dtype, 4.0) * cm

    # ── entry point ───────────────────────────────────────────────────────────

    def draw(self):
        c = self.canv
        # Subtle card background
        c.setFillColor(colors.HexColor("#f6f9ff"))
        c.setStrokeColor(colors.HexColor("#b8cfe8"))
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height, radius=5, stroke=1, fill=1)

        fn = {
            "shapes_2d": self._shapes_2d,
            "shapes_3d": self._shapes_3d,
            "spatial_position": self._spatial_position,
            "object_row": self._object_row,
            "number_line": self._number_line,
            "direction_turn": self._direction_turn,
        }.get(self._dtype)

        if fn:
            fn(c)
        else:
            c.setFont("Helvetica-Oblique", 9)
            c.setFillColor(colors.HexColor("#aaaaaa"))
            c.drawCentredString(self.width / 2, self.height / 2 - 4, "[ Figure ]")

    # ── 2-D shapes ────────────────────────────────────────────────────────────

    def _shapes_2d(self, c):
        shapes = self._spec.get("shapes", [])
        labels = self._spec.get("labels", shapes)
        n = len(shapes)
        if not n:
            return
        margin = 0.5 * cm
        cell_w = (self.width - 2 * margin) / n
        shape_size = min(cell_w * 0.62, 1.55 * cm)
        cy = self.height * 0.6
        label_y = 0.32 * cm
        for i, (shp, lbl) in enumerate(zip(shapes, labels)):
            cx = margin + cell_w * (i + 0.5)
            self._draw_2d(c, shp.lower(), cx, cy, shape_size,
                          self._PALETTE[i % len(self._PALETTE)])
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(colors.HexColor("#222222"))
            c.drawCentredString(cx, label_y, lbl)

    @staticmethod
    def _draw_2d(c, name, cx, cy, size, fill_color):
        half = size / 2
        c.setFillColor(fill_color)
        c.setStrokeColor(colors.HexColor("#2c3e50"))
        c.setLineWidth(1.5)
        if name == "circle":
            c.circle(cx, cy, half, stroke=1, fill=1)
        elif name == "square":
            c.rect(cx - half, cy - half, size, size, stroke=1, fill=1)
        elif name == "rectangle":
            rw, rh = size * 1.55, size * 0.65
            c.rect(cx - rw / 2, cy - rh / 2, rw, rh, stroke=1, fill=1)
        elif name in ("triangle", "equilateral triangle"):
            p = c.beginPath()
            p.moveTo(cx, cy + half)
            p.lineTo(cx - half, cy - half)
            p.lineTo(cx + half, cy - half)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
        elif name == "pentagon":
            pts = [
                (cx + half * math.cos(math.pi / 2 + 2 * math.pi * i / 5),
                 cy + half * math.sin(math.pi / 2 + 2 * math.pi * i / 5))
                for i in range(5)
            ]
            p = c.beginPath()
            p.moveTo(*pts[0])
            for pt in pts[1:]:
                p.lineTo(*pt)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
        elif name == "hexagon":
            pts = [
                (cx + half * math.cos(2 * math.pi * i / 6),
                 cy + half * math.sin(2 * math.pi * i / 6))
                for i in range(6)
            ]
            p = c.beginPath()
            p.moveTo(*pts[0])
            for pt in pts[1:]:
                p.lineTo(*pt)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
        elif name in ("diamond", "rhombus"):
            p = c.beginPath()
            p.moveTo(cx, cy + half)
            p.lineTo(cx + half, cy)
            p.lineTo(cx, cy - half)
            p.lineTo(cx - half, cy)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
        elif name == "star":
            outer, inner = half, half * 0.42
            pts = []
            for i in range(10):
                r = outer if i % 2 == 0 else inner
                a = math.pi / 2 + math.pi * i / 5
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            p = c.beginPath()
            p.moveTo(*pts[0])
            for pt in pts[1:]:
                p.lineTo(*pt)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
        else:
            c.circle(cx, cy, half, stroke=1, fill=1)

    # ── 3-D shapes ────────────────────────────────────────────────────────────

    def _shapes_3d(self, c):
        shapes = self._spec.get("shapes", [])
        labels = self._spec.get("labels", shapes)
        n = len(shapes)
        if not n:
            return
        margin = 0.5 * cm
        cell_w = (self.width - 2 * margin) / n
        size = min(cell_w * 0.60, 1.4 * cm)
        cy = self.height * 0.60
        label_y = 0.32 * cm
        for i, (shp, lbl) in enumerate(zip(shapes, labels)):
            cx = margin + cell_w * (i + 0.5)
            self._draw_3d(c, shp.lower(), cx, cy, size,
                          self._PALETTE[i % len(self._PALETTE)])
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(colors.HexColor("#222222"))
            c.drawCentredString(cx, label_y, lbl)

    @staticmethod
    def _draw_3d(c, name, cx, cy, size, base_color):
        h = size
        off_x, off_y = h * 0.36, h * 0.21
        c.setLineWidth(1.2)
        c.setStrokeColor(colors.HexColor("#2c3e50"))

        def _lighter(col, d=0.16):
            return colors.Color(min(col.red + d, 1), min(col.green + d, 1), min(col.blue + d, 1))

        def _darker(col, d=0.18):
            return colors.Color(max(col.red - d, 0), max(col.green - d, 0), max(col.blue - d, 0))

        if name == "cube":
            # Front face
            c.setFillColor(base_color)
            c.rect(cx - h / 2, cy - h / 2, h, h, stroke=1, fill=1)
            # Top face
            c.setFillColor(_lighter(base_color))
            p = c.beginPath()
            p.moveTo(cx - h / 2, cy + h / 2)
            p.lineTo(cx - h / 2 + off_x, cy + h / 2 + off_y)
            p.lineTo(cx + h / 2 + off_x, cy + h / 2 + off_y)
            p.lineTo(cx + h / 2, cy + h / 2)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
            # Right face
            c.setFillColor(_darker(base_color))
            p = c.beginPath()
            p.moveTo(cx + h / 2, cy - h / 2)
            p.lineTo(cx + h / 2 + off_x, cy - h / 2 + off_y)
            p.lineTo(cx + h / 2 + off_x, cy + h / 2 + off_y)
            p.lineTo(cx + h / 2, cy + h / 2)
            p.close()
            c.drawPath(p, stroke=1, fill=1)

        elif name == "sphere":
            c.setFillColor(base_color)
            c.circle(cx, cy, h / 2, stroke=1, fill=1)
            # Specular highlight
            c.setFillColor(colors.Color(1, 1, 1, 0.45))
            c.setStrokeColor(colors.Color(0, 0, 0, 0))
            c.circle(cx - h * 0.14, cy + h * 0.16, h * 0.11, stroke=0, fill=1)
            # Equator ellipse
            c.setStrokeColor(colors.Color(0, 0, 0, 0.22))
            c.setLineWidth(0.7)
            c.ellipse(cx - h / 2, cy - h * 0.09, cx + h / 2, cy + h * 0.09, stroke=1, fill=0)
            c.setStrokeColor(colors.HexColor("#2c3e50"))
            c.setLineWidth(1.2)
            c.circle(cx, cy, h / 2, stroke=1, fill=0)

        elif name == "cylinder":
            bw, bh, ey = h * 0.72, h * 1.1, h * 0.20
            # Body fill
            c.setFillColor(base_color)
            c.rect(cx - bw / 2, cy - bh / 2, bw, bh, stroke=0, fill=1)
            # Bottom ellipse
            c.setFillColor(_darker(base_color))
            c.ellipse(cx - bw / 2, cy - bh / 2 - ey,
                      cx + bw / 2, cy - bh / 2 + ey, stroke=1, fill=1)
            # Top ellipse
            c.setFillColor(_lighter(base_color))
            c.ellipse(cx - bw / 2, cy + bh / 2 - ey,
                      cx + bw / 2, cy + bh / 2 + ey, stroke=1, fill=1)
            # Body outline
            c.setFillColor(colors.Color(0, 0, 0, 0))
            c.rect(cx - bw / 2, cy - bh / 2, bw, bh, stroke=1, fill=0)

        elif name == "cone":
            bw, bh, ey = h * 0.76, h * 1.15, h * 0.18
            c.setFillColor(base_color)
            p = c.beginPath()
            p.moveTo(cx, cy + bh / 2)
            p.lineTo(cx - bw / 2, cy - bh / 2)
            p.lineTo(cx + bw / 2, cy - bh / 2)
            p.close()
            c.drawPath(p, stroke=1, fill=1)
            c.setFillColor(_darker(base_color))
            c.ellipse(cx - bw / 2, cy - bh / 2 - ey,
                      cx + bw / 2, cy - bh / 2 + ey, stroke=1, fill=1)

        else:
            c.setFillColor(base_color)
            c.circle(cx, cy, h / 2, stroke=1, fill=1)

    # ── spatial position ──────────────────────────────────────────────────────

    def _spatial_position(self, c):
        subject = self._spec.get("subject", "Object")
        reference = self._spec.get("reference", "Container")
        pos = self._spec.get("position", "above").lower().replace("_", " ")

        cx = self.width / 2
        cy = self.height / 2
        bw, bh = 1.75 * cm, 1.05 * cm
        gap = 0.42 * cm
        sub_col, ref_col = self._PALETTE[0], self._PALETTE[1]

        if pos in ("inside", "in", "within", "into", "in the"):
            # Reference drawn bigger, subject centered inside
            self._obj_box(c, reference, cx, cy, bw * 1.72, bh * 1.9, ref_col)
            self._obj_box(c, subject, cx, cy, bw * 0.72, bh * 0.72, sub_col)
        elif pos in ("above", "on top", "on top of", "on"):
            self._obj_box(c, reference, cx, cy - bh / 2 - gap / 2, bw, bh, ref_col)
            self._obj_box(c, subject, cx, cy + bh / 2 + gap / 2, bw * 0.78, bh * 0.78, sub_col)
        elif pos in ("below", "under", "underneath", "beneath"):
            self._obj_box(c, reference, cx, cy + bh / 2 + gap / 2, bw, bh, ref_col)
            self._obj_box(c, subject, cx, cy - bh / 2 - gap / 2, bw * 0.78, bh * 0.78, sub_col)
        elif pos in ("next to", "beside", "right of", "to the right of", "right"):
            self._obj_box(c, reference, cx - bw / 2 - gap / 2, cy, bw, bh, ref_col)
            self._obj_box(c, subject, cx + bw / 2 + gap / 2, cy, bw * 0.78, bh * 0.78, sub_col)
        elif pos in ("left of", "to the left of", "left"):
            self._obj_box(c, reference, cx + bw / 2 + gap / 2, cy, bw, bh, ref_col)
            self._obj_box(c, subject, cx - bw / 2 - gap / 2, cy, bw * 0.78, bh * 0.78, sub_col)
        elif pos in ("in front", "in front of"):
            self._obj_box(c, reference, cx, cy + bh * 0.55, bw, bh, ref_col)
            self._obj_box(c, subject, cx, cy - bh * 0.58, bw * 0.88, bh * 0.88, sub_col)
        elif pos in ("behind", "in back of", "in back", "behind the"):
            self._obj_box(c, reference, cx, cy - bh * 0.3, bw, bh, ref_col)
            self._obj_box(c, subject, cx, cy + bh * 0.78, bw * 0.78, bh * 0.78, sub_col)
        else:
            self._obj_box(c, reference, cx, cy, bw, bh, ref_col)
            self._obj_box(c, subject, cx, cy + bh + gap, bw * 0.78, bh * 0.78, sub_col)

        # Position word watermark on the right
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(colors.HexColor("#aaaaaa"))
        c.drawCentredString(self.width * 0.87, self.height / 2, pos.upper())

    @staticmethod
    def _obj_box(c, label, cx, cy, w, h, color):
        c.setFillColor(color)
        c.setStrokeColor(colors.HexColor("#2c3e50"))
        c.setLineWidth(1.1)
        c.roundRect(cx - w / 2, cy - h / 2, w, h, 5, stroke=1, fill=1)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.white)
        c.drawCentredString(cx, cy - 4, label.capitalize())

    # ── object row ────────────────────────────────────────────────────────────

    def _object_row(self, c):
        objects = self._spec.get("objects", [])
        labels = self._spec.get("labels", objects)
        highlight = (self._spec.get("highlight") or "").lower()
        n = max(len(objects), 1)
        margin = 0.5 * cm
        cell_w = (self.width - 2 * margin) / n
        cy = self.height * 0.58
        bw = min(cell_w * 0.78, 1.95 * cm)
        bh = min(self.height * 0.44, 1.65 * cm)

        # LEFT / RIGHT direction bar
        bar_y = 0.28 * cm
        c.setStrokeColor(colors.HexColor("#cccccc"))
        c.setLineWidth(0.8)
        c.line(margin, bar_y, self.width - margin, bar_y)
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(colors.HexColor("#aaaaaa"))
        c.drawString(margin, bar_y + 0.07 * cm, "← LEFT")
        c.drawRightString(self.width - margin, bar_y + 0.07 * cm, "RIGHT →")

        for i, (obj, lbl) in enumerate(zip(objects, labels)):
            cx = margin + cell_w * (i + 0.5)
            is_hl = obj.lower() == highlight or lbl.lower() == highlight
            stroke_col = colors.HexColor("#c0392b") if is_hl else colors.HexColor("#2c3e50")
            lw = 2.2 if is_hl else 1.0
            fill_col = self._PALETTE[i % len(self._PALETTE)]
            c.setFillColor(fill_col)
            c.setStrokeColor(stroke_col)
            c.setLineWidth(lw)
            c.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, 6, stroke=1, fill=1)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.white)
            c.drawCentredString(cx, cy - 4, lbl.capitalize())

    # ── number line ───────────────────────────────────────────────────────────

    def _number_line(self, c):
        start = int(self._spec.get("start", 0))
        end = int(self._spec.get("end", 10))
        marks = [int(m) for m in (self._spec.get("marks") or [])]
        label = self._spec.get("label", "")
        margin = 0.9 * cm
        line_y = self.height * 0.56
        line_w = self.width - 2 * margin
        tick_h = 0.18 * cm
        span = max(end - start, 1)
        scale = line_w / span

        # Main axis + arrowhead
        c.setStrokeColor(colors.HexColor("#333333"))
        c.setLineWidth(1.5)
        c.line(margin, line_y, margin + line_w, line_y)
        ah = margin + line_w
        c.line(ah, line_y, ah - 0.18 * cm, line_y + 0.10 * cm)
        c.line(ah, line_y, ah - 0.18 * cm, line_y - 0.10 * cm)

        # Ticks + numbers
        c.setLineWidth(0.9)
        for n in range(start, end + 1):
            x = margin + (n - start) * scale
            c.setStrokeColor(colors.HexColor("#555555"))
            c.line(x, line_y - tick_h, x, line_y + tick_h)
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#333333"))
            c.drawCentredString(x, line_y - tick_h - 0.27 * cm, str(n))

        # Red marker dots
        for m in marks:
            if start <= m <= end:
                x = margin + (m - start) * scale
                c.setFillColor(colors.HexColor("#e74c3c"))
                c.setStrokeColor(colors.HexColor("#e74c3c"))
                c.circle(x, line_y, 0.17 * cm, stroke=0, fill=1)
                c.setFont("Helvetica-Bold", 8)
                c.setFillColor(colors.HexColor("#c0392b"))
                c.drawCentredString(x, line_y + 0.30 * cm, str(m))

        if label:
            c.setFont("Helvetica-Oblique", 8)
            c.setFillColor(colors.HexColor("#666666"))
            c.drawCentredString(self.width / 2, line_y + 0.58 * cm, label)

    # ── direction / turn ─────────────────────────────────────────────────────

    def _direction_turn(self, c):
        direction = self._spec.get("direction", "right").lower()
        steps = int(self._spec.get("steps", 2))

        pad = 0.45 * cm
        person_x = pad + 0.4 * cm
        arr_y = self.height / 2
        head_r = 0.22 * cm

        # ── Person icon ──
        c.setFillColor(colors.HexColor("#2980b9"))
        c.setStrokeColor(colors.HexColor("#1a5276"))
        c.setLineWidth(1.2)
        c.circle(person_x, arr_y + head_r * 2.0, head_r, stroke=1, fill=1)  # head
        c.line(person_x, arr_y + head_r * 0.9, person_x, arr_y - head_r * 1.5)  # body
        c.line(person_x, arr_y - head_r * 0.4,
               person_x - head_r, arr_y - head_r * 1.5)  # left leg
        c.line(person_x, arr_y - head_r * 0.4,
               person_x + head_r, arr_y - head_r * 1.5)  # right leg
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(colors.HexColor("#1a5276"))
        c.drawCentredString(person_x, arr_y - head_r * 2.4, "YOU")

        # ── Forward arrow ──
        fwd_start = person_x + 0.38 * cm
        fwd_end = self.width * 0.50
        ah_sz = 0.18 * cm
        c.setStrokeColor(colors.HexColor("#27ae60"))
        c.setLineWidth(2.0)
        c.line(fwd_start, arr_y, fwd_end, arr_y)
        # Arrowhead
        c.line(fwd_end, arr_y, fwd_end - ah_sz, arr_y + ah_sz * 0.55)
        c.line(fwd_end, arr_y, fwd_end - ah_sz, arr_y - ah_sz * 0.55)
        mid_fwd = (fwd_start + fwd_end) / 2
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#1e8449"))
        c.drawCentredString(mid_fwd, arr_y + 0.24 * cm, f"{steps} steps forward")

        # ── Turn arc ──
        arc_r = 0.50 * cm
        turn_cx = fwd_end + arc_r
        turn_cy = arr_y
        c.setStrokeColor(colors.HexColor("#e74c3c"))
        c.setLineWidth(2.0)

        if direction == "right":
            # Arc from 90° (top) sweeping clockwise (-90°) to 0° (right of center)
            # Visually: the path bends downward = turning right
            c.arc(turn_cx - arc_r, turn_cy - arc_r * 1.4,
                  turn_cx + arc_r, turn_cy + arc_r * 0.6,
                  startAng=90, extent=-90)
            # Arrowhead pointing downward at the end of arc
            tip_x, tip_y = turn_cx + arc_r, turn_cy - arc_r * 0.4
            c.line(tip_x, tip_y, tip_x - ah_sz, tip_y + ah_sz * 0.7)
            c.line(tip_x, tip_y, tip_x - ah_sz * 0.4, tip_y + ah_sz * 1.0)
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(colors.HexColor("#c0392b"))
            label_x = turn_cx + arc_r + 0.55 * cm
            c.drawString(label_x, turn_cy + 0.08 * cm, "TURN")
            c.drawString(label_x, turn_cy - 0.22 * cm, "RIGHT →")
        else:
            # Arc from 90° (top) sweeping counter-clockwise (+90°) to 180° (left)
            c.arc(turn_cx - arc_r * 2, turn_cy - arc_r * 0.6,
                  turn_cx, turn_cy + arc_r * 1.4,
                  startAng=0, extent=90)
            tip_x, tip_y = turn_cx - arc_r * 2, turn_cy + arc_r * 0.4
            c.line(tip_x, tip_y, tip_x + ah_sz, tip_y - ah_sz * 0.7)
            c.line(tip_x, tip_y, tip_x + ah_sz * 0.4, tip_y - ah_sz * 1.0)
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(colors.HexColor("#c0392b"))
            label_x = turn_cx - arc_r * 2 - 1.2 * cm
            c.drawString(label_x, turn_cy + 0.08 * cm, "← TURN")
            c.drawString(label_x, turn_cy - 0.22 * cm, "   LEFT")

        # ── Mini compass ──
        comp_x = self.width - 0.75 * cm
        comp_y = self.height - 0.85 * cm
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(colors.HexColor("#777777"))
        c.drawCentredString(comp_x, comp_y + 0.32 * cm, "N")
        c.drawCentredString(comp_x, comp_y - 0.48 * cm, "S")
        c.drawRightString(comp_x - 0.18 * cm, comp_y - 0.06 * cm, "W")
        c.drawString(comp_x + 0.18 * cm, comp_y - 0.06 * cm, "E")
        c.setStrokeColor(colors.HexColor("#bbbbbb"))
        c.setLineWidth(0.6)
        c.line(comp_x, comp_y - 0.38 * cm, comp_x, comp_y + 0.22 * cm)
        c.line(comp_x - 0.32 * cm, comp_y - 0.08 * cm, comp_x + 0.32 * cm, comp_y - 0.08 * cm)


# ── Style helpers ─────────────────────────────────────────────────────────────

def _build_styles():
    base = getSampleStyleSheet()
    custom = {
        "worksheet_title": ParagraphStyle(
            "worksheet_title", parent=base["Title"],
            fontSize=16, leading=20, spaceAfter=4,
            textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER,
        ),
        "meta_line": ParagraphStyle(
            "meta_line", parent=base["Normal"],
            fontSize=9, textColor=colors.HexColor("#555555"),
            alignment=TA_CENTER, spaceAfter=2,
        ),
        "instructions_box": ParagraphStyle(
            "instructions_box", parent=base["Normal"],
            fontSize=9.5, leading=14, leftIndent=8, rightIndent=8,
            spaceBefore=4, spaceAfter=8, textColor=colors.HexColor("#333333"),
        ),
        "section_header": ParagraphStyle(
            "section_header", parent=base["Heading2"],
            fontSize=11, leading=15, spaceBefore=14, spaceAfter=4,
            textColor=colors.HexColor("#0d3b66"), fontName="Helvetica-Bold",
        ),
        "section_instructions": ParagraphStyle(
            "section_instructions", parent=base["Normal"],
            fontSize=9, leading=13, spaceAfter=6,
            fontName="Helvetica-Oblique", textColor=colors.HexColor("#555555"),
        ),
        "question": ParagraphStyle(
            "question", parent=base["Normal"],
            fontSize=10.5, leading=15, spaceBefore=6, spaceAfter=3,
            fontName="Helvetica",
        ),
        "hint": ParagraphStyle(
            "hint", parent=base["Normal"],
            fontSize=9, leading=13, leftIndent=12, spaceAfter=4,
            fontName="Helvetica-Oblique", textColor=colors.HexColor("#888888"),
        ),
        "answer_key_title": ParagraphStyle(
            "answer_key_title", parent=base["Heading1"],
            fontSize=13, spaceBefore=0, spaceAfter=10,
            textColor=colors.HexColor("#1a1a2e"),
            alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "answer_item": ParagraphStyle(
            "answer_item", parent=base["Normal"],
            fontSize=9.5, leading=14, spaceBefore=3,
        ),
        "marks_badge": ParagraphStyle(
            "marks_badge", parent=base["Normal"],
            fontSize=9, alignment=TA_RIGHT, textColor=colors.HexColor("#777777"),
        ),
    }
    return base, custom


# ── Section renderers ─────────────────────────────────────────────────────────

def _add_hint(q: dict, styles: dict, story: list):
    hint = q.get("hint")
    if hint:
        story.append(Paragraph(f"Hint: {hint}", styles["hint"]))


def _add_diagram(q: dict, page_w: float, story: list):
    """
    Insert an actual diagram when q['diagram'] is a valid spec dict,
    or nothing when the field is absent / null.
    """
    spec = q.get("diagram")
    if not isinstance(spec, dict) or not spec.get("type"):
        return
    story.append(Spacer(1, 0.18 * cm))
    story.append(WorksheetDiagram(spec=spec, avail_width=page_w))
    story.append(Spacer(1, 0.12 * cm))


class _ImagePlaceholder(Flowable):
    """
    Dashed box shown when an image_prompt exists but generation failed/skipped.
    Gives the teacher a clear space to draw or paste in a picture.
    """
    def __init__(self, label: str, width: float, height: float):
        super().__init__()
        self.label  = label
        self.width  = width
        self.height = height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setDash(4, 3)
        c.setStrokeColor(colors.HexColor("#b0b8c4"))
        c.setFillColor(colors.HexColor("#f8f9fb"))
        c.roundRect(0, 0, self.width, self.height, 6, fill=1, stroke=1)
        c.setDash()
        c.setFillColor(colors.HexColor("#9aa5b4"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(self.width / 2, self.height / 2 + 6, "[ Picture ]")
        # Truncate long prompt labels
        label = self.label if len(self.label) <= 55 else self.label[:52] + "…"
        c.setFont("Helvetica-Oblique", 7)
        c.drawCentredString(self.width / 2, self.height / 2 - 6, label)
        c.restoreState()


def _add_image(q: dict, page_w: float, story: list):
    """
    Embed an AI-generated image when q['image_path'] points to a readable file.
    If generation was requested (image_prompt present) but failed, render a
    dashed placeholder box so the layout still shows where the image belongs.
    """
    path   = q.get("image_path")
    prompt = q.get("image_prompt", "")
    img_w  = page_w * 0.55
    img_h  = img_w  * 0.65

    story.append(Spacer(1, 0.18 * cm))

    if path and os.path.isfile(path):
        try:
            img = RLImage(path, width=img_w, height=img_h)
            img.hAlign = "CENTER"
            story.append(img)
        except Exception as e:
            print(f"[PDF] Could not embed image '{path}': {e}")
            if prompt:
                story.append(_ImagePlaceholder(prompt, img_w, img_h))
    elif prompt:
        # Image was requested but generation was unavailable — show placeholder
        story.append(_ImagePlaceholder(prompt, img_w, img_h))
    else:
        story.pop()   # remove the Spacer we already added — nothing to show
        return

    story.append(Spacer(1, 0.12 * cm))


def _render_mcq(section: dict, styles: dict, page_w: float, story: list):
    for q in section.get("questions", []):
        num = q.get("number", "?")
        qtext = q.get("question", "")
        mpq = section.get("marks_per_question", 1)
        row = [
            Paragraph(f"<b>{num}.</b> {qtext}", styles["question"]),
            Paragraph(f"[{mpq} mark{'s' if mpq > 1 else ''}]", styles["marks_badge"]),
        ]
        t = Table([row], colWidths=[page_w - 3.5 * cm, 2.5 * cm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(KeepTogether([t]))
        _add_image(q, page_w, story)
        _add_diagram(q, page_w, story)
        labels = ["A", "B", "C", "D"]
        for i, opt in enumerate(q.get("options", [])[:4]):
            story.append(BubbleOption(labels[i], opt, page_w))
        _add_hint(q, styles, story)
        story.append(Spacer(1, 0.3 * cm))


def _render_fill_blank(section: dict, styles: dict, page_w: float, story: list):
    for q in section.get("questions", []):
        num = q.get("number", "?")
        qtext = q.get("question", "").replace("___", "________________")
        mpq = section.get("marks_per_question", 1)
        row = [
            Paragraph(f"<b>{num}.</b> {qtext}", styles["question"]),
            Paragraph(f"[{mpq} mark{'s' if mpq > 1 else ''}]", styles["marks_badge"]),
        ]
        t = Table([row], colWidths=[page_w - 3.5 * cm, 2.5 * cm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
        _add_image(q, page_w, story)
        _add_diagram(q, page_w, story)
        _add_hint(q, styles, story)
        story.append(Spacer(1, 0.25 * cm))


def _render_true_false(section: dict, styles: dict, page_w: float, story: list):
    for q in section.get("questions", []):
        num = q.get("number", "?")
        qtext = q.get("question", "")
        mpq = section.get("marks_per_question", 1)
        row = [
            Paragraph(f"<b>{num}.</b> {qtext}", styles["question"]),
            Paragraph(f"[{mpq} mark{'s' if mpq > 1 else ''}]", styles["marks_badge"]),
        ]
        t = Table([row], colWidths=[page_w - 3.5 * cm, 2.5 * cm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
        _add_image(q, page_w, story)
        _add_diagram(q, page_w, story)
        t2 = Table(
            [[CheckBox("True", page_w / 2), CheckBox("False", page_w / 2)]],
            colWidths=[page_w / 2, page_w / 2],
        )
        story.append(t2)
        _add_hint(q, styles, story)
        story.append(Spacer(1, 0.2 * cm))


def _render_short_answer(section: dict, styles: dict, page_w: float, story: list):
    for q in section.get("questions", []):
        num = q.get("number", "?")
        qtext = q.get("question", "")
        mpq = section.get("marks_per_question", 1)
        partial = q.get("partial_marks") or mpq
        num_lines = max(2, min(6, int(partial) + 1))
        row = [
            Paragraph(f"<b>{num}.</b> {qtext}", styles["question"]),
            Paragraph(f"[{mpq} mark{'s' if mpq > 1 else ''}]", styles["marks_badge"]),
        ]
        t = Table([row], colWidths=[page_w - 3.5 * cm, 2.5 * cm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
        _add_image(q, page_w, story)
        _add_diagram(q, page_w, story)
        _add_hint(q, styles, story)
        story.append(RuledLines(num_lines=num_lines, width=page_w - 0.5 * cm))
        story.append(Spacer(1, 0.3 * cm))


def _render_match(section: dict, styles: dict, page_w: float, story: list):
    for q in section.get("questions", []):
        num = q.get("number", "?")
        qtext = q.get("question", "Match the following:")
        mpq = section.get("marks_per_question", 1)
        story.append(Paragraph(f"<b>{num}.</b> {qtext}", styles["question"]))
        left_items = q.get("left", [])
        right_items = q.get("right", [])
        labels = ["A", "B", "C", "D", "E"]
        col_w = (page_w - 1 * cm) / 2
        table_data = [[
            Paragraph("<b>Column I</b>", styles["question"]),
            Paragraph("<b>Column II</b>", styles["question"]),
        ]]
        for i, (l, r) in enumerate(zip(left_items, right_items)):
            lbl = labels[i] if i < len(labels) else str(i + 1)
            table_data.append([
                Paragraph(f"{i + 1}. {l}", styles["question"]),
                Paragraph(f"{lbl}. {r}", styles["question"]),
            ])
        t = Table(table_data, colWidths=[col_w, col_w])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
        story.append(Paragraph(
            f"&nbsp;&nbsp;&nbsp;[{mpq} mark{'s' if mpq > 1 else ''}]",
            styles["marks_badge"],
        ))
        _add_hint(q, styles, story)
        story.append(Spacer(1, 0.3 * cm))


SECTION_RENDERERS = {
    "mcq": _render_mcq,
    "fill_blank": _render_fill_blank,
    "true_false": _render_true_false,
    "short_answer": _render_short_answer,
    "match": _render_match,
}


# ── Answer key ────────────────────────────────────────────────────────────────

def _build_answer_key(worksheet: dict, styles: dict, story: list):
    story.append(PageBreak())
    story.append(Paragraph(
        "✂  ─────────────────────────── DETACH BEFORE DISTRIBUTING ───────────────────────────── ✂",
        styles["meta_line"],
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("ANSWER KEY", styles["answer_key_title"]))
    story.append(Paragraph(
        f"<b>{worksheet.get('title', 'Worksheet')}</b> — "
        f"{worksheet.get('grade', '')} {worksheet.get('subject', '')}",
        styles["meta_line"],
    ))
    story.append(Spacer(1, 0.3 * cm))
    for sec in worksheet.get("sections", []):
        story.append(Paragraph(f"<b>{sec.get('title', 'Section')}</b>", styles["section_header"]))
        for q in sec.get("questions", []):
            num = q.get("number", "?")
            answer = q.get("answer", "—")
            bloom = q.get("bloom_level", "")
            diff = q.get("difficulty_tag", "")
            badge = (
                f" <font color='#888888' size='8'>[{bloom} | {diff}]</font>"
                if bloom else ""
            )
            story.append(Paragraph(f"<b>{num}.</b> {answer}{badge}", styles["answer_item"]))


# ── Main renderer ─────────────────────────────────────────────────────────────

def render_worksheet_pdf(worksheet: dict, output_path: str) -> str:
    """
    Render a worksheet dict (conforming to WORKSHEET_SCHEMA) to a PDF.

    Args:
        worksheet:    The validated worksheet JSON dict.
        output_path:  Full path to write the PDF (including filename).

    Returns:
        output_path — the path to the saved PDF.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        title=worksheet.get("title", "Worksheet"),
    )

    page_w = A4[0] - 4.0 * cm
    _, styles = _build_styles()
    story = []

    # Header
    story.append(Paragraph(worksheet.get("title", "Worksheet"), styles["worksheet_title"]))
    story.append(Paragraph(
        f"Subject: {worksheet.get('subject', '')} &nbsp;|&nbsp; "
        f"Grade: {worksheet.get('grade', '')} &nbsp;|&nbsp; "
        f"Topic: {worksheet.get('topic', '')}",
        styles["meta_line"],
    ))
    story.append(Paragraph(
        f"Time: {worksheet.get('time_limit', '')} &nbsp;|&nbsp; "
        f"Total Marks: {worksheet.get('total_marks', '')}",
        styles["meta_line"],
    ))
    story.append(HRFlowable(
        width="100%", thickness=1.2,
        color=colors.HexColor("#0d3b66"), spaceAfter=6,
    ))

    # General instructions
    instructions = worksheet.get("instructions", "")
    if instructions:
        inst_table = Table(
            [[Paragraph(f"<b>Instructions:</b> {instructions}", styles["instructions_box"])]],
            colWidths=[page_w],
        )
        inst_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#0d3b66")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f4ff")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(inst_table)
        story.append(Spacer(1, 0.4 * cm))

    # Name / Date / Roll line
    name_row = Table(
        [[
            Paragraph("Name: ____________________________", styles["question"]),
            Paragraph("Date: ________________", styles["question"]),
            Paragraph("Roll No: ____________", styles["question"]),
        ]],
        colWidths=[page_w * 0.45, page_w * 0.3, page_w * 0.25],
    )
    story.append(name_row)
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#cccccc"), spaceBefore=6, spaceAfter=10,
    ))

    # Sections
    for sec in worksheet.get("sections", []):
        sec_type = sec.get("type", "").lower()
        renderer = SECTION_RENDERERS.get(sec_type)
        if renderer is None:
            continue

        mpq = sec.get("marks_per_question", 1)
        num_q = len(sec.get("questions", []))
        header_text = sec.get("title", sec_type.upper())
        story.append(Paragraph(
            f"{header_text} &nbsp;<font color='#777777' size='9'>({mpq * num_q} marks)</font>",
            styles["section_header"],
        ))
        sec_instructions = sec.get("instructions", "")
        if sec_instructions:
            story.append(Paragraph(sec_instructions, styles["section_instructions"]))

        renderer(sec, styles, page_w, story)

    # Answer key (detachable)
    _build_answer_key(worksheet, styles, story)

    doc.build(story)
    print(f"[PDF] Worksheet saved: {output_path}")
    return output_path
