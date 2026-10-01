from __future__ import annotations

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path


PROXY_PATH = Path(__file__).resolve().parents[1] / "deploy" / "audiobookshelf-player-port80-proxy"


def load_proxy_module():
    loader = importlib.machinery.SourceFileLoader("port80_proxy", str(PROXY_PATH))
    spec = importlib.util.spec_from_loader("port80_proxy", loader)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load port 80 proxy module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def read1(self, _size: int) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class FakeWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.flushes = 0

    def write(self, chunk: bytes) -> None:
        self.data.extend(chunk)

    def flush(self) -> None:
        self.flushes += 1


class Port80ProxyTest(unittest.TestCase):
    def test_target_path_preserves_sse_path(self) -> None:
        proxy = load_proxy_module()
        handler = object.__new__(proxy.ProxyHandler)
        handler.command = "GET"
        handler.path = "/player/events"

        self.assertEqual(handler.target_path(), "/player/events")

    def test_stream_response_flushes_each_chunk(self) -> None:
        proxy = load_proxy_module()
        handler = object.__new__(proxy.ProxyHandler)
        handler.wfile = FakeWriter()

        handler.stream_response(FakeResponse([b"data: one\n\n", b"data: two\n\n"]))

        self.assertEqual(handler.wfile.data, b"data: one\n\ndata: two\n\n")
        self.assertEqual(handler.wfile.flushes, 2)


if __name__ == "__main__":
    unittest.main()
