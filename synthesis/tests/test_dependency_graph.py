from pathlib import Path

from dependency_graph import build_dependency_graph, expand_to_primitives


SYNTHESIS_DIR = Path(__file__).resolve().parents[1]


def _gate_names(path: Path) -> list[str]:
    gates = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields[:1] == ["GATE"]:
            gates.append(fields[1])
    return gates


def test_public_genlib_exposes_only_zero_and_imply() -> None:
    assert _gate_names(SYNTHESIS_DIR / "imply.genlib") == ["IMPLY", "ZERO"]


def test_abc_adapter_genlib_keeps_mapping_helpers() -> None:
    assert _gate_names(SYNTHESIS_DIR / "abc_imply.genlib") == [
        "IMPLY", "INV", "ZERO", "ONE"]


def test_inv_expands_to_zero_and_imply_primitives() -> None:
    gates = [("INV", {"a": "a", "O": "y"})]

    assert expand_to_primitives(gates) == [
        ("ZERO", {"O": "__zero_y_0"}),
        ("IMPLY", {"a": "a", "b": "__zero_y_0", "O": "y"}),
    ]


def test_dependency_graph_tree_shows_primitive_inputs() -> None:
    gates = [
        ("ZERO", {"O": "__zero_y_0"}),
        ("IMPLY", {"a": "a", "b": "__zero_y_0", "O": "y"}),
    ]

    graph = build_dependency_graph(["a"], ["y"], gates)

    assert graph.to_tree_text() == "\n".join([
        "y = IMPLY(a, __zero_y_0)",
        "  a = INPUT",
        "  __zero_y_0 = ZERO",
    ])


def test_dependency_graph_computes_paper_style_metrics() -> None:
    gates = [
        ("ZERO", {"O": "z"}),
        ("IMPLY", {"a": "a", "b": "z", "O": "n1"}),
        ("IMPLY", {"a": "b", "b": "n1", "O": "y"}),
    ]

    graph = build_dependency_graph(["a", "b"], ["y"], gates)

    assert graph.fanout()["z"] == 1
    assert graph.fanout()["n1"] == 1
    assert graph.cell_usage()["y"] == 1


def test_dependency_graph_dot_includes_paper_style_labels() -> None:
    gates = [
        ("ZERO", {"O": "__zero_y_0"}),
        ("IMPLY", {"a": "a", "b": "__zero_y_0", "O": "y"}),
    ]

    graph = build_dependency_graph(["a"], ["y"], gates)
    dot = graph.to_dot()

    assert "rankdir=BT" in dot
    assert 'shape=circle' in dot
    assert 'label="g1\\nFO=1\\nCU=1"' in dot
    assert 'tooltip="z0 ZERO"' in dot
    assert 'label="g2\\nFO=0\\nCU=1"' in dot
    assert 'tooltip="y IMPLY output"' in dot
    assert '"__zero_y_0" -> "y";' in dot
    assert '"a" -> "y"' not in dot


def test_dependency_graph_accepts_adapter_level_inv() -> None:
    gates = [
        ("INV", {"a": "a", "O": "n1"}),
        ("IMPLY", {"a": "n1", "b": "b", "O": "y"}),
    ]

    graph = build_dependency_graph(["a", "b"], ["y"], gates)

    assert graph.to_tree_text() == "\n".join([
        "y = IMPLY(n1, b)",
        "  n1 = INV(a)",
        "    a = INPUT",
        "  b = INPUT",
    ])
    assert graph.gate_ids() == {"n1": "g1", "y": "g2"}
