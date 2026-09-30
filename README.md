# Büchi 自动机语言包含性复核站点

判定 **L(A) ⊆ L(B)**：左侧 A 为（可能非确定的）Büchi 自动机，右侧 B 为确定、完全
的 Büchi 自动机（每个状态 × 字母恰好一条迁移）。不包含时给出可逐字符重放的
**有限前缀 + 无限重复环** 反例，并展示两侧对应状态链；包含时绝不生成反例。

纯 Python 标准库实现，无第三方依赖。

## 判定方法

在乘积图（节点 `(q, p)`）上做完整搜索，节点与后继按 `(状态, 字母)` 稳定排序，
结果可复现：

1. 从乘积初态构造可达乘积图；
2. 先处理**右侧仍可经过接受态**的前缀——前缀在完整可达乘积图上搜索，沿途允许
   经过任意多个右接受态（这些接受只发生有限次）；
3. 再在**右组件全为非接受态**的诱导子图上以稳定顺序计算 SCC（Tarjan），寻找
   **含左侧接受态且可闭合**的强连通分量；找到即为反例；
4. 反例 = 初态到该 SCC 的最短前缀 + SCC 内经过左接受态的最短闭合环。

对完整状态空间求 SCC，不以有限抽样或单一路径代替。测试中另有独立的朴素嵌套
可达性参考实现，随机自动机与生产实现进行上千组对照。

## 输入

- 共同 ASCII 字母表（如 `ab`，可连写或以逗号/空格分隔）；
- 两侧状态各不超过 8 个；
- 初态、接受态（空格/逗号分隔）；
- 迁移每行：`状态 字母 -> 目标...`；左侧目标可多个（非确定分支），右侧必须恰好一个；
- 缺失、悬空、重复引用等问题一次性列全，提交新复核会清除旧结论。

## 本地运行（无需容器）

```bash
python3 -m app.server            # 默认 0.0.0.0:8080
PORT=8123 python3 -m app.server  # 自定义端口
# 健康地址
curl http://127.0.0.1:8080/healthz
```

## Docker Compose

```bash
# 宿主机端口可用 HOST_PORT 配置（默认 8080）
HOST_PORT=9090 docker compose up --build web

# 一次性验收：代码测试（包含/反例/非确定分支/输入校验边界）+ 构建检查 + 健康地址冒烟
# 结束后退出，退出码即验收结果（0 通过）
docker compose run --build verify
# 或
docker compose up --build --exit-code-from verify verify
```

`verify` 服务会等待 `web` 健康检查通过后：

1. 字节码编译与关键模块导入（构建检查）；
2. `python -m unittest discover` 运行全部测试；
3. 请求 `http://web:8080/healthz` 做 HTTP 冒烟；
4. 退出并以退出码报告验收结果。

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/verify_smoke.py http://127.0.0.1:8080/healthz
```

## 目录

```
app/core/automata.py   解析、校验、乘积图 + SCC 包含判定、反例构造
app/server.py          标准库 HTTP 服务；后台单线程搜索 + 代际令牌防过期覆盖
app/web.py             内联页面（错误列全、结论展示、反例逐字符重放）
tests/                 算法/校验（含随机对照）与 HTTP/竞态测试
scripts/               verify.sh 验收脚本、verify_smoke.py 冒烟
```
