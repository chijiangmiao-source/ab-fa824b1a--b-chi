#!/bin/sh
# Compose verify 服务的一次性验收脚本：
#   1) 构建检查（全部源码可编译、关键模块可导入）
#   2) 代码测试：包含 / 反例 / 非确定分支 / 输入校验边界
#   3) 健康地址 HTTP 冒烟
# 结束后退出，退出码即验收结果。
set -eu

WEB_HEALTH_URL="${WEB_HEALTH_URL:-http://web:8080/healthz}"

echo "== [1/3] 构建检查：字节码编译与模块导入 =="
python -m compileall -q app scripts
python - <<'PY'
import importlib
for mod in ("app.core.automata", "app.server", "app.web"):
    importlib.import_module(mod)
print("关键模块导入成功")
PY

echo "== [2/3] 代码测试（包含 / 反例 / 非确定分支 / 输入校验边界）=="
python -m unittest discover -v -s tests -p "test_*.py"

echo "== [3/3] HTTP 冒烟：${WEB_HEALTH_URL} =="
python scripts/verify_smoke.py "${WEB_HEALTH_URL}"

echo "== 验收全部通过 =="
