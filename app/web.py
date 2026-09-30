"""前端页面（内联 HTML/CSS/JS，无外部依赖）。"""

from __future__ import annotations

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Büchi 自动机语言包含性复核</title>
<style>
  :root {
    --bg: #0f1420;
    --panel: #1a2233;
    --panel2: #202b40;
    --line: #2d3a55;
    --text: #e6ebf5;
    --muted: #93a1bd;
    --accent: #5aa9ff;
    --ok: #3ecf8e;
    --bad: #ff6b6b;
    --warn: #ffc857;
    --left: #7fd1ff;
    --right: #c9a6ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    line-height: 1.55;
  }
  header { padding: 20px 28px 12px; border-bottom: 1px solid var(--line); }
  header h1 { margin: 0; font-size: 20px; letter-spacing: .5px; }
  header p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
  main {
    display: grid; grid-template-columns: minmax(380px, 1.05fr) minmax(380px, 1fr);
    gap: 18px; padding: 18px 28px 40px; align-items: start;
  }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; }
  .card h2 { font-size: 15px; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }
  .card h2 .tag { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
  .tag.left { background: rgba(127,209,255,.15); color: var(--left); }
  .tag.right { background: rgba(201,166,255,.15); color: var(--right); }
  label { display: block; font-size: 12px; color: var(--muted); margin: 10px 0 4px; }
  input[type=text], textarea {
    width: 100%; background: var(--panel2); color: var(--text);
    border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px; outline: none;
  }
  input[type=text]:focus, textarea:focus { border-color: var(--accent); }
  textarea { min-height: 150px; resize: vertical; white-space: pre; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .hint { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .actions { margin-top: 16px; display: flex; gap: 10px; align-items: center; }
  button {
    background: var(--accent); color: #08111f; border: 0; border-radius: 8px;
    padding: 9px 20px; font-size: 14px; font-weight: 700; cursor: pointer;
  }
  button:disabled { opacity: .55; cursor: wait; }
  button.ghost { background: transparent; color: var(--muted); border: 1px solid var(--line); font-weight: 500; }
  .spinner {
    width: 15px; height: 15px; border: 2px solid var(--line);
    border-top-color: var(--accent); border-radius: 50%;
    animation: spin .8s linear infinite; display: none;
  }
  .spinner.on { display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  #errors { display: none; margin: 0 28px; }
  #errors.on { display: block; }
  .error-box {
    background: rgba(255,107,107,.08); border: 1px solid rgba(255,107,107,.45);
    border-radius: 10px; padding: 12px 16px;
  }
  .error-box h3 { margin: 0 0 8px; color: var(--bad); font-size: 14px; }
  .error-box ul { margin: 0; padding-left: 20px; font-size: 13px; }
  .error-box li { margin: 3px 0; }

  #result { margin: 0 28px; display: none; }
  #result.on { display: block; margin-top: 18px; }
  .verdict { font-size: 18px; font-weight: 700; padding: 14px 18px; border-radius: 10px; }
  .verdict.ok { background: rgba(62,207,142,.1); border: 1px solid rgba(62,207,142,.5); color: var(--ok); }
  .verdict.bad { background: rgba(255,107,107,.08); border: 1px solid rgba(255,107,107,.5); color: var(--bad); }
  .stats { color: var(--muted); font-size: 12px; margin-top: 8px; }

  .ce { margin-top: 14px; }
  .word { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 14px; margin: 6px 0 2px; word-break: break-all; }
  .word .pre { color: var(--text); }
  .word .cyc { color: var(--warn); font-weight: 700; }
  .word .sup { color: var(--warn); font-size: 11px; vertical-align: super; }
  .replay-controls { margin: 12px 0 6px; display: flex; gap: 8px; align-items: center; }
  .replay-controls button { padding: 6px 14px; font-size: 13px; }
  .chains { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }
  .chain {
    background: var(--panel2); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
    font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; overflow-x: auto; white-space: nowrap;
  }
  .chain h4 { margin: 0 0 8px; font-size: 12px; color: var(--muted); font-family: inherit; }
  .chain .st { padding: 2px 7px; border-radius: 6px; display: inline-block; }
  .chain .st.acc { outline: 2px solid var(--ok); }
  .chain.left .st.cur { background: rgba(127,209,255,.25); }
  .chain.right .st.cur { background: rgba(201,166,255,.25); }
  .chain .ar { color: var(--muted); margin: 0 3px; }
  .chain .ar b { color: var(--warn); font-weight: 700; }
  .chain .lbl { font-size: 10px; color: var(--muted); margin-left: 6px; }
  .note { color: var(--muted); font-size: 12px; margin-top: 8px; }
  .stale-note { color: var(--warn); font-size: 12px; margin-left: 8px; display: none; }
  .stale-note.on { display: inline; }
</style>
</head>
<body>
<header>
  <h1>轨道故障规程 · Büchi 自动机语言包含性复核</h1>
  <p>共同 ASCII 字母表；左（可非确定）、右（确定、完全）各不超过 8 个状态；迁移写法 <code>q0 a -&gt; q1</code>，左侧目标可写多个（空格分隔）。右侧每个状态与字母必须恰好一条迁移。</p>
</header>

<main>
  <section>
    <div class="card">
      <h2>共同字母表</h2>
      <label for="alphabet">字母（ASCII 字符，可连写或逗号/空格分隔，如 <code>ab</code>）</label>
      <input id="alphabet" type="text" value="ab" autocomplete="off">
    </div>

    <div class="card" style="margin-top:16px">
      <h2><span class="tag left">左 · A</span> 被包含方（允许非确定分支）</h2>
      <div class="row">
        <div>
          <label for="l-states">状态（空格/逗号分隔，至多 8 个）</label>
          <input id="l-states" type="text" value="q0 q1">
        </div>
        <div>
          <label for="l-initial">初态</label>
          <input id="l-initial" type="text" value="q0">
        </div>
      </div>
      <label for="l-accepting">接受态</label>
      <input id="l-accepting" type="text" value="q1">
      <label for="l-trans">按字母迁移（每行 <code>状态 字母 -&gt; 目标...</code>）</label>
      <textarea id="l-trans">q0 a -> q0 q1
q0 b -> q0
q1 a -> q1
q1 b -> q1</textarea>
    </div>

    <div class="card" style="margin-top:16px">
      <h2><span class="tag right">右 · B</span> 包含方（确定、完全）</h2>
      <div class="row">
        <div>
          <label for="r-states">状态（至多 8 个）</label>
          <input id="r-states" type="text" value="p0 p1">
        </div>
        <div>
          <label for="r-initial">初态</label>
          <input id="r-initial" type="text" value="p0">
        </div>
      </div>
      <label for="r-accepting">接受态</label>
      <input id="r-accepting" type="text" value="p1">
      <label for="r-trans">按字母迁移（每状态每字母恰好一条）</label>
      <textarea id="r-trans">p0 a -> p0
p0 b -> p1
p1 a -> p1
p1 b -> p1</textarea>
    </div>

    <div class="actions">
      <button id="submit">提交复核</button>
      <button id="reset" class="ghost">恢复示例</button>
      <span class="spinner" id="spinner"></span>
      <span class="stale-note" id="stale-note">此前结果已被新提交取代</span>
    </div>
  </section>

  <section>
    <div id="errors"><div class="error-box"><h3>输入校验未通过（请一次处理下列全部问题）</h3><ul id="error-list"></ul></div></div>

    <div id="result">
      <div id="verdict" class="verdict"></div>
      <div class="stats" id="stats"></div>
      <div class="ce" id="ce-panel" style="display:none">
        <div class="word" id="word"></div>
        <div class="note">前缀读一次，随后黄色的环无限重复（环中左侧必经过接受态、右侧全部为非接受态）。</div>
        <div class="replay-controls">
          <button id="step" class="ghost">下一步 ▶</button>
          <button id="play" class="ghost">自动重放</button>
          <button id="restart" class="ghost">回到前缀起点</button>
          <span id="position" class="note"></span>
        </div>
        <div class="chains">
          <div class="chain left"><h4>左侧状态链（A，绿框=接受态）</h4><div id="l-chain"></div></div>
          <div class="chain right"><h4>右侧状态链（B，绿框=接受态）</h4><div id="r-chain"></div></div>
        </div>
      </div>
    </div>
  </section>
</main>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
let pollTimer = null, currentJob = null, lastCE = null, playTimer = null;
let replayIdx = 0;

function sidePayload(prefix) {
  return {
    states: $(prefix + "-states").value,
    initial: $(prefix + "-initial").value,
    accepting: $(prefix + "-accepting").value,
    transitions: $(prefix + "-trans").value,
  };
}

function clearConclusions() {
  // 新提交前清除旧结论与旧错误
  $("errors").classList.remove("on");
  $("result").classList.remove("on");
  $("ce-panel").style.display = "none";
  stopPlay();
  lastCE = null;
}

function showErrors(errors) {
  const ul = $("error-list");
  ul.innerHTML = "";
  for (const e of errors) {
    const li = document.createElement("li");
    li.textContent = e;
    ul.appendChild(li);
  }
  $("errors").classList.add("on");
}

async function submitVerify() {
  clearConclusions();
  $("stale-note").classList.remove("on");
  const payload = {
    alphabet: $("alphabet").value,
    left: sidePayload("l"),
    right: sidePayload("r"),
  };
  $("submit").disabled = true;
  $("spinner").classList.add("on");
  try {
    const resp = await fetch("/api/verify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      finishPending();
      showErrors(data.errors || ["提交失败"]);
      return;
    }
    currentJob = data.job_id;
    poll(data.job_id);
  } catch (err) {
    finishPending();
    showErrors(["网络错误：" + err]);
  }
}

function finishPending() {
  $("submit").disabled = false;
  $("spinner").classList.remove("on");
}

function poll(jobId) {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const resp = await fetch("/api/jobs/" + jobId, {cache: "no-store"});
      const data = await resp.json();
      if (currentJob !== jobId) return;  // 已被更新的提交取代
      if (resp.status === 409 || data.status === "stale") {
        $("stale-note").classList.add("on");
        finishPending();
        return;
      }
      if (data.status === "pending") {
        poll(jobId);
        return;
      }
      finishPending();
      if (data.status === "error") {
        showErrors(data.errors);
        return;
      }
      renderResult(data.result);
    } catch (err) {
      finishPending();
      showErrors(["查询结果失败：" + err]);
    }
  }, 120);
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

function renderResult(result) {
  clearConclusions();
  $("result").classList.add("on");
  const v = $("verdict");
  if (result.contained) {
    v.className = "verdict ok";
    v.textContent = "✓ 包含成立：L(A) ⊆ L(B)（完整乘积图与 SCC 搜索未发现反例）";
  } else {
    v.className = "verdict bad";
    v.textContent = "✗ 不包含：L(A) ⊄ L(B)，存在左侧接受、右侧无法无穷接受的无限词";
  }
  const s = result.stats || {};
  $("stats").textContent =
    `乘积节点 ${s.product_nodes} · 乘积边 ${s.product_edges} · 前缀节点 ${s.prefix_nodes} · 右非接受子图节点 ${s.nonaccepting_nodes} · SCC ${s.scc_count}`;
  if (!result.contained && result.counterexample) {
    lastCE = result.counterexample;
    renderCounterexample(result.counterexample);
  }
}

// --- 反例重放 ---
function flatSteps(ce) {
  // 前缀步骤 + 环步骤（环首步的起点即前缀终点）
  return ce.prefix.concat(ce.cycle);
}

function renderCounterexample(ce) {
  $("ce-panel").style.display = "block";
  const w = $("word");
  w.innerHTML =
    '无限反例 w = <span class="pre">' + esc(ce.prefix_word || "ε") +
    '</span><span class="cyc">(' + esc(ce.cycle_word) + ')<span class="sup">ω</span></span>';
  replayIdx = 0;
  drawChains(ce, -1);
  updatePosition(ce);
}

function chainHTML(ce, side, sideName, curStepIdx) {
  // side: 'left'/'right'；前缀节点 + 环节点（环尾节点与环首相同，以闭合标记展示）
  const fromK = side === "left" ? "left_from" : "right_from";
  const toK = side === "left" ? "left_to" : "right_to";
  const acc = new Set(side === "left" ? leftAcc() : rightAcc());
  const steps = flatSteps(ce);
  let html = "";
  const nodeAt = (i) => i === 0 ? steps[0][fromK] : steps[i - 1][toK];
  const totalNodes = steps.length + 1;
  for (let i = 0; i < totalNodes; i++) {
    const node = nodeAt(i);
    const cls = ["st"];
    if (acc.has(node)) cls.push("acc");
    if (i === curStepIdx + 1 || (curStepIdx === -1 && i === 0)) cls.push("cur");
    html += '<span class="' + cls.join(" ") + '">' + esc(node) + "</span>";
    if (i < steps.length) {
      const inCycle = i >= ce.prefix.length;
      html += '<span class="ar"> —<b>' + esc(steps[i].letter) + "</b>→</span>";
    }
  }
  // 闭合环标记
  html += '<span class="lbl">（黄色箭头段为无限重复环，环尾回到环首）</span>';
  return html;
}

function leftAcc() {
  return $("l-accepting").value.split(/[\s,]+/).filter(Boolean);
}
function rightAcc() {
  return $("r-accepting").value.split(/[\s,]+/).filter(Boolean);
}

function drawChains(ce, curStepIdx) {
  $("l-chain").innerHTML = chainHTML(ce, "left", "A", curStepIdx);
  $("r-chain").innerHTML = chainHTML(ce, "right", "B", curStepIdx);
}

function updatePosition(ce) {
  const steps = flatSteps(ce);
  const n = steps.length, pre = ce.prefix.length;
  if (replayIdx < 0) {
    $("position").textContent = "位置：前缀起点（尚未读字符）";
  } else if (replayIdx < pre) {
    $("position").textContent = `位置：前缀第 ${replayIdx + 1}/${pre} 个字符`;
  } else {
    const k = replayIdx - pre + 1;
    $("position").textContent = `位置：环第 ${k}/${n - pre} 个字符（重复后回到环首继续）`;
  }
}

function stepOnce() {
  if (!lastCE) return;
  const pre = lastCE.prefix.length;
  if (replayIdx + 1 >= flatSteps(lastCE).length) {
    // 走完环尾：闭合回到环首节点（前缀为空时回到初态节点）
    replayIdx = pre > 0 ? pre - 1 : -1;
    drawChains(lastCE, replayIdx);
    $("position").textContent = "环闭合，回到环首（无限重复）";
    return;
  }
  replayIdx += 1;
  drawChains(lastCE, replayIdx);
  updatePosition(lastCE);
}

function stopPlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  $("play").textContent = "自动重放";
}

function togglePlay() {
  if (!lastCE) return;
  if (playTimer) { stopPlay(); return; }
  $("play").textContent = "暂停";
  playTimer = setInterval(stepOnce, 850);
}

$("submit").addEventListener("click", submitVerify);
$("step").addEventListener("click", () => { stopPlay(); stepOnce(); });
$("play").addEventListener("click", togglePlay);
$("restart").addEventListener("click", () => { stopPlay(); replayIdx = -1; if (lastCE) { drawChains(lastCE, -1); updatePosition(lastCE); } });
$("reset").addEventListener("click", () => location.reload());
</script>
</body>
</html>
"""
