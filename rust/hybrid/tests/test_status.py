import asyncio
import contextlib
import importlib.util
import io
import json
import math
import shutil
import struct
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

URL = 'https://nomstead.com/play?private=yes'
WS = 'ws://127.0.0.1:9222/devtools/page/ABC-123_4'


def values(**changes):
    result = dict(url=URL, width=1200.0, height=800.0, dpr=1.5,
                  energy=70, xp=1234, toast='hello', sequence_available=False,
                  sequence=0, modal=False)
    result.update(changes)
    return result


def response(**changes):
    return json.dumps({'id': 1, 'result': {'result': {'type': 'object', 'value': values(**changes)}}})


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False
        self.recv_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        self.recv_calls += 1
        item = next(self.messages)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return await item()
        return item


class StrictJsonTests(unittest.TestCase):
    def test_strict_json_rejects_nonfinite_numbers_everywhere(self):
        tokens = ('1e999', '-1e999', '1.7976931348623159e308', 'NaN', 'Infinity', '-Infinity')
        layouts = ('TOKEN', '[TOKEN, "PRIVATE_MARKER"]',
                   '{"method":"event","params":{"x":TOKEN,"text":"PRIVATE_MARKER"}}',
                   '{"error":{"data":{"x":TOKEN,"text":"PRIVATE_MARKER"}}}',
                   '{"result":{"ignored":{"x":TOKEN,"text":"PRIVATE_MARKER"}}}',
                   '{"ignored":TOKEN,"ignored":0,"text":"PRIVATE_MARKER"}')
        for token in tokens:
            for layout in layouts:
                with self.subTest(token=token, layout=layout):
                    with self.assertRaises(ValueError) as caught:
                        bridge._strict_json(layout.replace('TOKEN', token))
                    self.assertEqual(str(caught.exception), 'nonfinite JSON number')
                    self.assertNotIn('PRIVATE_MARKER', str(caught.exception))

    def test_strict_json_preserves_finite_float_and_integer_semantics(self):
        cases = [('0.5', 0.5), ('-12.25', -12.25), ('1e308', 1e308),
                 ('1.7976931348623157e308', sys.float_info.max),
                 ('5e-324', float.fromhex('0x0.0000000000001p-1022')),
                 ('1e-999', 0.0), ('-1e-999', -0.0), ('0', 0),
                 ('123456789012345678901234567890', 123456789012345678901234567890),
                 ('"1e999"', '1e999')]
        for token, expected in cases:
            with self.subTest(token=token):
                actual = bridge._strict_json(token)
                self.assertIs(type(actual), type(expected))
                self.assertEqual(actual, expected)
                if type(actual) is float:
                    self.assertEqual(math.copysign(1, actual), math.copysign(1, expected))


