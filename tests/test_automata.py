"""核心算法测试：包含、反例、非确定分支、输入校验边界。"""

from __future__ import annotations

import random
import unittest
from typing import Dict, List, Optional, Set, Tuple

from app.core.automata import (
    Automaton,
    Counterexample,
    TransitionStep,
    ValidationError,
    build_automaton,
    check_inclusion,
    parse_alphabet,
)


def make(
    name: str,
    alphabet: str,
    states: List[str],
    initial: str,
    accepting: List[str],
    transitions: List[str],
    *,
    require_total: bool = False,
) -> Automaton:
    return build_automaton(
        name,
        parse_alphabet(alphabet),
        " ".join(states),
        initial,
        " ".join(accepting),
        "\n".join(transitions),
        require_total=require_total,
    )


def total_right(
    states: List[str],
    initial: str,
    accepting: List[str],
    transitions: List[str],
    alphabet: str = "ab",
) -> Automaton:
    return make("R", alphabet, states, initial, accepting, transitions, require_total=True)


def replay(ce: Counterexample) -> Tuple[List[str], List[str], List[str], List[str]]:
    """重放反例，返回 (左前缀状态, 右前缀状态, 左环状态, 右环状态)。"""
    lp = [ce.prefix[0].left_from] if ce.prefix else []
    rp = [ce.prefix[0].right_from] if ce.prefix else []
    for step in ce.prefix:
        assert step.left_to is not None
        lp.append(step.left_to)
        rp.append(step.right_to)
    lc = [ce.cycle[0].left_from]
    rc = [ce.cycle[0].right_from]
    for step in ce.cycle:
        lc.append(step.left_to)
        rc.append(step.right_to)
    return lp, rp, lc, rc


def assert_valid_counterexample(
    test: unittest.TestCase,
    left: Automaton,
    right: Automaton,
    ce: Counterexample,
) -> None:
    test.assertTrue(ce.cycle, "无限重复环不得为空")
    lp, rp, lc, rc = replay(ce)

    # 前缀与环在节点上首尾相接
    if ce.prefix:
        test.assertEqual((lp[-1], rp[-1]), (lc[0], rc[0]))
    else:
        test.assertEqual((lc[0], rc[0]), (left.initial, right.initial))
    # 环闭合
    test.assertEqual((lc[0], rc[0]), (lc[-1], rc[-1]))

    # 每一步在两个自动机中都是合法迁移
    for step in ce.prefix + ce.cycle:
        test.assertIn(step.left_to, left.successors(step.left_from, step.letter))
        test.assertIn(step.right_to, right.successors(step.right_from, step.letter))

    # 环中：左侧至少经过一个接受态；右侧完全不出现接受态
    test.assertTrue(any(s in left.accepting for s in lc[:-1]))
    test.assertTrue(all(s not in right.accepting for s in rc[:-1]))


