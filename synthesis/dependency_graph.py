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

    def fanout(self) -> dict[str, int]:
        """Count how many operation nodes consume each net."""
        counts = {name: 0 for name in self.nodes}
        for node in self.nodes.values():
            for dep in node.deps:
                counts[dep] = counts.get(dep, 0) + 1
        return counts

    def cell_usage(self) -> dict[str, int]:
        """Estimate SIMPLER-style cell usage for each dependency cone.

        This is the Strahler-number heuristic described by SIMPLER: visit the
        largest child cones first, then compute how many live cells are needed
        while the earlier child results are kept around. Inputs are not gates,
        so they get CU 0; ZERO is a real primitive reset and gets CU 1.
        """
        memo: dict[str, int] = {}

        def cu(net: str) -> int:
            if net in memo:
                return memo[net]
            node = self.nodes[net]
            if node.typ == "INPUT":
                memo[net] = 0
                return 0
            child_cus = []
            for dep in node.deps:
                if self.nodes[dep].typ != "INPUT":
                    child_cus.append(cu(dep))
            if not child_cus:
                memo[net] = 1
                return 1
            child_cus.sort(reverse=True)
            memo[net] = max(child_cu + index
                            for index, child_cu in enumerate(child_cus))
            return memo[net]

        for name in self.nodes:
            cu(name)
        return memo

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
        """Render a SIMPLER Fig. 6-style Graphviz DOT DAG.

        The paper figure shows only gate vertices and wire edges. Inputs are
        implicit leaves, not drawn as boxes, so this view hides INPUT nodes and
        numbers the visible operation vertices as g1, g2, ...
        """
        fo = self.fanout()
        cu = self.cell_usage()
        gate_ids = self.gate_ids()
        lines = [
            "digraph imply_dependency {",
            "  graph [rankdir=BT, bgcolor=\"white\", margin=0.12, "
            "nodesep=0.28, ranksep=0.54, splines=true, outputorder=edgesfirst];",
            "  node [shape=circle, fixedsize=true, width=0.95, height=0.95, "
            "fontname=\"Helvetica\", fontsize=9, margin=0.02, style=\"filled\", "
            "fillcolor=\"#f8fbff\", color=\"#3a6ea5\", fontcolor=\"#1f4e79\", "
            "penwidth=2];",
            "  edge [color=\"#3a6ea5\", arrowsize=0.72, penwidth=1.6];",
        ]
        output_set = set(self.outputs)
        for node in self.nodes.values():
            if node.typ == "INPUT":
                continue
            label = f"{gate_ids[node.name]}\\nFO={fo[node.name]}\\nCU={cu[node.name]}"
            tooltip = f"{_display_name(node.name)} {node.typ}"
            if node.name in output_set:
                tooltip += " output"
            lines.append(
                f'  "{node.name}" [label="{label}", tooltip="{tooltip}"];')
            for dep in node.deps:
                if self.nodes[dep].typ == "INPUT":
                    continue
                lines.append(f'  "{dep}" -> "{node.name}";')
        lines.append("}")
        return "\n".join(lines) + "\n"

    def gate_ids(self) -> dict[str, str]:
        """Assign paper-style gN names to visible operation vertices."""
        ids: dict[str, str] = {}
        next_id = 1
        for name, node in self.nodes.items():
            if node.typ == "INPUT":
                continue
            ids[name] = f"g{next_id}"
            next_id += 1
        return ids


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
        elif typ == "INV":
            nodes[out] = GraphNode(out, "INV", (pins["a"],))
        elif typ == "ONE":
            nodes[out] = GraphNode(out, "ONE")
        else:
            deps = []
            for pin_name, net_name in pins.items():
                if pin_name != "O":
                    deps.append(net_name)
            nodes[out] = GraphNode(out, typ, tuple(deps))
    return DependencyGraph(inputs, outputs, nodes)


def _display_name(name: str) -> str:
    if name.startswith("__zero_"):
        return f"z{name.rsplit('_', 1)[-1]}"
    return name
