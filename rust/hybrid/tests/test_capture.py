import asyncio
import base64
import contextlib
import io
import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from PIL import Image, ImageFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge
from test_status import FakeSocket, URL, WS, values


STAMP = 0x0102030405060708


def jpeg_bytes(mode='RGB', size=(5, 3)):
    channels = {'RGB': 3, 'L': 1, 'CMYK': 4}[mode]
    pixels = bytes((i * 47 + 19) % 256 for i in range(size[0] * size[1] * channels))
    with Image.frombytes(mode, size, pixels) as image, io.BytesIO() as output:
        image.save(output, format='JPEG', quality=87)
        return output.getvalue()


def metadata_image(size=(2, 1), image_format='JPEG'):
    image = mock.Mock()
    image.size = size
    image.format = image_format
    return image


class CaptureHelperTests(unittest.TestCase):
    def setUp(self):
        for name in ('decode_jpeg_rgb', 'encode_rgb_payload'):
            self.assertTrue(callable(getattr(bridge, name, None)), f'missing helper: {name}')

    def test_real_rgb_jpeg_matches_independent_pillow_decode(self):
        data = jpeg_bytes()
        with Image.open(io.BytesIO(data)) as image:
            with image.convert('RGB') as converted:
                expected = converted.tobytes()
        frame = bridge.decode_jpeg_rgb(data, STAMP)
        self.assertEqual(frame, bridge.RgbPayload(5, 3, 15, STAMP, expected))
        self.assertIs(type(frame.rgb), bytes)
        self.assertEqual(bridge.decode_rgb_payload(bridge.encode_rgb_payload(frame)), frame)

    def test_grayscale_and_cmyk_jpeg_are_converted_to_rgb(self):
        for mode in ('L', 'CMYK'):
            with self.subTest(mode=mode):
                data = jpeg_bytes(mode)
                with Image.open(io.BytesIO(data)) as image:
                    with image.convert('RGB') as converted:
                        expected = converted.tobytes()
                frame = bridge.decode_jpeg_rgb(data, STAMP)
                self.assertEqual(frame, bridge.RgbPayload(5, 3, 15, STAMP, expected))

    def test_exif_orientation_does_not_rotate_pixels(self):
        with Image.new('RGB', (5, 3), (20, 90, 140)) as image, io.BytesIO() as output:
            exif = Image.Exif()
            exif[274] = 6
            image.save(output, format='JPEG', exif=exif)
            data = output.getvalue()
        frame = bridge.decode_jpeg_rgb(data, STAMP)
        self.assertEqual((frame.width, frame.height, frame.stride, len(frame.rgb)), (5, 3, 15, 45))

    def test_encode_independent_complete_golden_wire(self):
        frame = bridge.RgbPayload(2, 1, 6, STAMP, b'\x01\x02\x03\x04\x05\x06')
        golden = (b'\x02\0\0\0\x01\0\0\0\x06\0\0\0'
                  b'\x08\x07\x06\x05\x04\x03\x02\x01\x01\x02\x03\x04\x05\x06')
        self.assertEqual(bridge.encode_rgb_payload(frame), golden)

    def test_timestamp_endpoints_succeed_without_replacement(self):
        data = jpeg_bytes()
        for stamp in (0, 2**64 - 1):
            with self.subTest(stamp=stamp):
                decoded = bridge.decode_jpeg_rgb(data, stamp)
                self.assertEqual(decoded.captured_monotonic_ns, stamp)
                self.assertEqual(bridge.decode_rgb_payload(bridge.encode_rgb_payload(decoded)), decoded)

    def test_empty_and_non_bytes_jpeg_rejected_before_open(self):
        class BytesSubclass(bytes):
            pass

        for data in (b'', None, 'jpeg', bytearray(b'jpeg'), memoryview(b'jpeg'), 3, BytesSubclass(b'jpeg')):
            with self.subTest(kind=type(data).__name__), mock.patch.object(Image, 'open') as opened:
                with self.assertRaises(bridge.ProtocolError):
                    bridge.decode_jpeg_rgb(data, STAMP)
                opened.assert_not_called()

    def test_invalid_timestamp_rejected_before_open(self):
        for stamp in (-1, 2**64, True, False, 1.5, '1', None):
            with self.subTest(stamp=stamp), mock.patch.object(Image, 'open') as opened:
                with self.assertRaises(bridge.ProtocolError):
                    bridge.decode_jpeg_rgb(b'jpeg', stamp)
                opened.assert_not_called()

    def test_compressed_limit_rejects_before_open(self):
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', 4), mock.patch.object(Image, 'open') as opened:
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_jpeg_rgb(b'12345', STAMP)
            opened.assert_not_called()

    def test_compressed_limit_includes_exact_cap(self):
        data = jpeg_bytes()
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', len(data)):
            self.assertEqual(bridge.decode_jpeg_rgb(data, STAMP).width, 5)

    def test_random_corrupt_and_substantially_truncated_jpeg_fail_eagerly(self):
        data = jpeg_bytes()
        corrupted = data.replace(b'\xff\xda', b'\0\0', 1)
        for bad in (b'PRIVATE_IMAGE_TEXT', b'\xff\xd8PRIVATE_IMAGE_TEXT\xff\xd9', corrupted, data[:len(data)//2]):
            with self.subTest(size=len(bad)), self.assertRaises(bridge.ProtocolError) as caught:
                bridge.decode_jpeg_rgb(bad, STAMP)
            self.assertNotIn('PRIVATE_IMAGE_TEXT', str(caught.exception))

    def test_valid_non_jpeg_images_are_rejected(self):
        for image_format in ('PNG', 'GIF', 'BMP'):
            with self.subTest(image_format=image_format):
                with Image.new('RGB', (2, 1)) as image, io.BytesIO() as output:
                    image.save(output, format=image_format)
                    data = output.getvalue()
                with self.assertRaises(bridge.ProtocolError):
                    bridge.decode_jpeg_rgb(data, STAMP)

    def test_metadata_dimensions_reject_before_pixel_operations_and_close(self):
        for size in ((0, 1), (1, 0), (8193, 1), (1, 8193), (-1, 1)):
            image = metadata_image(size)
            with self.subTest(size=size), mock.patch.object(Image, 'open', return_value=image):
                with self.assertRaises(bridge.ProtocolError):
                    bridge.decode_jpeg_rgb(b'jpeg', STAMP)
            image.load.assert_not_called()
            image.convert.assert_not_called()
            image.tobytes.assert_not_called()
            image.close.assert_called_once_with()

    def test_metadata_rgb_budget_rejects_before_pixel_operations_and_close(self):
        image = metadata_image()
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', 33), \
                mock.patch.object(Image, 'open', return_value=image):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_jpeg_rgb(b'jpeg', STAMP)
        image.load.assert_not_called()
        image.convert.assert_not_called()
        image.tobytes.assert_not_called()
        image.close.assert_called_once_with()

    def test_real_opened_and_converted_images_and_stream_close_on_success(self):
        data = jpeg_bytes()
        original_open = Image.open
        resources = {}

        def track(stream):
            resources['stream'] = stream
            image = original_open(stream)
            resources['image'] = image
            original_convert = image.convert

            def convert(mode):
                converted = original_convert(mode)
                resources['converted'] = converted
                return converted

            image.convert = convert
            return image

        with mock.patch.object(Image, 'open', side_effect=track):
            frame = bridge.decode_jpeg_rgb(data, STAMP)
        self.assertEqual(len(frame.rgb), 45)
        self.assertTrue(resources['stream'].closed)
        for name in ('image', 'converted'):
            with self.subTest(resource=name), self.assertRaises(ValueError):
                resources[name].getpixel((0, 0))

    def test_load_failure_closes_opened_image_and_suppresses_private_error(self):
        image = metadata_image()
        image.load.side_effect = OSError('PRIVATE_IMAGE_TEXT')
        with mock.patch.object(Image, 'open', return_value=image):
            with self.assertRaises(bridge.ProtocolError) as caught:
                bridge.decode_jpeg_rgb(b'jpeg', STAMP)
        self.assertNotIn('PRIVATE_IMAGE_TEXT', str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        image.convert.assert_not_called()
        image.close.assert_called_once_with()

    def test_conversion_and_pixel_copy_failures_close_all_acquired_images(self):
        for stage in ('convert', 'tobytes'):
            image = metadata_image()
            converted = image.convert.return_value
            converted.tobytes.return_value = b'\0' * 6
            getattr(image if stage == 'convert' else converted, stage).side_effect = ValueError('PRIVATE_IMAGE_TEXT')
            with self.subTest(stage=stage), mock.patch.object(Image, 'open', return_value=image):
                with self.assertRaises(bridge.ProtocolError) as caught:
                    bridge.decode_jpeg_rgb(b'jpeg', STAMP)
            self.assertNotIn('PRIVATE_IMAGE_TEXT', str(caught.exception))
            image.close.assert_called_once_with()
            if stage == 'tobytes':
                converted.close.assert_called_once_with()

    def test_inconsistent_decoded_pixel_count_is_rejected_and_closed(self):
        image = metadata_image()
        converted = image.convert.return_value
        converted.tobytes.return_value = b'\0' * 5
        with mock.patch.object(Image, 'open', return_value=image):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_jpeg_rgb(b'jpeg', STAMP)
        image.close.assert_called_once_with()
        converted.close.assert_called_once_with()

    def test_encode_rejects_invalid_numeric_types_ranges_and_layout(self):
        valid = bridge.RgbPayload(2, 1, 6, STAMP, b'\0' * 6)
        invalid = {
            'width': (0, -1, 8193, 2**64, True, False, 2.0, '2', None),
            'height': (0, -1, 8193, 2**64, True, False, 1.0, '1', None),
            'stride': (0, -1, 5, 7, 2**64, True, False, 6.0, '6', None),
            'captured_monotonic_ns': (-1, 2**64, True, False, 1.0, '1', None),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), mock.patch.object(bridge.struct, 'pack') as pack:
                    with self.assertRaises(bridge.ProtocolError):
                        bridge.encode_rgb_payload(replace(valid, **{field: value}))
                    pack.assert_not_called()

    def test_encode_rejects_wrong_frame_and_pixel_types_or_lengths(self):
        valid = bridge.RgbPayload(2, 1, 6, STAMP, b'\0' * 6)
        for frame in (None, {}, (2, 1, 6, STAMP, b'\0' * 6), object()):
            with self.subTest(kind=type(frame).__name__), self.assertRaises(bridge.ProtocolError):
                bridge.encode_rgb_payload(frame)
        for pixels in (None, '123456', bytearray(6), memoryview(b'123456'), b'12345', b'1234567'):
            with self.subTest(kind=type(pixels).__name__), mock.patch.object(bridge.struct, 'pack') as pack:
                with self.assertRaises(bridge.ProtocolError):
                    bridge.encode_rgb_payload(replace(valid, rgb=pixels))
                pack.assert_not_called()

    def test_encode_rgb_budget_checks_include_frame_header_and_allow_exact_cap(self):
        frame = bridge.RgbPayload(2, 1, 6, STAMP, b'123456')
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', 33), mock.patch.object(bridge.struct, 'pack') as pack:
            with self.assertRaises(bridge.ProtocolError):
                bridge.encode_rgb_payload(frame)
            pack.assert_not_called()
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', 34):
            self.assertEqual(bridge.decode_rgb_payload(bridge.encode_rgb_payload(frame)), frame)

    def test_max_dimension_accepted_when_rgb_fits(self):
        for width, height in ((8192, 1), (1, 8192)):
            with self.subTest(size=(width, height)):
                frame = bridge.RgbPayload(width, height, width * 3, STAMP, bytes(width * height * 3))
                self.assertEqual(bridge.decode_rgb_payload(bridge.encode_rgb_payload(frame)), frame)

    def test_helpers_have_no_external_io_or_clock_and_preserve_pillow_settings(self):
        data = jpeg_bytes()
        settings = (Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES)
        denied = AssertionError('unexpected external IO or clock')
        with contextlib.ExitStack() as stack:
            for target in ('builtins.open', 'io.open', 'socket.socket', 'subprocess.Popen',
                           'bridge.http.client.HTTPConnection', 'bridge._ReadOnlyConnect',
                           'bridge.WorkerClient.spawn', 'bridge.asyncio.create_subprocess_exec',
                           'bridge.time.monotonic_ns', 'bridge.time.monotonic', 'bridge.time.time'):
                stack.enter_context(mock.patch(target, side_effect=denied))
            frame = bridge.decode_jpeg_rgb(data, STAMP)
            bridge.encode_rgb_payload(frame)
        self.assertEqual((Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES), settings)


def capture_status(request_id, **changes):
    return json.dumps({'id': request_id, 'result': {'result': {'value': values(**changes)}}})


def screenshot_response(data):
    return json.dumps({'id': 2, 'result': {'data': base64.b64encode(data).decode('ascii')}})


class CaptureTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sys.platform == 'win32':
            import ctypes
            try:
                ctypes.windll.winmm.timeBeginPeriod(1)
            except Exception:
                pass

    @classmethod
    def tearDownClass(cls):
        if sys.platform == 'win32':
            import ctypes
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        super().tearDownClass()

    async def asyncSetUp(self):
        self.assertTrue(callable(getattr(bridge, 'capture', None)), 'missing helper: capture')
        self.jpeg = jpeg_bytes(size=(11, 7))
        self.messages = [capture_status(1), screenshot_response(self.jpeg), capture_status(3)]
        self.tab = bridge.Tab(URL, WS)
        self.guards = contextlib.ExitStack()
        self.addCleanup(self.guards.close)
        for target in ('builtins.open', 'io.open', 'socket.create_connection', 'subprocess.Popen',
                       'bridge.http.client.HTTPConnection', 'bridge.WorkerClient.spawn',
                       'bridge.asyncio.create_subprocess_exec'):
            self.guards.enter_context(mock.patch(target, side_effect=AssertionError('external IO')))
        self.guards.enter_context(mock.patch.object(asyncio.get_running_loop(), 'create_connection',
                                                   side_effect=AssertionError('external IO')))

    async def assert_failure(self, messages, sent, **options):
        socket = options.pop('socket', FakeSocket(messages))
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket) as connect, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(bridge.CdpError) as caught:
                await bridge.capture(self.tab, options.pop('kind', 'SCREEN_FULL'))
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertNotIn(URL, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')
        self.assertTrue(socket.closed)
        self.assertEqual(len(socket.sent), sent)
        self.assertEqual(connect.call_count, 1)

    async def test_full_and_alert_use_real_jpeg_and_exact_fixed_commands(self):
        with Image.open(io.BytesIO(self.jpeg)) as opened, opened.convert('RGB') as reference:
            full = reference.tobytes()
            with reference.crop((3, 1, 7, 4)) as cropped:
                alert = cropped.tobytes()
        expected_commands = [
            {'id': 1, 'method': 'Runtime.evaluate',
             'params': {'expression': bridge.STATUS_READONLY, 'returnByValue': True}},
            {'id': 2, 'method': 'Page.captureScreenshot',
             'params': {'format': 'jpeg', 'quality': 50, 'fromSurface': True,
                        'optimizeForSpeed': True, 'captureBeyondViewport': False}},
            {'id': 3, 'method': 'Runtime.evaluate',
             'params': {'expression': bridge.STATUS_READONLY, 'returnByValue': True}},
        ]
        for kind, pixels, dimensions in [('SCREEN_FULL', full, (11, 7, 33)),
                                         ('SCREEN_ALERT', alert, (4, 3, 12))]:
            socket = FakeSocket(self.messages)
            with self.subTest(kind=kind), \
                    mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket) as connect, \
                    mock.patch.object(bridge.time, 'monotonic_ns', return_value=STAMP):
                frame = await bridge.capture(self.tab, kind)
            self.assertIs(type(frame), bridge.CapturedFrame)
            self.assertEqual(frame.image, bridge.RgbPayload(*dimensions, STAMP, pixels))
            self.assertEqual(frame.status, bridge.Status(**values()))
            self.assertEqual(socket.sent, expected_commands)
            self.assertTrue(socket.closed)
            connect.assert_called_once_with(WS, proxy=None, compression=None,
                open_timeout=3.0, close_timeout=1, max_size=bridge._CAPTURE_CDP_MAX_BYTES,
                max_queue=1, ping_interval=None)
            if kind == 'SCREEN_FULL':
                self.assertEqual((frame.css_x, frame.css_y, frame.css_width, frame.css_height),
                                 (0.0, 0.0, 1200.0, 800.0))

    async def test_fractional_dpr_mapping_uses_quantized_actual_pixel_edges(self):
        for dpr in (1.25, 1.5):
            socket = FakeSocket([capture_status(1, dpr=dpr), self.messages[1], capture_status(3, dpr=dpr)])
            with self.subTest(dpr=dpr), mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
                frame = await bridge.capture(self.tab, 'SCREEN_ALERT')
            self.assertEqual(frame.status.dpr, dpr)
            self.assertEqual((frame.image.width, frame.image.height), (4, 3))
            self.assertAlmostEqual(frame.css_x, 3600 / 11)
            self.assertAlmostEqual(frame.css_y, 800 / 7)
            self.assertAlmostEqual(frame.css_width, 4800 / 11)
            self.assertAlmostEqual(frame.css_height, 2400 / 7)
            self.assertAlmostEqual(frame.css_x + 4 * frame.css_width / frame.image.width, 8400 / 11)
            self.assertAlmostEqual(frame.css_y + 3 * frame.css_height / frame.image.height, 3200 / 7)

    async def test_invalid_local_input_never_connects(self):
        class StringSubclass(str):
            pass

        cases = [(self.tab, kind) for kind in (None, True, '', 'screen_full', 'SCREEN_OTHER', StringSubclass('SCREEN_FULL'))]
        cases += [(tab, 'SCREEN_FULL') for tab in (None, {}, bridge.Tab('https://evil.com/PRIVATE', WS),
                  bridge.Tab(URL, WS + '?PRIVATE'))]
        for tab, kind in cases:
            with self.subTest(kind=kind, tab=type(tab).__name__), \
                    mock.patch.object(bridge, '_ReadOnlyConnect') as connect:
                with self.assertRaises(bridge.CdpError) as caught:
                    await bridge.capture(tab, kind)
                self.assertNotIn('PRIVATE', str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
                connect.assert_not_called()

    async def test_pre_and_post_status_validation_failures_stop_sequence(self):
        invalid = dict(url=['https://evil.com/PRIVATE', 'https://www.nomstead.com/play'],
                       width=[True, 99, 8193, float('nan'), float('inf'), '1200'],
                       height=[False, 0], dpr=[False, 0, -1, float('inf')],
                       energy=[True, -1, 2**32], xp=[True, -1, 2**53, 1.0],
                       sequence_available=[True, 0], sequence=[1, False], modal=[0], toast=[None])
        for field, variants in invalid.items():
            for value in variants:
                for stage in (1, 3):
                    messages = list(self.messages)
                    messages[stage - 1] = capture_status(stage, **{field: value})
                    with self.subTest(field=field, value=value, stage=stage):
                        await self.assert_failure(messages, stage)

    async def test_observed_url_dimensions_or_dpr_change_rejects_without_recapture(self):
        for changes in ({'url': 'https://nomstead.com/other?PRIVATE'}, {'width': 1201},
                        {'height': 801}, {'dpr': 1.25}):
            with self.subTest(changes=changes):
                await self.assert_failure(self.messages[:2] + [capture_status(3, **changes)], 3)

    async def test_same_origin_pre_url_and_mutable_status_fields_can_differ(self):
        before = dict(url='https://nomstead.com/other', energy=None, xp=None, toast='before', modal=True)
        after = dict(url='https://nomstead.com/other', energy=2, xp=45, toast='after', modal=False)
        socket = FakeSocket([capture_status(1, **before), self.messages[1], capture_status(3, **after)])
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
            frame = await bridge.capture(self.tab, 'SCREEN_FULL')
        self.assertEqual(frame.status, bridge.Status(**values(**before)))
        self.assertTrue(socket.closed)

    async def test_events_do_not_replace_screenshot_receipt_timestamp(self):
        event = '{"method":"Page.event","params":{}}'
        socket = FakeSocket([event, self.messages[0], event, self.messages[1], event, self.messages[2]])
        steps = []
        strict_json, decode_jpeg, send = bridge._strict_json, bridge.decode_jpeg_rgb, socket.send

        def clock():
            steps.append('clock')
            return 100 + steps.count('clock')

        def parse(raw):
            self.assertEqual(steps[-1], 'clock')
            steps.append('parse')
            return strict_json(raw)

        def decode(data, stamp):
            self.assertEqual(stamp, 104)
            steps.append('decode')
            return decode_jpeg(data, stamp)

        async def track_send(raw):
            if json.loads(raw)['id'] == 3:
                self.assertIn('decode', steps)
            await send(raw)

        socket.send = track_send
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket), \
                mock.patch.object(bridge.time, 'monotonic_ns', side_effect=clock), \
                mock.patch.object(bridge, '_strict_json', side_effect=parse), \
                mock.patch.object(bridge, 'decode_jpeg_rgb', side_effect=decode):
            frame = await bridge.capture(self.tab, 'SCREEN_ALERT')
        self.assertEqual(frame.image.captured_monotonic_ns, 104)
        self.assertEqual(steps.count('clock'), 6)

    async def test_invalid_events_json_binary_utf8_and_deep_json_close(self):
        bad = [b'{}', '[]', 'null', '1', '{', '{}', '{"method":1}',
               '{"method":"event","params":[]}', '{"method":"event","error":{"message":"PRIVATE"}}',
               '{"method":"event","params":{"x":NaN}}', '{"method":"\ud800"}',
               '[' * 2000 + '0' + ']' * 2000]
        for raw in bad:
            with self.subTest(raw=repr(raw)[:65]):
                await self.assert_failure([raw], 1)
                await self.assert_failure(self.messages[:1] + [raw], 2)

    async def test_invalid_response_ids_errors_and_result_shapes_close(self):
        bad = [{'id': True}, {'id': 0}, {'id': 4}, {'id': 1.0},
               {'id': 2, 'error': {'message': 'PRIVATE'}}, {'id': 2},
               {'id': 2, 'result': []}, {'id': 2, 'result': {'exceptionDetails': {}}},
               {'id': 2, 'result': {'data': ''}}, {'id': 2, 'result': {'data': None}}]
        for response in bad:
            with self.subTest(response=response):
                await self.assert_failure(self.messages[:1] + [json.dumps(response)], 2)
        for stage, stale in ((2, 1), (3, 2)):
            with self.subTest(stage=stage):
                await self.assert_failure(self.messages[:stage - 1] + [json.dumps({'id': stale, 'result': {}})], stage)

    async def test_status_result_shape_and_exception_details_rejected(self):
        results = [{}, {'result': []}, {'result': {'value': []}},
                   {'exceptionDetails': {}, 'result': {'value': values()}},
                   {'result': {'value': dict(values(), extra='PRIVATE')}}]
        for result in results:
            for stage in (1, 3):
                with self.subTest(result=result, stage=stage):
                    messages = self.messages[:stage - 1] + [json.dumps({'id': stage, 'result': result})]
                    await self.assert_failure(messages, stage)

    async def test_optional_response_keys_are_allowed(self):
        messages = [json.dumps(dict(json.loads(raw), sessionId='optional', extra=42)) for raw in self.messages]
        socket = FakeSocket(messages)
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
            frame = await bridge.capture(self.tab, 'SCREEN_FULL')
        self.assertEqual((frame.image.width, frame.image.height), (11, 7))

    async def test_message_character_and_utf8_caps_precede_json_parse(self):
        for raw in ('x' * 65, 'é' * 33):
            with self.subTest(raw=raw[:3]), mock.patch.object(bridge, '_CDP_MAX_BYTES', 64), \
                    mock.patch.object(bridge, '_strict_json') as parse:
                await self.assert_failure([raw], 1)
                parse.assert_not_called()
            with mock.patch.object(bridge, '_CAPTURE_CDP_MAX_BYTES', 64), \
                    mock.patch.object(bridge, '_strict_json', wraps=bridge._strict_json) as parse:
                await self.assert_failure(self.messages[:1] + [raw], 2)
                self.assertEqual(parse.call_count, 1)

    async def test_events_keep_status_cap_on_screenshot_socket(self):
        event = json.dumps({'method': 'Page.event', 'params': {'text': 'x' * 400}})
        with mock.patch.object(bridge, '_CDP_MAX_BYTES', 350):
            await self.assert_failure(self.messages[:1] + [event], 2)

    async def test_capture_rejects_overflow_events_at_each_exchange(self):
        for token in ('1e999', '-1e999'):
            event = '{"method":"Page.event","params":{"ignored":{"x":TOKEN,"text":"PRIVATE_MARKER"}}}'.replace('TOKEN', token)
            for stage in (1, 2, 3):
                socket = FakeSocket(self.messages[:stage - 1] + [event] + self.messages[stage - 1:])
                with self.subTest(token=token, stage=stage):
                    await self.assert_failure([], stage, socket=socket)
                    self.assertEqual([command['id'] for command in socket.sent], list(range(1, stage + 1)))
                    self.assertEqual(socket.recv_calls, stage)

    async def test_base64_rejection_precedes_pillow(self):
        for value in ('', None, 4, 'é', '%%%%', 'YQ', 'Y Q==', 'YQ==PRIVATE'):
            with self.subTest(value=value), mock.patch.object(bridge, 'decode_jpeg_rgb') as decode:
                raw = json.dumps({'id': 2, 'result': {'data': value}})
                await self.assert_failure(self.messages[:1] + [raw], 2)
                decode.assert_not_called()

    async def test_base64_length_guard_precedes_decode_and_pillow(self):
        with mock.patch.object(bridge, '_CAPTURE_BASE64_MAX_CHARS', 4), \
                mock.patch('base64.b64decode') as base64_decode, \
                mock.patch.object(bridge, 'decode_jpeg_rgb') as decode:
            await self.assert_failure(self.messages, 2)
            base64_decode.assert_not_called()
            decode.assert_not_called()

    async def test_decoded_jpeg_cap_precedes_pillow(self):
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', len(self.jpeg) - 1), \
                mock.patch.object(bridge, 'decode_jpeg_rgb') as decode:
            await self.assert_failure(self.messages, 2)
            decode.assert_not_called()

    async def test_valid_base64_corrupt_truncated_or_non_jpeg_fails(self):
        with Image.new('RGB', (2, 1)) as image, io.BytesIO() as output:
            image.save(output, 'PNG')
            png = output.getvalue()
        for data in (b'PRIVATE', self.jpeg[:len(self.jpeg)//2], png):
            with self.subTest(size=len(data)):
                await self.assert_failure(self.messages[:1] + [screenshot_response(data)], 2)

    async def test_decoded_rgb_budget_failure_does_not_send_post_status(self):
        data = jpeg_bytes(size=(40, 40))
        self.assertLess(len(data), 40 * 40 * 3)
        with mock.patch.object(bridge, 'MAX_FRAME_LEN', len(data)):
            await self.assert_failure(self.messages[:1] + [screenshot_response(data)], 2)

    async def test_screenshot_above_one_mib_is_not_limited_by_status_cap(self):
        data = self.jpeg + b'\0' * 800000
        response = screenshot_response(data)
        self.assertGreater(len(response), 1024 * 1024)
        socket = FakeSocket([self.messages[0], response, self.messages[2]])
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
            frame = await bridge.capture(self.tab, 'SCREEN_FULL')
        self.assertEqual((frame.image.width, frame.image.height), (11, 7))
        self.assertTrue(socket.closed)

    async def test_empty_alert_crop_rejected(self):
        data = jpeg_bytes(size=(1, 1))
        await self.assert_failure([self.messages[0], screenshot_response(data), self.messages[2]], 3, kind='SCREEN_ALERT')

    async def test_never_completing_receive_times_out_and_closes(self):
        async def wait_forever():
            await asyncio.Future()

        with mock.patch.object(bridge, '_CDP_TIMEOUT', .035):
            await self.assert_failure(self.messages[:1] + [wait_forever], 2)

    async def test_events_cannot_reset_single_deadline(self):
        async def event():
            await asyncio.sleep(.01)
            return '{"method":"Page.event"}'

        socket = FakeSocket(self.messages[:1] + [event] * 100)
        with mock.patch.object(bridge, '_CDP_TIMEOUT', .045):
            await self.assert_failure([], 2, socket=socket)
        self.assertLess(socket.recv_calls, 10)

    async def test_three_exchanges_share_one_deadline(self):
        def delayed(message, delay=.015):
            async def receive():
                await asyncio.sleep(delay)
                return message
            return receive

        # Exchanges 1 and 2 take ~15ms each (~30ms total < 55ms), ensuring both complete cleanly.
        # Exchange 3 sends its request (sent == 3), then its 50ms delay pushes total to ~80ms > 55ms,
        # proving that the 3 exchanges share a single 55ms deadline while being 100% jitter-immune on Windows.
        delays = [.008, .008, .080]
        with mock.patch.object(bridge, '_CDP_TIMEOUT', .060):
            await self.assert_failure([delayed(raw, d) for raw, d in zip(self.messages, delays)], 3)

    async def test_cancellation_propagates_and_closes(self):
        waiting = asyncio.Event()

        async def receive():
            waiting.set()
            await asyncio.Future()

        socket = FakeSocket(self.messages[:1] + [receive])
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
            task = asyncio.create_task(bridge.capture(self.tab, 'SCREEN_FULL'))
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(socket.closed)
        self.assertEqual(len(socket.sent), 2)

    async def test_transport_send_receive_and_close_failures_never_return_success(self):
        for stage in ('send', 'recv', 'close'):
            socket = FakeSocket(self.messages)
            if stage in ('send', 'recv'):
                setattr(socket, stage, mock.AsyncMock(side_effect=OSError('PRIVATE')))
            else:
                class CloseFailureSocket(FakeSocket):
                    async def __aexit__(self, *args):
                        self.closed = True
                        raise OSError('PRIVATE')
                socket = CloseFailureSocket(self.messages)
            with self.subTest(stage=stage):
                await self.assert_failure([], {'send': 0, 'recv': 1, 'close': 3}[stage], socket=socket)
                if stage == 'recv':
                    self.assertEqual(socket.sent, [{'id': 1, 'method': 'Runtime.evaluate',
                        'params': {'expression': bridge.STATUS_READONLY, 'returnByValue': True}}])

    async def test_connect_failure_is_safe_and_not_retried(self):
        with mock.patch.object(bridge, '_ReadOnlyConnect', side_effect=OSError('PRIVATE')) as connect:
            with self.assertRaises(bridge.CdpError) as caught:
                await bridge.capture(self.tab, 'SCREEN_FULL')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(connect.call_count, 1)


if __name__ == '__main__':
    unittest.main()
