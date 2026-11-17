import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class WorkerCheckTests(unittest.IsolatedAsyncioTestCase):
    async def run_check(self, payload_error=False, read_error=None, shutdown_error=None):
        status = bridge.Status('https://nomstead.com/qn', 800, 600, 1, 70, 123, '', False, 0, False)
        client = mock.Mock()
        async def reply(payload):
            return bridge.Frame(1, bridge.KIND_RESPONSE, 1, b'wrong' if payload_error else payload)
        client.request = mock.AsyncMock(side_effect=reply)
        client.shutdown = mock.AsyncMock(side_effect=shutdown_error)
        client._abort_preserving = mock.AsyncMock()
        output = io.StringIO()
        with mock.patch.object(bridge.WorkerClient, 'spawn', return_value=client) as spawn, \
                mock.patch.object(bridge, 'discover_tab', return_value=bridge.Tab(status.url, 'ws://127.0.0.1:9222/devtools/page/abc')), \
                mock.patch.object(bridge, 'read_status', return_value=status, side_effect=read_error), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = await bridge._main_async(argparse.Namespace(worker='worker.exe', timeout=3, check=True))
        spawn.assert_awaited_once()
        return result, client, output.getvalue()

    async def test_check_requires_rust_confirmation_before_success(self):
        result, client, output = await self.run_check()
        self.assertEqual(result, 0)
        payload = client.request.call_args.args[0]
        self.assertEqual(payload[0], bridge.OP_CHECK_STATUS)
        self.assertEqual(bridge.decode_status(payload[1:]).energy, 70)
        client.shutdown.assert_awaited_once()
        client._abort_preserving.assert_not_awaited()
        self.assertIn('Python CDP + Rust worker', output)

    async def test_mismatched_worker_or_cdp_failure_aborts_without_success(self):
        for mismatch, error in [(True, None), (False, bridge.CdpError('PRIVATE_URL'))]:
            with self.subTest(mismatch=mismatch):
                result, client, output = await self.run_check(mismatch, error)
                self.assertEqual(result, 1)
                client._abort_preserving.assert_awaited_once()
                client.shutdown.assert_not_awaited()
                self.assertNotIn('CHECK OK', output)
                self.assertNotIn('PRIVATE_URL', output)

    async def test_shutdown_failure_never_reports_check_success(self):
        result, client, output = await self.run_check(
            shutdown_error=bridge.ProtocolError('PRIVATE_ERROR'))
        self.assertEqual(result, 1)
        client._abort_preserving.assert_awaited_once()
        self.assertNotIn('CHECK OK', output)
        self.assertNotIn('PRIVATE_ERROR', output)

    async def test_application_control_failure_identifies_worker_before_any_cdp(self):
        error = OSError('PRIVATE_ERROR')
        error.winerror = 4551
        output = io.StringIO()
        executable = str(Path('worker.exe').resolve())
        with mock.patch.object(bridge.WorkerClient, 'spawn', side_effect=error), \
                mock.patch.object(bridge, 'discover_tab') as discover, \
                contextlib.redirect_stderr(output):
            result = await bridge._main_async(
                argparse.Namespace(worker=executable, timeout=3, check=True))
        self.assertEqual(result, 1)
        discover.assert_not_called()
        self.assertIn('4551', output.getvalue())
        self.assertIn(executable, output.getvalue())
        self.assertNotIn('PRIVATE_ERROR', output.getvalue())


if __name__ == '__main__':
    unittest.main()
