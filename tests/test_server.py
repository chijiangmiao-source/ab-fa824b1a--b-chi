"""HTTP 层测试：健康检查、提交/轮询、校验、结论与过期作业保护。"""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from typing import Any, Dict, Tuple

from app.server import create_server

EXAMPLE_LEFT = {
    "states": "q0 q1",
    "initial": "q0",
    "accepting": "q1",
    "transitions": "q0 a -> q0 q1\nq0 b -> q0\nq1 a -> q1\nq1 b -> q1",
}
EXAMPLE_RIGHT = {
    "states": "p0 p1",
    "initial": "p0",
    "accepting": "p1",
    "transitions": "p0 a -> p0\np0 b -> p1\np1 a -> p1\np1 b -> p1",
}


class ServerHarness:
    def __init__(self):
        self.httpd = create_server("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def request(self, path: str, payload: Any = None, method: str = "GET") -> Tuple[int, Any]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url(path), data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def submit(self, payload: Dict[str, Any]) -> int:
        status, body = self.request("/api/verify", payload, method="POST")
        assert status == 202, body
        return body["job_id"]

    def wait_done(self, job_id: int, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        while True:
            status, body = self.request(f"/api/jobs/{job_id}")
            assert status == 200, body
            if body["status"] != "pending":
                return body
            assert time.monotonic() < deadline, "作业超时未完成"
            time.sleep(0.01)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.h = ServerHarness()

    def tearDown(self):
        self.h.stop()

    def test_healthz(self):
        status, body = self.h.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_index_html_served(self):
        req = urllib.request.Request(self.h.url("/"))
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers["Content-Type"])
            html = resp.read().decode("utf-8")
        self.assertIn("Büchi", html)

    def test_contained_verdict_has_no_fake_counterexample(self):
        # 两侧相同语言 => 包含，且绝不能附带反例
        job = self.h.submit({"alphabet": "ab", "left": EXAMPLE_RIGHT, "right": EXAMPLE_RIGHT})
        body = self.h.wait_done(job)
        self.assertEqual(body["status"], "done")
        result = body["result"]
        self.assertTrue(result["contained"])
        self.assertIsNone(result["counterexample"])

    def test_counterexample_replay_data(self):
        # 默认示例：左含 q1 自环接受 a^ω 分支，右语言要求至少一个 b => 不包含
        job = self.h.submit({"alphabet": "ab", "left": EXAMPLE_LEFT, "right": EXAMPLE_RIGHT})
        body = self.h.wait_done(job)
        self.assertEqual(body["status"], "done")
        result = body["result"]
        self.assertFalse(result["contained"])
        ce = result["counterexample"]
        self.assertTrue(ce["cycle"])  # 环非空
        self.assertEqual(ce["cycle_word"], "a")
        # 每一步都含两侧状态链字段
        for step in ce["prefix"] + ce["cycle"]:
            self.assertEqual(set(step), {"letter", "left_from", "left_to", "right_from", "right_to"})
        # 环尾状态与环首状态一致（可无限重复闭合）
        first, last = ce["cycle"][0], ce["cycle"][-1]
        self.assertEqual((first["left_from"], first["right_from"]),
                         (last["left_to"], last["right_to"]))

    def test_validation_errors_collected(self):
        bad_right = {
            "states": "p0 p1",
            "initial": "p0",
            "accepting": "p1",
            "transitions": "p0 a -> px",  # 悬空目标 + 缺三条迁移
        }
        job = self.h.submit({"alphabet": "ab", "left": EXAMPLE_LEFT, "right": bad_right})
        body = self.h.wait_done(job)
        self.assertEqual(body["status"], "error")
        joined = "\n".join(body["errors"])
        self.assertIn("px", joined)
        self.assertIn("p0 --b-->", joined)
        self.assertIn("p1 --a-->", joined)
        self.assertIn("p1 --b-->", joined)
        self.assertGreaterEqual(len(body["errors"]), 4)

    def test_errors_from_both_sides_collected_at_once(self):
        bad_left = {
            "states": "q0",
            "initial": "q0",
            "accepting": "qx",          # 悬空接受态
            "transitions": "q0 a -> q0",
        }
        bad_right = {
            "states": "p0",
            "initial": "p0",
            "accepting": "p0",
            "transitions": "p0 a -> py",  # 悬空目标 + 缺 b 迁移
        }
        job = self.h.submit({"alphabet": "ab", "left": bad_left, "right": bad_right})
        body = self.h.wait_done(job)
        self.assertEqual(body["status"], "error")
        joined = "\n".join(body["errors"])
        self.assertIn("左侧", joined)
        self.assertIn("'qx'", joined)
        self.assertIn("右侧", joined)
        self.assertIn("'py'", joined)
        self.assertIn("p0 --b-->", joined)

    def test_bad_json_rejected(self):
        req = urllib.request.Request(
            self.h.url("/api/verify"),
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("应当返回 400")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_stale_job_does_not_overwrite_current(self):
        # 连续提交两个作业：旧作业号查询应被判过期（409），当前作业结论不受影响
        first = self.h.submit({"alphabet": "ab", "left": EXAMPLE_LEFT, "right": EXAMPLE_RIGHT})
        second_payload = {"alphabet": "ab", "left": EXAMPLE_RIGHT, "right": EXAMPLE_RIGHT}
        second = self.h.submit(second_payload)
        self.assertGreater(second, first)

        # 等第二个（当前）作业完成
        body2 = self.h.wait_done(second)
        self.assertTrue(body2["result"]["contained"])

        # 旧作业号已无法取到结果 —— 它不能覆盖当前结论
        status, body = self.h.request(f"/api/jobs/{first}")
        self.assertEqual(status, 409)
        self.assertEqual(body["status"], "stale")

        # 当前作业仍可查询，结论不变
        status, body = self.h.request(f"/api/jobs/{second}")
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["contained"])

    def test_background_race_stale_computation_dropped(self):
        # 拉长单次计算：先提交作业 1，随即提交作业 2。
        # 作业 1 在作业 2 之后才执行完，其结果必须被丢弃，绝不能覆盖作业 2。
        import app.server as srv
        from app.server import JobManager

        manager = JobManager()
        self.addCleanup(lambda: manager._executor.shutdown(wait=False))

        def slow_evaluate(payload):
            time.sleep(0.35)
            return {"contained": payload["marker"], "counterexample": None, "stats": {}}

        original = srv._evaluate
        srv._evaluate = slow_evaluate
        try:
            j1 = manager.submit({"marker": False})  # 期望的“旧”结论：不包含
            time.sleep(0.05)
            j2 = manager.submit({"marker": True})   # 当前结论：包含
            self.assertGreater(j2, j1)

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                job2 = manager.get(j2)
                if job2 is not None and job2.status == "done":
                    break
                time.sleep(0.02)
            else:
                self.fail("当前作业未在时限内完成")
        finally:
            srv._evaluate = original

        # 给作业 1 的过期回调一个落定窗口
        time.sleep(0.1)
        # 旧作业号已过期，无法查询
        self.assertIsNone(manager.get(j1))
        # 当前作业结论为作业 2 的结果，未被作业 1 覆盖
        self.assertTrue(manager.get(j2).result["contained"])
        left = {
            "states": "q0 q1 q2",
            "initial": "q0",
            "accepting": "q2",
            "transitions": (
                "q0 a -> q1 q2\n"
                "q0 b -> q1\n"
                "q1 a -> q1\n"
                "q1 b -> q1\n"
                "q2 a -> q2\n"
                "q2 b -> q1"
            ),
        }
        right = {
            "states": "p0 p1 p2",
            "initial": "p0",
            "accepting": "p1",
            "transitions": (
                "p0 a -> p0\n"
                "p0 b -> p1\n"
                "p1 a -> p2\n"
                "p1 b -> p1\n"
                "p2 a -> p2\n"
                "p2 b -> p1"
            ),
        }
        job = self.h.submit({"alphabet": "ab", "left": left, "right": right})
        body = self.h.wait_done(job)
        result = body["result"]
        self.assertFalse(result["contained"])
        ce = result["counterexample"]
        self.assertEqual(ce["prefix_word"], "a")
        self.assertEqual(ce["cycle_word"], "a")
        self.assertEqual(ce["cycle"][-1]["left_to"], "q2")


if __name__ == "__main__":
    unittest.main()