class InclusionTests(unittest.TestCase):
    def test_equal_automata_are_contained(self):
        trans = ["q0 a -> q1", "q0 b -> q0", "q1 a -> q1", "q1 b -> q0"]
        left = make("L", "ab", ["q0", "q1"], "q0", ["q1"], trans)
        right = total_right(["q0", "q1"], "q0", ["q1"], trans)
        result = check_inclusion(left, right)
        self.assertTrue(result.contained)
        self.assertIsNone(result.counterexample)

    def test_strict_subset_contained(self):
        # 右语言：所有无穷词（全状态接受）；左语言：a^ω
        right = total_right(["p0"], "p0", ["p0"], ["p0 a -> p0", "p0 b -> p0"])
        left = make("L", "ab", ["q0"], "q0", ["q0"], ["q0 a -> q0"])
        result = check_inclusion(left, right)
        self.assertTrue(result.contained)
        self.assertIsNone(result.counterexample)

    def test_not_contained_simple(self):
        # 右语言：含至少一个 b；左语言：a^ω —— 不包含
        right = total_right(
            ["p0", "p1"],
            "p0",
            ["p1"],
            [
                "p0 a -> p0",
                "p0 b -> p1",
                "p1 a -> p1",
                "p1 b -> p1",
            ],
        )
        left = make("L", "ab", ["q0"], "q0", ["q0"], ["q0 a -> q0", "q0 b -> q0"])
        result = check_inclusion(left, right)
        self.assertFalse(result.contained)
        self.assertIsNotNone(result.counterexample)
        assert_valid_counterexample(self, left, right, result.counterexample)
        self.assertEqual(result.counterexample.cycle_word, "a")

    def test_not_contained_with_finite_prefix(self):
        # 右语言：含至少一个 b，且首个 b 之后不再出现 b（即 b a^ω 型）。
        # 左语言：至少含一个 b（首个 b 后进入接受汇点 q1）。
        # 反例：b b a^ω —— 前缀 bb 经过一次右接受态 p1，再在 (q1, 非接受 p2) 成环。
        right = total_right(
            ["p0", "p1", "p2"],
            "p0",
            ["p1"],
            [
                "p0 a -> p0",
                "p0 b -> p1",
                "p1 a -> p1",
                "p1 b -> p2",
                "p2 a -> p2",
                "p2 b -> p2",
            ],
        )
        left = make(
            "L",
            "ab",
            ["q0", "q1"],
            "q0",
            ["q1"],
            [
                "q0 a -> q0",
                "q0 b -> q1",
                "q1 a -> q1",
                "q1 b -> q1",
            ],
        )
        result = check_inclusion(left, right)
        self.assertFalse(result.contained)
        self.assertIsNotNone(result.counterexample)
        ce = result.counterexample
        assert_valid_counterexample(self, left, right, ce)
        self.assertTrue(ce.prefix_word)  # 必须有非空前缀才能到达接受环
        self.assertIn("b", ce.prefix_word)

    def test_nondeterministic_left_only_branch_reaches_accepting_loop(self):
        # 左侧 q0 --a--> 非接受死分支 q1（a 自环） 与 接受分支 q2（a 自环）。
        # 右侧只能接受有限次 b 后全 a 的词……具体：右接受 p1，p1 读 a 到非接受 p2，
        # p2 在 a 上自环。词 a^ω 下，右路径 q: p0 -a-> p0 永不接受，因此
        # 左接受分支给出反例 a^ω。
        right = total_right(
            ["p0", "p1", "p2"],
            "p0",
            ["p1"],
            [
                "p0 a -> p0",
                "p0 b -> p1",
                "p1 a -> p2",
                "p1 b -> p1",
                "p2 a -> p2",
                "p2 b -> p1",
            ],
        )
        left = make(
            "L",
            "ab",
            ["q0", "q1", "q2"],
            "q0",
            ["q2"],
            [
                "q0 a -> q1 q2",
                "q0 b -> q1",
                "q1 a -> q1",
                "q1 b -> q1",
                "q2 a -> q2",
                "q2 b -> q1",
            ],
        )
        result = check_inclusion(left, right)
        self.assertFalse(result.contained)
        self.assertIsNotNone(result.counterexample)
        ce = result.counterexample
        assert_valid_counterexample(self, left, right, ce)
        # 读完首字符 a 后才进入左侧接受分支，故前缀为 "a"、环为 "a"
        self.assertEqual(ce.prefix_word, "a")
        self.assertEqual(ce.cycle_word, "a")
        # 状态链必须走向接受分支 q2
        self.assertEqual(ce.prefix[-1].left_to, "q2")
        self.assertEqual([s.left_to for s in ce.cycle], ["q2"])

    def test_nondeterministic_left_contained_via_some_branch(self):
        # 左侧非确定：某分支进入接受环，只要右自动机对每个接受分支都能无穷接受 => 包含。
        # 右语言：所有词（p0 接受且完全）；左随便非确定。
        right = total_right(
            ["p0", "p1"], "p0", ["p0", "p1"],
            ["p0 a -> p1", "p0 b -> p0", "p1 a -> p1", "p1 b -> p0"],
        )
        left = make(
            "L", "ab", ["q0", "q1"], "q0", ["q1"],
            ["q0 a -> q0 q1", "q0 b -> q0", "q1 a -> q1", "q1 b -> q1"],
        )
        result = check_inclusion(left, right)
        self.assertTrue(result.contained)
        self.assertIsNone(result.counterexample)

    def test_right_dead_state_does_not_hide_counterexample(self):
        # 右接受态不可达（p1），p0 为非接受死状态：任何左接受词都应判不包含。
        right = total_right(
            ["p0", "p1"], "p0", ["p1"],
            ["p0 a -> p0", "p0 b -> p0", "p1 a -> p1", "p1 b -> p1"],
        )
        left = make("L", "ab", ["q0"], "q0", ["q0"], ["q0 a -> q0", "q0 b -> q0"])
        result = check_inclusion(left, right)
        self.assertFalse(result.contained)
        self.assertIsNotNone(result.counterexample)
        assert_valid_counterexample(self, left, right, result.counterexample)

    def test_prefix_may_cross_right_accepting_finitely_often(self):
        # 右语言：至多含一个 b（读 b 时接受 p1 一次，之后进入非接受死状态 p2）。
        # 左语言含 b a^ω：右侧只能在 p1 接受一次，随后永远停在非接受 p2，
        # 因此不包含 —— 反例前缀恰好经过一次右接受态 p1，再在非接受子图中成环。
        right = total_right(
            ["p0", "p1", "p2"],
            "p0",
            ["p1"],
            [
                "p0 a -> p0",
                "p0 b -> p1",
                "p1 a -> p2",
                "p1 b -> p2",
                "p2 a -> p2",
                "p2 b -> p2",
            ],
        )
        # b a^ω ∈ L(R)
        left_yes = make(
            "L", "ab", ["q0", "q1"], "q0", ["q1"],
            ["q0 a -> q0", "q0 b -> q1", "q1 a -> q1", "q1 b -> q0"],
        )
        # q1 --b--> q0 使 (ba)^ω 接受：q0 b->q1 a->q0 ...，不包含
        result_yes = check_inclusion(left_yes, right)
        self.assertFalse(result_yes.contained)  # (ba)^ω 是左接受词但右侧 b 后进入死区
        self.assertIsNotNone(result_yes.counterexample)
        assert_valid_counterexample(self, left_yes, right, result_yes.counterexample)

    def test_start_state_self_loop_counterexample_nonempty_cycle(self):
        # 乘积初态本身即坏 SCC（左接受自环、右非接受自环），环必须非空。
        right = total_right(["p0"], "p0", [], ["p0 a -> p0", "p0 b -> p0"])
        left = make("L", "ab", ["q0"], "q0", ["q0"], ["q0 a -> q0", "q0 b -> q0"])
        result = check_inclusion(left, right)
        self.assertFalse(result.contained)
        self.assertIsNotNone(result.counterexample)
        ce = result.counterexample
        self.assertEqual(ce.prefix_word, "")
        self.assertEqual(len(ce.cycle), 1)
        assert_valid_counterexample(self, left, right, ce)

    def test_left_no_accepting_runs_is_vacuously_contained(self):
        # 左侧接受态不可达：L(left)=∅，必然包含
        right = total_right(["p0"], "p0", [], ["p0 a -> p0", "p0 b -> p0"])
        left = make("L", "ab", ["q0", "q1"], "q0", ["q1"], ["q0 a -> q0", "q0 b -> q0"])
        result = check_inclusion(left, right)
        self.assertTrue(result.contained)


