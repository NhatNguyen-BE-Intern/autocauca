import asyncio
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


def encode_frame(kind, request_id, payload=b"", *, version=bridge.VERSION, reserved=0):
    body = struct.pack("<BBHI", version, kind, reserved, request_id) + payload
    return struct.pack("<I", len(body)) + body


def rgb_payload(width, height, stride, timestamp, rgb):
    return struct.pack("<IIIQ", width, height, stride, timestamp) + rgb


class FakeWriter:
    def __init__(self, reader=None, *, on_write=None):
        self.reader = reader
        self.on_write = on_write
        self.writes = []
        self.closed = False
        self.close_error = None
        self.wait_closed_event = None
        self.wait_closed_error = None
        self.block_drain_kind = None
        self.drain_event = None
        self.write_error_kind = None
        self.write_error = None
        self.last_kind = None

    def write(self, data):
        _length = struct.unpack_from("<I", data)[0]
        _version, kind, _reserved, request_id = struct.unpack_from("<BBHI", data, 4)
        self.last_kind = kind
        if kind == self.write_error_kind and self.write_error is not None:
            raise self.write_error
        self.writes.append(bytes(data))
        if self.on_write is not None:
            self.on_write(bytes(data))

    async def drain(self):
        if self.last_kind == self.block_drain_kind and self.drain_event is not None:
            await self.drain_event.wait()

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error

    async def wait_closed(self):
        if self.wait_closed_event is not None:
            await self.wait_closed_event.wait()
        if self.wait_closed_error is not None:
            raise self.wait_closed_error


class FakeProcess:
    def __init__(self, *, on_write=None, exit_code=0, terminate_completes=True,
                 initially_exited=False, auto_exit_on_wait=True):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = FakeWriter(self.stdout, on_write=on_write)
        self.returncode = exit_code if initially_exited else None
        self._exit_code = exit_code
        self._terminate_completes = terminate_completes
        self._auto_exit_on_wait = auto_exit_on_wait
        self._exit_event = asyncio.Event()
        self.on_terminate = None
        if initially_exited:
            self._exit_event.set()
            self.stderr.feed_eof()
            self.stdout.feed_eof()
        self.wait_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    async def wait(self):
        self.wait_calls += 1
        if self.returncode is None:
            if self._auto_exit_on_wait:
                self._finish(self._exit_code)
            else:
                await self._exit_event.wait()
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        if self.on_terminate is not None:
            self.on_terminate()
        if self.returncode is None and self._terminate_completes:
            self._finish(-15)

    def kill(self):
        self.kill_calls += 1
        if self.returncode is None:
            self._finish(-9)

    def _finish(self, returncode):
        self.returncode = returncode
        self._exit_event.set()
        self.stderr.feed_eof()
        self.stdout.feed_eof()


def worker_for(process, *, timeout=0.05):
    async def spawn(_executable, **_kwargs):
        return process
    return mock.patch.object(bridge.asyncio, "create_subprocess_exec", new=mock.AsyncMock(side_effect=spawn))


def feed_reply(process, kind, request_id, payload=b"", *, version=bridge.VERSION, reserved=0):
    body = struct.pack("<BBHI", version, kind, reserved, request_id) + payload
    process.stdout.feed_data(struct.pack("<I", len(body)) + body)


