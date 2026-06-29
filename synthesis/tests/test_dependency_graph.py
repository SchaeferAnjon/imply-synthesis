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
