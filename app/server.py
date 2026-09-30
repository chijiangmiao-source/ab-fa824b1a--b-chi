"""HTTP 服务：验证页面、健康检查与后台图搜索 API。

仅使用 Python 标准库。图搜索在单线程后台执行器中运行，每次提交获得递增
作业号；过期作业完成后不会覆盖当前结果（代际校验，stale 结果直接丢弃）。
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.core.automata import (
    ValidationError,
    build_automaton,
    check_inclusion,
    parse_alphabet,
)
from app.web import INDEX_HTML

MAX_BODY_BYTES = 64 * 1024


class Job:
    def __init__(self, job_id: int, payload: Dict[str, Any]):
        self.id = job_id
        self.payload = payload
        self.status = "pending"  # pending | done | error
        self.result: Optional[Dict[str, Any]] = None
        self.errors: Optional[list] = None


class JobManager:
    """管理当前作业；过期作业完成时不得覆盖更新的作业。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search")
        self._current_id = 0
        self._current: Optional[Job] = None

    def submit(self, payload: Dict[str, Any]) -> int:
        with self._lock:
            self._current_id += 1
            job = Job(self._current_id, payload)
            self._current = job
        self._executor.submit(self._run, job)
        return job.id

    def get(self, job_id: int) -> Optional[Job]:
        with self._lock:
            if self._current is None or job_id != self._current.id:
                return None
            return self._current

    def _run(self, job: Job) -> None:
        try:
            outcome = _evaluate(job.payload)
            with self._lock:
                if self._current is None or self._current.id != job.id:
                    # 已有更新的提交：丢弃过期结果，绝不覆盖当前结果
                    return
                job.result = outcome
                job.status = "done"
        except ValidationError as exc:
            with self._lock:
                if self._current is None or self._current.id != job.id:
                    return
                job.errors = exc.errors
                job.status = "error"
        except Exception as exc:  # pragma: no cover - 防御性
            with self._lock:
                if self._current is None or self._current.id != job.id:
                    return
                job.errors = [f"服务器内部错误：{exc}"]
                job.status = "error"


def _side(payload: Any, side: str) -> Dict[str, str]:
    if not isinstance(payload, dict):
        raise ValidationError([f"{side}：请求体格式错误"])
    out = {}
    for key, label in (
        ("states", "状态"),
        ("initial", "初态"),
        ("accepting", "接受态"),
        ("transitions", "迁移"),
    ):
        value = payload.get(key, "")
        if not isinstance(value, str):
            raise ValidationError([f"{side}：{label}必须是字符串"])
        out[key] = value
    return out


def _evaluate(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError(["请求体格式错误"])
    alphabet_raw = payload.get("alphabet", "")
    if not isinstance(alphabet_raw, str):
        raise ValidationError(["共同字母表必须是字符串"])
    alphabet = parse_alphabet(alphabet_raw)

    left_data = _side(payload.get("left"), "左侧")
    right_data = _side(payload.get("right"), "右侧")

    # 两侧独立校验后合并错误：左侧的问题不得遮蔽右侧缺失/悬空/重复等问题。
    errors: list = []
    left = right = None
    try:
        left = build_automaton(
            "左侧",
            alphabet,
            left_data["states"],
            left_data["initial"],
            left_data["accepting"],
            left_data["transitions"],
            require_total=False,
        )
    except ValidationError as exc:
        errors.extend(exc.errors)
    try:
        right = build_automaton(
            "右侧",
            alphabet,
            right_data["states"],
            right_data["initial"],
            right_data["accepting"],
            right_data["transitions"],
            require_total=True,
        )
    except ValidationError as exc:
        errors.extend(exc.errors)

    if errors:
        # 字母表类错误两侧可能各报一次，去重但保留顺序
        merged: list = []
        for err in errors:
            if err not in merged:
                merged.append(err)
        raise ValidationError(merged)

    result = check_inclusion(left, right)
    return result.as_dict()


class Handler(BaseHTTPRequestHandler):
    server_version = "BuchiVerify/1.0"
    manager: JobManager = None  # 由 server 注入（类属性）

    def log_message(self, fmt: str, *args: Any) -> None:
        # 简洁日志；测试环境不打印噪声
        import sys

        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, status: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if path == "/":
            self._send_html(200, INDEX_HTML)
            return
        if path.startswith("/api/jobs/"):
            try:
                job_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._send_json(404, {"error": "作业不存在"})
                return
            job = self.manager.get(job_id)
            if job is None:
                self._send_json(409, {"status": "stale", "error": "该作业已被更新的提交取代"})
                return
            if job.status == "pending":
                self._send_json(200, {"status": "pending"})
            elif job.status == "error":
                self._send_json(200, {"status": "error", "errors": job.errors})
            else:
                self._send_json(200, {"status": "done", "result": job.result})
            return
        self._send_json(404, {"error": "未找到"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/verify":
            self._send_json(404, {"error": "未找到"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"errors": ["请求体为空或超过大小限制"]})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"errors": ["请求不是合法 JSON"]})
            return
        job_id = self.manager.submit(payload)
        self._send_json(202, {"job_id": job_id})


def create_server(host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    manager = JobManager()

    class _Handler(Handler):
        pass

    _Handler.manager = manager
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.job_manager = manager  # type: ignore[attr-defined]
    return httpd


def main() -> None:
    import os

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    httpd = create_server(host, port)
    print(f"Büchi 包含性验证站点监听 http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
