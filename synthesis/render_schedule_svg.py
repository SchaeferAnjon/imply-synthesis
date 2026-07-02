#!/usr/bin/env python3
"""Render an IMPLY/FALSE sequence as draw.io and SVG schedule diagrams.

The source of truth is compile.py's .seq.txt artifact. The generated .drawio
file can be opened in diagrams.net, while the SVG is suitable for README
embedding on GitHub.
"""
import argparse
import ast
import html
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring


FALSE_RE = re.compile(r"^\s*(\d+)\s+FALSE\s+(\[.*\])\s*$")
IMPLY_RE = re.compile(r"^\s*(\d+)\s+IMPLY\s+(\d+)\s+->\s+(\d+)\s*$")
DRAWIO_TEXT_WARNING = (
    '<switch><g requiredFeatures="http://www.w3.org/TR/SVG11/feature#Extensibility"/>'
    '<a transform="translate(0,-5)" '
    'xlink:href="https://www.drawio.com/doc/faq/svg-export-text-problems" '
    'target="_blank"><text text-anchor="middle" font-size="10px" x="50%" '
    'y="100%">Text is not SVG - cannot display</text></a></switch>'
)


def parse_sequence(path: Path):
    inputs, outputs, ops = {}, {}, []
    for line in path.read_text().splitlines():
        if line.startswith("# inputs:"):
            inputs = ast.literal_eval(line.split(":", 1)[1].strip())
        elif line.startswith("# outputs:"):
            outputs = ast.literal_eval(line.split(":", 1)[1].strip())
        else:
            m = FALSE_RE.match(line)
            if m:
                ops.append(("FALSE", int(m.group(1)), ast.literal_eval(m.group(2))))
                continue
            m = IMPLY_RE.match(line)
            if m:
                ops.append(("IMPLY", int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if not ops:
        raise SystemExit(f"no sequence operations found in {path}")
    touched = []
    touched.extend(inputs.values())
    touched.extend(outputs.values())
    for op in ops:
        if op[0] == "FALSE":
            touched.extend(op[2])
        else:
            touched.extend([op[2], op[3]])
    n_cells = 1 + max(touched)
    return inputs, outputs, ops, n_cells


def layout_rows(inputs: dict[str, int], outputs: dict[str, int], n_cells: int) -> list[int]:
    input_cells = set(inputs.values())
    output_cells = set(outputs.values())
    work_only = [c for c in range(n_cells) if c not in input_cells and c not in output_cells]
    output_only = [c for c in range(n_cells) if c in output_cells and c not in input_cells]
    input_or_inout = [c for c in range(n_cells) if c in input_cells]
    return work_only + output_only + input_or_inout


def cell_names(cell: int, mapping: dict[str, int]) -> list[str]:
    return [name for name, idx in mapping.items() if idx == cell]


def row_label(cell: int, inputs: dict[str, int], outputs: dict[str, int]) -> tuple[str, str, str]:
    input_names = cell_names(cell, inputs)
    output_names = cell_names(cell, outputs)
    if input_names and output_names:
        return f"{' / '.join(input_names)} -> {' / '.join(output_names)}", f"c{cell}", "io"
    if input_names:
        return " / ".join(input_names), f"c{cell}", "input"
    if output_names:
        return " / ".join(output_names), f"c{cell}", "output"
    work_index = row_label.work_map[cell]
    return f"w{work_index}", f"c{cell}", "work"


def short_cell_label(cell: int, inputs: dict[str, int], outputs: dict[str, int]) -> str:
    label, _, _ = row_label(cell, inputs, outputs)
    return label.replace(" -> ", "/")


def graph_row_label(cell: int, inputs: dict[str, int], outputs: dict[str, int]) -> str:
    input_names = cell_names(cell, inputs)
    output_names = cell_names(cell, outputs)
    if input_names:
        return " / ".join(input_names)
    if output_names:
        return " / ".join(output_names)
    return row_label(cell, inputs, outputs)[0]


row_label.work_map = {}


def build_geometry(inputs: dict[str, int], outputs: dict[str, int],
                   ops: list[tuple], n_cells: int):
    rows = layout_rows(inputs, outputs, n_cells)
    work_counter = 1
    row_label.work_map = {}
    for cell in rows:
        if cell not in inputs.values() and cell not in outputs.values():
            row_label.work_map[cell] = work_counter
            work_counter += 1

    left, top, step_w, row_h = 178, 58, 54, 50
    right, bottom = 142, 72
    width = left + step_w * len(ops) + right
    height = top + row_h * len(rows) + bottom
    y_for = {cell: top + i * row_h + row_h // 2 for i, cell in enumerate(rows)}
    x_for = {step: left + (step - 1) * step_w + step_w // 2
             for step in range(1, len(ops) + 1)}
    return rows, y_for, x_for, width, height, left, top, step_w, row_h, right


def text(x, y, body, cls="", anchor="middle"):
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" class="{cls}">'
        f'{html.escape(body)}</text>'
    )


def role_class(kind: str) -> str:
    if kind in {"input", "output", "io"}:
        return kind
    return "work"


def source_tag(cell: int) -> str:
    return f"src c{cell}"


def render_svg(title: str, inputs: dict[str, int], outputs: dict[str, int],
               ops: list[tuple], n_cells: int) -> str:
    rows, y_for, x_for, width, height, left, top, step_w, _row_h, right = (
        build_geometry(inputs, outputs, ops, n_cells)
    )
    box_w, box_h = 36, 32
    axis_y = height - 44
    line_start = left - 56
    line_end = width - right
    outputs_by_cell = {}
    for name, cell in outputs.items():
        outputs_by_cell.setdefault(cell, []).append(name)

    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(title)}</title>',
        '<desc id="desc">C64-style scheduling graph generated from the '
        'IMPLY/FALSE sequence artifact.</desc>',
        '<defs>',
        '<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 Z" '
        'fill="#111111"/></marker>',
        '<marker id="axisArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 Z" '
        'fill="#111111"/></marker>',
        '</defs>',
        '<style>',
        'text{font-family:Arial,Helvetica,sans-serif;fill:#111111}',
        '.row-title{font-size:15px;font-weight:700}',
        '.badge{stroke:#111111;stroke-width:2.2}',
        '.badge.work{fill:#ef9a9a}',
        '.badge.input{fill:#c7e8f6}',
        '.badge.output{fill:#d8efd2}',
        '.badge.io{fill:#c7e8f6}',
        '.rail{stroke:#111111;stroke-width:2.1;fill:none}',
        '.flow{stroke:#111111;stroke-width:1.8;fill:none;marker-end:url(#arrow)}',
        '.axis{stroke:#111111;stroke-width:1.5;fill:none;marker-end:url(#axisArrow)}',
        '.step{font-size:14px}',
        '.step-label{font-size:17px;font-weight:700}',
        '.op{fill:#dcead7;stroke:#111111;stroke-width:3}',
        '.op-label{font-size:11px;font-weight:700}',
        '.false-label{font-size:18px;font-weight:700}',
        '.out{font-size:20px;font-weight:700;fill:#ff0000;font-style:italic}',
        '</style>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    for cell in rows:
        y = y_for[cell]
        _label, _cell_id, kind = row_label(cell, inputs, outputs)
        label = graph_row_label(cell, inputs, outputs)
        cls = role_class(kind)
        badge_x = line_start - 28
        out.append(f'<circle cx="{badge_x}" cy="{y}" r="16" class="badge {cls}"/>')
        out.append(text(badge_x, y + 5, label, "row-title"))
        out.append(f'<path d="M{line_start - 8},{y} H{line_end}" class="rail"/>')
        if cell in outputs_by_cell:
            names = " / ".join(name.capitalize() for name in outputs_by_cell[cell])
            out.append(text(line_end + 18, y - 10, names, "out", "start"))

    for op in ops:
        if op[0] == "FALSE":
            _, step, cells = op
            x = x_for[step]
            for cell in cells:
                y = y_for[cell]
                out.append(
                    f'<rect x="{x - box_w / 2:.1f}" y="{y - box_h / 2:.1f}" '
                    f'width="{box_w}" height="{box_h}" class="op"/>'
                )
                out.append(text(x, y + 6, "⊥", "false-label"))
        else:
            _, step, src, dst = op
            x = x_for[step]
            y_src = y_for[src]
            y_dst = y_for[dst]
            target_y = y_dst - box_h / 2 if y_src < y_dst else y_dst + box_h / 2
            out.append(
                f'<path d="M{x - box_w / 2 - 10:.1f},{y_src} H{x} '
                f'V{target_y:.1f}" class="flow"/>'
            )
            out.append(
                f'<rect x="{x - box_w / 2:.1f}" y="{y_dst - box_h / 2:.1f}" '
                f'width="{box_w}" height="{box_h}" class="op"/>'
            )
            out.append(text(x, y_dst + 4, "IMP", "op-label"))

    out.append(f'<path d="M{line_start - 48},{axis_y} H{line_end}" class="axis"/>')
    out.append(text(line_start - 38, axis_y + 22, "Steps", "step-label", "start"))
    for step in range(1, len(ops) + 1):
        out.append(text(x_for[step], axis_y + 22, str(step), "step"))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def mx_geometry(parent, x, y, w, h):
    SubElement(parent, "mxGeometry", {
        "x": str(x), "y": str(y), "width": str(w), "height": str(h),
        "as": "geometry",
    })


def mx_absolute_edge(root, cell_id, points, style, parent="1"):
    cell = SubElement(root, "mxCell", {
        "id": str(cell_id),
        "value": "",
        "style": style,
        "parent": parent,
        "edge": "1",
    })
    geom = SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
    SubElement(geom, "mxPoint", {
        "x": str(points[0][0]), "y": str(points[0][1]), "as": "sourcePoint",
    })
    if len(points) > 2:
        arr = SubElement(geom, "Array", {"as": "points"})
        for x, y in points[1:-1]:
            SubElement(arr, "mxPoint", {"x": str(x), "y": str(y)})
    SubElement(geom, "mxPoint", {
        "x": str(points[-1][0]), "y": str(points[-1][1]), "as": "targetPoint",
    })


def mx_cell(root, cell_id, value="", style="", vertex=False, edge=False,
            parent="1", source=None, target=None, x=0, y=0, w=0, h=0):
    attrs = {"id": str(cell_id), "value": value, "style": style, "parent": parent}
    if vertex:
        attrs["vertex"] = "1"
    if edge:
        attrs["edge"] = "1"
    if source is not None:
        attrs["source"] = str(source)
    if target is not None:
        attrs["target"] = str(target)
    cell = SubElement(root, "mxCell", attrs)
    if vertex:
        mx_geometry(cell, x, y, w, h)
    elif edge:
        geom = SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        SubElement(geom, "Array", {"as": "points"})
    return cell


def render_drawio(title: str, inputs: dict[str, int], outputs: dict[str, int],
                  ops: list[tuple], n_cells: int) -> str:
    rows, y_for, x_for, width, height, left, _top, _step_w, _row_h, right = (
        build_geometry(inputs, outputs, ops, n_cells)
    )
    box_w, box_h = 36, 32
    axis_y = height - 44
    line_start = left - 56
    line_end = width - right
    root_file = Element("mxfile", {
        "host": "app.diagrams.net",
        "modified": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent": "Codex generated C64-style schedule",
        "version": "24.7.17",
    })
    diagram = SubElement(root_file, "diagram", {"name": "full_adder_schedule"})
    model = SubElement(diagram, "mxGraphModel", {
        "dx": str(width), "dy": str(height), "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
        "fold": "1", "page": "1", "pageScale": "1",
        "pageWidth": str(width), "pageHeight": str(height), "math": "0",
        "shadow": "0",
    })
    root = SubElement(model, "root")
    SubElement(root, "mxCell", {"id": "0"})
    SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    next_id = 2
    outputs_by_cell = {}
    for name, cell in outputs.items():
        outputs_by_cell.setdefault(cell, []).append(name)

    mx_cell(root, next_id, "",
            "rounded=0;whiteSpace=wrap;html=0;fillColor=#ffffff;strokeColor=none;",
            vertex=True, x=0, y=0, w=width, h=height)
    next_id += 1

    for cell in rows:
        y = y_for[cell]
        _label, _cell_id, kind = row_label(cell, inputs, outputs)
        label = graph_row_label(cell, inputs, outputs)
        fill = {
            "work": "#ef9a9a",
            "input": "#c7e8f6",
            "output": "#d8efd2",
            "io": "#c7e8f6",
        }[role_class(kind)]
        badge_x = line_start - 28
        mx_cell(root, next_id, label,
                "ellipse;whiteSpace=wrap;html=0;fontStyle=1;fontSize=15;"
                f"fillColor={fill};strokeColor=#111111;strokeWidth=2;",
                vertex=True, x=badge_x - 16, y=y - 16, w=32, h=32)
        next_id += 1
        mx_absolute_edge(
            root, next_id,
            [(line_start - 8, y), (line_end, y)],
            "endArrow=none;html=0;rounded=0;strokeWidth=2;strokeColor=#111111;",
        )
        next_id += 1
        if cell in outputs_by_cell:
            mx_cell(root, next_id, " / ".join(name.capitalize() for name in outputs_by_cell[cell]),
                    "text;html=0;strokeColor=none;fillColor=none;fontColor=#ff0000;"
                    "fontSize=20;fontStyle=3;align=left;verticalAlign=middle;",
                    vertex=True, x=line_end + 16, y=y - 24, w=96, h=28)
            next_id += 1

    for op in ops:
        if op[0] == "FALSE":
            _, step, cells = op
            x = x_for[step]
            for cell in cells:
                y = y_for[cell]
                mx_cell(root, next_id, "⊥",
                        "rounded=0;whiteSpace=wrap;html=0;fontStyle=1;fontSize=18;"
                        "fillColor=#dcead7;strokeColor=#111111;strokeWidth=3;",
                        vertex=True, x=x - box_w / 2, y=y - box_h / 2, w=box_w, h=box_h)
                next_id += 1
        else:
            _, step, src, dst = op
            x = x_for[step]
            y_src = y_for[src]
            y_dst = y_for[dst]
            target_y = y_dst - box_h / 2 if y_src < y_dst else y_dst + box_h / 2
            mx_absolute_edge(
                root, next_id,
                [(x - box_w / 2 - 10, y_src), (x, y_src), (x, target_y)],
                "endArrow=classic;html=0;rounded=0;strokeWidth=2;strokeColor=#111111;endSize=6;",
            )
            next_id += 1
            mx_cell(root, next_id, "IMP",
                    "rounded=0;whiteSpace=wrap;html=0;fontStyle=1;fontSize=11;"
                    "fillColor=#dcead7;strokeColor=#111111;strokeWidth=3;",
                    vertex=True, x=x - box_w / 2, y=y_dst - box_h / 2, w=box_w, h=box_h)
            next_id += 1

    mx_absolute_edge(
        root, next_id,
        [(line_start - 48, axis_y), (line_end, axis_y)],
        "endArrow=classic;html=0;rounded=0;strokeWidth=1.5;strokeColor=#111111;endSize=6;",
    )
    next_id += 1
    mx_cell(root, next_id, "Steps",
            "text;html=0;strokeColor=none;fillColor=none;fontSize=17;fontStyle=1;align=left;",
            vertex=True, x=line_start - 38, y=axis_y + 5, w=70, h=28)
    next_id += 1
    for step in range(1, len(ops) + 1):
        mx_cell(root, next_id, str(step),
                "text;html=0;strokeColor=none;fillColor=none;fontSize=14;align=center;",
                vertex=True, x=x_for[step] - 12, y=axis_y + 6, w=24, h=24)
        next_id += 1

    return tostring(root_file, encoding="unicode") + "\n"


def clean_drawio_svg(path: Path) -> None:
    path.write_text(path.read_text().replace(DRAWIO_TEXT_WARNING, ""))


def export_drawio_svg(drawio_path: Path, svg_path: Path) -> None:
    if shutil.which("drawio") is None:
        raise SystemExit("drawio CLI not found; install draw.io or omit --export-with-drawio")
    subprocess.run([
        "drawio",
        "--export",
        "--format", "svg",
        "--svg-theme", "light",
        "--embed-svg-fonts", "false",
        "--output", str(svg_path),
        str(drawio_path),
    ], check=True)
    clean_drawio_svg(svg_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sequence", type=Path)
    ap.add_argument("svg_output", type=Path)
    ap.add_argument("--drawio", type=Path, default=None)
    ap.add_argument("--export-with-drawio", action="store_true")
    ap.add_argument("--title", default="Full adder IMPLY/FALSE schedule")
    args = ap.parse_args()

    inputs, outputs, ops, n_cells = parse_sequence(args.sequence)
    args.svg_output.parent.mkdir(parents=True, exist_ok=True)
    if args.drawio:
        args.drawio.parent.mkdir(parents=True, exist_ok=True)
        args.drawio.write_text(render_drawio(args.title, inputs, outputs, ops, n_cells))
    if args.export_with_drawio:
        if not args.drawio:
            raise SystemExit("--export-with-drawio requires --drawio")
        export_drawio_svg(args.drawio, args.svg_output)
    else:
        args.svg_output.write_text(render_svg(args.title, inputs, outputs, ops, n_cells))


if __name__ == "__main__":
    main()
