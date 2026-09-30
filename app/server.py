"""HTTP 服务：静态页面 + /api/verify 后台图搜索。

- 输入校验同步完成（纯解析，快速），问题一次性返回并促使前端清除旧结论。
- 图搜索放入后台单工作线程；每个任务有独立 id，结果按键存放，
  过期任务不会覆盖更新任务的结论；新任务入队时旧的排队任务直接作废。
- 端口由环境变量 PORT 配置（默认 8080）。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .buchi import check_inclusion, validate_payload

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


@dataclass
class Job:
    job_id: str
    status: str = "queued"  # queued | running | done | superseded
    result: Optional[Dict[str, Any]] = None
    seq: int = 0


class JobManager:
    """单工作线程、按提交序号合并过期任务。"""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._pending: list = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._latest_seq = 0
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def submit(self, left, right) -> Job:
        with self._cond:
            self._latest_seq += 1
            job = Job(job_id=uuid.uuid4().hex, seq=self._latest_seq)
            self._jobs[job.job_id] = job
            self._pending.append((job, left, right))
            self._cond.notify_all()
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _worker(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                job, left, right = self._pending.pop(0)
                # 排队期间已被更新提交超越的任务直接作废，不做无用图搜索
                if job.seq < self._latest_seq:
                    job.status = "superseded"
                    continue
                job.status = "running"

            # 后台执行图搜索（纯函数，不触碰其他任务的状态）
            outcome = check_inclusion(left, right)

            with self._cond:
                if job.status == "superseded":
                    continue
                payload: Dict[str, Any] = {"included": outcome.included}
                if outcome.counterexample is not None:
                    ce = outcome.counterexample
                    payload["counterexample"] = {
                        "word": ce.infinite_word,
                        "prefix_letters": list(ce.prefix_letters),
                        "cycle_letters": list(ce.cycle_letters),
                        "left_prefix_states": list(ce.left_prefix_states),
                        "right_prefix_states": list(ce.right_prefix_states),
                        "left_cycle_states": list(ce.left_cycle_states),
                        "right_cycle_states": list(ce.right_cycle_states),
                    }
                job.result = payload
                job.status = "done"
                self._cond.notify_all()


MANAGER: Optional[JobManager] = None


def _serialize_automaton_spec(spec: Any) -> Any:
    return spec  # 直接来自 JSON，原样保留


class Handler(BaseHTTPRequestHandler):
    server_version = "BuchiInclusion/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if os.environ.get("QUIET"):
            return
        super().log_message(fmt, *args)

    # -- helpers -----------------------------------------------------------

    def _send_json(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: str, content_type: str) -> None:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- routing -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/" or path == "/index.html":
            self._send_file(os.path.join(STATIC_DIR, "index.html"),
                            "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            name = os.path.basename(path)
            self._send_file(
                os.path.join(STATIC_DIR, name),
                "application/javascript; charset=utf-8"
                if name.endswith(".js")
                else "text/plain; charset=utf-8",
            )
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            job = MANAGER.get(job_id)  # type: ignore[union-attr]
            if job is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "任务不存在"})
                return
            body: Dict[str, Any] = {"job_id": job.job_id, "status": job.status}
            if job.status == "done":
                body["result"] = job.result
            self._send_json(HTTPStatus.OK, body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        global MANAGER
        parsed = urlparse(self.path)
        if parsed.path != "/api/verify":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"errors": ["请求体不是合法的 JSON"]})
            return

        # 输入校验同步执行：缺失/悬空/重复一次列全
        left, right, errors = validate_payload(payload)
        if errors:
            self._send_json(HTTPStatus.BAD_REQUEST, {"errors": errors})
            return

        assert MANAGER is not None and left is not None and right is not None
        job = MANAGER.submit(left, right)
        self._send_json(HTTPStatus.ACCEPTED,
                        {"job_id": job.job_id, "status": job.status})


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    global MANAGER
    MANAGER = JobManager()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Büchi 包含性校验服务监听 http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    serve(host, port)
