"""容器验收脚本：代码测试 + 构建检查 + 健康地址 HTTP 冒烟。

任一步失败即以非零退出码结束；全部成功退出 0。
健康地址通过 HEALTH_URL 环境变量配置（Compose 中默认 http://web:8080/health）。
"""

import json
import os
import py_compile
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_tests() -> bool:
    print("== [1/3] 代码测试：包含 / 反例 / 非确定分支 / 输入校验边界 ==")
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def build_check() -> bool:
    print("== [2/3] 构建检查：全部 Python 源码字节码编译 ==")
    ok = True
    for path in list(ROOT.rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            print(f"  OK  {path.relative_to(ROOT)}")
        except py_compile.PyCompileError as exc:
            ok = False
            print(f"  FAIL {path}: {exc}")
    return ok


def health_smoke() -> bool:
    url = os.environ.get("HEALTH_URL", "http://127.0.0.1:8080/health")
    print(f"== [3/3] HTTP 冒烟：GET {url} ==")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                print(f"  FAIL 状态码 {resp.status}")
                return False
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 验收脚本需报告任何失败
        print(f"  FAIL 请求异常：{exc}")
        return False
    if body.get("status") != "ok":
        print(f"  FAIL 响应体异常：{body}")
        return False
    print(f"  OK  {body}")
    return True


def main() -> int:
    steps = (run_tests, build_check, health_smoke)
    for step in steps:
        if not step():
            print("\n验收结果：失败 ✗", flush=True)
            return 1
    print("\n验收结果：全部通过 ✓", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
