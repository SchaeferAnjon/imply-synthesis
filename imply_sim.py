"""IMPLY 和 FALSE 脉冲的逻辑层小型模拟器。

这不是一个 SPICE 级别的电路仿真（不模拟电压、电流、器件物理）。
它只维护"一整行忆阻器 crossbar"的布尔状态（每个 cell 非 0 即 1），
这已经足够用来检查：给定一段生成好的脉冲序列，最后算出来的结果对不对。

对硬件的抽象：
    cells[i] ∈ {0, 1}    # 0 = 高阻态 R_off，1 = 低阻态 R_on（即存的那个比特）
    imply(a, b)          # 执行一次 IMPLY：cells[b] := (¬cells[a]) ∨ cells[b]
    false_reset([...])   # 并行清零若干个 cell；不管清几个，都只算「一步」
"""

from dataclasses import dataclass, field
# dataclass：Python 提供的「自动生成 __init__ 等样板代码」的装饰器，
# 让下面的 CrossbarRow 类不用手写 __init__ 就能有 cells/steps/trace 三个字段。


@dataclass
class CrossbarRow:
    """代表一整行忆阻器（一个 crossbar 的一行）。"""

    cells: list[int] = field(default_factory=list)
    # cells：这一行里每个忆阻器当前存的比特，下标就是"第几个 cell"。
    steps: int = 0
    # steps：到目前为止，物理上一共打了几个脉冲（是真实的"时间"代价，不是操作条数）。
    trace: list[str] = field(default_factory=list)
    # trace：把每一步做了什么，按顺序记下来，方便事后打印/调试。

    def imply(self, i_a: int, i_b: int) -> None:
        """执行一次原地 IMPLY：cells[i_b] = (¬cells[i_a]) ∨ cells[i_b]。

        这是硬件唯一的计算原语。注意它是「破坏性」的：
        目的地 i_b 原来的值会被这条公式的结果直接覆盖掉。
        """
        a = self.cells[i_a]      # 读出源 cell 当前的值
        b = self.cells[i_b]      # 读出目的 cell 当前的值（马上就要被覆盖）
        if a == 0:
            # ¬a = 1，所以 (¬a) ∨ b 恒为 1，不用管 b 是什么
            self.cells[i_b] = 1
        else:
            # ¬a = 0，所以 (¬a) ∨ b = b，目的地保持原值不变
            self.cells[i_b] = b
        self.steps += 1                          # 物理上又消耗了一个脉冲
        self.trace.append(f"IMPLY {i_a}->{i_b}")  # 记一笔账，方便回放

    def false_reset(self, indices: list[int]) -> None:
        """并行 FALSE 脉冲：把列表里的所有 cell 同时清零，一次脉冲只算一步。

        「并行」是这个函数存在的全部意义：物理上一次 FALSE 电压
        可以同时打在很多根 bitline 上，所以哪怕清零 5 个 cell，
        代价也只是 1 步，而不是 5 步。
        """
        for i in indices:
            self.cells[i] = 0    # 逐个清零（循环只是代码层面的写法，
                                  # 物理上是同时发生的，所以 steps 只 +1）
        self.steps += 1
        self.trace.append(f"FALSE {indices}")

    def reset_counters(self) -> None:
        """把步数计数器和执行轨迹清零，方便同一个 CrossbarRow 复用着跑下一组测试。"""
        self.steps = 0
        self.trace.clear()


def imply_truth(a: int, b: int) -> int:
    """IMPLY 的"标准答案"（真值表参考实现）：a → b ≡ (¬a) ∨ b。

    之所以单独写一个纯函数版本，是为了在 verify_imply() 里
    拿它和"真正跑一遍模拟器"的结果做对照，两边算出来必须一致。
    """
    return (1 - a) | b
    # (1 - a)：a 是 0/1，所以 1-a 就是"取反"；| 是按位或，对 0/1 就是逻辑或。


def verify_imply() -> None:
    """穷举 a、b 的全部 4 种取值，逐一验证模拟器算出的 IMPLY 是否正确。"""
    print("=" * 50)
    print("[1]  Verifying IMPLY truth table")   # 打印标题：验证 IMPLY 真值表
    print("=" * 50)
    print(f"{'a':>2} {'b':>2} | {'expected':>8} {'got':>4}  step  trace")
    print("-" * 50)

    all_ok = True   # 只要有一组失败，这个标志就会被压成 False
    for a in (0, 1):            # 穷举 a 的两种取值
        for b in (0, 1):        # 穷举 b 的两种取值，共 2×2 = 4 组
            row = CrossbarRow(cells=[a, b])   # 造一行只有 2 个 cell 的 crossbar：cell0=a, cell1=b
            row.imply(0, 1)                   # 真正执行一次 IMPLY：目的 cell 变成 (¬a)∨b
            got = row.cells[1]                # 模拟器算出来的结果
            expected = imply_truth(a, b)      # 用参考公式算出的"标准答案"
            ok = got == expected              # 两者是否一致
            all_ok &= ok                      # 累积到总标志上
            if ok:
                mark = "OK"
            else:
                mark = "FAIL"
            print(f"{a:>2} {b:>2} | {expected:>8} {got:>4}  "
                  f"{row.steps:>3}   {row.trace}  [{mark}]")

    print("-" * 50)
    if all_ok:
        print("ALL PASS")
    else:
        print("SOME FAILED")
    assert all_ok, "IMPLY truth table verification failed"
    # assert：只要 all_ok 是 False 就直接抛异常中断程序——
    # 这是"硬件最基本的一条指令都不对，后面全白搭"，必须立刻暴露出来。


