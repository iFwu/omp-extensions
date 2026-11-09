"""Exercise real curl retries and verification of restored host files."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import runpy
import tempfile
import threading
import unittest

installer = runpy.run_path(str(Path(__file__).resolve().parents[1] / "ci-omp.py"))


class CIHostTests(unittest.TestCase):
    def test_transient_download_failure_is_retried_before_checksum_verification(self):
        asset = "omp-linux-x64"
        payload = b"official-host-fixture"
        checksum = f"{hashlib.sha256(payload).hexdigest()}  {asset}\n".encode()
        attempts = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                attempts.append(self.path)
                if self.path == f"/{asset}" and attempts.count(self.path) == 1:
                    self.send_error(503)
                    return
                body = payload if self.path == f"/{asset}" else checksum
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer["download"](root, asset, f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(installer["verify"](root, asset).read_bytes(), payload)
            self.assertEqual(attempts.count(f"/{asset}"), 2)
            self.assertEqual(list(root.glob("*.download")), [])

    def test_restored_host_is_rejected_when_its_bytes_change(self):
        asset = "omp-darwin-arm64"
        payload = b"verified-host-fixture"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / asset
            binary.write_bytes(payload)
            (root / "SHA256SUMS.txt").write_text(f"{hashlib.sha256(payload).hexdigest()}  {asset}\n")
            self.assertEqual(installer["verify"](root, asset), binary)
            binary.write_bytes(b"corrupt-cached-host")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                installer["verify"](root, asset)


if __name__ == "__main__":
    unittest.main()