class UrlTests(unittest.TestCase):
    def test_game_url_trust_boundary(self):
        for url in [URL, 'https://www.nomstead.com:443/a#b', 'HTTPS://NOMSTEAD.COM/']:
            bridge.validate_game_url(url)
        for url in [None, 12, '', 'http://nomstead.com', 'https://nomstead.com.evil',
                    'https://nomstead.com@evil', 'https://user@nomstead.com',
                    'https://nomstead.com:444', 'https://nomstead.com:bad',
                    'https://nomstead.com:', 'https://nomstead.com./',
                    'https://nomstead.com/ space', 'https://nomstead.com/\n',
                    'https://nomstead.com\\evil', 'https://nomstead.com/\x7f']:
            with self.subTest(url=url), self.assertRaises(bridge.CdpError):
                bridge.validate_game_url(url)

    def test_ws_endpoint_is_exact_loopback_page(self):
        bridge.validate_ws_url(WS)
        for url in [None, '', WS + '?', WS + '#', WS + '/', WS + '/extra',
                    WS.replace('127.0.0.1', 'localhost'), WS.replace('9222', '9223'),
                    WS.replace('ws:', 'wss:'), WS.replace('ABC-123_4', '%41'),
                    'ws://127.0.0.1:9222/devtools/page/', WS + '\n',
                    WS.replace('127.0.0.1', 'user@127.0.0.1')]:
            with self.subTest(url=url), self.assertRaises(bridge.CdpError):
                bridge.validate_ws_url(url)


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_exactly_one_trusted_page(self):
        target = dict(type='page', url=URL, webSocketDebuggerUrl=WS)
        unrelated = [dict(type='worker', url=URL), dict(type='page', url='https://evil.com')]
        with mock.patch.object(bridge, '_fetch_targets', return_value=unrelated + [target]):
            self.assertEqual(await bridge.discover_tab(), bridge.Tab(URL, WS))
        for targets in [[], unrelated, [target, target], [dict(target, webSocketDebuggerUrl=WS+'?')],
                        [dict(type='page', url=URL)], {}, None]:
            with self.subTest(targets=targets), mock.patch.object(bridge, '_fetch_targets', return_value=targets):
                with self.assertRaises(bridge.CdpError):
                    await bridge.discover_tab()

    async def test_transport_failures_are_safe_and_cancellation_propagates(self):
        for error in [TimeoutError('private'), OSError('private'), ValueError('private')]:
            with mock.patch.object(bridge, '_fetch_targets', side_effect=error):
                with self.assertRaises(bridge.CdpError):
                    await bridge.discover_tab()
        with mock.patch.object(bridge, '_fetch_targets', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await bridge.discover_tab()


class HttpTests(unittest.TestCase):
    def fetch(self, body=b'[]', status=200, headers=None, read_error=None):
        connection = mock.MagicMock()
        reply = mock.MagicMock()
        reply.status = status
        reply.getheader.side_effect = lambda key: (headers or {}).get(key)
        pieces = [body, b'']
        reply.read1.side_effect = read_error or pieces
        connection.getresponse.return_value = reply
        factory = mock.patch.object(bridge.http.client, 'HTTPConnection', return_value=connection)
        return factory, connection, reply

    def test_fixed_destination_and_cleanup(self):
        factory, connection, reply = self.fetch()
        with factory as constructor:
            self.assertEqual(bridge._fetch_targets(), [])
        constructor.assert_called_once_with('127.0.0.1', 9222, timeout=3.0)
        connection.request.assert_called_once_with('GET', '/json')
        connection.close.assert_called_once()
        reply.close.assert_called_once()

    def test_discovery_rejects_hidden_exponent_overflow_and_closes(self):
        for token in ('1e999', '-1e999'):
            body = json.dumps([{'type': 'page', 'url': URL,
                                'ignored': {'x': 'TOKEN', 'text': 'PRIVATE_MARKER'}}])
            factory, connection, reply = self.fetch(body=body.replace('"TOKEN"', token).encode('utf-8'))
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(token=token):
                with factory as constructor, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(bridge.CdpError) as caught:
                        bridge._fetch_targets()
                self.assertNotIn('PRIVATE_MARKER', str(caught.exception))
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')
                constructor.assert_called_once_with('127.0.0.1', 9222, timeout=3.0)
                connection.request.assert_called_once_with('GET', '/json')
                connection.close.assert_called_once()
                reply.close.assert_called_once()

    def test_redirect_malformed_and_oversized_responses_fail_without_followup(self):
        cases = [dict(status=302, headers={'Location': 'https://evil.com'}),
                 dict(body=b'{'), dict(body=b'{}'), dict(body=b'\xff'),
                 dict(body=b'[NaN]'), dict(body=b'x'*(1024*1024+1)),
                 dict(body=b'['*10000+b'"PRIVATE_PAYLOAD"'+b']'*10000),
                 dict(headers={'Content-Length': str(1024*1024+1)}),
                 dict(headers={'Content-Length': 'nonsense'}),
                 dict(headers={'Content-Length': '5'}),
                 dict(read_error=TimeoutError()), dict(read_error=OSError())]
        for case in cases:
            factory, connection, reply = self.fetch(**case)
            with self.subTest(case=list(case)), factory:
                with self.assertRaises(bridge.CdpError):
                    bridge._fetch_targets()
            connection.request.assert_called_once_with('GET', '/json')
            connection.close.assert_called_once()
            reply.close.assert_called_once()

    def test_read_deadline_is_absolute(self):
        factory, connection, reply = self.fetch()
        with factory, mock.patch.object(bridge.time, 'monotonic', side_effect=[0, 0, 0, 4]):
            with self.assertRaises(bridge.CdpError):
                bridge._fetch_targets()
        connection.close.assert_called_once()

    def test_watchdog_bounds_detached_response_socket(self):
        connection = mock.MagicMock()
        sock = connection.sock
        stopped = threading.Event()
        sock.shutdown.side_effect = lambda _: stopped.set()
        def slow_headers():
            connection.sock = None
            stopped.wait(.3)
            raise OSError('deadline')
        connection.getresponse.side_effect = slow_headers
        started = time.monotonic()
        with mock.patch.object(bridge.http.client, 'HTTPConnection', return_value=connection), \
                mock.patch.object(bridge, '_CDP_TIMEOUT', .03):
            with self.assertRaises(bridge.CdpError):
                bridge._fetch_targets()
        self.assertLess(time.monotonic()-started, .2)
        self.assertTrue(stopped.is_set())


class ReadStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_rejects_overflow_event_before_valid_response(self):
        for token in ('1e999', '-1e999'):
            event = '{"method":"Page.event","params":{"x":TOKEN,"text":"PRIVATE_MARKER"}}'.replace('TOKEN', token)
            socket = FakeSocket([event, response()])
            stdout, stderr = io.StringIO(), io.StringIO()
            close = mock.AsyncMock(wraps=socket.__aexit__)
            with self.subTest(token=token):
                with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket) as connect, \
                        mock.patch.object(FakeSocket, '__aexit__', new=close), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(bridge.CdpError) as caught:
                        await bridge.read_status(bridge.Tab(URL, WS))
                self.assertNotIn('PRIVATE_MARKER', str(caught.exception))
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')
                self.assertTrue(socket.closed)
                close.assert_awaited_once()
                self.assertEqual(socket.recv_calls, 1)
                self.assertEqual(connect.call_count, 1)
                self.assertEqual(socket.sent, [{'id': 1, 'method': 'Runtime.evaluate',
                    'params': {'expression': bridge.STATUS_READONLY, 'returnByValue': True}}])

    async def test_one_fixed_evaluation_event_and_close(self):
        socket = FakeSocket([json.dumps({'method':'Page.event', 'params':{}}), response()])
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket) as connect, \
                mock.patch.object(bridge.WorkerClient, 'spawn', side_effect=AssertionError('worker')):
            status = await bridge.read_status(bridge.Tab(URL, WS))
        self.assertEqual(status, bridge.Status(**values()))
        self.assertEqual(socket.sent, [{'id':1, 'method':'Runtime.evaluate',
                                      'params':{'expression':bridge.STATUS_READONLY, 'returnByValue':True}}])
        self.assertTrue(socket.closed)
        self.assertEqual(connect.call_args.args, (WS,))
        self.assertEqual(connect.call_args.kwargs, dict(proxy=None, compression=None, open_timeout=3.0,
                         close_timeout=1, max_size=1024*1024, max_queue=4, ping_interval=None))

    async def test_default_and_explicit_https_port_share_origin(self):
        socket = FakeSocket([response(url='https://nomstead.com:443/other')])
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
            self.assertEqual((await bridge.read_status(bridge.Tab(URL, WS))).energy, 70)

    async def test_revalidate_constructed_tab_before_connect(self):
        for tab in [bridge.Tab('https://evil.com', WS), bridge.Tab(URL, WS+'?')]:
            with mock.patch.object(bridge, '_ReadOnlyConnect') as connect:
                with self.assertRaises(bridge.CdpError):
                    await bridge.read_status(tab)
                connect.assert_not_called()

    async def test_reject_malformed_messages_and_live_origin_change_then_close(self):
        bad = ['[]', 'null', '1', '{', b'{}', '{}', '{"method":1}',
               '{"method":"event","params":[]}', '{"id":true}', '{"id":2}',
               '{"id":1,"error":{"message":"private"}}',
               '{"id":1,"result":{"exceptionDetails":{}}}',
               '{"id":1,"result":{"result":{"value":[]}}}',
               response(url='https://evil.com'), response(url='https://www.nomstead.com'),
               response(sequence_available=True), response(sequence=1), response(dpr=0),
               response(width=True), response(xp=2**53), response(width=float('nan')),
               ' '* (1024*1024+1), OSError('closed')]
        for message in bad:
            socket = FakeSocket([message])
            with self.subTest(message=str(message)[:60]), mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
                with self.assertRaises(bridge.CdpError):
                    await bridge.read_status(bridge.Tab(URL, WS))
            self.assertTrue(socket.closed)
            self.assertEqual(len(socket.sent), 1)

    async def test_send_failure_and_cancellation_close(self):
        for error in [OSError('closed'), asyncio.CancelledError()]:
            socket = FakeSocket([])
            socket.send = mock.AsyncMock(side_effect=error)
            with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
                with self.assertRaises(asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else bridge.CdpError):
                    await bridge.read_status(bridge.Tab(URL, WS))
            self.assertTrue(socket.closed)

    async def test_receive_cancellation_propagates_and_handshake_failure_is_safe(self):
        socket = FakeSocket([asyncio.CancelledError()])
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
            with self.assertRaises(asyncio.CancelledError):
                await bridge.read_status(bridge.Tab(URL, WS))
        self.assertTrue(socket.closed)
        with mock.patch.object(bridge, '_ReadOnlyConnect', side_effect=OSError('private')):
            with self.assertRaises(bridge.CdpError):
                await bridge.read_status(bridge.Tab(URL, WS))

    async def test_events_do_not_reset_response_deadline(self):
        async def event():
            await asyncio.sleep(.012)
            return '{"method":"event"}'
        socket = FakeSocket([event]*20)
        with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket), mock.patch.object(bridge, '_CDP_TIMEOUT', .035):
            with self.assertRaises(bridge.CdpError):
                await bridge.read_status(bridge.Tab(URL, WS))
        self.assertTrue(socket.closed)
        self.assertLess(socket.recv_calls, 8)

    async def test_redirect_hook_returns_exception_without_connecting(self):
        from websockets.datastructures import Headers
        from websockets.exceptions import InvalidStatus
        from websockets.http11 import Response
        error = InvalidStatus(Response(302, 'Found', Headers({'Location':'ws://evil.com/'})))
        connector = bridge._ReadOnlyConnect(WS)
        self.assertIs(connector.process_redirect(error), error)


