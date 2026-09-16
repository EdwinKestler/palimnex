"""Small in-memory RESP-command double used by the v2.5 test suite.

It deliberately implements only commands exercised by the Palimnex
cache and projection code.  Tests must fail when production starts relying on
an unmodelled Redis command instead of silently accepting it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import time
from typing import Any


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.hashes: dict[str, dict[str, bytes]] = {}
        self.expiries: dict[str, float] = {}
        self.streams: dict[str, list[dict[str, bytes]]] = {}
        self.stream_ids: dict[str, list[bytes]] = {}
        self.stream_counters: dict[str, int] = {}
        self.commands: list[tuple[Any, ...]] = []
        self.trusted_write_checks = 0

    @staticmethod
    def _text(value: str | bytes | int) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    @staticmethod
    def _bytes(value: str | bytes | int) -> bytes:
        return value if isinstance(value, bytes) else str(value).encode("utf-8")

    def require_trusted_write_endpoint(self) -> None:
        self.trusted_write_checks += 1

    def _expire(self, key: str) -> None:
        deadline = self.expiries.get(key)
        if deadline is not None and deadline <= time.monotonic():
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.streams.pop(key, None)
            self.stream_ids.pop(key, None)
            self.stream_counters.pop(key, None)
            self.expiries.pop(key, None)

    def _get(self, key: str) -> bytes | None:
        self._expire(key)
        return self.values.get(key)

    def _set(self, key: str, value: str | bytes | int) -> None:
        self.values[key] = self._bytes(value)
        self.expiries.pop(key, None)

    def execute_many(self, commands: list[tuple[str | bytes, ...]]) -> list[Any]:
        return [self.execute(*command) for command in commands]

    def execute(self, command: str | bytes, *args: str | bytes) -> Any:
        name = self._text(command).upper()
        self.commands.append((name, *args))
        if name == "GET":
            return self._get(self._text(args[0]))
        if name == "MGET":
            return [self._get(self._text(key)) for key in args]
        if name == "SET":
            return self._execute_set(args)
        if name == "DEL":
            deleted = 0
            for raw_key in args:
                key = self._text(raw_key)
                self._expire(key)
                if key in self.values:
                    deleted += 1
                    del self.values[key]
                if key in self.hashes:
                    deleted += 1
                    del self.hashes[key]
                if key in self.streams:
                    deleted += 1
                    del self.streams[key]
                    self.stream_ids.pop(key, None)
                    self.stream_counters.pop(key, None)
                self.expiries.pop(key, None)
            return deleted
        if name == "EXISTS":
            key = self._text(args[0])
            return int(
                self._get(key) is not None
                or key in self.hashes
                or key in self.streams
            )
        if name == "HLEN":
            key = self._text(args[0])
            self._expire(key)
            return len(self.hashes.get(key, {}))
        if name == "HMGET":
            key = self._text(args[0])
            self._expire(key)
            values = self.hashes.get(key, {})
            return [values.get(self._text(field)) for field in args[1:]]
        if name == "HSCAN":
            key = self._text(args[0])
            self._expire(key)
            values = self.hashes.get(key, {})
            flat: list[bytes] = []
            for field, value in sorted(values.items()):
                flat.extend((field.encode("ascii"), value))
            return [b"0", flat]
        if name == "XREVRANGE":
            if (
                len(args) != 5
                or self._text(args[1]) != "+"
                or self._text(args[2]) != "-"
                or self._text(args[3]).upper() != "COUNT"
            ):
                raise AssertionError(
                    "FakeRedis implements only bounded XREVRANGE key + - COUNT n"
                )
            key = self._text(args[0])
            self._expire(key)
            count = int(self._text(args[4]))
            records = self.streams.get(key, [])
            identifiers = self._stream_identifiers(key, records)
            response = []
            for index in range(len(records) - 1, max(-1, len(records) - count - 1), -1):
                flat: list[bytes] = []
                for field, value in records[index].items():
                    flat.extend((field.encode("ascii"), value))
                response.append([identifiers[index], flat])
            return response
        if name == "XRANGE":
            if (
                len(args) != 5
                or self._text(args[3]).upper() != "COUNT"
            ):
                raise AssertionError(
                    "FakeRedis implements only bounded XRANGE key start end COUNT n"
                )
            key = self._text(args[0])
            self._expire(key)
            start = self._bytes(args[1])
            end = self._bytes(args[2])
            count = int(self._text(args[4]))
            records = self.streams.get(key, [])
            identifiers = self._stream_identifiers(key, records)
            if start == b"-" and end == b"+":
                selected = list(zip(identifiers, records))[:count]
            elif start == end and count == 1:
                selected = [
                    (identifier, record)
                    for identifier, record in zip(identifiers, records)
                    if identifier == start
                ][:1]
            else:
                raise AssertionError(
                    "FakeRedis XRANGE supports only exact id COUNT 1 or - + COUNT n"
                )
            response = []
            for identifier, record in selected:
                flat: list[bytes] = []
                for field, value in record.items():
                    flat.extend((field.encode("ascii"), value))
                response.append([identifier, flat])
            return response
        if name == "MEMORY":
            if len(args) not in {2, 4} or self._text(args[0]).upper() != "USAGE":
                raise AssertionError("FakeRedis implements only MEMORY USAGE")
            if len(args) == 4 and (
                self._text(args[2]).upper() != "SAMPLES"
                or self._text(args[3]) != "0"
            ):
                raise AssertionError("FakeRedis MEMORY USAGE requires SAMPLES 0")
            key = self._text(args[1])
            self._expire(key)
            key_bytes = len(key.encode("utf-8"))
            if key in self.values:
                return max(1, key_bytes + len(self.values[key]))
            if key in self.hashes:
                return max(
                    1,
                    key_bytes
                    + sum(
                        len(field.encode("utf-8")) + len(value)
                        for field, value in self.hashes[key].items()
                    ),
                )
            if key in self.streams:
                return max(
                    1,
                    key_bytes
                    + sum(
                        sum(len(field.encode("utf-8")) + len(value) for field, value in row.items())
                        for row in self.streams[key]
                    ),
                )
            return None
        if name == "INCR":
            key = self._text(args[0])
            value = int(self._get(key) or b"0") + 1
            self._set(key, value)
            return value
        if name == "DECR":
            key = self._text(args[0])
            value = int(self._get(key) or b"0") - 1
            self._set(key, value)
            return value
        if name == "PEXPIRE":
            key = self._text(args[0])
            if self._get(key) is None:
                return 0
            self.expiries[key] = time.monotonic() + int(self._text(args[1])) / 1_000
            return 1
        if name == "EXPIRE":
            key = self._text(args[0])
            self._expire(key)
            if key not in self.values and key not in self.hashes and key not in self.streams:
                return 0
            self.expiries[key] = time.monotonic() + int(self._text(args[1]))
            return 1
        if name == "KEYS":
            pattern = self._text(args[0])
            keys = set(self.values) | set(self.hashes) | set(self.streams)
            return [key.encode() for key in sorted(keys) if fnmatch.fnmatch(key, pattern)]
        if name == "EVAL":
            return self._eval(args)
        raise AssertionError(f"FakeRedis does not implement {name}")

    def _stream_identifiers(
        self, key: str, records: list[dict[str, bytes]]
    ) -> list[bytes]:
        identifiers = self.stream_ids.get(key)
        if identifiers is None or len(identifiers) != len(records):
            identifiers = [
                f"{index + 1}-0".encode("ascii") for index in range(len(records))
            ]
            self.stream_ids[key] = identifiers
            self.stream_counters[key] = max(
                self.stream_counters.get(key, 0), len(records)
            )
        return identifiers

    def _execute_set(self, args: tuple[str | bytes, ...]) -> str | None:
        key = self._text(args[0])
        value = args[1]
        options = [self._text(item).upper() for item in args[2:]]
        if "NX" in options and self._get(key) is not None:
            return None
        self._set(key, value)
        if "PX" in options:
            position = options.index("PX")
            self.expiries[key] = time.monotonic() + int(options[position + 1]) / 1_000
        elif "EX" in options:
            position = options.index("EX")
            self.expiries[key] = time.monotonic() + int(options[position + 1])
        return "OK"

    def _eval(self, args: tuple[str | bytes, ...]) -> Any:
        script = self._text(args[0])
        key_count = int(self._text(args[1]))
        keys = [self._text(item) for item in args[2 : 2 + key_count]]
        argv = list(args[2 + key_count :])

        if "redis.sha1hex" in script:
            active = self._get(keys[0])
            if active is None:
                return None
            lease = self._text(argv[0]) + hashlib.sha1(active).hexdigest()
            value = int(self._get(lease) or b"0") + 1
            self._set(lease, value)
            self.expiries[lease] = time.monotonic() + int(self._text(argv[1])) / 1_000
            return [active, lease.encode(), value]
        if "local n=redis.call('incr'" in script:
            value = int(self._get(keys[0]) or b"0") + 1
            self._set(keys[0], value)
            self.expiries[keys[0]] = time.monotonic() + int(self._text(argv[0])) / 1_000
            return value
        if "local n=tonumber(redis.call('get'" in script:
            value = int(self._get(keys[0]) or b"0")
            if value <= 1:
                return self.execute("DEL", keys[0])
            self._set(keys[0], value - 1)
            return value - 1
        if "local expected={" in script and "redis.call('xadd',KEYS[1]" in script:
            return self._project_event(keys, argv)

        owner = self._bytes(argv[0]) if argv else b""
        if self._get(keys[0]) != owner:
            return -1 if "return -1" in script else 0
        if "redis.call('pexpire',KEYS[1],ARGV[2])" in script:
            self.expiries[keys[0]] = time.monotonic() + int(self._text(argv[1])) / 1_000
            return 1
        if "redis.call('hset',KEYS[2]" in script:
            values = self.hashes.setdefault(keys[1], {})
            for field, value in zip(argv[1::2], argv[2::2], strict=True):
                values[self._text(field)] = self._bytes(value)
            return 1
        if "for i=2,#KEYS do redis.call('set'" in script:
            for key, value in zip(keys[1:], argv[1:], strict=True):
                self._set(key, value)
            return 1
        if "for i=2,#KEYS do n=n+redis.call('del'" in script:
            return self.execute("DEL", *keys[1:])
        if "redis.call('set',KEYS[2],ARGV[2])" in script:
            self._set(keys[1], argv[1])
            return 1
        if "redis.call('del',KEYS[1])" in script:
            return self.execute("DEL", keys[0])
        raise AssertionError("FakeRedis does not implement this Lua script")

    def _project_event(self, keys: list[str], argv: list[str | bytes]) -> int:
        expected = [
            ("event", self._bytes(argv[1])),
            ("session", self._bytes(argv[2])),
            ("kind", self._bytes(argv[3])),
            ("subject", self._bytes(argv[4])),
            ("observed", self._bytes(argv[5])),
            ("supersedes", self._bytes(argv[6])),
            ("contradicts", self._bytes(argv[7])),
            ("trust", self._bytes(argv[8])),
            ("sensitivity", self._bytes(argv[9])),
            ("digest", self._bytes(argv[10])),
        ]
        retry = self._text(argv[12]) == "1"
        receipt = self._get(keys[1])
        if receipt is not None:
            separator = receipt.find(b"|")
            if separator <= 0:
                return -1
            stream_id = receipt[:separator]
            receipt_digest = receipt[separator + 1 :]
            if (
                re.fullmatch(rb"[0-9]+-[0-9]+", stream_id) is None
                or receipt_digest != self._bytes(argv[10])
            ):
                return -1
            records = self.streams.get(keys[0], [])
            identifiers = self._stream_identifiers(keys[0], records)
            matches = [
                record
                for identifier, record in zip(identifiers, records)
                if identifier == stream_id
            ]
            if matches:
                if len(matches) != 1 or list(matches[0].items()) != expected:
                    return -1
                self.expiries[keys[0]] = (
                    time.monotonic() + int(self._text(argv[11]))
                )
                return 0
            retry = True

        records = self.streams.get(keys[0], [])
        identifiers = self._stream_identifiers(keys[0], records)
        if retry:
            matches = [
                (identifier, record)
                for identifier, record in zip(identifiers[: int(self._text(argv[0]))], records)
                if record.get("event") == self._bytes(argv[1])
            ]
            if len(matches) > 1:
                return -1
            if matches:
                stream_id, record = matches[0]
                if list(record.items()) != expected:
                    return -1
                self._set(keys[1], stream_id + b"|" + self._bytes(argv[10]))
                self.expiries[keys[1]] = (
                    time.monotonic() + int(self._text(argv[11]))
                )
                self.expiries[keys[0]] = (
                    time.monotonic() + int(self._text(argv[11]))
                )
                return 0

        fields = dict(expected)
        if keys[0] not in self.streams:
            self.streams[keys[0]] = []
            self.stream_ids[keys[0]] = []
        stream = self.streams[keys[0]]
        identifiers = self.stream_ids.setdefault(keys[0], [])
        next_id = self.stream_counters.get(keys[0], 0) + 1
        self.stream_counters[keys[0]] = next_id
        stream_id = f"{next_id}-0".encode("ascii")
        stream.append(fields)
        identifiers.append(stream_id)
        maximum = int(self._text(argv[0]))
        if len(stream) > maximum:
            del stream[: len(stream) - maximum]
            del identifiers[: len(identifiers) - maximum]
        self._set(keys[1], stream_id + b"|" + self._bytes(argv[10]))
        self.expiries[keys[1]] = time.monotonic() + int(self._text(argv[11]))
        self.expiries[keys[0]] = time.monotonic() + int(self._text(argv[11]))
        self._set(keys[2], argv[1])
        self.expiries[keys[2]] = time.monotonic() + int(self._text(argv[11]))
        if self._text(argv[6]):
            self._set(keys[3], argv[1])
            self.expiries[keys[3]] = time.monotonic() + int(self._text(argv[11]))
        if self._text(argv[7]):
            self._set(keys[4], argv[1])
            self.expiries[keys[4]] = time.monotonic() + int(self._text(argv[11]))
        return 1

    def all_stored_bytes(self) -> bytes:
        material = list(self.values.values())
        for records in self.streams.values():
            for record in records:
                material.extend(key.encode() for key in record)
                material.extend(record.values())
        for fields in self.hashes.values():
            for field, value in fields.items():
                material.extend((field.encode("ascii"), value))
        return b"\n".join(material)
