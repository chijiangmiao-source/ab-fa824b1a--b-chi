"""Büchi 包含性判定与输入校验测试。

覆盖：
- 明确包含 / 不包含的经典例子
- 反例 lasso 可逐字符重放且语义正确
- 左侧仅经非确定分支进入接受环
- 输入校验：缺失迁移、悬空引用、重复定义、状态上限、非 ASCII 等
- 稳定排序：同一输入反复运行结论与反例完全一致
- 随机自动机差分：与 Kosaraju 独立参照实现对比
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.buchi import (  # noqa: E402
    Automaton,
    check_inclusion,
    validate_payload,
)


def make_auto(name, alphabet, states, initial, accepting, table, det=False):
    transitions = {}
    for (s, a), targets in table.items():
        if isinstance(targets, str):
            targets = [targets]
        transitions[(s, a)] = tuple(targets)
    return Automaton(
        name=name,
        alphabet=tuple(alphabet),
        states=tuple(states),
        initial=initial,
        accepting=frozenset(accepting),
        transitions=transitions,
        deterministic=det,
    )


def replay_and_assert(testcase, left, right, result):
    """逐字符重放反例，验证其确为 L(left)\\L(right) 中的 ω-字。"""
    testcase.assertFalse(result.included)
    ce = result.counterexample
    testcase.assertIsNotNone(ce)
    testcase.assertTrue(len(ce.cycle_letters) > 0)

    # 前缀链长度 = 前缀字符 + 1
    testcase.assertEqual(
        len(ce.left_prefix_states), len(ce.prefix_letters) + 1
    )
    testcase.assertEqual(
        len(ce.right_prefix_states), len(ce.prefix_letters) + 1
    )
    # 环链首尾同态，长度 = 环字符 + 1
    testcase.assertEqual(len(ce.left_cycle_states), len(ce.cycle_letters) + 1)
    testcase.assertEqual(
        len(ce.right_cycle_states), len(ce.cycle_letters) + 1
    )
    testcase.assertEqual(ce.left_cycle_states[0], ce.left_cycle_states[-1])
    testcase.assertEqual(ce.right_cycle_states[0], ce.right_cycle_states[-1])

    def check_edges(letters, lchain, rchain, l0, r0):
        testcase.assertEqual(lchain[0], l0)
        testcase.assertEqual(rchain[0], r0)
        for i, ch in enumerate(letters):
            testcase.assertIn(
                lchain[i + 1], left.successors(lchain[i], ch)
            )
            testcase.assertEqual(
                (rchain[i + 1],), right.successors(rchain[i], ch)
            )
        return lchain[-1], rchain[-1]

    lp, rp = check_edges(
        ce.prefix_letters,
        ce.left_prefix_states,
        ce.right_prefix_states,
        left.initial,
        right.initial,
    )
    check_edges(
        ce.cycle_letters,
        ce.left_cycle_states,
        ce.right_cycle_states,
        lp,
        rp,
    )

    # 环上左侧必须出现接受态（无穷次访问）
    testcase.assertTrue(
        any(s in left.accepting for s in ce.left_cycle_states[:-1])
    )
    # 环上右侧绝不能出现接受态（仅有限次）
    testcase.assertFalse(
        any(s in right.accepting for s in ce.right_cycle_states[:-1])
    )


class InclusionTests(unittest.TestCase):
    def test_equal_languages_included(self):
        # 两侧相同：单状态、a 自环、接受
        left = make_auto("L", "a", ["q"], "q", {"q"}, {("q", "a"): "q"})
        right = make_auto(
            "R", "a", ["q"], "q", {"q"}, {("q", "a"): "q"}, det=True
        )
        result = check_inclusion(left, right)
        self.assertTrue(result.included)
        self.assertIsNone(result.counterexample)

    def test_not_included_gives_replayable_lasso(self):
        # 左：a^ω 被接受；右：同一结构但不接受 → 不包含
        left = make_auto("L", "a", ["q"], "q", {"q"}, {("q", "a"): "q"})
        right = make_auto(
            "R", "a", ["q"], "q", set(), {("q", "a"): "q"}, det=True
        )
        result = check_inclusion(left, right)
        replay_and_assert(self, left, right, result)
        self.assertEqual(result.counterexample.prefix_letters, ())
        self.assertEqual(result.counterexample.cycle_letters, ("a",))

    def test_finite_appearance_of_right_accepting_still_counterexample(self):
        # 右自动机：初态接受，读 a 后进入非接受自环。
        # a^ω 不被右接受（接受态仅出现有限次），左接受 a^ω → 反例
        left = make_auto("L", "a", ["q"], "q", {"q"}, {("q", "a"): "q"})
        right = make_auto(
            "R",
            "a",
            ["q0", "q1"],
            "q0",
            {"q0"},
            {("q0", "a"): "q1", ("q1", "a"): "q1"},
            det=True,
        )
        result = check_inclusion(left, right)
        replay_and_assert(self, left, right, result)
        # 前缀先经过右侧接受态 q0，再进入非接受子图
        self.assertEqual(
            result.counterexample.right_prefix_states, ("q0", "q1")
        )

    def test_nondeterministic_left_branch_into_accepting_loop(self):
        # 左：q0 读 a 可去 q1（接受自环）或 q2（非接受死路）。
        # 只有非确定地选择 q1 分支才接受 a^ω。
        # 右完全不接受 → 必须报反例，且反例走 q1 分支。
        left = make_auto(
            "L",
            "a",
            ["q0", "q1", "q2"],
            "q0",
            {"q1"},
            {
                ("q0", "a"): ["q1", "q2"],
                ("q1", "a"): ["q1"],
                ("q2", "a"): ["q2"],
            },
        )
        right = make_auto(
            "R",
            "a",
            ["r"],
            "r",
            set(),
            {("r", "a"): "r"},
            det=True,
        )
        result = check_inclusion(left, right)
        replay_and_assert(self, left, right, result)
        self.assertIn("q1", result.counterexample.left_cycle_states)

    def test_nondeterministic_branch_when_included(self):
        # 左有非确定分支，但所有分支语言都被右接受 → 包含，
        # 不得生成伪造反例。
        left = make_auto(
            "L",
            "ab",
            ["q0", "q1"],
            "q0",
            {"q1"},
            {
                ("q0", "a"): ["q0", "q1"],
                ("q0", "b"): ["q1"],
                ("q1", "a"): ["q1"],
                ("q1", "b"): ["q1"],
            },
        )
        right = make_auto(
            "R",
            "ab",
            ["r"],
            "r",
            {"r"},
            {("r", "a"): "r", ("r", "b"): "r"},
            det=True,
        )
        result = check_inclusion(left, right)
        self.assertTrue(result.included)
        self.assertIsNone(result.counterexample)

    def test_two_letter_language_subset(self):
        # 左：仅接受含无穷多个 a 的 {a,b} 字（q0 非接受 --b-->q0, a->q1 接受）
        # 右：接受所有字（单状态接受）→ 包含
        left = make_auto(
            "L",
            "ab",
            ["q0", "q1"],
            "q0",
            {"q1"},
            {
                ("q0", "a"): ["q1"],
                ("q0", "b"): ["q0"],
                ("q1", "a"): ["q1"],
                ("q1", "b"): ["q1"],
            },
        )
        right = make_auto(
            "R",
            "ab",
            ["r"],
            "r",
            {"r"},
            {("r", "a"): "r", ("r", "b"): "r"},
            det=True,
        )
        self.assertTrue(check_inclusion(left, right).included)
        # 反向：右要求无穷多个 a，左是“所有字”（两状态都接受）……
        # 构造左=所有字，右=无穷a，则 b^ω 是反例
        allwords = make_auto(
            "L",
            "ab",
            ["q"],
            "q",
            {"q"},
            {("q", "a"): ["q"], ("q", "b"): ["q"]},
        )
        result = check_inclusion(allwords, left)
        # left 本身要求无穷 a，b^ω 不接受 → 不包含
        replay_and_assert(self, allwords, left, result)

    def test_deterministic_stable_output(self):
        left = make_auto(
            "L",
            "ab",
            ["q0", "q1", "q2"],
            "q0",
            {"q2"},
            {
                ("q0", "a"): ["q1", "q2"],
                ("q0", "b"): ["q0"],
                ("q1", "a"): ["q2"],
                ("q1", "b"): ["q1"],
                ("q2", "a"): ["q2"],
                ("q2", "b"): ["q2"],
            },
        )
        right = make_auto(
            "R",
            "ab",
            ["r0", "r1"],
            "r0",
            {"r1"},
            {
                ("r0", "a"): "r0",
                ("r0", "b"): "r1",
                ("r1", "a"): "r1",
                ("r1", "b"): "r1",
            },
            det=True,
        )
        first = check_inclusion(left, right)
        for _ in range(10):
            again = check_inclusion(left, right)
            self.assertEqual(again.included, first.included)
            self.assertEqual(again.counterexample, first.counterexample)


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


def base_payload():
    return {
        "alphabet": "ab",
        "left": {
            "states": "q0 q1",
            "initial": "q0",
            "accepting": "q1",
            "transitions": [
                {"source": "q0", "letter": "a", "target": "q1"},
                {"source": "q0", "letter": "b", "target": "q0"},
                {"source": "q1", "letter": "a", "target": "q1"},
                {"source": "q1", "letter": "b", "target": "q1"},
            ],
        },
        "right": {
            "states": "r",
            "initial": "r",
            "accepting": "r",
            "transitions": [
                {"source": "r", "letter": "a", "target": "r"},
                {"source": "r", "letter": "b", "target": "r"},
            ],
        },
    }


class ValidationTests(unittest.TestCase):
    def test_valid_payload(self):
        left, right, errors = validate_payload(base_payload())
        self.assertEqual(errors, [])
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)

    def test_missing_transitions_listed_all_at_once(self):
        payload = base_payload()
        # 删除右侧两条迁移，应一次报出两条缺失
        payload["right"]["transitions"] = []
        _, _, errors = validate_payload(payload)
        missing = [e for e in errors if "缺少迁移" in e]
        self.assertEqual(len(missing), 2)

    def test_dangling_reference(self):
        payload = base_payload()
        payload["right"]["transitions"][0]["target"] = "rx"
        payload["left"]["initial"] = "qx"
        _, _, errors = validate_payload(payload)
        joined = "\n".join(errors)
        self.assertIn("rx", joined)
        self.assertIn("qx", joined)
        # 旧结论不得产生：校验失败不返回自动机
        self.assertIn("悬空引用", joined)

    def test_duplicate_transition_reference(self):
        payload = base_payload()
        # 右侧同一 (状态,字母) 两条不同目标 → 重复/多条迁移
        payload["right"]["transitions"].append(
            {"source": "r", "letter": "a", "target": "r2"}
        )
        payload["right"]["states"] = "r r2"
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("重复" in e or "多条" in e for e in errors))

    def test_duplicate_state_definition(self):
        payload = base_payload()
        payload["right"]["states"] = "r r"
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("重复" in e for e in errors))

    def test_too_many_states_boundary(self):
        # 8 个状态合法，9 个拒绝
        payload = base_payload()
        states = [f"s{i}" for i in range(8)]
        payload["right"] = {
            "states": " ".join(states),
            "initial": "s0",
            "accepting": "",
            "transitions": [
                {"source": s, "letter": ch, "target": "s0"}
                for s in states
                for ch in "ab"
            ],
        }
        _, _, errors = validate_payload(payload)
        self.assertEqual(errors, [])

        payload["right"]["states"] = " ".join(f"s{i}" for i in range(9))
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("超过上限 8" in e for e in errors))

    def test_non_ascii_alphabet(self):
        payload = base_payload()
        payload["alphabet"] = "aé"
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("ASCII" in e for e in errors))

    def test_duplicate_alphabet_letter(self):
        payload = base_payload()
        payload["alphabet"] = "aa"
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("重复" in e for e in errors))

    def test_empty_alphabet(self):
        payload = base_payload()
        payload["alphabet"] = ""
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("字母表不能为空" in e for e in errors))

    def test_accepting_dangling(self):
        payload = base_payload()
        payload["left"]["accepting"] = "q9"
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("q9" in e and "接受态" in e for e in errors))

    def test_letter_outside_alphabet(self):
        payload = base_payload()
        payload["left"]["transitions"][0]["letter"] = "c"
        _, _, errors = validate_payload(payload)
        self.assertTrue(any("字母表外" in e for e in errors))

    def test_all_errors_returned_together(self):
        # 同时制造多个互不相同的问题，确认一次列全
        payload = base_payload()
        payload["left"]["states"] = ""
        payload["right"]["initial"] = ""
        payload["right"]["transitions"] = []
        _, _, errors = validate_payload(payload)
        self.assertGreaterEqual(len(errors), 3)


# ---------------------------------------------------------------------------
# 随机差分测试：独立 Kosaraju 参照实现
# ---------------------------------------------------------------------------


def reference_included(left, right):
    """独立参照：全图可达 + 删去右接受态后的 Kosaraju SCC 判定。"""
    nodes = [(l, r) for l in left.states for r in right.states]

    def succ(node):
        l, r = node
        out = []
        for ch in left.alphabet:
            for r2 in right.successors(r, ch):
                for l2 in left.successors(l, ch):
                    out.append((l2, r2))
        return sorted(set(out))

    # 全图可达
    start = (left.initial, right.initial)
    reachable = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for v in succ(u):
            if v not in reachable:
                reachable.add(v)
                stack.append(v)

    # H：右侧非接受态闭子图
    h_nodes = {n for n in nodes if n[1] not in right.accepting}
    h_reach = {n for n in reachable if n in h_nodes}

    # Kosaraju 第一遍：H 内 DFS 结束序
    visited = set()
    order = []
    for root in sorted(h_reach):
        if root in visited:
            continue
        stack = [(root, iter(sorted(succ(root))))]
        visited.add(root)
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if nxt in h_reach and nxt not in visited:
                    visited.add(nxt)
                    stack.append((nxt, iter(sorted(succ(nxt)))))
                    advanced = True
                    break
            if not advanced:
                order.append(node)
                stack.pop()

    # 逆图
    rev = {n: [] for n in h_reach}
    for u in h_reach:
        for v in succ(u):
            if v in h_reach:
                rev[v].append(u)

    assigned = set()
    for root in reversed(order):
        if root in assigned:
            continue
        comp = set()
        stack = [root]
        assigned.add(root)
        while stack:
            u = stack.pop()
            comp.add(u)
            for v in rev[u]:
                if v not in assigned:
                    assigned.add(v)
                    stack.append(v)
        # 含环：多点 SCC 必有环；单点需子图内自环
        has_cycle = len(comp) > 1
        if not has_cycle:
            only = next(iter(comp))
            has_cycle = any(v == only for v in succ(only) if v in h_reach)
        if has_cycle and any(l in left.accepting for l, _ in comp):
            return False  # 发现反例
    return True


class RandomDifferentialTests(unittest.TestCase):
    def test_random_automata_against_reference(self):
        rng = random.Random(20260930)
        letters = ("a", "b")
        checked = 0
        for trial in range(400):
            nL = rng.randint(1, 4)
            nR = rng.randint(1, 4)
            ls = [f"l{i}" for i in range(nL)]
            rs = [f"r{i}" for i in range(nR)]

            def random_nfa(states, sparse):
                table = {}
                for s in states:
                    for ch in letters:
                        if sparse and rng.random() < 0.3:
                            continue
                        k = rng.randint(1, 1 if sparse else 2)
                        table[(s, ch)] = tuple(
                            rng.sample(states, k=min(k, len(states)))
                        )
                return table

            ltab = random_nfa(ls, sparse=True)
            # 右侧必须完备确定
            rtab = {
                (s, ch): (rng.choice(rs),)
                for s in rs
                for ch in letters
            }
            left = Automaton(
                "L",
                letters,
                tuple(ls),
                ls[0],
                frozenset(rng.sample(ls, k=rng.randint(0, len(ls)))),
                ltab,
                deterministic=False,
            )
            right = Automaton(
                "R",
                letters,
                tuple(rs),
                rs[0],
                frozenset(rng.sample(rs, k=rng.randint(0, len(rs)))),
                rtab,
                deterministic=True,
            )
            result = check_inclusion(left, right)
            expected = reference_included(left, right)
            self.assertEqual(
                result.included,
                expected,
                msg=f"trial {trial} 不一致",
            )
            if not result.included:
                replay_and_assert(self, left, right, result)
            checked += 1
        self.assertEqual(checked, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
