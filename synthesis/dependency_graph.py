"""Primitive dependency graph for IMPLY/FALSE sequence generation.

ABC still needs a small adapter library with helper gates such as INV. This
module removes that adapter layer before scheduling: every helper is expanded
into a graph whose real operation nodes are only ZERO and IMPLY. ZERO becomes a
FALSE reset in the final pulse program.
"""
from dataclasses import dataclass


Gate = tuple[str, dict[str, str]]


def _safe(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _zero_name(out: str, index: int) -> str:
    return f"__zero_{_safe(out)}_{index}"


def expand_to_primitives(gates: list[Gate]) -> list[Gate]:
    """Return gates whose real operation nodes are ZERO and IMPLY only.

    BUF is kept as a zero-cost alias because it is a wire, not a pulse.
    """
    primitive: list[Gate] = []
    zero_index = 0
    for typ, pins in gates:
        if typ in ("IMPLY", "ZERO", "BUF"):
            primitive.append((typ, dict(pins)))
        elif typ == "INV":
            z = _zero_name(pins["O"], zero_index)
            zero_index += 1
            primitive.append(("ZERO", {"O": z}))
            primitive.append(("IMPLY", {"a": pins["a"], "b": z, "O": pins["O"]}))
        elif typ == "ONE":
            z_src = _zero_name(pins["O"], zero_index)
            zero_index += 1
            z_dst = _zero_name(pins["O"], zero_index)
            zero_index += 1
            primitive.append(("ZERO", {"O": z_src}))
            primitive.append(("ZERO", {"O": z_dst}))
            primitive.append(("IMPLY", {"a": z_src, "b": z_dst, "O": pins["O"]}))
        else:
            raise ValueError(f"cannot lower helper gate {typ!r} to primitives")
    return primitive


@dataclass(frozen=True)
class GraphNode:
    name: str
    typ: str
    deps: tuple[str, ...] = ()


@dataclass
class DependencyGraph:
    inputs: list[str]
    outputs: list[str]
    nodes: dict[str, GraphNode]

    def to_tree_text(self) -> str:
        """Render output cones as a readable dependency tree."""
        lines: list[str] = []
        seen: set[tuple[str, int]] = set()

        def walk(net: str, depth: int) -> None:
            node = self.nodes[net]
            indent = "  " * depth
            if node.typ == "INPUT":
                lines.append(f"{indent}{net} = INPUT")
            elif node.typ == "ZERO":
                lines.append(f"{indent}{net} = ZERO")
            elif node.typ == "BUF":
                lines.append(f"{indent}{net} = BUF({node.deps[0]})")
            else:
                deps = ", ".join(node.deps)
                lines.append(f"{indent}{net} = {node.typ}({deps})")
            marker = (net, depth)
            if marker in seen:
                return
            seen.add(marker)
            for dep in node.deps:
                walk(dep, depth + 1)

        for output in self.outputs:
            walk(output, 0)
        return "\n".join(lines)

    def to_dot(self) -> str:
        """Render a Graphviz DOT graph for slides / supervisor inspection."""
        lines = ["digraph imply_dependency {", "  rankdir=BT;"]
        for node in self.nodes.values():
            if node.typ == "INPUT":
                shape = "box"
            elif node.typ == "ZERO":
                shape = "diamond"
            else:
                shape = "ellipse"
            label = f"{node.name}\\n{node.typ}"
            lines.append(f'  "{node.name}" [label="{label}", shape={shape}];')
            for dep in node.deps:
                lines.append(f'  "{dep}" -> "{node.name}";')
        lines.append("}")
        return "\n".join(lines) + "\n"


def build_dependency_graph(inputs: list[str], outputs: list[str],
                           gates: list[Gate]) -> DependencyGraph:
    nodes: dict[str, GraphNode] = {}
    for net in inputs:
        nodes[net] = GraphNode(net, "INPUT")
    for typ, pins in gates:
        out = pins["O"]
        if typ == "ZERO":
            nodes[out] = GraphNode(out, "ZERO")
        elif typ == "IMPLY":
            nodes[out] = GraphNode(out, "IMPLY", (pins["a"], pins["b"]))
        elif typ == "BUF":
            nodes[out] = GraphNode(out, "BUF", (pins["a"],))
        else:
            raise ValueError(f"dependency graph expects primitive gate, got {typ}")
    return DependencyGraph(inputs, outputs, nodes)
