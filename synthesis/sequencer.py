"""把 IMPLY/INV 网表降解为可执行的 IMPLY/FALSE 程序。

输入 : 解析后的 BLIF 网表（来自 ABC，可能包含 IMPLY/INV/BUF/ZERO/ONE）
输出 : Program，即在 crossbar 行上按顺序执行的 FALSE/IMPLY 操作

这里处理的硬件约束：
- IMPLY(src, dst) 会覆盖 dst，因此还要用的值不能放在即将被覆盖的 dst。
- NOT x 不是硬件原语：INV 会降为 FALSE(w) + IMPLY(x, w)，得到 w = !x。
- BUF（如 ABC 的 `.barbuf` 透传）是零代价别名，不产生脉冲。

优化项（optimize=True）：
- 反相缓存：!n 算过一次后缓存复用；INV 还会登记反向别名。
- 死目标复用：当 b 后续不再使用时，IMPLY 直接原地写 b 的 cell（1 步）。
- cell 回收：值死亡后把 cell 放回 free 列表。
- 并行 FALSE 打包：在合法区间内移动 reset，最小化 FALSE 脉冲数。
- 行宽预算 max_cells：预算内优先开新 cell（reset 可前置合并），
  到达预算后转为复用空闲 cell。None = 不设预算（步数最少），
  0 = 尽量复用（cell 最少）。
- 调度组合搜索：尝试三种门顺序，保留目标函数最优程序。

naive 模式（optimize=False）只做拓扑序，不启用上述优化，
作为对照基线。
"""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field

# 程序操作用轻量 tuple 表示，打印结果直观且和展示格式一致。
Op = tuple  # ("FALSE", [cells]) | ("IMPLY", src, dst)


@dataclass
class Program:
    ops: list[Op]
    n_cells: int
    in_cell: dict[str, int]
    out_cell: dict[str, int]

    @property
    def steps(self) -> int:
        """程序总脉冲数。"""
        return len(self.ops)


def topo_order(inputs: list[str], gates: list[tuple]) -> list[tuple]:
    """按拓扑顺序排序门，保证每个门执行时输入已就绪。"""
    known = set(inputs)
    pending, ordered = list(gates), []
    while pending:
        rest = []
        for g in pending:
            typ, pins = g
            ready = True
            for pin_name, net_name in pins.items():
                if pin_name == "O":
                    continue
                if net_name not in known:
                    ready = False
                    break
            if ready:
                ordered.append(g)
                known.add(pins["O"])
            else:
                rest.append(g)
        if len(rest) == len(pending):
            raise RuntimeError("netlist not acyclic / undriven net")
        pending = rest
    return ordered


def fold_zero_imply_inverters(gates: list[tuple], outputs: list[str]) -> list[tuple]:
    """识别 ZERO+IMPLY 形成的反相模式，便于调度阶段优化。

    项目对外原语图仍然只有 ZERO 和 IMPLY，但在调度视角下，
    下面这种结构本质就是 INV：

        ZERO z
        IMPLY x, z -> y

    在这里折叠成 INV 后，现有的反相缓存与反向别名逻辑就能直接复用；
    最终发出的脉冲程序仍只包含 FALSE 和 IMPLY。
    """
    uses = Counter()
    consumer = {}
    for gate in gates:
        typ, pins = gate
        for pin_name, net_name in pins.items():
            if pin_name == "O":
                continue
            uses[net_name] += 1
            consumer[net_name] = gate

    folded_zero: set[str] = set()
    for typ, pins in gates:
        if typ != "ZERO":
            continue
        zero_net = pins["O"]
        if zero_net in outputs or uses[zero_net] != 1:
            continue
        use_gate = consumer.get(zero_net)
        if use_gate is None:
            continue
        use_typ, use_pins = use_gate
        if use_typ == "IMPLY" and use_pins["b"] == zero_net:
            folded_zero.add(zero_net)

    out = []
    for typ, pins in gates:
        if typ == "ZERO" and pins["O"] in folded_zero:
            continue
        if typ == "IMPLY" and pins["b"] in folded_zero:
            out.append(("INV", {"a": pins["a"], "O": pins["O"]}))
        else:
            out.append((typ, pins))
    return out


