"""The real SDK against a stub HTTP server on localhost, with a fake key. No request leaves this machine.

Skipped unless the SDK is importable, so run it with .venv/bin/python -m unittest tests.test_llm_live_client.
The stub stands in for the API, so its results are labelled fake too.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from st2fb import fbt
from st2fb.llm import benchmark
from st2fb.llm.client import FAKE, FatalApiError, LlmRequest, TransientApiError
from st2fb.llm.config import FALLBACK_BETA, LlmConfig, UsageEntry, cost_usd
from st2fb.translate import translate_source

HAS_SDK = importlib.util.find_spec("anthropic") is not None
FAKE_KEY = "sk-ant-FAKE-KEY-FOR-TESTS-0123456789"
REPO = Path(__file__).resolve().parent.parent
LATCH = fbt.write_fbt(translate_source((REPO / "corpus/00_latch/program.st").read_text()))


def message(content=None, stop_reason="end_turn", usage=None, model="claude-sonnet-5-5", **extra):
    return {
        "id": "msg_stub",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content if content is not None else [{"type": "text", "text": "hello"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 10, "output_tokens": 20},
        **extra,
    }


class Stub:
    """Replies with (status, body, headers) in order, repeating the last one."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                stub.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status, payload, headers = stub.replies.pop(0) if len(stub.replies) > 1 else stub.replies[0]
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.send_header("request-id", "req_stub")
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def request(config=None):
    return LlmRequest(system="SYSTEM TEXT", user="USER TEXT", config=config or LlmConfig(), tag="t")