class ValidationTests(unittest.TestCase):
    def test_right_missing_transitions_all_listed(self):
        with self.assertRaises(ValidationError) as ctx:
            total_right(["p0", "p1"], "p0", ["p1"], [
                "p0 a -> p1",
                # 缺 p0 b、p1 a、p1 b
            ])
        messages = "\n".join(ctx.exception.errors)
        self.assertIn("p0 --b-->", messages)
        self.assertIn("p1 --a-->", messages)
        self.assertIn("p1 --b-->", messages)
        self.assertEqual(len(ctx.exception.errors), 3)

    def test_dangling_and_duplicate_reports_collected_at_once(self):
        with self.assertRaises(ValidationError) as ctx:
            make(
                "L", "ab", ["q0", "q0"], "qx", ["qy"],
                ["q0 a -> qz", "q0 b -> q0 q0"],
            )
        messages = "\n".join(ctx.exception.errors)
        self.assertIn("状态重复声明", messages)
        self.assertIn("初态 'qx' 未在状态列表中声明", messages)
        self.assertIn("接受态 'qy' 未在状态列表中声明", messages)
        self.assertIn("目标状态 'qz' 未声明", messages)
        self.assertIn("重复引用目标 q0", messages)

    def test_right_nondeterministic_transition_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            total_right(["p0", "p1"], "p0", ["p1"], [
                "p0 a -> p0 p1",
                "p0 b -> p0",
                "p1 a -> p1",
                "p1 b -> p1",
            ])
        self.assertTrue(any("必须恰好一条" in e for e in ctx.exception.errors))

    def test_left_may_have_missing_or_multi_transitions(self):
        left = make(
            "L", "ab", ["q0", "q1"], "q0", ["q1"],
            ["q0 a -> q0 q1"],  # 缺 q0 b、q1 全部 —— 左侧允许
        )
        self.assertEqual(left.successors("q0", "a"), ("q0", "q1"))
        self.assertEqual(left.successors("q0", "b"), ())

    def test_state_limit_eight(self):
        with self.assertRaises(ValidationError) as ctx:
            total_right(
                [f"p{i}" for i in range(9)], "p0", [],
                [f"p{i} a -> p{i}\np{i} b -> p{i}" for i in range(9)],
            )
        self.assertTrue(any("超过上限 8" in e for e in ctx.exception.errors))

    def test_bad_alphabet_and_transition_letters(self):
        # 字母表含非 ASCII 字符
        with self.assertRaises(ValidationError):
            total_right(["p0"], "p0", [], ["p0 a -> p0", "p0 b -> p0"], alphabet="aé")
        # 迁移使用字母表外的字母
        with self.assertRaises(ValidationError) as ctx2:
            total_right(["p0"], "p0", [], ["p0 a -> p0", "p0 x -> p0"])
        self.assertTrue(any("不在字母表" in e for e in ctx2.exception.errors))

    def test_alphabet_duplicates_and_empty(self):
        with self.assertRaises(ValidationError) as ctx:
            total_right(["p0"], "p0", [], ["p0 a -> p0"], alphabet="aa")
        self.assertTrue(any("字母表重复" in e for e in ctx.exception.errors))
        with self.assertRaises(ValidationError):
            total_right(["p0"], "p0", [], [], alphabet="")

    def test_malformed_transition_line(self):
        with self.assertRaises(ValidationError) as ctx:
            total_right(["p0"], "p0", [], ["p0 a p0"])
        self.assertTrue(any("格式错误" in e for e in ctx.exception.errors))

    def test_alphabet_parsing(self):
        self.assertEqual(parse_alphabet("ab"), ("a", "b"))
        self.assertEqual(parse_alphabet("a, b"), ("a", "b"))
        self.assertEqual(parse_alphabet("a b"), ("a", "b"))