@dataclass
class _Core:
    """用指定门顺序策略对网表执行一次完整发射（生成程序）。"""
    optimize: bool
    scheduler: str = "topo"            # "topo" | "greedy-steps" | "greedy-cells"
    preserve_inputs: bool = False      # True 时保证输入 cell 结尾仍可读
    max_cells: int | None = None       # 行宽预算；None 不设限，0 尽量复用
    ops: list[Op] = field(default_factory=list)
    val: dict[str, int] = field(default_factory=dict)   # net -> 保存该值的 cell
    neg: dict[str, int] = field(default_factory=dict)   # net -> 保存 !net 的 cell
    claims: dict[int, set] = field(default_factory=dict)  # cell -> {(kind, net)}
    free: list[int] = field(default_factory=list)       # 可复用 cell（LIFO）
    n_cells: int = 0                                   # 下一个新 cell 编号
    remaining: Counter = field(default_factory=Counter)
    protected: set = field(default_factory=set)

    # ------------------------------------------------------------- 基础设施
    def alloc(self) -> int:
        """分配一个可用 cell：预算内先开新 cell，到预算后复用空闲 cell。"""
        at_budget = (self.max_cells is not None
                     and self.n_cells >= self.max_cells)
        if self.optimize and at_budget and self.free:
            return self.free.pop()
        c = self.n_cells
        self.n_cells += 1
        return c

    def fresh_false(self) -> int:
        """分配一个 cell 并发出 FALSE，把它清零。"""
        c = self.alloc()
        self.claims[c] = set()
        self.ops.append(("FALSE", [c]))
        return c

    def emit_imply(self, src: int, dst: int) -> None:
        """发出一条 IMPLY(src, dst) 脉冲操作。"""
        if src == dst:
            # IMPLY(x, x) 恒为 1，这通常是 cell 记账错误，不是有效脉冲。
            raise ValueError(f"IMPLY src==dst cell {src} (cell alias bug?)")
        self.ops.append(("IMPLY", src, dst))

    def live_vals(self, cell: int, exclude: str | None = None) -> list[str]:
        """返回某个 cell 中仍有后续用途的普通值。"""
        result = []
        for k, n in self.claims.get(cell, ()):
            if k != "val":
                continue
            if n == exclude:
                continue
            if self.remaining[n] > 0 or n in self.protected:
                result.append(n)
        return result

    def live_negs(self, cell: int) -> list[str]:
        """返回某个 cell 中仍有后续用途的反相缓存值。"""
        result = []
        for k, n in self.claims.get(cell, ()):
            if k != "neg":
                continue
            if self.remaining[n] > 0 or n in self.protected:
                result.append(n)
        return result

    def dec(self, net: str) -> None:
        """消费一次 net 的剩余使用计数，并尝试回收其所在 cell。"""
        self.remaining[net] -= 1
        cell = self.val.get(net)
        if cell is not None:
            self.maybe_reclaim(cell)

    def maybe_reclaim(self, cell: int) -> None:
        # 只有当 cell 内所有“还会用到”的值都死亡后，才能回收到 free。
        if (not self.optimize or cell in self.free or self.live_vals(cell)
                or self.live_negs(cell)):
            return
        for k, n in list(self.claims.get(cell, ())):
            if k == "val" and self.val.get(n) == cell:
                del self.val[n]
            if k == "neg" and self.neg.get(n) == cell:
                del self.neg[n]
        self.claims[cell] = set()
        self.free.append(cell)

    def retarget(self, cell: int, out: str) -> None:
        """记录破坏性写入后：该 cell 现在保存 out。"""
        for k, n in list(self.claims.get(cell, ())):
            if k == "val" and self.val.get(n) == cell:
                del self.val[n]
            if k == "neg" and self.neg.get(n) == cell:
                del self.neg[n]
        self.claims[cell] = {("val", out)}
        self.val[out] = cell

    def ensure_neg(self, net: str) -> int:
        """确保并返回保存 !net 的 cell（必要时新建）。"""
        if self.optimize and net in self.neg:
            return self.neg[net]
        w = self.fresh_false()
        self.emit_imply(self.val[net], w)
        if self.optimize:
            self.neg[net] = w
            self.claims[w].add(("neg", net))
        return w

    # ---------------------------------------------------------------- 门处理
    def destructible(self, b: str) -> bool:
        """判断 b 是否可作为 IMPLY 目标被原地覆盖。"""
        # 安全原地写条件：b 非受保护输出、这是 b 最后一次使用、且 cell 不共享活值。
        if not self.optimize:
            return False
        if b in self.protected:
            return False
        if self.remaining[b] != 1:
            return False
        if self.live_vals(self.val[b], exclude=b):
            return False
        return True

    def do_inv(self, pins: dict) -> None:
        """发射 INV：优先复用反相缓存，否则用 FALSE+IMPLY 构造。"""
        a, z = pins["a"], pins["O"]
        if self.optimize and a in self.neg:        # 命中反相缓存：不新增脉冲
            c = self.neg[a]
        else:                                      # FALSE + IMPLY：2 步
            c = self.fresh_false()
            self.emit_imply(self.val[a], c)
            if self.optimize:
                self.neg[a] = c
                self.claims[c].add(("neg", a))
        self.claims[c].add(("val", z))
        self.val[z] = c
        if self.optimize:                  # 反向别名：若 z = !a，则 a = !z
            ca = self.val.get(a)
            if ca is not None and z not in self.neg:
                self.neg[z] = ca
                self.claims[ca].add(("neg", z))
        self.dec(a)

    def do_imply(self, pins: dict) -> None:
        """发射 IMPLY：优先原地覆盖，否则走构造路径。"""
        a, b, z = pins["a"], pins["b"], pins["O"]
        assert a != b, "degenerate IMPLY(x,x) not expected from ABC"
        if self.destructible(b):                   # 1 步，原地写
            cb = self.val[b]
            self.emit_imply(self.val[a], cb)
            self.retarget(cb, z)
        else:                                      # 通过 !b 与 !a 构造（1-5 步）
            nb = self.ensure_neg(b)
            t = None
            if self.optimize and a in self.neg and not self.live_vals(self.neg[a]):
                t = self.neg[a]                     # 消耗缓存 !a 作为目标 cell
                del self.neg[a]
            if t is None:
                t = self.fresh_false()
                self.emit_imply(self.val[a], t)     # t = !a
            self.emit_imply(nb, t)                  # t = b | !a = z
            self.retarget(t, z)
        self.dec(a)
        self.dec(b)

    def do_buf(self, pins: dict) -> None:
        """BUF 透传：给同一个 cell 绑定一个新网名，不发脉冲。"""
        a, z = pins["a"], pins["O"]
        c = self.val[a]
        self.claims[c].add(("val", z))
        self.val[z] = c
        self.dec(a)

    def do_const(self, typ: str, pins: dict) -> None:
        """处理常量门：ZERO 直接清零；ONE 由清零后再构造得到。"""
        z = pins["O"]
        c = self.fresh_false()                     # ZERO 本质就是拿到一个已清零 cell。
        if typ == "ONE":
            zc = self.fresh_false()
            self.emit_imply(zc, c)                  # c = !0 | 0 = 1
            if self.optimize:
                self.free.append(zc)
        self.claims[c].add(("val", z))
        self.val[z] = c

    def emit_gate(self, typ: str, pins: dict) -> None:
        """根据门类型分发到对应发射逻辑。"""
        if typ == "INV":
            self.do_inv(pins)
        elif typ == "IMPLY":
            self.do_imply(pins)
        elif typ == "BUF":
            self.do_buf(pins)
        elif typ in ("ZERO", "ONE"):
            self.do_const(typ, pins)
        else:
            raise ValueError(f"unexpected gate {typ}")

    # ------------------------------------------------------------ 调度
    def score(self, typ: str, pins: dict) -> int:
        """当前机器状态下的贪心评分函数。"""
        dying = 0
        for pin_name, net_name in pins.items():
            if pin_name != "O" and self.remaining[net_name] == 1:
                dying += 1
        if typ == "BUF":
            s = 95                                  # free alias
        elif typ == "INV":
            if pins["a"] in self.neg:
                s = 90
            else:
                s = 10
        elif typ == "IMPLY":
            a, b = pins["a"], pins["b"]
            if self.destructible(b):
                s = 60
            else:
                s = 0
                if b in self.neg:
                    s += 20
                if a in self.neg and not self.live_vals(self.neg[a]):
                    s += 20
        else:
            s = 0
        if self.scheduler == "greedy-cells":
            return 50 * dying + s
        return s + 5 * dying

    def run(self, inputs: list[str], outputs: list[str],
            gates: list[tuple]) -> Program:
        """执行一次调度并返回 Program。"""
        if self.optimize:
            gates = fold_zero_imply_inverters(gates, outputs)
        self.protected = set(outputs)
        if self.preserve_inputs:
            # 保护输入：不可原地覆盖、不可回收，保证末态仍保留原输入值。
            self.protected |= set(inputs)
        # remaining 用于判断覆盖写是否安全，避免 IMPLY 破坏仍需使用的值。
        for _, pins in gates:
            for k, v in pins.items():
                if k != "O":
                    self.remaining[v] += 1
        in_cell = {}
        for net in inputs:
            c = self.alloc()
            self.claims[c] = {("val", net)}
            self.val[net] = c
            in_cell[net] = c

        if self.scheduler == "topo" or not self.optimize:
            for typ, pins in topo_order(inputs, gates):
                self.emit_gate(typ, pins)
        else:
            computed = set(inputs)
            pending = list(gates)
            while pending:
                ready = []
                for gate in pending:
                    gate_ready = True
                    for pin_name, net_name in gate[1].items():
                        if pin_name == "O":
                            continue
                        if net_name not in computed:
                            gate_ready = False
                            break
                    if gate_ready:
                        ready.append(gate)

                best = ready[0]
                best_score = self.score(*best)
                for gate in ready[1:]:
                    gate_score = self.score(*gate)
                    if gate_score > best_score:
                        best = gate
                        best_score = gate_score
                self.emit_gate(*best)
                computed.add(best[1]["O"])
                pending.remove(best)

        if self.optimize:
            ops = pack_false(self.ops)
        else:
            ops = self.ops
        out_cell = {}
        for out_name in outputs:
            out_cell[out_name] = self.val[out_name]
        return Program(ops, self.n_cells, in_cell, out_cell)


