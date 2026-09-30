#!/usr/bin/env python
"""健康地址 HTTP 冒烟检查。

用法：python verify_smoke.py [URL]（默认 http://127.0.0.1:8080/healthz）
成功（HTTP 200 且 body.status == "ok"）以 0 退出，否则以 1 退出。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


def check(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"冒烟失败：HTTP 状态 {resp.status}", file=sys.stderr)
                return False
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("status") != "ok":
                print(f"冒烟失败：响应内容异常：{body!r}", file=sys.stderr)
                return False
            print(f"冒烟通过：GET {url} -> 200 {body}")
            return True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"冒烟失败：{exc}", file=sys.stderr)
        return False


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/healthz"
    # 容器内 depends_on 健康门控后通常立即可用；这里仍做有限重试以增强稳健性。
    for attempt in range(1, 16):
        if check(url):
            return 0
        print(f"第 {attempt} 次尝试未通过，1 秒后重试…", file=sys.stderr)
        time.sleep(1)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