class CodecTests(unittest.TestCase):
    def test_independent_golden_roundtrip_unicode_and_null(self):
        status = bridge.Status(**values(url='https://nomstead.com', width=100, height=8192,
                                       dpr=2, energy=None, xp=None, toast='cá', modal=True))
        golden = (b'\x14\0\0\0https://nomstead.com' +
                  struct.pack('<ddd', 100, 8192, 2) + b'\0\0\x03\0\0\0c\xc3\xa1' +
                  b'\0' + b'\0'*8 + b'\x01')
        # URL is 20 UTF-8 bytes, verified independently of the encoder.
        self.assertEqual(bridge.encode_status(status), golden)
        self.assertEqual(bridge.decode_status(golden), status)

    def test_integer_boundaries_and_maximum_utf8(self):
        for energy, xp, sequence in [(0,0,0), (2**32-1,2**64-1,2**64-1)]:
            status = bridge.Status(**values(energy=energy, xp=xp, sequence_available=True,
                                           sequence=sequence, toast='é'*2048))
            self.assertEqual(bridge.decode_status(bridge.encode_status(status)), status)
        status = bridge.Status(**values(toast='', energy=None, xp=None))
        self.assertEqual(bridge.decode_status(bridge.encode_status(status)), status)
        status = bridge.Status(**values(url='https://nomstead.com/'+'a'*4075))
        self.assertEqual(bridge.decode_status(bridge.encode_status(status)), status)

    def test_present_integer_golden_bytes(self):
        status = bridge.Status(**values(url='https://nomstead.com', width=100, height=100,
                                       dpr=1, energy=0x04030201, xp=0x0807060504030201,
                                       toast='', sequence_available=True, sequence=0x1817161514131211))
        golden = (b'\x14\0\0\0https://nomstead.com' + struct.pack('<ddd',100,100,1) +
                  b'\x01\x01\x02\x03\x04' + b'\x01\x01\x02\x03\x04\x05\x06\x07\x08' +
                  b'\0\0\0\0\x01\x11\x12\x13\x14\x15\x16\x17\x18\0')
        self.assertEqual(bridge.encode_status(status),golden)
        self.assertEqual(bridge.decode_status(golden),status)

    def test_reject_invalid_types_ranges_utf8_and_sequence(self):
        invalid = dict(width=[True,99,8193,float('nan'),float('inf'),'1200',None],
                       height=[False,0,8193], dpr=[True,0,-1,float('inf')],
                       energy=[True,-1,2**32,1.0], xp=[False,-1,2**64,1.0],
                       sequence=[True,-1,2**64,1.0,1], sequence_available=[0,1,None],
                       modal=[0,1,None], url=['https://evil.com',None, 'https://nomstead.com/'+ 'a'*4096],
                       toast=[None,42,'é'*2049,'\ud800'])
        for key, variants in invalid.items():
            for value in variants:
                with self.subTest(field=key, value=str(value)[:30]), self.assertRaises(bridge.ProtocolError):
                    bridge.encode_status(bridge.Status(**values(**{key:value})))

    def test_decode_rejects_every_truncation_tags_utf8_lengths_and_trailing_bytes(self):
        payload = bridge.encode_status(bridge.Status(**values(url='https://nomstead.com', toast='')))
        for end in range(len(payload)):
            with self.subTest(end=end), self.assertRaises(bridge.ProtocolError):
                bridge.decode_status(payload[:end])
        # Offsets: URL 4+20; numeric fields 24; energy tag 48; XP tag 53;
        # toast length 62; sequence flag 66; sequence 67..74; modal 75.
        for offset in [48,53,66,75]:
            bad = bytearray(payload)
            bad[offset] = 2
            with self.subTest(tag=offset), self.assertRaises(bridge.ProtocolError):
                bridge.decode_status(bytes(bad))
        for bad in [payload+b'x', b'\x01\x10\0\0', b'\x01\0\0\0\xff', bytearray(payload), None]:
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_status(bad)
        for offset, encoded in [(24, struct.pack('<d',float('nan'))), (67,struct.pack('<Q',1))]:
            bad = payload[:offset] + encoded + payload[offset+8:]
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_status(bad)