class Sequencer:
    """面向外部的调度 API：封装多策略候选并择优。"""

    def __init__(self, optimize: bool, objective: str = "steps",
                 preserve_inputs: bool = True, max_cells: int | None = None):
        """配置调度器参数。

        preserve_inputs: 默认保护输入 cell（结尾仍可读）。
        max_cells: 行宽预算。None 不设限（步数最少），0 尽量复用（cell 最少）。
        """
        self.optimize = optimize
        self.objective = objective
        self.preserve_inputs = preserve_inputs
        self.max_cells = max_cells

    def run(self, inputs: list[str], outputs: list[str],
            gates: list[tuple]) -> Program:
        """运行多策略组合搜索并按目标函数选择最佳程序。"""
        if not self.optimize:
            return _Core(False).run(inputs, outputs, gates)
        candidates = []
        for sched in ("topo", "greedy-steps", "greedy-cells"):
            program = _Core(True, sched,
                            preserve_inputs=self.preserve_inputs,
                            max_cells=self.max_cells).run(
                                inputs, outputs, gates)
            candidates.append(program)
        if self.objective == "cells":
            best = candidates[0]
            for program in candidates[1:]:
                if (program.n_cells, program.steps) < (best.n_cells, best.steps):
                    best = program
            return best
        best = candidates[0]
        for program in candidates[1:]:
            if (program.steps, program.n_cells) < (best.steps, best.n_cells):
                best = program
        return best


