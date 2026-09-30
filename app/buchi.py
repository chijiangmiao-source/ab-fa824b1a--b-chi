"""Büchi 自动机模型、输入校验与语言包含性判定。

判定 L(left) ⊆ L(right)：
取反右侧的接受条件后，在乘积 (l, r) 上搜索一条被左侧接受态无穷次访问、
而右侧接受态仅出现有限次的路径。若存在这样的路径（lasso：前缀 + 环），
则反例为 ω-正规字 prefix + cycle^ω；否则包含关系成立。

搜索分两阶段（均在确定性排序的图上进行，保证结果可复现）：
  阶段 A：从初态出发，允许经过右侧接受态；先处理仍可到达右侧接受态的
          前缀部分。
  阶段 B：在右侧恒为非接受态的闭子图中，寻找包含左侧接受态且可从前缀
          到达、可闭合（能成环回到自身）的强连通分量；在该 SCC 内取
          确定性的最短环作为无限重复段。

有限抽样或单一路径不能代替完整的乘积图搜索。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Automaton:
    """一台（广义）Büchi 自动机。

    transitions: 对于 deterministic=True 的自动机，每个 (state, letter)
    恰好映射到一个状态；否则映射到一个后继集合（非确定）。
    """

    name: str
    alphabet: Tuple[str, ...]
    states: Tuple[str, ...]
    initial: str
    accepting: FrozenSet[str]
    transitions: Dict[Tuple[str, str], Tuple[str, ...]]
    deterministic: bool = True

    def successors(self, state: str, letter: str) -> Tuple[str, ...]:
        return self.transitions.get((state, letter), ())


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class StateStep:
    """反例重放中的一步：读到字符后进入的状态。"""

    letter: str
    state: str


@dataclass(frozen=True)
class Counterexample:
    """可逐字符重放的反例：prefix + cycle 的无限重复。"""

    prefix_letters: Tuple[str, ...]
    cycle_letters: Tuple[str, ...]
    # 与前缀对应的状态链（含起点初态，故比前缀字符多一项）
    left_prefix_states: Tuple[str, ...]
    right_prefix_states: Tuple[str, ...]
    # 环上的状态链：len = 环字符数 + 1，末态等于首态
    left_cycle_states: Tuple[str, ...]
    right_cycle_states: Tuple[str, ...]

    @property
    def infinite_word(self) -> str:
        return "".join(self.prefix_letters) + "(" + "".join(self.cycle_letters) + ")^ω"


@dataclass(frozen=True)
class InclusionResult:
    included: bool
    counterexample: Optional[Counterexample] = None


# ---------------------------------------------------------------------------
# 输入解析与校验
# ---------------------------------------------------------------------------


def _parse_text(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [tok.strip() for tok in value.replace(",", " ").split()]
    if isinstance(value, Sequence):
        out: List[str] = []
        for item in value:
            out.extend(_parse_text(str(item)))
        return out
    return _parse_text(str(value))


def _parse_alphabet(value: object) -> Tuple[List[str], List[str]]:
    """共同 ASCII 字母表：返回 (字符列表, 错误列表)。"""
    errors: List[str] = []
    if isinstance(value, str):
        raw = value.strip()
        chars = [c for c in raw if not c.isspace() and c != ","]
    else:
        chars = []
        for item in value if isinstance(value, Sequence) else [value]:
            text = str(item)
            for c in text:
                if not c.isspace() and c != ",":
                    chars.append(c)
    result: List[str] = []
    seen: Set[str] = set()
    for c in chars:
        if ord(c) > 127:
            errors.append(f"字母表含非 ASCII 字符：{c!r}")
            continue
        if c in seen:
            errors.append(f"字母表中字符 {c!r} 重复")
            continue
        seen.add(c)
        result.append(c)
    return result, errors


def _parse_state_set(value: object) -> Set[str]:
    return set(_parse_text(value))


def _parse_transitions(
    raw: object,
) -> Dict[Tuple[str, str], List[str]]:
    """迁移表：支持 {"q0,a": "q1"} 或 [{"source","letter","target"}]。"""
    table: Dict[Tuple[str, str], List[str]] = {}
    if isinstance(raw, dict):
        for key, targets in raw.items():
            parts = str(key).split(",")
            if len(parts) != 2:
                continue
            source, letter = parts[0].strip(), parts[1].strip()
            for target in _parse_text(targets):
                table.setdefault((source, letter), []).append(target)
    elif isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source", "")).strip()
            letter = str(row.get("letter", "")).strip()
            for target in _parse_text(row.get("target", "")):
                table.setdefault((source, letter), []).append(target)
    return table


def build_automaton(
    spec: object,
    alphabet: Sequence[str],
    *,
    name: str,
    deterministic: bool,
) -> Tuple[Optional[Automaton], List[str]]:
    """根据前端提交构造一台自动机，同时收集全部错误。"""
    errors: List[str] = []
    if not isinstance(spec, dict):
        return None, [f"{name}：提交内容必须是对象"]

    declared = _parse_text(spec.get("states"))
    state_set: Set[str] = set(declared)
    duplicates = sorted({s for s in declared if declared.count(s) > 1})
    for s in duplicates:
        errors.append(f"{name}：状态 {s!r} 重复定义")

    if not declared:
        errors.append(f"{name}：至少需要一个状态")
    if len(declared) > 8:
        errors.append(f"{name}：状态数 {len(declared)} 超过上限 8")

    initial = str(spec.get("initial", "")).strip()
    if not initial:
        errors.append(f"{name}：缺少初态")
    elif initial not in state_set:
        errors.append(f"{name}：初态 {initial!r} 未在状态列表中（悬空引用）")

    accepting = _parse_state_set(spec.get("accepting"))
    for s in sorted(accepting):
        if s not in state_set:
            errors.append(f"{name}：接受态 {s!r} 未在状态列表中（悬空引用）")

    raw_table = _parse_transitions(spec.get("transitions"))

    # 校验迁移中出现的所有引用（含指向未知状态的悬空引用）
    for (source, letter), targets in sorted(raw_table.items()):
        if source not in state_set:
            errors.append(f"{name}：迁移源状态 {source!r} 未定义（悬空引用）")
        if letter not in alphabet:
            errors.append(f"{name}：迁移 {source!r} --{letter!r}--> 使用了字母表外的字符")
        for target in targets:
            if target not in state_set:
                errors.append(
                    f"{name}：迁移 {source!r} --{letter!r}--> 指向未定义状态 {target!r}（悬空引用）"
                )

    # 右侧：每个状态与字母恰好一条迁移；检查缺失与重复
    table: Dict[Tuple[str, str], Tuple[str, ...]] = {}
    if deterministic:
        for state in declared:
            for letter in alphabet:
                targets = raw_table.get((state, letter))
                if not targets:
                    errors.append(
                        f"{name}：状态 {state!r} 在字母 {letter!r} 下缺少迁移"
                    )
                    continue
                if len(targets) > 1:
                    errors.append(
                        f"{name}：状态 {state!r} 在字母 {letter!r} 下存在重复/多条迁移："
                        + ", ".join(targets)
                    )
                table[(state, letter)] = tuple(sorted(set(targets)))
    else:
        for (source, letter), targets in sorted(raw_table.items()):
            if source in state_set and letter in alphabet:
                # 稳定去重，保持排序
                table[(source, letter)] = tuple(sorted(set(targets)))

    if errors or not declared or not initial or initial not in state_set:
        return None, errors

    auto = Automaton(
        name=name,
        alphabet=tuple(alphabet),
        states=tuple(declared),
        initial=initial,
        accepting=frozenset(accepting),
        transitions=table,
        deterministic=deterministic,
    )
    return auto, errors


def validate_payload(
    payload: object,
) -> Tuple[Optional[Automaton], Optional[Automaton], List[str]]:
    """校验整份提交，一次性列出全部问题（缺失、悬空、重复引用等）。"""
    errors: List[str] = []
    if not isinstance(payload, dict):
        return None, None, ["请求体必须是 JSON 对象"]

    alphabet, alpha_errors = _parse_alphabet(payload.get("alphabet"))
    errors.extend(alpha_errors)
    if not alphabet:
        errors.append("字母表不能为空：至少需要一个 ASCII 字符")

    left, left_errors = build_automaton(
        payload.get("left", {}), alphabet, name="左侧", deterministic=False
    )
    right, right_errors = build_automaton(
        payload.get("right", {}), alphabet, name="右侧", deterministic=True
    )
    errors.extend(left_errors)
    errors.extend(right_errors)
    if errors:
        return None, None, errors
    return left, right, []


# ---------------------------------------------------------------------------
# 乘积图与包含性搜索
# ---------------------------------------------------------------------------


ProductNode = Tuple[str, str]  # (左侧状态, 右侧状态)


def _sorted_successors(
    left: Automaton,
    right: Automaton,
    node: ProductNode,
) -> List[Tuple[str, ProductNode]]:
    """按 (字母, 左后继, 右后继) 稳定排序的乘积出边。"""
    l, r = node
    edges: List[Tuple[str, str, str]] = []
    for letter in left.alphabet:
        r_targets = right.successors(r, letter)
        for r2 in r_targets:  # 右侧确定，至多一个
            for l2 in left.successors(l, letter):
                edges.append((letter, l2, r2))
    edges.sort()
    return [(letter, (l2, r2)) for letter, l2, r2 in edges]


def _can_reach_right_accepting(
    left: Automaton, right: Automaton
) -> Set[ProductNode]:
    """反向可达：哪些乘积节点仍可（在零步或多步后）经过右侧接受态。

    在完整乘积图上做逆向搜索。为得到逆向边，枚举全部节点与出边
    （状态数 ≤ 8，规模可控），节点与边均按排序顺序枚举以保证确定性。
    """
    nodes = [(l, r) for l in left.states for r in right.states]
    reverse: Dict[ProductNode, List[ProductNode]] = {n: [] for n in nodes}
    for node in nodes:
        for _, nxt in _sorted_successors(left, right, node):
            reverse.setdefault(nxt, []).append(node)

    good: Set[ProductNode] = {
        (l, r) for (l, r) in nodes if r in right.accepting
    }
    stack = sorted(good)
    while stack:
        cur = stack.pop()
        for prev in reverse.get(cur, ()):
            if prev not in good:
                good.add(prev)
                stack.append(prev)
    return good


def _tarjan_scc(
    sub_nodes: Set[ProductNode],
    left: Automaton,
    right: Automaton,
) -> List[Set[ProductNode]]:
    """在给定子图上以 Tarjan 求 SCC；迭代顺序全部稳定排序。"""
    index_of: Dict[ProductNode, int] = {}
    lowlink: Dict[ProductNode, int] = {}
    on_stack: Set[ProductNode] = set()
    stack: List[ProductNode] = []
    sccs: List[Set[ProductNode]] = []
    counter = 0

    def neighbors(node: ProductNode) -> List[ProductNode]:
        return [
            nxt
            for _, nxt in _sorted_successors(left, right, node)
            if nxt in sub_nodes
        ]

    for root in sorted(sub_nodes):
        if root in index_of:
            continue
        work: List[Tuple[ProductNode, int]] = [(root, 0)]
        index_of[root] = lowlink[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)

        while work:
            node, edge_idx = work[-1]
            nbrs = neighbors(node)
            if edge_idx < len(nbrs):
                work[-1] = (node, edge_idx + 1)
                nxt = nbrs[edge_idx]
                if nxt not in index_of:
                    index_of[nxt] = lowlink[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    lowlink[node] = min(lowlink[node], index_of[nxt])
            else:
                if lowlink[node] == index_of[node]:
                    component: Set[ProductNode] = set()
                    while True:
                        top = stack.pop()
                        on_stack.discard(top)
                        component.add(top)
                        if top == node:
                            break
                    sccs.append(component)
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
    return sccs


def _reconstruct(
    parent: Dict[ProductNode, Tuple[ProductNode, str]],
    start: ProductNode,
    end: ProductNode,
) -> Tuple[List[str], List[ProductNode]]:
    """沿 parent 指针恢复 start -> end 的字符序列与节点序列。"""
    letters: List[str] = []
    chain: List[ProductNode] = [end]
    cur = end
    while cur != start:
        prev, letter = parent[cur]
        letters.append(letter)
        chain.append(prev)
        cur = prev
    letters.reverse()
    chain.reverse()
    return letters, chain


def _chain_states(chain: Sequence[ProductNode], side: int) -> Tuple[str, ...]:
    return tuple(node[side] for node in chain)


def check_inclusion(
    left: Automaton, right: Automaton
) -> InclusionResult:
    """判定 L(left) ⊆ L(right)，不成立时给出 lasso 反例。"""
    start: ProductNode = (left.initial, right.initial)

    # good：仍可（零步或多步后）经过右侧接受态的乘积节点。
    good = _can_reach_right_accepting(left, right)

    # ---- 阶段 A：稳定排序的可达性搜索（前缀） ----
    # good 层（右侧仍可经过接受态）优先扩展，排空后再扩展 bad 层；
    # 注意 bad 节点（如可经别的字母到达接受态、但当前路径不再去）
    # 仍须完整可达，阶段 B 才不会漏掉反例。
    parent: Dict[ProductNode, Tuple[ProductNode, str]] = {start: (start, "")}
    frontier_good: List[ProductNode] = [start] if start in good else []
    frontier_bad: List[ProductNode] = [] if start in good else [start]

    def expand(frontier: List[ProductNode]) -> None:
        node = frontier.pop(0)
        for letter, nxt in _sorted_successors(left, right, node):
            if nxt in parent:
                continue
            parent[nxt] = (node, letter)
            # 非 good 节点的后继不可能是 good，否则它自身也应在 good
            if nxt in good:
                frontier_good.append(nxt)
            else:
                frontier_bad.append(nxt)

    while frontier_good:
        expand(frontier_good)
    while frontier_bad:
        expand(frontier_bad)

    # ---- 阶段 B：右侧全为非接受态的闭子图 ----
    bad_subgraph = {
        (l, r)
        for l in left.states
        for r in right.states
        if r not in right.accepting
    }
    candidates = set(parent) & bad_subgraph
    for component in _tarjan_scc(candidates, left, right):
        # 可闭合：单点 SCC 需要子图内自环；多点 SCC 必有环
        if len(component) == 1:
            only = next(iter(component))
            has_loop = any(
                nxt == only
                for _, nxt in _sorted_successors(left, right, only)
                if nxt in bad_subgraph
            )
            if not has_loop:
                continue
        # 必须含左侧接受态（在环上被无穷次访问）
        if not any(l in left.accepting for l, _ in component):
            continue
        return InclusionResult(
            included=False,
            counterexample=_build_counterexample(
                left, right, component, parent, start
            ),
        )

    return InclusionResult(included=True)


def _shortest_path(
    left: Automaton,
    right: Automaton,
    component: Set[ProductNode],
    src: ProductNode,
    dst: ProductNode,
) -> Tuple[List[str], List[ProductNode]]:
    """分量子图内 src -> dst 的确定性最短路径（出边稳定排序）。

    src == dst 时求一条非空闭环；节点链末节点为 dst，比字符序列多一项。
    """
    if src == dst:
        # BFS 但不把 src 标记为已访问，从而允许重新进入 src
        dist: Dict[ProductNode, int] = {src: 0}
        back: Dict[ProductNode, Tuple[ProductNode, str]] = {}
        queue: List[ProductNode] = [src]
        while queue:
            node = queue.pop(0)
            for letter, nxt in _sorted_successors(left, right, node):
                if nxt not in component:
                    continue
                if nxt == src:
                    back[src] = (node, letter)
                    back_nodes: List[ProductNode] = []
                    back_letters: List[str] = []
                    cur = src
                    while True:
                        prev, edge_letter = back[cur]
                        back_letters.append(edge_letter)
                        back_nodes.append(prev)
                        cur = prev
                        if cur == src:
                            break
                    back_nodes.reverse()
                    back_letters.reverse()
                    return back_letters, back_nodes + [src]
                if nxt not in dist:
                    dist[nxt] = dist[node] + 1
                    back[nxt] = (node, letter)
                    queue.append(nxt)
        raise RuntimeError("SCC 内未找到预期闭环，不应发生")

    parent: Dict[ProductNode, Tuple[ProductNode, str]] = {src: (src, "")}
    queue = [src]
    while queue:
        node = queue.pop(0)
        for letter, nxt in _sorted_successors(left, right, node):
            if nxt not in component or nxt in parent:
                continue
            parent[nxt] = (node, letter)
            if nxt == dst:
                return _reconstruct(parent, src, dst)
            queue.append(nxt)
    raise RuntimeError("SCC 内未找到预期路径，不应发生")


def _build_counterexample(
    left: Automaton,
    right: Automaton,
    component: Set[ProductNode],
    parent: Dict[ProductNode, Tuple[ProductNode, str]],
    start: ProductNode,
) -> Counterexample:
    """把 SCC 反例具体化为 前缀 + 确定性最短环。

    前缀：乘积初态 -> 分量入口 entry -> 排序最靠前的左侧接受态节点
    target（entry -> target 段位于右侧非接受态子图内，归入前缀）。
    环：target -> target 的最短非空闭环，环上确有左侧接受态、
    绝无右侧接受态。环链首尾同为 target，可无限重复。
    """
    entry = sorted(component & set(parent))[0]
    prefix_letters, prefix_chain = _reconstruct(parent, start, entry)

    accept_nodes = sorted(
        node for node in component if node[0] in left.accepting
    )
    target = accept_nodes[0]

    if entry != target:
        to_target_letters, to_target_chain = _shortest_path(
            left, right, component, entry, target
        )
        prefix_letters = prefix_letters + to_target_letters
        prefix_chain = list(prefix_chain) + to_target_chain[1:]

    cycle_letters, cycle_chain_nodes = _shortest_path(
        left, right, component, target, target
    )

    return Counterexample(
        prefix_letters=tuple(prefix_letters),
        cycle_letters=tuple(cycle_letters),
        left_prefix_states=_chain_states(prefix_chain, 0),
        right_prefix_states=_chain_states(prefix_chain, 1),
        left_cycle_states=_chain_states(cycle_chain_nodes, 0),
        right_cycle_states=_chain_states(cycle_chain_nodes, 1),
    )