# ---------------------------------------------------------------------------
# 与独立暴力判定对照的随机属性测试
# ---------------------------------------------------------------------------


def brute_force_not_contained(left: Automaton, right: Automaton) -> Optional[Counterexample]:
    """独立参考实现：朴素嵌套可达性（双 DFS），与生产代码的 SCC 算法无关。

    反例存在 ⇔ 存在从乘积初态可达的节点 u，u[0] 为左接受态、u[1] 为右非接受态，
    且在「右组件全非接受」诱导子图中存在一条从 u 出发、长度 ≥1 回到 u 的行走。
    前缀可在完整乘积图上经过任意多个右接受态。
    """

    start = (left.initial, right.initial)

    def edges(node):
        q, p = node
        out = []
        for a in left.alphabet:
            for q2 in left.successors(q, a):
                for p2 in right.successors(p, a):
                    out.append(((q2, p2), a))
        return out

    # BFS：start 到所有可达节点的一条最短路径（及边标签）
    parent: Dict[Tuple[str, str], Tuple[Tuple[str, str], str]] = {start: (start, "")}
    queue = [start]
    head = 0
    while head < len(queue):
        for dst, a in edges(queue[head]):
            if dst not in parent:
                parent[dst] = (queue[head], a)
                queue.append(dst)
        head += 1

    def path_to(node):
        steps = []
        cur = node
        while cur != start:
            prev, a = parent[cur]
            steps.append((prev, a, cur))
            cur = prev
        steps.reverse()
        return steps

    # 在右全非接受子图中，判定 dst 能否经 ≥1 步回到 dst，并返回边序列。
    # dst 初始标记已访问，但一旦某条边重新指向 dst（含 dst 自环）即找到闭合行走。
    def reaches(src, dst):
        parent: Dict[Tuple[str, str], Tuple[Tuple[str, str], str]] = {}
        visited = {dst}
        stack = [dst]
        found = None
        while stack:
            node = stack.pop()
            for (nxt, a) in edges(node):
                if nxt[1] in right.accepting:
                    continue
                if nxt == dst:  # 发现指向 dst 的边（含 dst 自环）
                    found = (node, a, nxt)
                    stack = []
                    break
                if nxt not in visited:
                    visited.add(nxt)
                    parent[nxt] = (node, a)
                    stack.append(nxt)
        if found is None:
            return None
        # 回溯：dst <- ... <- node
        ring_rev = [found]
        cur = found[0]
        while cur != dst:
            prev, a = parent[cur]
            ring_rev.append((prev, a, cur))
            cur = prev
        ring_rev.reverse()
        return ring_rev

    for u in sorted(n for n in queue if n[0] in left.accepting and n[1] not in right.accepting):
        ring = reaches(u, u)
        if ring is not None:
            mk = lambda t: TransitionStep(t[1], t[0][0], t[2][0], t[0][1], t[2][1])
            return Counterexample(
                [mk(t) for t in path_to(u)],
                [mk(t) for t in ring],
            )
    return None


