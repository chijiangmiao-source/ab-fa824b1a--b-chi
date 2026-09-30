"""Büchi 自动机的数据模型、输入校验与语言包含性判定。

判定方法（经典的基于乘积图的 Büchi 包含判定，L(A) ⊆ L(B)）：

1. 构造乘积图，节点为 ``(q, p)``（左状态 q，右状态 p），按 ``(q, p, 字母)``
   稳定排序展开后继，保证搜索过程可复现。
2. 先处理「右侧仍可经过接受态」的前缀：从乘积初态在完整可达乘积图上搜索
   （前缀沿途允许经过任意多个右接受态），候选环入口即图中任意可达节点。
3. 再在右组件全为非接受态的诱导子图上计算可达闭包与强连通分量（SCC），
   寻找可闭合且含左接受态的 SCC；找到即为反例：
   前缀（从初态到该 SCC）+ 无限重复环（SCC 内绕行一周，途中经过左接受态）。

全程对完整状态空间做搜索（Tarjan SCC），不使用有限抽样或单一路径。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

MAX_STATES = 8
MAX_WORD_LEN = 16
_STATE_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")


class ValidationError(Exception):
    """输入校验错误，携带全部问题（一次列全，而非遇到第一个即停止）。"""

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class Automaton:
    """一个（可能非确定的）Büchi 自动机。

    transitions: state -> letter -> 去重后的后继状态元组（已排序）。
    """

    name: str
    alphabet: Tuple[str, ...]
    states: Tuple[str, ...]
    initial: str
    accepting: FrozenSet[str]
    transitions: Dict[str, Dict[str, Tuple[str, ...]]]

    def successors(self, state: str, letter: str) -> Tuple[str, ...]:
        return self.transitions.get(state, {}).get(letter, ())


@dataclass
class TransitionStep:
    """反例重放中的一步迁移。"""

    letter: str
    left_from: str
    left_to: str
    right_from: str
    right_to: str


@dataclass
class Counterexample:
    """可逐字符重放的反例：有限前缀 + 无限重复环。"""

    prefix: List[TransitionStep] = field(default_factory=list)
    cycle: List[TransitionStep] = field(default_factory=list)

    @property
    def prefix_word(self) -> str:
        return "".join(step.letter for step in self.prefix)

    @property
    def cycle_word(self) -> str:
        return "".join(step.letter for step in self.cycle)

    def as_dict(self) -> dict:
        return {
            "prefix_word": self.prefix_word,
            "cycle_word": self.cycle_word,
            "prefix": [_step_dict(s) for s in self.prefix],
            "cycle": [_step_dict(s) for s in self.cycle],
        }


def _step_dict(step: TransitionStep) -> dict:
    return {
        "letter": step.letter,
        "left_from": step.left_from,
        "left_to": step.left_to,
        "right_from": step.right_from,
        "right_to": step.right_to,
    }


@dataclass
class InclusionResult:
    contained: bool
    counterexample: Optional[Counterexample] = None
    stats: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "contained": self.contained,
            "counterexample": self.counterexample.as_dict() if self.counterexample else None,
            "stats": self.stats,
        }


# ---------------------------------------------------------------------------
# 输入解析与校验
# ---------------------------------------------------------------------------


def _split_tokens(raw: Optional[str]) -> List[str]:
    if raw is None:
        return []
    return [tok for tok in re.split(r"[\s,]+", raw.strip()) if tok]


def parse_alphabet(raw: str) -> Tuple[str, ...]:
    """解析共同 ASCII 字母表：允许 "ab"、"a,b"、"a b" 等写法。"""

    cleaned = raw.strip()
    if "," in cleaned or re.search(r"\s", cleaned):
        tokens = _split_tokens(cleaned)
    else:
        tokens = list(cleaned)
    return tuple(tokens)


def build_automaton(
    name: str,
    alphabet: Sequence[str],
    states_raw: str,
    initial_raw: str,
    accepting_raw: str,
    transitions_raw: str,
    *,
    require_total: bool = False,
) -> Automaton:
    """构建并校验一个自动机。

    收集全部错误后一次性抛出 :class:`ValidationError`，便于页面一次列全。
    右侧（``require_total=True``）必须为每个状态和字母恰好定义一条迁移。
    """

    label = name
    errors: List[str] = []

    states = _split_tokens(states_raw)
    initial = initial_raw.strip()
    accepting = set(_split_tokens(accepting_raw))

    # --- 状态声明 ---
    seen: Set[str] = set()
    duplicates: List[str] = []
    for state in states:
        if not _STATE_RE.match(state):
            errors.append(f"{label}：状态名 {state!r} 非法（允许 1–16 位字母、数字、下划线）")
        if state in seen:
            duplicates.append(state)
        seen.add(state)
    if duplicates:
        errors.append(f"{label}：状态重复声明：{', '.join(sorted(set(duplicates)))}")
    state_set = set(states)
    if not states:
        errors.append(f"{label}：至少需要一个状态")
    if len(states) > MAX_STATES:
        errors.append(f"{label}：状态数 {len(states)} 超过上限 {MAX_STATES}")

    # --- 初态 / 接受态 ---
    if not initial:
        errors.append(f"{label}：缺少初态")
    elif initial not in state_set:
        errors.append(f"{label}：初态 {initial!r} 未在状态列表中声明（悬空引用）")
    for state in sorted(accepting):
        if state not in state_set:
            errors.append(f"{label}：接受态 {state!r} 未在状态列表中声明（悬空引用）")

    # --- 字母表 ---
    alpha = list(alphabet)
    alpha_seen: Set[str] = set()
    alpha_dups: List[str] = []
    for letter in alpha:
        if letter in alpha_seen:
            alpha_dups.append(letter)
        if not (len(letter) == 1 and 32 <= ord(letter) <= 126 and letter != " "):
            errors.append(f"{label}：字母 {letter!r} 不是单个可打印 ASCII 字符（不含空格）")
        alpha_seen.add(letter)
    if alpha_dups:
        errors.append(f"{label}：字母表重复：{', '.join(alpha_dups)}")
    if not alpha:
        errors.append(f"{label}：字母表为空")
    if len(alpha) > MAX_WORD_LEN:
        errors.append(f"{label}：字母表超过 {MAX_WORD_LEN} 个字符")

    # --- 迁移 ---
    # transitions[state][letter] 保留出现顺序，稍后去重并排序。
    raw_trans: Dict[str, Dict[str, List[str]]] = {}
    for lineno, line in enumerate(transitions_raw.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("->")]
        if len(parts) != 2:
            errors.append(
                f"{label}：第 {lineno} 行迁移格式错误，应为 '状态 字母 -> 目标'（实际：{line!r}）"
            )
            continue
        lhs, rhs = parts
        lhs_tokens = _split_tokens(lhs.replace(",", " "))
        rhs_tokens = _split_tokens(rhs.replace(",", " "))
        if len(lhs_tokens) != 2:
            errors.append(
                f"{label}：第 {lineno} 行箭头左侧必须恰为 '状态 字母'（实际：{line!r}）"
            )
            continue
        src, letter_sym = lhs_tokens
        if not rhs_tokens:
            errors.append(f"{label}：第 {lineno} 行缺少目标状态（实际：{line!r}）")
            continue

        if src not in state_set:
            errors.append(f"{label}：第 {lineno} 行源状态 {src!r} 未声明（悬空引用）")
        if letter_sym not in alpha_seen:
            errors.append(f"{label}：第 {lineno} 行字母 {letter_sym!r} 不在字母表中")
        for dst in rhs_tokens:
            if dst not in state_set:
                errors.append(f"{label}：第 {lineno} 行目标状态 {dst!r} 未声明（悬空引用）")

        raw_trans.setdefault(src, {}).setdefault(letter_sym, [])
        for dst in rhs_tokens:
            raw_trans[src][letter_sym].append(dst)

    # 迁移表内部的重复后继 / 重复整行
    transitions: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    for src in sorted(raw_trans):
        transitions[src] = {}
        for letter_sym in sorted(raw_trans[src]):
            dests = raw_trans[src][letter_sym]
            dup_dests = sorted({d for d in dests if dests.count(d) > 1})
            if dup_dests:
                errors.append(
                    f"{label}：迁移 {src} --{letter_sym}--> 重复引用目标 {', '.join(dup_dests)}"
                )
            transitions[src][letter_sym] = tuple(sorted(set(dests)))

    # 完整性 / 确定性（仅强制右侧 require_total=True）：
    # - 右侧每个 (状态, 字母) 必须恰好定义一条迁移（缺失即报错，多目标违反确定性）；
    # - 左侧为非确定自动机：允许多目标，也允许不写（解释为无后继分支）；
    # - 同一对的重复目标已在上方作为「重复引用」报错。
    if require_total and state_set and alpha_seen:
        for src in sorted(state_set):
            for letter_sym in sorted(alpha_seen):
                dests = transitions.get(src, {}).get(letter_sym, ())
                if not dests:
                    errors.append(
                        f"{label}：缺少迁移 {src} --{letter_sym}-->（每个状态和字母都须恰好定义一条迁移）"
                    )
                elif len(dests) > 1:
                    errors.append(
                        f"{label}：迁移 {src} --{letter_sym}--> 有 {len(dests)} 个目标"
                        f"（{', '.join(dests)}），右侧必须恰好一条（确定）"
                    )

    if errors:
        # 去重后保持稳定顺序
        unique: List[str] = []
        for err in errors:
            if err not in unique:
                unique.append(err)
        raise ValidationError(unique)

    # 补全空迁移表（左侧允许非完全，但已校验过的场景下这里都存在）
    for src in states:
        transitions.setdefault(src, {})

    return Automaton(
        name=name,
        alphabet=tuple(sorted(alpha)),
        states=tuple(states),
        initial=initial,
        accepting=frozenset(accepting),
        transitions=transitions,
    )



# ---------------------------------------------------------------------------
# 语言包含性判定
# ---------------------------------------------------------------------------


@dataclass
class _ProductEdge:
    src: Tuple[str, str]
    dst: Tuple[str, str]
    letter: str
    left_to: str
    right_to: str


def check_inclusion(left: Automaton, right: Automaton) -> InclusionResult:
    """判定 L(left) ⊆ L(right)；不包含时构造可重放反例。"""

    if left.alphabet != right.alphabet:
        raise ValidationError(
            [f"两侧字母表不一致：左 {''.join(left.alphabet)!r} / 右 {''.join(right.alphabet)!r}"]
        )

    alphabet = left.alphabet
    left_acc = left.accepting
    right_acc = right.accepting

    start = (left.initial, right.initial)

    # --- 1. 可达乘积图（BFS，节点与后继均稳定排序）---
    # adjacency 按 (letter, right_to, left_to) 排序后存储，保证遍历确定性。
    adj: Dict[Tuple[str, str], List[_ProductEdge]] = {}
    queue: List[Tuple[str, str]] = [start]
    enqueued = {start}
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        q, p = node
        edges: List[_ProductEdge] = []
        for letter in alphabet:  # 字母按字母表顺序
            for q2 in left.successors(q, letter):  # 后继已排序
                for p2 in right.successors(p, letter):
                    edges.append(
                        _ProductEdge(
                            src=node,
                            dst=(q2, p2),
                            letter=letter,
                            left_to=q2,
                            right_to=p2,
                        )
                    )
        edges.sort(key=lambda e: (e.letter, e.right_to, e.left_to))
        adj[node] = edges
        for edge in edges:
            if edge.dst not in enqueued:
                enqueued.add(edge.dst)
                queue.append(edge.dst)

    reachable_nodes = set(queue)

    # --- 2. 前缀区域：整个可达乘积图 ---
    # 前缀沿途可经过任意多个右接受态（接受态只允许出现有限次，无限重复发生在环外）。
    prefix_nodes = reachable_nodes

    # --- 3. 环区域：右组件全为非接受态的诱导子图 ---
    nonacc_nodes = {n for n in reachable_nodes if n[1] not in right_acc}

    # 在 nonacc 子图上以稳定顺序做 Tarjan SCC
    index_of: Dict[Tuple[str, str], int] = {}
    lowlink: Dict[Tuple[str, str], int] = {}
    on_stack: Set[Tuple[str, str]] = set()
    tarjan_stack: List[Tuple[str, str]] = []
    sccs: List[List[Tuple[str, str]]] = []
    counter = 0

    ordered_nodes = sorted(nonacc_nodes)

    def neighbors(node: Tuple[str, str]) -> List[Tuple[str, str]]:
        return [e.dst for e in adj[node] if e.dst in nonacc_nodes]

    for root in ordered_nodes:
        if root in index_of:
            continue
        work: List[Tuple[Tuple[str, str], int]] = [(root, 0)]
        index_of[root] = lowlink[root] = counter
        counter += 1
        tarjan_stack.append(root)
        on_stack.add(root)
        while work:
            node, ni = work[-1]
            nbrs = neighbors(node)
            if ni < len(nbrs):
                nxt = nbrs[ni]
                work[-1] = (node, ni + 1)
                if nxt not in index_of:
                    index_of[nxt] = lowlink[nxt] = counter
                    counter += 1
                    tarjan_stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    lowlink[node] = min(lowlink[node], index_of[nxt])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == index_of[node]:
                    comp: List[Tuple[str, str]] = []
                    while True:
                        w = tarjan_stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    sccs.append(comp)

    bad_scc: Optional[Set[Tuple[str, str]]] = None
    # SCC 按其中最小节点排序，保证选取稳定
    sccs.sort(key=lambda comp: min(comp))
    for comp in sccs:
        comp_set = set(comp)
        has_left_acc = any(n[0] in left_acc for n in comp)
        # 可闭合：分量内至少一条内边（自环或多节点分量天然存在环）
        has_internal_edge = any(
            e.dst in comp_set for n in comp for e in adj[n]
        )
        if has_left_acc and has_internal_edge:
            bad_scc = comp_set
            break

    stats = {
        "product_nodes": len(reachable_nodes),
        "product_edges": sum(len(edges) for edges in adj.values()),
        "prefix_nodes": len(prefix_nodes),
        "nonaccepting_nodes": len(nonacc_nodes),
        "scc_count": len(sccs),
    }

    if bad_scc is None:
        return InclusionResult(contained=True, counterexample=None, stats=stats)

    counterexample = _build_counterexample(
        start=start,
        adj=adj,
        prefix_nodes=prefix_nodes,
        bad_scc=bad_scc,
        left_acc=left_acc,
    )
    return InclusionResult(contained=False, counterexample=counterexample, stats=stats)


def _shortest_path(
    start: Tuple[str, str],
    targets: Set[Tuple[str, str]],
    allowed: Set[Tuple[str, str]],
    adj: Dict[Tuple[str, str], List[_ProductEdge]],
    *,
    allow_zero: bool = True,
) -> Optional[List[_ProductEdge]]:
    """在 allowed 节点集上按稳定顺序 BFS，求 start 到任一 target 的最短边序列。

    ``allow_zero=False`` 且 start 自身属于 targets 时，求一条非空闭合行走
    （用于保证无限重复环至少含一条迁移）。
    """

    if start in targets and allow_zero:
        return []
    prev: Dict[Tuple[str, str], _ProductEdge] = {}
    visited: Set[Tuple[str, str]] = set()
    queue: List[Tuple[str, str]] = []
    if allow_zero:
        visited.add(start)
        queue.append(start)
    else:
        # start 保持「未访问」，允许经由一条非空路径重新回到它（求最短闭合环）
        for edge in adj[start]:
            nxt = edge.dst
            if nxt in allowed and nxt not in visited:
                visited.add(nxt)
                prev[nxt] = edge
                queue.append(nxt)
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        if node in targets:
            path: List[_ProductEdge] = []
            cur = node
            while True:
                e = prev[cur]
                path.append(e)
                cur = e.src
                if cur == start:
                    break
            path.reverse()
            return path
        for edge in adj[node]:
            nxt = edge.dst
            if nxt not in allowed or nxt in visited:
                continue
            visited.add(nxt)
            prev[nxt] = edge
            queue.append(nxt)
    return None


def _build_counterexample(
    *,
    start: Tuple[str, str],
    adj: Dict[Tuple[str, str], List[_ProductEdge]],
    prefix_nodes: Set[Tuple[str, str]],
    bad_scc: Set[Tuple[str, str]],
    left_acc: FrozenSet[str],
) -> Counterexample:
    # 1) 前缀：start -> 坏 SCC（在整个可达乘积图内，允许经过右接受态）
    pre_edges = _shortest_path(start, bad_scc, prefix_nodes, adj)
    assert pre_edges is not None, "坏 SCC 必须从前缀可达"
    entry = pre_edges[-1].dst if pre_edges else start

    # 2) 环：entry 出发，先走到某个左接受节点，再返回 entry；
    #    环必须非空（无限重复至少一条迁移）。坏 SCC 闭合且含左接受态，
    #    且 SCC 内强连通，因此这样的行走一定存在。
    acc_targets = {n for n in bad_scc if n[0] in left_acc}
    to_acc = _shortest_path(entry, acc_targets, bad_scc, adj)
    assert to_acc is not None
    acc_node = to_acc[-1].dst if to_acc else entry
    back = _shortest_path(
        acc_node,
        {entry},
        bad_scc,
        adj,
        allow_zero=bool(to_acc),  # entry 自身即接受态时，返回路径必须非空
    )
    assert back is not None and (to_acc or back), "无限重复环不得为空"

    cycle_edges = to_acc + back
    steps_prefix = [
        TransitionStep(e.letter, e.src[0], e.left_to, e.src[1], e.right_to)
        for e in pre_edges
    ]
    steps_cycle = [
        TransitionStep(e.letter, e.src[0], e.left_to, e.src[1], e.right_to)
        for e in cycle_edges
    ]
    return Counterexample(prefix=steps_prefix, cycle=steps_cycle)
