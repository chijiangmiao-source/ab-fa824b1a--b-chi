"""HTTP 层端到端测试：后台任务轮询、过期防护、校验边界、健康地址。"""

import json
import os
import sys
import threading
import time
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import server as srv  # noqa: E402


def _post(url, obj):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


def _wait_job(base, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while True:
        _, body = _get(f"{base}/api/jobs/{job_id}")
        job = json.loads(body)
        if job["status"] in ("done", "superseded"):
            return job
        if time.time() > deadline:
            raise AssertionError("任务超时未完成")
        time.sleep(0.02)


GOOD_INCLUDED = {
    "alphabet": "a",
    "left": {
        "states": "q",
        "initial": "q",
        "accepting": "q",
        "transitions": [{"source": "q", "letter": "a", "target": "q"}],
    },
    "right": {
        "states": "r",
        "initial": "r",
        "accepting": "r",
        "transitions": [{"source": "r", "letter": "a", "target": "r"}],
    },
}


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        srv.MANAGER = srv.JobManager()
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_health(self):
        status, body = _get(f"{self.base}/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_index_and_js_served(self):
        status, html = _get(self.base + "/")
        self.assertEqual(status, 200)
        self.assertIn("Büchi", html)
        status, js = _get(self.base + "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("submitForVerification", js)

    def test_inclusion_included_no_fake_counterexample(self):
        status, body = _post(f"{self.base}/api/verify", GOOD_INCLUDED)
        self.assertEqual(status, 202)
        job = _wait_job(self.base, body["job_id"])
        self.assertEqual(job["status"], "done")
        self.assertTrue(job["result"]["included"])
        self.assertNotIn("counterexample", job["result"])

    def test_counterexample_is_replayable(self):
        payload = json.loads(json.dumps(GOOD_INCLUDED))
        payload["right"]["accepting"] = ""
        status, body = _post(f"{self.base}/api/verify", payload)
        self.assertEqual(status, 202)
        job = _wait_job(self.base, body["job_id"])
        self.assertFalse(job["result"]["included"])
        ce = job["result"]["counterexample"]
        self.assertEqual(ce["cycle_letters"], ["a"])
        self.assertEqual(ce["left_cycle_states"][0], ce["left_cycle_states"][-1])
        self.assertEqual(
            ce["right_cycle_states"][0], ce["right_cycle_states"][-1]
        )
        self.assertIn("(a)", ce["word"])

    def test_nondeterministic_branch_accepted_in_background(self):
        payload = {
            "alphabet": "a",
            "left": {
                "states": "q0 q1 q2",
                "initial": "q0",
                "accepting": "q1",
                "transitions": [
                    {"source": "q0", "letter": "a", "target": "q1, q2"},
                    {"source": "q1", "letter": "a", "target": "q1"},
                    {"source": "q2", "letter": "a", "target": "q2"},
                ],
            },
            "right": {
                "states": "r",
                "initial": "r",
                "accepting": "",
                "transitions": [
                    {"source": "r", "letter": "a", "target": "r"}
                ],
            },
        }
        status, body = _post(f"{self.base}/api/verify", payload)
        self.assertEqual(status, 202)
        job = _wait_job(self.base, body["job_id"])
        self.assertFalse(job["result"]["included"])
        self.assertIn("q1", job["result"]["counterexample"]["left_cycle_states"])

    def test_validation_boundaries_returned_together(self):
        # 缺迁移 + 悬空接受态 + 非 ASCII 字母表：一次列全
        payload = {
            "alphabet": "aé",
            "left": {
                "states": "q",
                "initial": "q",
                "accepting": "qz",
                "transitions": [],
            },
            "right": {
                "states": "r",
                "initial": "r",
                "accepting": "",
                "transitions": [],
            },
        }
        status, body = _post(f"{self.base}/api/verify", payload)
        self.assertEqual(status, 400)
        joined = "\n".join(body["errors"])
        self.assertIn("ASCII", joined)
        self.assertIn("缺少迁移", joined)
        self.assertIn("qz", joined)
        self.assertGreaterEqual(len(body["errors"]), 3)

    def test_bad_json(self):
        req = urllib.request.Request(
            f"{self.base}/api/verify",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_unknown_job_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base}/api/jobs/nope", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_stale_job_does_not_overwrite_newer(self):
        # 连续提交多个任务：每个任务结果按键隔离，旧任务结果永不写入新任务；
        # 排队中被超越的任务标记 superseded（或正常完成但互不干扰）。
        jobs = []
        for i in range(6):
            payload = json.loads(json.dumps(GOOD_INCLUDED))
            # 偶数包含、奇数不包含，交替制造不同结论
            if i % 2 == 1:
                payload["right"]["accepting"] = ""
            status, body = _post(f"{self.base}/api/verify", payload)
            self.assertEqual(status, 202)
            jobs.append((i, body["job_id"]))

        results = {}
        for i, job_id in jobs:
            job = _wait_job(self.base, job_id)
            results[i] = job
            expected_included = i % 2 == 0
            if job["status"] == "done":
                self.assertEqual(
                    job["result"]["included"],
                    expected_included,
                    msg=f"任务 {i} 的结论被过期计算覆盖",
                )
        # 结果对象互不相同，确认按键隔离
        done_jobs = [j for j in results.values() if j["status"] == "done"]
        ids = {j["job_id"] for j in done_jobs}
        self.assertEqual(len(ids), len(done_jobs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