def pack_false(ops: list[Op]) -> list[Op]:
    """在给定 IMPLY 顺序下，把 FALSE reset 重新打包为最少脉冲。

    一个 reset 只要位于“上次触碰该 cell 之后、下次触碰之前”都合法，
    因此可转化为 IMPLY 间隙上的区间刺点最小化问题。
    这里使用按最早右端点的贪心扫描得到最优脉冲数；
    同时允许 reset 适度后移以与后续 reset 合并，最后再放回最早可行间隙。
    """
    implies = [op for op in ops if op[0] != "FALSE"]
    n = len(implies)
    intervals: list[list] = []           # [lo_gap, hi_gap, cell]
    pending: dict[int, list] = {}        # cell -> 等待确定 hi 的区间
    last_gap: dict[int, int] = {}        # cell -> 上次触碰后最早合法 gap
    seen = 0
    for op in ops:
        if op[0] == "FALSE":
            for c in op[1]:
                iv = [last_gap.get(c, 0), n, c]
                intervals.append(iv)
                pending.setdefault(c, []).append(iv)
        else:
            for c in {op[1], op[2]}:
                for iv in pending.pop(c, ()):
                    iv[1] = seen         # 必须在当前 IMPLY 前触发
                last_gap[c] = seen + 1   # 后续 reset 只能在当前 IMPLY 后
            seen += 1

    intervals.sort(key=lambda iv: iv[1])
    groups: list[list] = []              # [placement_gap, cover_point, cells]
    points: list[int] = []               # 升序 cover points
    for lo, hi, c in intervals:
        # 仅当没有现有点覆盖 [lo, hi] 时才新建脉冲；否则并入最早兼容脉冲。
        k = bisect_left(points, lo)
        if k == len(groups):
            groups.append([lo, hi, {c}])
            points.append(hi)
        else:
            g = groups[k]
            g[2].add(c)
            if lo > g[0]:
                g[0] = lo

    by_gap: dict[int, set] = {}
    for gap, _, cells in groups:
        by_gap.setdefault(gap, set()).update(cells)
    out: list[Op] = []
    for k in range(n + 1):
        if k in by_gap:
            out.append(("FALSE", sorted(by_gap[k])))
        if k < n:
            out.append(implies[k])
    return out