def dispatch_auto(process, *, operation=None, operation_payload=b"success", operation_id_offset=0):
    def on_write(data):
        version, kind, _reserved, request_id = struct.unpack_from("<BBHI", data, 4)
        if kind == bridge.KIND_HELLO:
            feed_reply(process, bridge.KIND_HELLO_ACK, 0, version=version)
        elif kind == bridge.KIND_REQUEST:
            reply_kind, payload = operation(request_id) if operation is not None else (bridge.KIND_RESPONSE, operation_payload)
            feed_reply(process, reply_kind, request_id + operation_id_offset, payload, version=version)
        elif kind == bridge.KIND_SHUTDOWN:
            feed_reply(process, bridge.KIND_SHUTDOWN_ACK, 0, version=version)
    process.stdin.on_write = on_write


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def read_bytes(self, chunks):
        reader = asyncio.StreamReader()
        task = asyncio.create_task(bridge.read_frame(reader))
        for chunk in chunks:
            reader.feed_data(chunk)
            await asyncio.sleep(0)
        reader.feed_eof()
        return await task

    async def test_round_trip_and_short_reads(self):
        frame = bridge.Frame(bridge.VERSION, bridge.KIND_RESPONSE, 7, b"payload")
        encoded = bridge.encode_frame(frame)
        decoded = await self.read_bytes([encoded[i:i + 1] for i in range(len(encoded))])
        self.assertEqual(decoded, frame)

    async def test_clean_eof_is_none_but_partial_prefix_or_body_is_error(self):
        self.assertIsNone(await self.read_bytes([]))
        with self.assertRaises(bridge.ProtocolError):
            await self.read_bytes([b"\x08\x00"])
        with self.assertRaises(bridge.ProtocolError):
            await self.read_bytes([encode_frame(bridge.KIND_RESPONSE, 1)[:-1]])

    async def test_rejects_short_oversized_version_reserved_and_invalid_ids(self):
        for raw in [
            struct.pack("<I", 7),
            struct.pack("<I", bridge.MAX_FRAME_LEN + 1),
            encode_frame(bridge.KIND_REQUEST, 1, version=2),
            encode_frame(bridge.KIND_REQUEST, 1, reserved=1),
            encode_frame(bridge.KIND_REQUEST, 0),
            encode_frame(bridge.KIND_HELLO, 1),
        ]:
            reader = asyncio.StreamReader()
            reader.feed_data(raw)
            reader.feed_eof()
            with self.subTest(raw=raw[:12]), self.assertRaises(bridge.ProtocolError):
                await bridge.read_frame(reader)

    async def test_rgb_validation_checks_overflow_stride_length_and_trailing_bytes(self):
        valid = rgb_payload(2, 1, 6, 123, bytes(range(6)))
        parsed = bridge.decode_rgb_payload(valid)
        self.assertEqual((parsed.width, parsed.height, parsed.stride, parsed.captured_monotonic_ns), (2, 1, 6, 123))
        self.assertEqual(parsed.rgb, bytes(range(6)))
        for bad in [
            rgb_payload(2**32 - 1, 1, 2**32 - 1, 0, b""),
            rgb_payload(8192, 8192, 8192 * 3, 0, b""),
            rgb_payload(2, 1, 5, 0, bytes(range(6))),
            rgb_payload(2, 1, 6, 0, bytes(range(7))),
        ]:
            with self.subTest(header=bad[:20]), self.assertRaises(bridge.ProtocolError):
                bridge.decode_rgb_payload(bad)

    async def test_worker_error_is_consumed_and_next_request_and_shutdown_remain_usable(self):
        process = FakeProcess()
        dispatch_auto(
            process,
            operation=lambda request_id: (
                (bridge.KIND_ERROR, b"\x01\x00") if request_id == 1
                else (bridge.KIND_RESPONSE, b"success")
            ),
        )
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.05)
            with self.assertRaises(bridge.WorkerOperationError) as caught:
                await client.request(b"first")
            self.assertEqual(caught.exception.code, 1)
            self.assertIn("1", str(caught.exception))
            self.assertFalse(client.channel.poisoned)
            self.assertEqual(process.terminate_calls, 0)

            response = await client.request(b"second")
            self.assertEqual((response.request_id, response.kind, response.payload),
                             (2, bridge.KIND_RESPONSE, b"success"))
            await client.shutdown()
            self.assertEqual([struct.unpack_from("<I", raw, 8)[0]
                              for raw in process.stdin.writes if struct.unpack_from("<BBHI", raw, 4)[1] == bridge.KIND_REQUEST], [1, 2])
            self.assertEqual(process.terminate_calls, 0)
            self.assertGreaterEqual(process.wait_calls, 1)
            self.assertTrue(client._stderr_task.done())

    async def test_overlap_and_local_validation_do_not_consume_id_or_poison(self):
        async def wait_for_write_count(writer, count):
            deadline = asyncio.get_running_loop().time() + 0.5
            while len(writer.writes) < count:
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError(f"expected {count} writes, got {len(writer.writes)}")
                await asyncio.sleep(0)

        process = FakeProcess()
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.2)
            original = process.stdin.on_write
            operation_started = asyncio.Event()

            def first_request_waits(data):
                kind = struct.unpack_from("<BBHI", data, 4)[1]
                if kind == bridge.KIND_REQUEST:
                    operation_started.set()
                    return
                original(data)

            process.stdin.on_write = first_request_waits
            first = asyncio.create_task(client.request(b"first"))
            await operation_started.wait()
            writes_before = len(process.stdin.writes)
            with self.assertRaises(bridge.ChannelBusyError):
                await client.request(b"overlap")
            self.assertEqual(len(process.stdin.writes), writes_before)
            self.assertEqual(client.channel._next_request_id, 1)
            feed_reply(process, bridge.KIND_RESPONSE, 1, b"first-ok")
            self.assertEqual((await first).payload, b"first-ok")
            self.assertEqual(client.channel._next_request_id, 2)
            writes_before = len(process.stdin.writes)
            with self.assertRaises(bridge.LocalRequestError):
                await client.request("not bytes")
            self.assertEqual(len(process.stdin.writes), writes_before)
            self.assertEqual(client.channel._next_request_id, 2)
            process.stdin.on_write = original
            second = await client.request(b"second")
            self.assertEqual((second.request_id, second.payload), (2, b"success"))
            self.assertFalse(client.channel.poisoned)
            self.assertEqual(process.terminate_calls, 0)
            await client.shutdown()

    async def test_operation_id_maximum_matches_worker_overflow_behavior(self):
        process = FakeProcess()
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.05)
            client.channel._next_request_id = bridge.MAX_OPERATION_ID
            response = await client.request(b"last allowed")
            self.assertEqual(response.request_id, 0xFFFFFFFE)
            writes_before = len(process.stdin.writes)
            with self.assertRaises(bridge.LocalRequestError):
                await client.request(b"must not wrap")
            self.assertEqual(len(process.stdin.writes), writes_before)
            self.assertEqual(client.channel._next_request_id, 0xFFFFFFFF)
            await client.shutdown()


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonzero_exit_after_shutdown_ack_is_failure(self):
        process = FakeProcess(exit_code=2)
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn('worker-test.exe', timeout=0.2)
            with self.assertRaises(bridge.ProtocolError):
                await client.shutdown()
        self.assertEqual(process.returncode, 2)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(client._stderr_task.done())

    async def test_spawn_uses_exec_without_shell_handshake_and_clean_shutdown(self):
        process = FakeProcess()
        dispatch_auto(process)
        executable = Path("worker-test.exe").resolve()
        with mock.patch.object(bridge.asyncio, "create_subprocess_exec", new=mock.AsyncMock(return_value=process)) as spawn:
            client = await bridge.WorkerClient.spawn(executable, timeout=0.2)
            spawn.assert_awaited_once_with(
                str(executable), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            self.assertEqual(struct.unpack_from("<BBHI", process.stdin.writes[0], 4)[:2], (bridge.VERSION, bridge.KIND_HELLO))
            await client.shutdown()
            self.assertTrue(process.stdin.closed)
            self.assertGreaterEqual(process.wait_calls, 1)
            self.assertEqual(process.terminate_calls, 0)
            self.assertTrue(client._stderr_task.done())

    async def test_handshake_timeout_terminates_and_reaps_child(self):
        process = FakeProcess()
        process.stdin.on_write = lambda _data: None
        with mock.patch.object(bridge.asyncio, "create_subprocess_exec", new=mock.AsyncMock(return_value=process)):
            with self.assertRaises(bridge.ProtocolError):
                await bridge.WorkerClient.spawn(Path("worker-test.exe"), timeout=0.01)
        self.assertEqual(process.terminate_calls, 1)
        self.assertGreaterEqual(process.wait_calls, 1)

    async def test_fatal_reply_poison_aborts_once_and_ignores_late_response(self):
        cases = [
            ("wrong id", lambda p: feed_reply(p, bridge.KIND_RESPONSE, 99, b"late"), True),
            ("wrong kind", lambda p: feed_reply(p, bridge.KIND_HELLO_ACK, 0), True),
            ("bad version", lambda p: feed_reply(p, bridge.KIND_RESPONSE, 1, version=2), True),
            ("bad reserved", lambda p: feed_reply(p, bridge.KIND_RESPONSE, 1, reserved=1), True),
            ("short length", lambda p: p.stdout.feed_data(struct.pack("<I", 7)), True),
            ("oversized length", lambda p: p.stdout.feed_data(struct.pack("<I", bridge.MAX_FRAME_LEN + 1)), True),
            ("truncated prefix", lambda p: (p.stdout.feed_data(b"\x08\x00"), p.stdout.feed_eof()), False),
            ("truncated body", lambda p: (p.stdout.feed_data(encode_frame(bridge.KIND_RESPONSE, 1)[:-1]), p.stdout.feed_eof()), False),
            ("clean eof", lambda p: p.stdout.feed_eof(), False),
            ("malformed error empty", lambda p: feed_reply(p, bridge.KIND_ERROR, 1, b""), True),
            ("malformed error short", lambda p: feed_reply(p, bridge.KIND_ERROR, 1, b"\x01"), True),
            ("malformed error long", lambda p: feed_reply(p, bridge.KIND_ERROR, 1, b"\x01\x00\x00"), True),
        ]
        for name, send_bad, can_deliver_late in cases:
            with self.subTest(name=name):
                process = FakeProcess()
                def on_write(data, process=process, send_bad=send_bad):
                    kind = struct.unpack_from("<BBHI", data, 4)[1]
                    if kind == bridge.KIND_HELLO:
                        feed_reply(process, bridge.KIND_HELLO_ACK, 0)
                    elif kind == bridge.KIND_REQUEST:
                        send_bad(process)
                    elif kind == bridge.KIND_SHUTDOWN:
                        feed_reply(process, bridge.KIND_SHUTDOWN_ACK, 0)
                process.stdin.on_write = on_write
                if can_deliver_late:
                    process.on_terminate = lambda p=process: feed_reply(p, bridge.KIND_RESPONSE, 1, b"late")
                with worker_for(process):
                    client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.03)
                    writes_before = len(process.stdin.writes)
                    with self.assertRaises(bridge.ProtocolError):
                        await client.request(b"fatal")
                    self.assertTrue(client.channel.poisoned)
                    self.assertTrue(client._closed)
                    self.assertEqual(len(process.stdin.writes), writes_before + 1)
                    with self.assertRaises(bridge.ProtocolError):
                        await client.request(b"must not write")
                    await client.shutdown()
                    self.assertEqual(len(process.stdin.writes), writes_before + 1)
                    self.assertEqual(process.terminate_calls, 1)
                    self.assertGreaterEqual(process.wait_calls, 1)
                    self.assertTrue(process.stdin.closed)
                    self.assertTrue(client._stderr_task.done())

    async def test_timeout_on_read_or_write_and_broken_pipe_poison_and_reap(self):
        process = FakeProcess()
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.02)
            process.stdin.on_write = lambda data: None if struct.unpack_from("<BBHI", data, 4)[1] == bridge.KIND_REQUEST else dispatch_auto(process)(data)
            # No response exercises the bounded read timeout.
            with self.assertRaises(bridge.ProtocolError):
                await client.request(b"read timeout")
            self.assertTrue(client.channel.poisoned)
            self.assertEqual(process.terminate_calls, 1)

        process = FakeProcess()
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.02)
            process.stdin.block_drain_kind = bridge.KIND_REQUEST
            process.stdin.drain_event = asyncio.Event()
            with self.assertRaises(bridge.ProtocolError):
                await client.request(b"write timeout")
            self.assertTrue(client.channel.poisoned)
            self.assertEqual(process.terminate_calls, 1)

        process = FakeProcess()
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.02)
            process.stdin.write_error_kind = bridge.KIND_REQUEST
            process.stdin.write_error = BrokenPipeError("closed pipe")
            with self.assertRaises(BrokenPipeError):
                await client.request(b"broken pipe")
            self.assertTrue(client.channel.poisoned)
            self.assertEqual(process.terminate_calls, 1)

    async def test_cancellation_after_request_write_poisons_aborts_and_reaps(self):
        process = FakeProcess()
        dispatch_auto(process)
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.05)
            process.stdin.on_write = lambda _data: None
            task = asyncio.create_task(client.request(b"cancel me"))
            while len(process.stdin.writes) < 2:
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(client.channel.poisoned)
            self.assertEqual(process.terminate_calls, 1)
            self.assertGreaterEqual(process.wait_calls, 1)
            self.assertTrue(client._stderr_task.done())
            writes_before = len(process.stdin.writes)
            with self.assertRaises(bridge.ProtocolError):
                await client.request(b"no reuse")
            self.assertEqual(len(process.stdin.writes), writes_before)

    async def test_kill_fallback_and_abort_are_bounded_and_idempotent(self):
        process = FakeProcess(terminate_completes=False, auto_exit_on_wait=False)
        process.stdin.on_write = lambda data: (
            feed_reply(process, bridge.KIND_HELLO_ACK, 0)
            if struct.unpack_from("<BBHI", data, 4)[1] == bridge.KIND_HELLO
            else feed_reply(process, bridge.KIND_RESPONSE, 99)
        )
        process.stdin.wait_closed_event = asyncio.Event()
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.01)
            with self.assertRaises(bridge.ProtocolError):
                await asyncio.wait_for(client.request(b"trigger abort"), 0.2)
            self.assertEqual(process.terminate_calls, 1)
            self.assertEqual(process.kill_calls, 1)
            self.assertEqual(process.returncode, -9)
            self.assertTrue(client._stderr_task.done())
            await client._abort()
            await client.shutdown()
            self.assertEqual(process.terminate_calls, 1)
            self.assertEqual(process.kill_calls, 1)

    async def test_already_exited_and_broken_pipe_during_close_are_reaped(self):
        process = FakeProcess()
        process.stdin.close_error = BrokenPipeError("already closed")
        def exited_with_bad_hello(data):
            feed_reply(process, bridge.KIND_RESPONSE, 1)
            process.returncode = 1
            process._exit_event.set()
            process.stderr.feed_eof()
        process.stdin.on_write = exited_with_bad_hello
        with worker_for(process):
            with self.assertRaises(bridge.ProtocolError):
                await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.02)
        self.assertEqual(process.terminate_calls, 0)
        self.assertGreaterEqual(process.wait_calls, 1)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stderr.at_eof())

    async def test_handshake_and_shutdown_reject_validly_framed_operation_errors(self):
        process = FakeProcess()
        process.stdin.on_write = lambda data: feed_reply(
            process, bridge.KIND_ERROR, 1, b"\x01\x00"
        )
        with worker_for(process):
            with self.assertRaises(bridge.ProtocolError):
                await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.02)
        self.assertEqual(process.terminate_calls, 1)

        process = FakeProcess()
        def operation_error_on_shutdown(data):
            kind = struct.unpack_from("<BBHI", data, 4)[1]
            if kind == bridge.KIND_HELLO:
                feed_reply(process, bridge.KIND_HELLO_ACK, 0)
            elif kind == bridge.KIND_SHUTDOWN:
                feed_reply(process, bridge.KIND_ERROR, 1, b"\x01\x00")
        process.stdin.on_write = operation_error_on_shutdown
        with worker_for(process):
            client = await bridge.WorkerClient.spawn("worker-test.exe", timeout=0.02)
            with self.assertRaises(bridge.ProtocolError):
                await client.shutdown()
        self.assertEqual(process.terminate_calls, 1)


if __name__ == "__main__":
    unittest.main()