@unittest.skipUnless(HAS_SDK, "needs the SDK: run with .venv/bin/python")
class LiveClientAgainstStub(unittest.TestCase):
    def client(self, *replies):
        from st2fb.llm.live_client import AnthropicClient

        stub = Stub(replies)
        self.addCleanup(stub.close)
        return AnthropicClient(FAKE_KEY, base_url=stub.url, kind=FAKE), stub

    def test_request_shape(self):
        client, stub = self.client((200, message(), {}))
        client.complete(request())
        sent = stub.requests[0]
        self.assertEqual(sent["path"], "/v1/messages")
        self.assertEqual(sent["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertIn(FALLBACK_BETA, sent["headers"]["anthropic-beta"])
        body = sent["body"]
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["max_tokens"], 16000)
        self.assertEqual(body["output_config"], {"effort": "medium"})
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["system"], [{"type": "text", "text": "SYSTEM TEXT", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(body["messages"], [{"role": "user", "content": "USER TEXT"}])
        # The skill: these return a 400 on these models.
        for field in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
            self.assertNotIn(field, body)

    def test_fallback_can_be_turned_off(self):
        client, stub = self.client((200, message(), {}))
        client.complete(request(LlmConfig(fallbacks=False)))
        self.assertNotIn("fallbacks", stub.requests[0]["body"])
        self.assertNotIn(FALLBACK_BETA, stub.requests[0]["headers"].get("anthropic-beta", ""))

    def test_opus_and_effort_are_passed(self):
        client, stub = self.client((200, message(model="claude-opus-5-5"), {}))
        client.complete(request(LlmConfig("claude-opus-5-5", "high")))
        self.assertEqual(stub.requests[0]["body"]["model"], "claude-opus-5-5")
        self.assertEqual(stub.requests[0]["body"]["output_config"], {"effort": "high"})

    def test_the_environment_supplies_neither_key_nor_address(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key", "ANTHROPIC_AUTH_TOKEN": "env-token", "ANTHROPIC_BASE_URL": "http://127.0.0.1:1"}):
            client, stub = self.client((200, message(), {}))
            client.complete(request())
        # This SDK sends an API key as a bearer token, per API version 2026-10-21.
        self.assertEqual(stub.requests[0]["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertNotIn("x-api-key", {name.lower() for name in stub.requests[0]["headers"]})

    def test_text_usage_and_request_id(self):
        usage = {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4}
        thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
        client, _ = self.client((200, message([thinking, {"type": "text", "text": "answer"}], usage=usage), {}))
        response = client.complete(request())
        self.assertEqual(response.text, "answer")
        self.assertEqual(response.usage, (UsageEntry("claude-sonnet-5-5", 10, 20, 3, 4),))
        self.assertEqual(response.request_id, "req_stub")
        self.assertFalse(response.fell_back)

    def test_refusal(self):
        details = {"type": "refusal", "category": "cyber", "explanation": "x"}
        client, _ = self.client((200, message([], "refusal", stop_details=details), {}))
        response = client.complete(request())
        self.assertEqual(response.stop_reason, "refusal")
        self.assertEqual(response.refusal_category, "cyber")
        self.assertEqual(response.text, "")

    def test_max_tokens(self):
        client, _ = self.client((200, message([{"type": "text", "text": "<FBType"}], "max_tokens"), {}))
        self.assertEqual(client.complete(request()).stop_reason, "max_tokens")

    def test_fallback_uses_iterations_for_cost_and_drops_declined_text(self):
        content = [
            {"type": "text", "text": "partial from the declined model"},
            {"type": "fallback", "from": {"model": "claude-sonnet-5-5"}, "to": {"model": "claude-sonnet-5"}},
            {"type": "text", "text": "answer"},
        ]
        usage = {
            "input_tokens": 100,
            "output_tokens": 200,
            "iterations": [
                {"type": "message", "input_tokens": 100, "output_tokens": 7, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                {"type": "fallback_message", "model": "claude-sonnet-5", "input_tokens": 100, "output_tokens": 200, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            ],
        }
        client, _ = self.client((200, message(content, usage=usage, model="claude-sonnet-5"), {}))
        response = client.complete(request())
        self.assertEqual(response.text, "answer")
        self.assertTrue(response.fell_back)
        self.assertEqual(response.served_by, "claude-sonnet-5")
        self.assertEqual([entry.model for entry in response.usage], ["claude-sonnet-5-5", "claude-sonnet-5"])
        self.assertAlmostEqual(cost_usd(response.usage), (100 * 2 + 7 * 10 + 100 * 2 + 200 * 10) / 1e6)

    def error(self, status, message_text="bad", headers=None):
        return (status, {"type": "error", "error": {"type": "x", "message": message_text}}, headers or {})

    def test_rate_limit_is_transient_and_carries_retry_after(self):
        client, stub = self.client(self.error(429, headers={"retry-after": "7"}))
        with self.assertRaises(TransientApiError) as caught:
            client.complete(request())
        self.assertEqual(caught.exception.retry_after, 7.0)
        self.assertFalse(caught.exception.billed_unknown)
        self.assertEqual(len(stub.requests), 1, "the SDK must not retry on its own: the ledger could not see it")

    def test_retry_after_in_date_form_or_absurdly_long(self):
        client, _ = self.client(self.error(429, headers={"retry-after": "Fri, 06 Nov 2026 12:00:00 GMT"}))
        with self.assertRaises(TransientApiError) as caught:
            client.complete(request())
        self.assertIsNone(caught.exception.retry_after)
        client, _ = self.client(self.error(429, headers={"retry-after": "86400"}))
        with self.assertRaises(TransientApiError) as caught:
            client.complete(request())
        self.assertEqual(caught.exception.retry_after, 120.0)

    def test_server_errors_are_transient(self):
        for status in (500, 529):
            client, stub = self.client(self.error(status))
            with self.assertRaises(TransientApiError):
                client.complete(request())
            self.assertEqual(len(stub.requests), 1)

    def test_client_errors_are_fatal(self):
        for status in (400, 401, 402, 403, 404, 413):
            client, _ = self.client(self.error(status))
            with self.assertRaises(FatalApiError):
                client.complete(request())

    def test_key_echoed_by_the_server_is_redacted(self):
        for status, expected in ((401, FatalApiError), (500, TransientApiError)):
            client, _ = self.client(self.error(status, f"invalid x-api-key {FAKE_KEY}"))
            with self.assertRaises(expected) as caught:
                client.complete(request())
            self.assertNotIn(FAKE_KEY, str(caught.exception))
            self.assertIn("[REDACTED]", str(caught.exception))

    def test_lost_connection_may_have_been_billed(self):
        from st2fb.llm.live_client import AnthropicClient

        client = AnthropicClient(FAKE_KEY, base_url="http://127.0.0.1:1", kind=FAKE)
        with self.assertRaises(TransientApiError) as caught:
            client.complete(request())
        self.assertTrue(caught.exception.billed_unknown)
        self.assertNotIn(FAKE_KEY, str(caught.exception))


def docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@unittest.skipUnless(HAS_SDK and docker_available(), "needs the SDK and Docker")
class KeyNeverReachesAnyOutput(unittest.TestCase):
    """The whole --live path, with a temp .env, the real SDK, the stub server, real FORTE and matiec."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st2fb-llm-key-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env_file = self.tmp / "test.env"
        self.env_file.write_text(f"ST2FB_ANTHROPIC_API_KEY={FAKE_KEY}\n")

    def run_live(self, stub, *extra):
        from st2fb.llm.keys import load_api_key
        from st2fb.llm.live_client import AnthropicClient

        def make(path):
            return AnthropicClient(load_api_key(path), base_url=stub.url, kind=FAKE)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(benchmark, "make_live_client", make), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = benchmark.main([
                "--live", "--budget-usd", "5", "--env-file", str(self.env_file), "--programs", "00_latch",
                "--modes", "llm_repair", "--out-dir", str(self.tmp / "out"), *extra,
            ])  # fmt: skip
        return code, out.getvalue() + err.getvalue()

    def assert_key_absent(self, output):
        self.assertNotIn(FAKE_KEY, output)
        files = [path for path in (self.tmp / "out").rglob("*") if path.is_file()]
        self.assertTrue(files)
        for path in files:
            self.assertNotIn(FAKE_KEY.encode(), path.read_bytes(), path)

    def test_after_a_successful_run(self):
        stub = Stub([(200, message([{"type": "text", "text": LATCH}]), {})])
        self.addCleanup(stub.close)
        code, output = self.run_live(stub)
        self.assertEqual(code, 0)
        self.assertEqual(stub.requests[0]["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        document = json.loads((self.tmp / "out/benchmark.json").read_text())
        self.assertTrue(next(r for r in document["results"] if r["mode"] == "llm_repair")["passed"])
        self.assert_key_absent(output)

    def test_after_an_error_that_echoes_the_key(self):
        stub = Stub([(401, {"type": "error", "error": {"type": "authentication_error", "message": f"bad key {FAKE_KEY}"}}, {})])
        self.addCleanup(stub.close)
        code, output = self.run_live(stub)
        self.assertEqual(code, benchmark.EXIT_API)
        self.assertIn("[REDACTED]", output)
        self.assert_key_absent(output)
        document = json.loads((self.tmp / "out/benchmark.json").read_text())
        self.assertIn("API error", document["stopped"])


if __name__ == "__main__":
    unittest.main()
