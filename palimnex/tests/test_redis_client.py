from __future__ import annotations

import io
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from palimnex import core
from palimnex.durable import HOT_STREAM_MAXLEN


class RedisClientBoundaryTests(unittest.TestCase):
    def test_tcp_port_zero_is_rejected(self) -> None:
        with self.assertRaisesRegex(core.RedisError, "between 1 and 65535"):
            core.RedisClient("redis://127.0.0.1:0/0")

    def test_plaintext_remote_and_unauthenticated_writes_are_refused(self) -> None:
        with self.assertRaisesRegex(core.RedisError, "loopback"):
            core.RedisClient("redis://198.51.100.9:6379/0")
        local = core.RedisClient("redis://127.0.0.1:6379/0")
        with self.assertRaisesRegex(core.RedisError, "cache writes require"):
            local.require_trusted_write_endpoint()
        authenticated = core.RedisClient("redis://:synthetic-password@127.0.0.1:6379/0")
        authenticated.require_trusted_write_endpoint()
        with self.assertRaisesRegex(core.RedisError, "authentication"):
            core.RedisClient("rediss://cache.example.invalid:6379/0")

    def test_plaintext_localhost_is_rejected_before_resolution_or_socket_io(self) -> None:
        with mock.patch.object(
            core.socket,
            "getaddrinfo",
            side_effect=AssertionError("mutable hostname was resolved"),
        ) as resolver, mock.patch.object(
            core.socket,
            "create_connection",
            side_effect=AssertionError("socket connection was attempted"),
        ) as connector:
            with self.assertRaisesRegex(core.RedisError, "explicit loopback"):
                core.RedisClient(
                    "redis://:synthetic-password@localhost:6379/0"
                )
        resolver.assert_not_called()
        connector.assert_not_called()

    def test_plaintext_peer_mismatch_closes_before_auth_or_command_bytes(self) -> None:
        class MismatchedPeerSocket:
            def __init__(self) -> None:
                self.sent = bytearray()
                self.closed = False

            def getpeername(self):
                return ("198.51.100.9", 6379)

            def sendall(self, payload: bytes) -> None:
                self.sent.extend(payload)

            def close(self) -> None:
                self.closed = True

        connection = MismatchedPeerSocket()
        client = core.RedisClient(
            "redis://:synthetic-password@127.0.0.1:6379/0"
        )
        with mock.patch.object(
            core.socket, "create_connection", return_value=connection
        ) as connector:
            with self.assertRaisesRegex(core.RedisError, "non-loopback peer"):
                client.execute("PING")

        connector.assert_called_once_with(("127.0.0.1", 6379), client.timeout)
        self.assertTrue(connection.closed)
        self.assertEqual(connection.sent, b"")

    def test_unix_socket_write_guard_requires_owner_only_real_socket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "redis.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(server.close)
            server.bind(str(path))
            os.chmod(path, 0o600)
            client = core.RedisClient(f"redis+unix://{path}?db=0")
            client.require_trusted_write_endpoint()
            os.chmod(path, 0o666)
            with self.assertRaisesRegex(core.RedisError, "owner-only"):
                client.require_trusted_write_endpoint()

    def test_resp_parser_rejects_oversize_and_excessive_depth(self) -> None:
        oversized_bulk = io.BytesIO(f"${core.MAX_RESP_BULK_BYTES + 1}\r\n".encode())
        with self.assertRaisesRegex(core.RedisError, "bulk length"):
            core.RedisClient._read(oversized_bulk)
        oversized_array = io.BytesIO(f"*{core.MAX_RESP_ARRAY_ITEMS + 1}\r\n".encode())
        with self.assertRaisesRegex(core.RedisError, "array length"):
            core.RedisClient._read(oversized_array)
        with self.assertRaisesRegex(core.RedisError, "nesting"):
            core.RedisClient._read(io.BytesIO(b"+OK\r\n"), core.MAX_RESP_DEPTH + 1)
        client = core.RedisClient("redis://127.0.0.1:6379/0")
        commands = [("PING",)] * (core.MAX_PIPELINE_COMMANDS + 1)
        with self.assertRaisesRegex(core.RedisError, "command count"):
            client.execute_many(commands)

    def test_resp_parser_enforces_aggregate_item_and_byte_limits(self) -> None:
        with mock.patch.object(core, "MAX_RESP_TOTAL_ITEMS", 3):
            self.assertEqual(
                core.RedisClient._read(io.BytesIO(b"*2\r\n:1\r\n:2\r\n")),
                [1, 2],
            )
            with self.assertRaisesRegex(core.RedisError, "aggregate configured limit"):
                core.RedisClient._read(io.BytesIO(b"*3\r\n:1\r\n:2\r\n:3\r\n"))
        with mock.patch.object(core, "MAX_RESP_TOTAL_BYTES", 9):
            self.assertEqual(core.RedisClient._read(io.BytesIO(b"$3\r\nabc\r\n")), b"abc")
            with self.assertRaisesRegex(core.RedisError, "aggregate configured limit"):
                core.RedisClient._read(io.BytesIO(b"$4\r\nabcd\r\n"))

    def test_exact_hot_stream_cap_fits_the_aggregate_resp_budget(self) -> None:
        def bulk(value: bytes) -> bytes:
            return b"$%d\r\n%s\r\n" % (len(value), value)

        fields = (
            b"event", b"e" * 32,
            b"session", b"s" * 32,
            b"kind", b"7",
            b"subject", b"a" * 64,
            b"observed", b"1",
            b"supersedes", b"",
            b"contradicts", b"",
            b"trust", b"1",
            b"sensitivity", b"0",
            b"digest", b"d" * 64,
        )
        encoded_fields = b"*20\r\n" + b"".join(bulk(value) for value in fields)
        records = []
        for index in range(HOT_STREAM_MAXLEN):
            stream_id = f"{index + 1}-0".encode("ascii")
            records.append(b"*2\r\n" + bulk(stream_id) + encoded_fields)
        response = (
            f"*{HOT_STREAM_MAXLEN}\r\n".encode("ascii") + b"".join(records)
        )

        parsed = core.RedisClient._read(io.BytesIO(response))

        self.assertEqual(len(parsed), HOT_STREAM_MAXLEN)
        self.assertEqual(parsed[0][0], b"1-0")
        self.assertEqual(parsed[-1][0], f"{HOT_STREAM_MAXLEN}-0".encode("ascii"))
        self.assertEqual(1 + HOT_STREAM_MAXLEN * 23, 94_209)
        self.assertLess(1 + HOT_STREAM_MAXLEN * 23, core.MAX_RESP_TOTAL_ITEMS)
        self.assertGreater(1 + (HOT_STREAM_MAXLEN + 1) * 23, 94_209)

    def test_resp_reader_uses_one_absolute_deadline_for_slow_trickle(self) -> None:
        class OneByteSocket:
            def __init__(self, connection: socket.socket):
                self.connection = connection
                self.timeouts: list[float] = []

            def settimeout(self, value: float) -> None:
                self.timeouts.append(value)
                self.connection.settimeout(value)

            def recv(self, size: int) -> bytes:
                return self.connection.recv(min(size, 1))

        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        right.sendall(b"+OK\r\n")
        wrapped = OneByteSocket(left)
        with mock.patch.object(
            core.time,
            "monotonic",
            side_effect=[100.0, 100.01, 100.02, 100.04, 100.051],
        ):
            reader = core._DeadlineSocketReader(wrapped, 0.05)
            with self.assertRaisesRegex(core.RedisError, "absolute deadline"):
                core.RedisClient._read(reader)
        self.assertEqual(len(wrapped.timeouts), 3)
        self.assertGreater(wrapped.timeouts[0], wrapped.timeouts[1])
        self.assertGreater(wrapped.timeouts[1], wrapped.timeouts[2])


if __name__ == "__main__":
    unittest.main()
