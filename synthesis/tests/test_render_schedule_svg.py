from pathlib import Path

from render_schedule_svg import parse_sequence, render_drawio, render_svg


def test_c64_style_schedule_renderer_uses_local_flow_arrows(tmp_path: Path) -> None:
    seq = tmp_path / "mini.seq.txt"
    seq.write_text("\n".join([
        "# mini: IMPLY/FALSE sequence, 3 steps, 3 cells",
        "# inputs:  {'a': 0}",
        "# outputs: {'y': 1}",
        "   1  FALSE [2]",
        "   2  IMPLY 0 -> 2",
        "   3  IMPLY 2 -> 1",
    ]))

    inputs, outputs, ops, n_cells = parse_sequence(seq)

    svg = render_svg("Mini schedule", inputs, outputs, ops, n_cells)
    drawio = render_drawio("Mini schedule", inputs, outputs, ops, n_cells)

    assert "C64-style scheduling graph" in svg
    assert 'marker-end:url(#arrow)' in svg
    assert 'class="badge input"' in svg
    assert 'class="op"' in svg
    assert "endArrow=classic" in drawio
    assert "IMP" in drawio