def random_automata(rng: random.Random) -> Tuple[Automaton, Automaton]:
    alpha = ["a", "b"]
    ls = [f"q{i}" for i in range(rng.randint(1, 3))]
    rs = [f"p{i}" for i in range(rng.randint(1, 3))]

    def random_nd(states, total):
        rows = []
        for s in states:
            for a in alpha:
                if total:
                    k = 1  # 右侧确定：恰好一个目标
                else:
                    k = rng.randint(0, len(states))  # 左侧非确定：0..n 个目标
                if k == 0:
                    continue
                dests = rng.sample(states, k)
                rows.append(f"{s} {a} -> {' '.join(dests)}")
        return rows

    left = make(
        "L", "ab", ls, rng.choice(ls),
        rng.sample(ls, rng.randint(0, len(ls))),
        random_nd(ls, False),
    )
    right = total_right(
        rs, rng.choice(rs),
        rng.sample(rs, rng.randint(0, len(rs))),
        random_nd(rs, True),
    )
    return left, right


class RandomizedEquivalenceTests(unittest.TestCase):
    def test_matches_brute_force(self):
        rng = random.Random(20260930)
        trials = 300
        for t in range(trials):
            left, right = random_automata(rng)
            result = check_inclusion(left, right)
            brute_ce = brute_force_not_contained(left, right)
            self.assertEqual(
                result.contained,
                brute_ce is None,
                msg=f"trial {t}: left={left} right={right}",
            )
            if not result.contained:
                self.assertIsNotNone(result.counterexample)
                assert_valid_counterexample(self, left, right, result.counterexample)


if __name__ == "__main__":
    unittest.main()