class ExpressionTests(unittest.TestCase):
    def test_actual_literal_reads_dom_without_mutating_page(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node unavailable for isolated DOM fixture')
        fixture = r'''
const fs=require('fs'); const expr=fs.readFileSync(0,'utf8');
const deny=()=>{throw Error('page mutation');};
global.MutationObserver=deny; global.localStorage=new Proxy({}, {set:deny});
global.window=new Proxy({}, {set:deny}); global.innerWidth=1200;global.innerHeight=800;global.devicePixelRatio=1.5;
global.location=Object.freeze({href:'https://nomstead.com/play'});
const run=(energy,xp,toast,modal)=>{
 global.document=Object.freeze({
  querySelector:s=>({'div.info > div.number':energy===null?null:{innerText:energy},'.remaining-xp':{innerText:xp},'.message-bar':{innerText:toast}}[s]),
  querySelectorAll:s=>s==='.modal-body'?modal.map(m=>({getClientRects:()=>m.rect?[{}]:[], visibility:m.visibility})):[]});
 global.getComputedStyle=e=>({visibility:e.visibility});
 return eval(expr);
};
let result=[];
for(const energy of ['70 / 80','0/80','80 / 80',null])result.push(run(energy,'1,234 remaining','  HELLO Cá  ',[{rect:true,visibility:'visible'}]));
result.push(run(null,'','', [{rect:false,visibility:'visible'},{rect:true,visibility:'hidden'}]));
let unsafe=false;try{run(null,'9007199254740993','',[]);}catch(e){unsafe=true;}
console.log(JSON.stringify({result,unsafe}));
'''
        process = subprocess.run([node, '-e', fixture], input=bridge.STATUS_READONLY,
                                 text=True, encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertTrue(output['unsafe'])
        self.assertEqual([s['energy'] for s in output['result']], [70,0,80,None,None])
        for status in output['result'][:4]:
            self.assertEqual(status['xp'],1234)
            self.assertEqual(status['toast'],'hello cá')
            self.assertTrue(status['modal'])
            self.assertIs(status['sequence_available'], False)
            self.assertEqual(status['sequence'], 0)
        self.assertFalse(output['result'][-1]['modal'])
        self.assertIsNone(output['result'][-1]['xp'])

    def test_xp_progress_bar_and_legacy_priority(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node unavailable for isolated DOM fixture')
        fixture = r'''
const fs=require('fs'); const expr=fs.readFileSync(0,'utf8');
global.innerWidth=1200;global.innerHeight=800;global.devicePixelRatio=1.5;
global.location=Object.freeze({href:'https://nomstead.com/play'});
const run=(legacyXp,progXp,barStyleWidth,barAttrStyle)=>{
 const bar=(barStyleWidth!==null||barAttrStyle!==null)?{
  style:barStyleWidth!==null?{width:barStyleWidth}:{},
  getAttribute:k=>k==='style'?barAttrStyle:null
 }:null;
 global.document=Object.freeze({
  querySelector:s=>({
   'div.info > div.number':{innerText:'70 / 80'},
   '.remaining-xp':legacyXp===null?null:{innerText:legacyXp},
   '.xp-progress-number':progXp===null?null:{innerText:progXp},
   '.xp-progress-bar':bar,
   '.message-bar':{innerText:''}
  }[s]),
  querySelectorAll:()=>[]
 });
 global.getComputedStyle=()=>({visibility:'visible'});
 return eval(expr).xp;
};
const out={
 bar_style_width: run(null, '19.1K/75K', '25.4227%', null),
 bar_attr_style: run(null, '19.1K/75K', null, 'height: 100%; width: 25.4227%;'),
 no_bar_k: run(null, '19.1K/75K', null, null),
 no_bar_plain: run(null, '450/1000', null, null),
 legacy_priority: run('2,345 remaining', '19.1K/75K', '25.4227%', null),
 empty_both: run('', '', null, null)
};
console.log(JSON.stringify(out));
'''
        process = subprocess.run([node, '-e', fixture], input=bridge.STATUS_READONLY,
                                 text=True, encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output['bar_style_width'], 19067)
        self.assertEqual(output['bar_attr_style'], 19067)
        self.assertEqual(output['no_bar_k'], 19100)
        self.assertEqual(output['no_bar_plain'], 450)
        self.assertEqual(output['legacy_priority'], 2345)
        self.assertIsNone(output['empty_both'])

    def test_toast_ignores_hidden_dom_elements(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node unavailable for isolated DOM fixture')
        fixture = r'''
const fs=require('fs'); const expr=fs.readFileSync(0,'utf8');
global.innerWidth=1200;global.innerHeight=800;global.devicePixelRatio=1.5;
global.location=Object.freeze({href:'https://nomstead.com/play'});
const mk=(text, rect, vis)=>({innerText:text, getClientRects:()=>rect?[{}]:[], _vis:vis});
const run=(primary, secondary)=>{
 global.document=Object.freeze({
  querySelector:s=>{
   if(s==='div.info > div.number')return {innerText:'70 / 80'};
   if(s==='.message-bar')return primary;
   if(s.includes('.toast'))return secondary;
   return null;
  },
  querySelectorAll:()=>[]
 });
 global.getComputedStyle=e=>({visibility:e._vis||'visible'});
 return eval(expr).toast;
};
const out={
 hidden_primary_fallback_secondary: run(mk('stale hidden', false, 'visible'), mk('Fresh Visible', true, 'visible')),
 invisible_primary_and_secondary: run(mk('hidden 1', true, 'hidden'), mk('hidden 2', false, 'visible')),
 visible_primary_wins: run(mk('Primary Toast', true, 'visible'), mk('Secondary Toast', true, 'visible'))
};
console.log(JSON.stringify(out));
'''
        process = subprocess.run([node, '-e', fixture], input=bridge.STATUS_READONLY,
                                 text=True, encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output['hidden_primary_fallback_secondary'], 'fresh visible')
        self.assertEqual(output['invisible_primary_and_secondary'], '')
        self.assertEqual(output['visible_primary_wins'], 'primary toast')


class HarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_deep_discovery_json_exits_safely_without_status_followup(self):
        spec = importlib.util.spec_from_file_location('live_status_smoke', Path(__file__).with_name('live_status_smoke.py'))
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        connection = mock.MagicMock()
        reply = connection.getresponse.return_value
        reply.status = 200
        reply.getheader.return_value = None
        reply.read1.side_effect = [b'['*10000+b'"PRIVATE_PAYLOAD"'+b']'*10000, b'']
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(bridge.http.client, 'HTTPConnection', return_value=connection) as http, \
                mock.patch.object(bridge, 'read_status') as read, \
                mock.patch.object(bridge, '_ReadOnlyConnect') as websocket, \
                mock.patch.object(bridge.WorkerClient, 'spawn', side_effect=AssertionError('worker')), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(await harness.run(), 1)
        http.assert_called_once_with('127.0.0.1', 9222, timeout=3.0)
        connection.request.assert_called_once_with('GET', '/json')
        connection.close.assert_called_once()
        reply.close.assert_called_once()
        read.assert_not_called()
        websocket.assert_not_called()
        self.assertIn('PENDING: discovery unavailable or trusted tab selection failed', stdout.getvalue())
        self.assertEqual(stderr.getvalue(), '')
        for secret in ['PRIVATE_PAYLOAD', 'Traceback', 'RecursionError']:
            self.assertNotIn(secret, stdout.getvalue())

    async def test_safe_success_missing_energy_and_error_outputs(self):
        spec = importlib.util.spec_from_file_location('live_status_smoke', Path(__file__).with_name('live_status_smoke.py'))
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        for energy, error, expected in [(70,None,0),(None,None,1),(70,bridge.CdpError('PRIVATE'),1)]:
            stdout = io.StringIO()
            with mock.patch.object(bridge, 'discover_tab', return_value=bridge.Tab(URL,WS)), \
                    mock.patch.object(bridge, 'read_status', return_value=bridge.Status(**values(energy=energy)), side_effect=error) as read, \
                    mock.patch.object(bridge.WorkerClient, 'spawn', side_effect=AssertionError('worker')), \
                    mock.patch.object(asyncio, 'create_subprocess_exec', side_effect=AssertionError('worker')), \
                    contextlib.redirect_stdout(stdout):
                self.assertEqual(await harness.run(), expected)
            output = stdout.getvalue()
            self.assertIn('BRIDGE-ONLY READ-ONLY; WORKER NOT TESTED',output)
            for secret in ['private=yes', WS, 'PRIVATE', 'hello', '1234']:
                self.assertNotIn(secret,output)
            read.assert_awaited_once()
            if expected == 0:
                self.assertIn('https://nomstead.com',output)
                self.assertIn('sequence_available=false sequence=0',output)
            elif energy is None:
                self.assertIn('log in directly',output)


if __name__ == '__main__':
    unittest.main()