def verify_false_reset() -> None:
    """验证 FALSE 必须做到两件事：① 真的把目标 cell 清零；② 不管清几个都只算一步。"""
    print()
    print("=" * 50)
    print("[2]  Verifying parallel FALSE reset")
    print("=" * 50)

    row = CrossbarRow(cells=[1, 1, 1, 1])   # 造一行 4 个 cell，初始全是 1
    row.false_reset([0, 2, 3])              # 一次脉冲同时清零下标 0、2、3（下标 1 不动）

    print(f"  cells before reset:  [1, 1, 1, 1]")
    print(f"  cells after  reset:  {row.cells}")
    print(f"  step count:          {row.steps}    (must be 1, not 3)")
    print(f"  trace:               {row.trace}")

    assert row.cells == [0, 1, 0, 0], "FALSE reset wrong target cells"
    # 检查①：0、2、3 被清零，1 号 cell（没被点名）必须保持原值 1
    assert row.steps == 1,            "FALSE must count as one step"
    # 检查②：哪怕清了 3 个 cell，steps 也必须还是 1，这就是"并行"的意义
    print("  [OK] one pulse, one step")


# 一个小小的组合逻辑演示：只用 IMPLY + FALSE 拼出 OR(a, b)。
#   思路：OR(a, b) 本质就是 (¬a) → b，也就是 imply(a_idx, b_idx)；
#   但 IMPLY 会把目的地 b 覆盖掉，我们又想保留 b 原来的值参与运算，
#   所以借用一个额外的工作 cell w 当"中转站"：
#       w := 0                # 第 1 步 FALSE：先把 w 清零
#       w := a -> w  = ¬a     # 第 2 步 IMPLY：IMPLY 打进一个 0 cell 就是取反，w 现在存的是 ¬a
#       b := w -> b  = a ∨ b  # 第 3 步 IMPLY：把 ¬a 再 IMPLY 进 b，得到 (¬¬a)∨b = a∨b
#   cell 布局：cells = [a, b, w]，下标依次是 [0, 1, 2]

def build_or(a: int, b: int) -> tuple[int, int, list[str]]:
    """返回 (or 的结果, 用了几步, 执行轨迹)——用 3 条 IMPLY/FALSE 指令拼出 OR(a, b)。"""
    row = CrossbarRow(cells=[a, b, 0])   # 初始布局：cell0=a, cell1=b, cell2=w（先占位，值随便）
    row.false_reset([2])                 # 第 1 步：w := 0（真正把 w 清干净）
    row.imply(0, 2)                      # 第 2 步：w := (¬a)∨w = (¬a)∨0 = ¬a
    row.imply(2, 1)                      # 第 3 步：b := (¬w)∨b = (¬¬a)∨b = a∨b
    return row.cells[1], row.steps, row.trace
    # 结果存在 cell1（也就是 b 原来的位置），一共花了 row.steps 步


def verify_or() -> None:
    """穷举 a、b 的全部 4 种取值，验证 build_or() 拼出来的电路真的算的是 OR。"""
    print()
    print("=" * 50)
    print("[3]  Composite demo: OR(a, b) in 3 IMPLY/FALSE steps")
    print("=" * 50)
    print(f"{'a':>2} {'b':>2} | {'expected':>8} {'got':>4}  steps")
    print("-" * 40)
    all_ok = True
    for a in (0, 1):
        for b in (0, 1):
            got, steps, _ = build_or(a, b)   # 跑一遍拼出来的 3 步小程序
            expected = a | b                  # Python 原生的 OR，当"标准答案"
            ok = got == expected
            all_ok &= ok
            if ok:
                mark = "OK"
            else:
                mark = "FAIL"
            print(f"{a:>2} {b:>2} | {expected:>8} {got:>4}  {steps:>4}  [{mark}]")
    print("-" * 40)
    if all_ok:
        print("ALL PASS")
    else:
        print("SOME FAILED")
    assert all_ok


if __name__ == "__main__":
    # 只有直接 `python3 imply_sim.py` 运行这个文件时才会执行下面这几行；
    # 被 compile.py 之类的脚本 import 时不会触发（这是 Python 的标准写法）。
    verify_imply()          # 先验证最底层的硬件指令：IMPLY 本身对不对
    verify_false_reset()    # 再验证 FALSE 的并行清零语义对不对
    verify_or()             # 最后验证"用底层指令拼高层逻辑"这件事本身也是对的
    print("\nDemo complete.")
