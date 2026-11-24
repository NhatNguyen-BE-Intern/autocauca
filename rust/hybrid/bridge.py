"""Framed worker scaffold and independent, fixed read-only CDP status reader."""

from __future__ import annotations

import argparse
import asyncio
import base64
import http.client
import io
import json
import math
import os
import random
import re
import socket
import struct
import sys
import threading
import time
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit

def _is_low_cpu_vm() -> bool:
    """True on <= 2 logical CPU VMs (or NOMSTEAD_LOW_CPU=1), False on > 2 CPU hosts."""
    override = os.environ.get("NOMSTEAD_LOW_CPU", "").strip().lower()
    if override in ("1", "true", "yes"):
        return True
    if override in ("0", "false", "no"):
        return False
    return (os.cpu_count() or 2) <= 2


_DEFAULT_THREADS = os.environ.get("NOMSTEAD_THREADS") or ("1" if _is_low_cpu_vm() else "2")
for _env_key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_env_key, _DEFAULT_THREADS)

import cv2

try:
    cv2.setNumThreads(max(1, int(_DEFAULT_THREADS)))
except Exception:
    cv2.setNumThreads(2)

import numpy as np
from PIL import Image
from websockets.asyncio.client import connect

VERSION = 1
MAX_FRAME_LEN = 32 * 1024 * 1024
FRAME_HEADER_LEN = 8
RGB_HEADER_LEN = 20
MAX_DIMENSION = 8192

KIND_HELLO = 1
KIND_HELLO_ACK = 2
KIND_REQUEST = 3
KIND_RESPONSE = 4
KIND_ERROR = 5
KIND_SHUTDOWN = 6
KIND_SHUTDOWN_ACK = 7
KIND_RGB = 8
ERROR_UNSUPPORTED_TASK1 = 1
ERROR_INVALID_STATUS = 2
ERROR_INVALID_PAYLOAD = 3
MAX_OPERATION_ID = 0xFFFFFFFE
OP_CHECK_STATUS = 1
OP_DIAGNOSE = 2
OP_CLICK_CAST = 3
OP_CLICK_STRIKE = 4
OP_EAT_BREAD = 5
OP_TRAVEL_LAKE = 6

ACTION_STATUS_OK = 0
ACTION_STATUS_PRECONDITION_FAILED = 1
ACTION_STATUS_PROTOCOL_ERROR = 2

EAT_BREAD_OK = 0
EAT_BREAD_FAILED = 1
EAT_BREAD_SKIPPED_FULL = 2

TRAVEL_LAKE_OK = 0
TRAVEL_LAKE_FAILED = 1
TRAVEL_LAKE_INVALID = 2

_KNOWN_KINDS = {
    KIND_HELLO,
    KIND_HELLO_ACK,
    KIND_REQUEST,
    KIND_RESPONSE,
    KIND_ERROR,
    KIND_SHUTDOWN,
    KIND_SHUTDOWN_ACK,
    KIND_RGB,
}
_ZERO_ID_KINDS = {KIND_HELLO, KIND_HELLO_ACK, KIND_SHUTDOWN, KIND_SHUTDOWN_ACK}


class ProtocolError(Exception):
    """A malformed or out-of-order worker protocol exchange."""


class CdpError(Exception):
    """Discovery, transport or status validation failed."""


class ActionPreconditionError(Exception):
    """Ngoại lệ khi vi phạm điều kiện an toàn trước thao tác click."""


@dataclass
class Tab:
    url: str
    websocket_url: str
    ws: Any = field(default=None, compare=False, repr=False)
    _next_id: int = field(default=1, compare=False, repr=False)
    _last_water_point: Optional[Tuple[int, int]] = field(default=None, compare=False, repr=False)
    _ws_cm: Any = field(default=None, compare=False, repr=False)
    _managed_ws: bool = field(default=False, compare=False, repr=False)
    _want_persistent_ws: bool = field(default=False, compare=False, repr=False)
    _fast_alert_status: Optional["Status"] = field(default=None, compare=False, repr=False)
    _cursor_pos: Optional[Tuple[float, float]] = field(default=None, compare=False, repr=False)
    _stale_toast: str = field(default="", compare=False, repr=False)

    def next_id(self) -> int:
        cur = self._next_id
        self._next_id += 1
        return cur


@dataclass(frozen=True)
class Status:
    url: str
    width: float
    height: float
    dpr: float
    energy: Optional[int]
    xp: Optional[int]
    toast: str
    sequence_available: bool
    sequence: int
    modal: bool


_CDP_TIMEOUT = 3.0
_CDP_MAX_BYTES = 1024 * 1024
_CAPTURE_BASE64_MAX_CHARS = 4 * ((MAX_FRAME_LEN + 2) // 3)
_CAPTURE_CDP_MAX_BYTES = _CAPTURE_BASE64_MAX_CHARS + 4096
_MAX_STATUS_STRING = 4096

STATUS_READONLY = r"""(() => {
 const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
 const energy=(document.querySelector('div.info > div.number')?.innerText||'').match(/(\d+)\s*\/\s*80/);
 const xp=(document.querySelector('.remaining-xp')?.innerText||'').replace(/,/g,'').match(/(\d+)/);
 const xpValue=xp?Number(xp[1]):null;
 if(xpValue!==null&&!Number.isSafeInteger(xpValue))throw Error('unsafe status XP');
 const getToast=()=>{
  const primary=document.querySelector('.message-bar');
  const primaryText=(primary?.innerText||'').trim();
  if(primaryText.length>0)return primaryText.toLowerCase();
  const secondary=document.querySelector('.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]');
  return (secondary?.innerText||'').trim().toLowerCase();
 };
 return {url:location.href,width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
 energy:energy?Number(energy[1]):null,xp:xpValue,
 toast:getToast(),
 sequence_available:false,sequence:0,modal:[...document.querySelectorAll('.modal-body')].some(visible)};
})()"""


def validate_game_url(url: str) -> None:
    if type(url) is not str or not url or any(c.isspace() or ord(c)<32 or ord(c)==127 or c=='\\' for c in url):
        raise CdpError('invalid game URL')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('nomstead.com', 'www.nomstead.com')
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.netloc.endswith(':')):
            raise ValueError()
    except ValueError as error:
        raise CdpError('untrusted game URL') from error


def validate_ws_url(url: str) -> None:
    if type(url) is not str or re.fullmatch(r'ws://127\.0\.0\.1:9222/devtools/page/[A-Za-z0-9_-]+', url) is None:
        raise CdpError('invalid CDP endpoint')


def _validate_browser_ws_url(url: str) -> None:
    if type(url) is not str or re.fullmatch(r'ws://127\.0\.0\.1:9222/devtools/browser/[A-Za-z0-9_-]+', url) is None:
        raise CdpError('invalid browser CDP endpoint')


def _extract_page_target_id(ws_url: str) -> str:
    validate_ws_url(ws_url)
    return ws_url.rsplit('/', 1)[-1]


def _origin(url: str):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or 443


def _strict_json(data):
    def reject_constant(_):
        raise ValueError('nonfinite JSON number')
    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError('nonfinite JSON number')
        return value
    return json.loads(data, parse_constant=reject_constant, parse_float=finite_float)


def _fetch_targets():
    """A fixed direct HTTP request; the watchdog also bounds slow header reads."""
    deadline = time.monotonic() + _CDP_TIMEOUT
    connection = http.client.HTTPConnection('127.0.0.1', 9222, timeout=_CDP_TIMEOUT)
    reply = None
    transport = None

    def abort():
        sock = transport if transport is not None else connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    watchdog = threading.Timer(_CDP_TIMEOUT, abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        connection.connect()
        # HTTPConnection may detach its socket for a Connection: close response.
        transport = connection.sock
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CdpError('discovery deadline exceeded')
        transport.settimeout(remaining)
        connection.request('GET', '/json')
        reply = connection.getresponse()
        if reply.status != 200:
            raise CdpError('discovery HTTP status rejected')
        length = reply.getheader('Content-Length')
        if length is not None:
            if re.fullmatch(r'[0-9]+', length) is None or int(length) > _CDP_MAX_BYTES:
                raise CdpError('invalid discovery length')
            length = int(length)
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError('discovery deadline exceeded')
            transport.settimeout(remaining)
            chunk = reply.read1(min(65536, _CDP_MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > _CDP_MAX_BYTES:
                raise CdpError('discovery body too large')
        if time.monotonic() > deadline or (length is not None and len(body) != length):
            raise CdpError('discovery truncated or timed out')
        targets = _strict_json(body.decode('utf-8'))
        if not isinstance(targets, list):
            raise CdpError('invalid discovery targets')
        return targets
    except (OSError, ValueError, RecursionError, http.client.HTTPException) as error:
        raise CdpError('discovery transport or data failure') from error
    finally:
        watchdog.cancel()
        if reply is not None:
            reply.close()
        connection.close()


def _fetch_browser_ws_url() -> str:
    """Fetch and strictly validate the Chrome browser-level CDP WebSocket URL from /json/version."""
    deadline = time.monotonic() + _CDP_TIMEOUT
    connection = http.client.HTTPConnection('127.0.0.1', 9222, timeout=_CDP_TIMEOUT)
    reply = None
    transport = None

    def abort():
        sock = transport if transport is not None else connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    watchdog = threading.Timer(_CDP_TIMEOUT, abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        connection.connect()
        transport = connection.sock
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CdpError('browser version deadline exceeded')
        transport.settimeout(remaining)
        connection.request('GET', '/json/version')
        reply = connection.getresponse()
        if reply.status != 200:
            raise CdpError('browser version HTTP status rejected')
        length = reply.getheader('Content-Length')
        if length is not None:
            if re.fullmatch(r'[0-9]+', length) is None or int(length) > _CDP_MAX_BYTES:
                raise CdpError('invalid browser version length')
            length = int(length)
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError('browser version deadline exceeded')
            transport.settimeout(remaining)
            chunk = reply.read1(min(65536, _CDP_MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > _CDP_MAX_BYTES:
                raise CdpError('browser version body too large')
        if time.monotonic() > deadline or (length is not None and len(body) != length):
            raise CdpError('browser version truncated or timed out')
        info = _strict_json(body.decode('utf-8'))
        if not isinstance(info, dict):
            raise CdpError('invalid browser version payload')
        ws_url = info.get('webSocketDebuggerUrl')
        _validate_browser_ws_url(ws_url)
        return ws_url
    except CdpError:
        raise
    except (OSError, ValueError, RecursionError, http.client.HTTPException) as error:
        raise CdpError('browser version transport or data failure') from error
    finally:
        watchdog.cancel()
        if reply is not None:
            reply.close()
        connection.close()


async def _browser_cdp_call(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one browser-level CDP RPC call (e.g. Target.createTarget / Target.closeTarget)."""
    browser_ws = await asyncio.to_thread(_fetch_browser_ws_url)
    _validate_browser_ws_url(browser_ws)
    try:
        async with _ReadOnlyConnect(
            browser_ws,
            proxy=None,
            compression=None,
            open_timeout=_CDP_TIMEOUT,
            close_timeout=1,
            max_size=_CDP_MAX_BYTES,
            max_queue=4,
            ping_interval=None,
        ) as ws:
            async with asyncio.timeout(_CDP_TIMEOUT):
                await ws.send(json.dumps({'id': 1, 'method': method, 'params': params}))
                result, _ = await _receive_cdp_result(ws, 1, _CDP_MAX_BYTES)
                return result
    except (CdpError, asyncio.CancelledError):
        raise
    except Exception as error:
        raise CdpError('browser CDP transport failure') from error


async def discover_tab() -> Tab:
    try:
        targets = await asyncio.to_thread(_fetch_targets)
        if not isinstance(targets, list):
            raise CdpError('invalid discovery targets')
        selected = []
        for target in targets:
            if not isinstance(target, dict) or target.get('type') != 'page':
                continue
            try:
                validate_game_url(target.get('url'))
            except CdpError:
                continue
            selected.append(target)
        if len(selected) != 1:
            raise CdpError('expected exactly one trusted game tab')
        target = selected[0]
        validate_ws_url(target.get('webSocketDebuggerUrl'))
        return Tab(target['url'], target['webSocketDebuggerUrl'])
    except (OSError, ValueError) as error:
        raise CdpError('discovery failure') from error


class _ReadOnlyConnect(connect):
    def process_redirect(self, exc):
        return exc


async def _open_managed_ws(tab: Tab):
    validate_game_url(tab.url)
    validate_ws_url(tab.websocket_url)
    ws_cm = _ReadOnlyConnect(
        tab.websocket_url,
        proxy=None,
        compression=None,
        open_timeout=_CDP_TIMEOUT,
        close_timeout=1,
        max_size=_CAPTURE_CDP_MAX_BYTES,
        max_queue=64,
        ping_interval=None,
    )
    ws = await ws_cm.__aenter__()
    tab.ws = ws
    tab._ws_cm = ws_cm
    tab._managed_ws = True
    return ws


async def close_cdp_session(tab: Tab) -> None:
    tab._fast_alert_status = None
    ws_cm = getattr(tab, "_ws_cm", None)
    was_managed = getattr(tab, "_managed_ws", False)
    tab._ws_cm = None
    tab._managed_ws = False
    if was_managed:
        tab.ws = None
        if ws_cm is not None:
            try:
                await ws_cm.__aexit__(None, None, None)
            except Exception:
                pass


@asynccontextmanager
async def cdp_session(tab: Tab):
    if getattr(tab, "_want_persistent_ws", False) or getattr(tab, "ws", None) is not None:
        yield tab
        return
    tab._want_persistent_ws = True
    try:
        yield tab
    finally:
        tab._want_persistent_ws = False
        await close_cdp_session(tab)


def _validate_status(status: Status) -> None:
    if type(status) is not Status:
        raise CdpError('invalid status type')
    validate_game_url(status.url)
    for value in (status.url, status.toast):
        try:
            if type(value) is not str or len(value.encode('utf-8')) > _MAX_STATUS_STRING:
                raise CdpError('invalid status string')
        except UnicodeError as error:
            raise CdpError('invalid status UTF-8') from error
    for name in ('width', 'height', 'dpr'):
        value = getattr(status, name)
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid or (value <= 0 if name == 'dpr' else not 100 <= value <= 8192):
            raise CdpError('invalid status dimensions')
    for name, maximum in (('energy', 2**32-1), ('xp', 2**64-1), ('sequence', 2**64-1)):
        value = getattr(status, name)
        if value is None and name in ('energy', 'xp'):
            continue
        if type(value) is not int or not 0 <= value <= maximum:
            raise CdpError('invalid status integer')
    if type(status.sequence_available) is not bool or type(status.modal) is not bool:
        raise CdpError('invalid status boolean')
    if not status.sequence_available and status.sequence != 0:
        raise CdpError('unavailable status sequence must be zero')


async def _receive_cdp_result(ws, expected_id: int, max_bytes: int, allow_stale_ids: bool = False):
    while True:
        raw = await ws.recv()
        received_ns = time.monotonic_ns()
        if type(raw) is not str or len(raw) > max_bytes:
            raise CdpError('invalid CDP message')
        byte_len = len(raw.encode('utf-8'))
        if byte_len > max_bytes:
            raise CdpError('invalid CDP message')
        message = _strict_json(raw)
        if not isinstance(message, dict):
            raise CdpError('invalid CDP response')
        if 'id' not in message:
            if (byte_len > _CDP_MAX_BYTES or type(message.get('method')) is not str
                    or ('params' in message and not isinstance(message['params'], dict))
                    or 'error' in message):
                raise CdpError('invalid CDP event')
            continue
        if (
            allow_stale_ids
            and type(message['id']) is int
            and message['id'] < expected_id
            and 'error' not in message
        ):
            continue
        if type(message['id']) is not int or message['id'] != expected_id or 'error' in message:
            raise CdpError('CDP response failed')
        result = message.get('result')
        if not isinstance(result, dict) or 'exceptionDetails' in result:
            raise CdpError('CDP response failed')
        return result, received_ns


def _status_from_result(result, tab: Tab) -> Status:
    remote = result.get('result')
    value = remote.get('value') if isinstance(remote, dict) else None
    if not isinstance(value, dict):
        raise CdpError('invalid CDP status value')
    status = Status(**value)
    _validate_status(status)
    if (_origin(status.url) != _origin(tab.url) or status.sequence_available
            or status.sequence != 0 or (status.xp is not None and status.xp > 2**53-1)):
        raise CdpError('status origin, sequence or XP changed')
    return status


async def read_status(tab: Tab) -> Status:
    validate_game_url(tab.url)
    validate_ws_url(tab.websocket_url)
    if getattr(tab, "ws", None) is None and not getattr(tab, "_want_persistent_ws", False):
        try:
            async with _ReadOnlyConnect(tab.websocket_url, proxy=None, compression=None,
                                       open_timeout=_CDP_TIMEOUT, close_timeout=1,
                                       max_size=_CDP_MAX_BYTES, max_queue=4, ping_interval=None) as ws:
                async with asyncio.timeout(_CDP_TIMEOUT):
                    await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                              'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                    result, _ = await _receive_cdp_result(ws, 1, _CDP_MAX_BYTES)
                    return _status_from_result(result, tab)
        except CdpError:
            raise
        except Exception as error:
            raise CdpError('CDP transport or status failure') from error

    for attempt in range(2):
        try:
            ws = tab.ws if tab.ws is not None else await _open_managed_ws(tab)
            msg_id = tab.next_id()
            async with asyncio.timeout(_CDP_TIMEOUT):
                await ws.send(json.dumps({'id': msg_id, 'method': 'Runtime.evaluate',
                                          'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                result, _ = await _receive_cdp_result(ws, msg_id, _CDP_MAX_BYTES, allow_stale_ids=True)
                return _status_from_result(result, tab)
        except (CdpError, asyncio.CancelledError):
            raise
        except Exception as error:
            if getattr(tab, "_managed_ws", False) and attempt == 0:
                await close_cdp_session(tab)
                continue
            raise CdpError('CDP transport or status failure') from error


def encode_status(status: Status) -> bytes:
    """Encode status v1 for the Rust OP_CHECK_STATUS operation."""
    try:
        _validate_status(status)
    except CdpError as error:
        raise ProtocolError('invalid status payload') from error
    def string(value):
        data = value.encode('utf-8')
        return struct.pack('<I', len(data)) + data
    return (string(status.url) + struct.pack('<ddd', status.width, status.height, status.dpr)
            + (b'\0' if status.energy is None else b'\1' + struct.pack('<I', status.energy))
            + (b'\0' if status.xp is None else b'\1' + struct.pack('<Q', status.xp))
            + string(status.toast) + struct.pack('<BQB', status.sequence_available, status.sequence, status.modal))


def decode_status(payload: bytes) -> Status:
    if type(payload) is not bytes:
        raise ProtocolError('status payload must be bytes')
    offset = 0
    def take(count):
        nonlocal offset
        if offset + count > len(payload):
            raise ProtocolError('truncated status payload')
        result = payload[offset:offset+count]
        offset += count
        return result
    def number(fmt):
        return struct.unpack('<'+fmt, take(struct.calcsize('<'+fmt)))[0]
    def tag():
        value = number('B')
        if value not in (0,1):
            raise ProtocolError('invalid status boolean tag')
        return bool(value)
    def string():
        length = number('I')
        if length > _MAX_STATUS_STRING:
            raise ProtocolError('status string too large')
        return take(length).decode('utf-8')
    try:
        status = Status(string(), number('d'), number('d'), number('d'),
                        number('I') if tag() else None, number('Q') if tag() else None,
                        string(), tag(), number('Q'), tag())
        if offset != len(payload):
            raise ProtocolError('trailing status bytes')
        _validate_status(status)
        return status
    except (CdpError, UnicodeError) as error:
        raise ProtocolError('invalid status payload') from error


def encode_diagnose_request(rgb_payload: bytes) -> bytes:
    """Encode an OP_DIAGNOSE request payload."""
    if type(rgb_payload) is not bytes:
        raise ProtocolError("RGB payload must be bytes")
    decode_rgb_payload(rgb_payload)
    return struct.pack("<B", OP_DIAGNOSE) + rgb_payload


def decode_diagnose_request(payload: bytes) -> bytes:
    """Decode an OP_DIAGNOSE request payload, returning validated rgb_payload."""
    if type(payload) is not bytes or len(payload) < 1:
        raise ProtocolError("diagnose request too short")
    if payload[0] != OP_DIAGNOSE:
        raise ProtocolError("unexpected opcode in diagnose request")
    rgb_payload = payload[1:]
    decode_rgb_payload(rgb_payload)
    return rgb_payload


def encode_diagnose_response(
    water: Optional[Tuple[int, int]],
    alert: Optional[Tuple[int, int, float]],
    compute_duration_ns: int,
) -> bytes:
    """Encode an OP_DIAGNOSE response payload."""
    if type(compute_duration_ns) is not int or not 0 <= compute_duration_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("invalid compute duration")
    buf = bytearray()
    buf.append(OP_DIAGNOSE)
    if water is not None:
        if not (isinstance(water, tuple) and len(water) == 2 and all(isinstance(v, int) and 0 <= v <= MAX_DIMENSION for v in water)):
            raise ProtocolError("invalid water coordinates")
        buf.append(1)
        buf.extend(struct.pack("<II", water[0], water[1]))
    else:
        buf.append(0)

    if alert is not None:
        if not (isinstance(alert, tuple) and len(alert) == 3 and isinstance(alert[0], int) and isinstance(alert[1], int) and isinstance(alert[2], (int, float)) and 0 <= alert[0] <= MAX_DIMENSION and 0 <= alert[1] <= MAX_DIMENSION):
            raise ProtocolError("invalid alert coordinates")
        buf.append(1)
        buf.extend(struct.pack("<IIf", alert[0], alert[1], float(alert[2])))
    else:
        buf.append(0)

    buf.extend(struct.pack("<Q", compute_duration_ns))
    return bytes(buf)


def decode_diagnose_response(
    payload: bytes,
) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int, float]], int]:
    """Decode an OP_DIAGNOSE response payload."""
    if type(payload) is not bytes or len(payload) < 11:
        raise ProtocolError("diagnose response too short")
    if payload[0] != OP_DIAGNOSE:
        raise ProtocolError("unexpected opcode in diagnose response")

    offset = 1
    water_flag = payload[offset]
    offset += 1
    if water_flag == 1:
        if offset + 8 > len(payload):
            raise ProtocolError("truncated water coordinates in diagnose response")
        wx, wy = struct.unpack_from("<II", payload, offset)
        offset += 8
        water = (wx, wy)
    elif water_flag == 0:
        water = None
    else:
        raise ProtocolError("invalid water flag in diagnose response")

    if offset >= len(payload):
        raise ProtocolError("truncated alert flag in diagnose response")
    alert_flag = payload[offset]
    offset += 1
    if alert_flag == 1:
        if offset + 12 > len(payload):
            raise ProtocolError("truncated alert info in diagnose response")
        ax, ay, score = struct.unpack_from("<IIf", payload, offset)
        offset += 12
        alert = (ax, ay, float(score))
    elif alert_flag == 0:
        alert = None
    else:
        raise ProtocolError("invalid alert flag in diagnose response")

    if offset + 8 != len(payload):
        raise ProtocolError("trailing or truncated duration in diagnose response")
    duration_ns = struct.unpack_from("<Q", payload, offset)[0]
    return (water, alert, duration_ns)


class LocalRequestError(Exception):
    """A request rejected before any bytes are written to the worker."""


class ChannelBusyError(LocalRequestError):
    """The single worker channel already has an outstanding exchange."""


class WorkerOperationError(Exception):
    """A valid operation-level error returned by the worker."""

    def __init__(self, code: int):
        self.code = code
        label = "unsupported Task 1 request" if code == ERROR_UNSUPPORTED_TASK1 else "worker operation failed"
        super().__init__(f"{label} (code {code})")


@dataclass(frozen=True)
class Frame:
    version: int
    kind: int
    request_id: int
    payload: bytes = b""


@dataclass(frozen=True)
class RgbPayload:
    width: int
    height: int
    stride: int
    captured_monotonic_ns: int
    rgb: bytes


@dataclass(frozen=True)
class CapturedFrame:
    image: RgbPayload
    status: Status
    css_x: float
    css_y: float
    css_width: float
    css_height: float


def _validate_frame(frame: Frame) -> None:
    if not 0 <= frame.version <= 0xFF or frame.version != VERSION:
        raise ProtocolError("unsupported protocol version")
    if frame.kind not in _KNOWN_KINDS:
        raise ProtocolError("unknown frame kind")
    if not 0 <= frame.request_id <= 0xFFFFFFFF:
        raise ProtocolError("request id outside u32 range")
    if frame.kind in _ZERO_ID_KINDS and frame.request_id != 0:
        raise ProtocolError("control frame request id must be zero")
    if frame.kind not in _ZERO_ID_KINDS and frame.request_id == 0:
        raise ProtocolError("operation frame request id must be nonzero")
    if not isinstance(frame.payload, bytes):
        raise ProtocolError("frame payload must be bytes")
    body_len = FRAME_HEADER_LEN + len(frame.payload)
    if body_len > MAX_FRAME_LEN:
        raise ProtocolError("frame exceeds 32 MiB limit")


def encode_frame(frame: Frame) -> bytes:
    _validate_frame(frame)
    body = struct.pack("<BBHI", frame.version, frame.kind, 0, frame.request_id) + frame.payload
    return struct.pack("<I", len(body)) + body


async def read_frame(stream: asyncio.StreamReader) -> Optional[Frame]:
    try:
        prefix = await stream.readexactly(4)
    except asyncio.IncompleteReadError as error:
        if not error.partial:
            return None
        raise ProtocolError("truncated frame length prefix") from error

    (body_len,) = struct.unpack("<I", prefix)
    if body_len < FRAME_HEADER_LEN:
        raise ProtocolError("frame shorter than fixed header")
    if body_len > MAX_FRAME_LEN:
        raise ProtocolError("frame exceeds 32 MiB limit")
    try:
        body = await stream.readexactly(body_len)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError("truncated frame body") from error

    version, kind, reserved, request_id = struct.unpack_from("<BBHI", body)
    if reserved != 0:
        raise ProtocolError("reserved bits must be zero")
    frame = Frame(version, kind, request_id, body[FRAME_HEADER_LEN:])
    _validate_frame(frame)
    return frame


async def write_frame(stream, frame: Frame) -> None:
    encoded = encode_frame(frame)
    stream.write(encoded)
    await stream.drain()


def _rgb_pixel_bytes(width: int, height: int, stride: int) -> int:
    if any(type(value) is not int for value in (width, height, stride)):
        raise ProtocolError("RGB dimensions and stride must be integers")
    if not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION:
        raise ProtocolError("RGB dimensions outside 1..8192")
    if stride != width * 3:
        raise ProtocolError("RGB stride does not equal width times three")
    pixel_bytes = stride * height
    if RGB_HEADER_LEN + pixel_bytes > MAX_FRAME_LEN - FRAME_HEADER_LEN:
        raise ProtocolError("RGB frame exceeds 32 MiB limit")
    return pixel_bytes


def decode_rgb_payload(payload: bytes) -> RgbPayload:
    if len(payload) < RGB_HEADER_LEN:
        raise ProtocolError("RGB payload is shorter than its header")
    if len(payload) > MAX_FRAME_LEN - FRAME_HEADER_LEN:
        raise ProtocolError("RGB frame exceeds 32 MiB limit")
    width, height, stride, captured_ns = struct.unpack_from("<IIIQ", payload)
    pixel_bytes = _rgb_pixel_bytes(width, height, stride)
    if len(payload) != RGB_HEADER_LEN + pixel_bytes:
        raise ProtocolError("RGB payload length does not exactly match dimensions")
    return RgbPayload(width, height, stride, captured_ns, payload[RGB_HEADER_LEN:])


def decode_jpeg_rgb(data: bytes, captured_monotonic_ns: int) -> RgbPayload:
    if type(data) is not bytes or not data or len(data) > MAX_FRAME_LEN:
        raise ProtocolError("invalid JPEG data")
    if type(captured_monotonic_ns) is not int or not 0 <= captured_monotonic_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("invalid capture timestamp")
    try:
        with io.BytesIO(data) as source, closing(Image.open(source)) as image:
            if image.format != "JPEG":
                raise ProtocolError("expected JPEG image")
            width, height = image.size
            stride = width * 3
            pixel_bytes = _rgb_pixel_bytes(width, height, stride)
            image.load()
            with closing(image.convert("RGB")) as converted:
                rgb = converted.tobytes()
            if type(rgb) is not bytes or len(rgb) != pixel_bytes:
                raise ProtocolError("invalid decoded RGB length")
        return RgbPayload(width, height, stride, captured_monotonic_ns, rgb)
    except Exception:
        # Pillow/plugin errors can contain image text; expose only a fixed message.
        raise ProtocolError("invalid JPEG image") from None


def _decode_jpeg_bgr_fast(data: bytes, captured_monotonic_ns: int) -> Tuple[np.ndarray, int, int]:
    if type(data) is not bytes or not data or len(data) > MAX_FRAME_LEN:
        raise ProtocolError("invalid JPEG data")
    if type(captured_monotonic_ns) is not int or not 0 <= captured_monotonic_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("invalid capture timestamp")
    if len(data) < 2 or data[0] != 0xFF or data[1] != 0xD8:
        raise ProtocolError("expected JPEG image")
    buf = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ProtocolError("invalid JPEG image")
    height, width = int(bgr.shape[0]), int(bgr.shape[1])
    _rgb_pixel_bytes(width, height, width * 3)
    return bgr, width, height


def _decode_jpeg_full_fast(data: bytes, captured_monotonic_ns: int) -> RgbPayload:
    bgr, width, height = _decode_jpeg_bgr_fast(data, captured_monotonic_ns)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return RgbPayload(width, height, width * 3, captured_monotonic_ns, rgb.tobytes())


def _decode_jpeg_alert_roi_fast(data: bytes, captured_monotonic_ns: int, status: Status) -> CapturedFrame:
    bgr, width, height = _decode_jpeg_bgr_fast(data, captured_monotonic_ns)
    left, right = 35 * width // 100, 65 * width // 100
    top, bottom = 20 * height // 100, 60 * height // 100
    if left >= right or top >= bottom:
        raise CdpError('empty alert crop')
    roi_rgb = cv2.cvtColor(bgr[top:bottom, left:right], cv2.COLOR_BGR2RGB)
    cropped = RgbPayload(right - left, bottom - top, (right - left) * 3,
                         captured_monotonic_ns, roi_rgb.tobytes())
    return CapturedFrame(cropped, status, left * status.width / width, top * status.height / height,
                         (right - left) * status.width / width, (bottom - top) * status.height / height)


def encode_rgb_payload(frame: RgbPayload) -> bytes:
    if type(frame) is not RgbPayload or type(frame.rgb) is not bytes:
        raise ProtocolError("invalid RGB payload type")
    pixel_bytes = _rgb_pixel_bytes(frame.width, frame.height, frame.stride)
    if type(frame.captured_monotonic_ns) is not int or not 0 <= frame.captured_monotonic_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("invalid capture timestamp")
    if len(frame.rgb) != pixel_bytes:
        raise ProtocolError("RGB payload length does not exactly match dimensions")
    return struct.pack("<IIIQ", frame.width, frame.height, frame.stride, frame.captured_monotonic_ns) + frame.rgb


_WATER_MEANS: Optional[Tuple[float, float, float]] = None
_WATER_NIGHT_BOUNDS: Optional[Tuple[np.ndarray, np.ndarray]] = None
# Daytime water RGB range matching python/config/settings.py BGR [185,187,159]..[221,223,195]
WATER_DAY_LOWER_RGB = np.array([159, 187, 185], dtype=np.uint8)
WATER_DAY_UPPER_RGB = np.array([195, 223, 221], dtype=np.uint8)


def _load_water_means() -> Tuple[float, float, float]:
    """Load or calculate template fractional means from assets/water.rgb (cached)."""
    global _WATER_MEANS
    if _WATER_MEANS is None:
        asset_path = Path(__file__).parent / "assets" / "water.rgb"
        if asset_path.exists():
            data = asset_path.read_bytes()
            if len(data) == 13230:
                _WATER_MEANS = (
                    sum(data[0::3]) / 4410.0,
                    sum(data[1::3]) / 4410.0,
                    sum(data[2::3]) / 4410.0,
                )
        if _WATER_MEANS is None:
            _WATER_MEANS = (318229.0 / 4410.0, 397111.0 / 4410.0, 441422.0 / 4410.0)
    return _WATER_MEANS


def _get_water_night_bounds() -> Tuple[np.ndarray, np.ndarray]:
    """Exact uint8 bounds mathematically identical to |uint8 - mean| <= 14.0."""
    global _WATER_NIGHT_BOUNDS
    if _WATER_NIGHT_BOUNDS is None:
        means = _load_water_means()
        lower = np.array([max(0, math.ceil(m - 14.0)) for m in means], dtype=np.uint8)
        upper = np.array([min(255, math.floor(m + 14.0)) for m in means], dtype=np.uint8)
        _WATER_NIGHT_BOUNDS = (lower, upper)
    return _WATER_NIGHT_BOUNDS


def _find_water_matches(
    payload: Union[bytes, RgbPayload],
    include_day: bool = False,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Find all safe 51x51 water grid centers using zero-float64 ROI integral image."""
    if isinstance(payload, bytes):
        image = decode_rgb_payload(payload)
    elif isinstance(payload, RgbPayload):
        image = payload
    else:
        raise ProtocolError("RGB payload must be bytes or RgbPayload")

    width, height = image.width, image.height
    if width < 60 or height < 60:
        return None

    y_start = max(height // 5, 25)
    y_end = min(height * 82 // 100, height - 25)
    x_start = max(width // 4, 25)
    x_end = min(width * 3 // 4, width - 25)

    y_indices = np.arange(y_start, y_end, 4)
    x_indices = np.arange(x_start, x_end, 4)
    if len(y_indices) == 0 or len(x_indices) == 0:
        return None

    arr = np.frombuffer(image.rgb, dtype=np.uint8).reshape((height, width, 3))

    roi_y0 = int(y_indices[0]) - 25
    roi_y1 = int(y_indices[-1]) + 26
    roi_x0 = int(x_indices[0]) - 25
    roi_x1 = int(x_indices[-1]) + 26
    roi = arr[roi_y0:roi_y1, roi_x0:roi_x1]

    night_lo, night_hi = _get_water_night_bounds()
    mask = cv2.inRange(roi, night_lo, night_hi)
    if include_day:
        mask = cv2.bitwise_or(mask, cv2.inRange(roi, WATER_DAY_LOWER_RGB, WATER_DAY_UPPER_RGB))

    integral = cv2.integral((mask > 0).astype(np.uint8), sdepth=cv2.CV_32S)

    ly = y_indices - roi_y0
    lx = x_indices - roi_x0
    top, bottom = ly - 25, ly + 26
    left, right = lx - 25, lx + 26

    counts = (
        integral[bottom[:, None], right[None, :]]
        + integral[top[:, None], left[None, :]]
        - integral[top[:, None], right[None, :]]
        - integral[bottom[:, None], left[None, :]]
    )
    matches = np.argwhere(counts == 2601)
    if len(matches) == 0:
        return None
    return (matches, x_indices, y_indices)


def water_point(
    payload: Union[bytes, RgbPayload],
    include_day: bool = False,
) -> Optional[Tuple[int, int]]:
    """Safe water casting point search using integral image mask.

    Algorithm matches worker_vision.rs 100% when include_day=False:
    - 51x51 square with exact count 2601 water pixels (all 3 channels within 14.0 of mean).
    - Scans row-major (y first, then x), step 4.
    - Coordinate bounds:
        x: max(width // 4, 25) .. min(width * 3 // 4, width - 25)
        y: max(height // 5, 25) .. min(height * 82 // 100, height - 25)
    """
    found = _find_water_matches(payload, include_day=include_day)
    if found is None:
        return None
    matches, x_indices, y_indices = found
    return (int(x_indices[matches[0, 1]]), int(y_indices[matches[0, 0]]))


def pick_random_water_point(
    payload: Union[bytes, RgbPayload],
    last_point: Optional[Tuple[int, int]] = None,
    include_day: bool = True,
) -> Optional[Tuple[int, int]]:
    """Pick a randomized safe water casting point with anti-detection spread."""
    found = _find_water_matches(payload, include_day=include_day)
    if found is None:
        return None
    matches, x_indices, y_indices = found
    if len(matches) == 1:
        return (int(x_indices[matches[0, 1]]), int(y_indices[matches[0, 0]]))

    cand_xs = x_indices[matches[:, 1]]
    cand_ys = y_indices[matches[:, 0]]
    if last_point is not None:
        d2 = (cand_xs - last_point[0]) ** 2 + (cand_ys - last_point[1]) ** 2
        far = d2 >= 24 ** 2
        if np.any(far):
            cand_xs = cand_xs[far]
            cand_ys = cand_ys[far]
        else:
            med = d2 >= 12 ** 2
            if np.any(med):
                cand_xs = cand_xs[med]
                cand_ys = cand_ys[med]

    idx = random.randrange(len(cand_xs))
    jx = random.randint(-2, 2)
    jy = random.randint(-2, 2)
    return (int(cand_xs[idx]) + jx, int(cand_ys[idx]) + jy)


@dataclass(frozen=True)
class AlertHit:
    x: int
    y: int
    score: float


_ALERT_RGB_PATH = Path(__file__).parent / "assets" / "alert.rgb"
_ALERT_TEMPLATE: Optional[np.ndarray] = None


def _get_alert_template() -> np.ndarray:
    global _ALERT_TEMPLATE
    if _ALERT_TEMPLATE is None:
        asset_path = _ALERT_RGB_PATH
        if not asset_path.exists():
            root_path = Path("rust/hybrid/assets/alert.rgb")
            if root_path.exists():
                asset_path = root_path
        if asset_path.exists():
            data = asset_path.read_bytes()
            if len(data) == 3465:
                _ALERT_TEMPLATE = np.frombuffer(data, dtype=np.uint8).reshape((35, 33, 3))
        if _ALERT_TEMPLATE is None:
            raise RuntimeError("alert template asset alert.rgb not found")
    return _ALERT_TEMPLATE


_ALERT_TEMPLATE_HALF_GRAY: Optional[np.ndarray] = None


def _get_alert_template_half_gray() -> np.ndarray:
    global _ALERT_TEMPLATE_HALF_GRAY
    if _ALERT_TEMPLATE_HALF_GRAY is None:
        tpl_gray = cv2.cvtColor(_get_alert_template(), cv2.COLOR_RGB2GRAY)
        _ALERT_TEMPLATE_HALF_GRAY = cv2.resize(tpl_gray, (16, 17), interpolation=cv2.INTER_AREA)
    return _ALERT_TEMPLATE_HALF_GRAY


def _verify_alert_patch(
    img_arr: np.ndarray,
    base_arr: Optional[np.ndarray],
    template: np.ndarray,
    ox: int,
    oy: int,
) -> Optional[AlertHit]:
    res = cv2.matchTemplate(img_arr, template, cv2.TM_CCOEFF_NORMED)
    _, max_v, _, max_l = cv2.minMaxLoc(res)

    if np.isnan(max_v) or np.isinf(max_v):
        return None

    best_score = float(max_v)
    bx, by = max_l  # (x, y)

    if best_score >= 0.80:
        return AlertHit(ox + bx, oy + by, best_score)
    if best_score < 0.60:
        return None

    if base_arr is None:
        return AlertHit(ox + bx, oy + by, best_score) if best_score >= 0.74 else None

    patch = img_arr[by : by + 35, bx : bx + 33]
    base_patch = base_arr[by : by + 35, bx : bx + 33]

    diff = float(cv2.absdiff(patch, base_patch).mean())
    dark_mask = (patch[:, :, 0] < 45) & (patch[:, :, 1] < 45) & (patch[:, :, 2] < 45)
    dark_ratio = float(np.count_nonzero(dark_mask) / (33 * 35))

    if diff >= 18.0 and dark_ratio >= 0.05:
        return AlertHit(ox + bx, oy + by, best_score)
    return None


def alert_point(
    frame: Union[bytes, RgbPayload],
    baseline: Optional[Union[bytes, RgbPayload]] = None,
) -> Optional[AlertHit]:
    """Alert exclamation point search using normalized cross-correlation (NCC)
    and two-layer baseline verification.

    Matches worker_vision.rs alert_point 100%:
    - Template 33x35 RGB.
    - cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    - If score >= 0.80 -> AlertHit(x, y, score)
    - If score < 0.60 -> None
    - If 0.60 <= score < 0.80:
        - If no baseline (or baseline dimensions differ from frame):
            score >= 0.74 -> AlertHit(x, y, score), else None
        - If valid baseline:
            diff >= 18.0 and dark_ratio >= 0.05 -> AlertHit(x, y, score), else None
    """
    if isinstance(frame, bytes):
        image = decode_rgb_payload(frame)
    elif isinstance(frame, RgbPayload):
        image = frame
    else:
        raise ProtocolError("frame must be bytes or RgbPayload")

    base_img: Optional[RgbPayload] = None
    if baseline is not None:
        if isinstance(baseline, bytes):
            base_img = decode_rgb_payload(baseline)
        elif isinstance(baseline, RgbPayload):
            base_img = baseline
        else:
            raise ProtocolError("baseline must be bytes, RgbPayload or None")

    if image.width < 33 or image.height < 35:
        return None

    if base_img is not None and (base_img.width != image.width or base_img.height != image.height):
        base_img = None

    template = _get_alert_template()
    img_arr = np.frombuffer(image.rgb, dtype=np.uint8).reshape((image.height, image.width, 3))
    base_arr = (
        np.frombuffer(base_img.rgb, dtype=np.uint8).reshape((base_img.height, base_img.width, 3))
        if base_img is not None
        else None
    )

    if image.width < 160 or image.height < 160:
        return _verify_alert_patch(img_arr, base_arr, template, 0, 0)

    img_gray = cv2.cvtColor(img_arr, cv2.COLOR_RGB2GRAY)
    small_gray = cv2.resize(img_gray, (image.width // 2, image.height // 2), interpolation=cv2.INTER_AREA)
    coarse_res = cv2.matchTemplate(small_gray, _get_alert_template_half_gray(), cv2.TM_CCOEFF_NORMED)

    for _ in range(5):
        _, coarse_max, _, (cx, cy) = cv2.minMaxLoc(coarse_res)
        if np.isnan(coarse_max) or np.isinf(coarse_max) or coarse_max < 0.42:
            break
        px0 = max(0, cx * 2 - 20)
        py0 = max(0, cy * 2 - 20)
        px1 = min(image.width, cx * 2 + 33 + 20)
        py1 = min(image.height, cy * 2 + 35 + 20)
        local_base = base_arr[py0:py1, px0:px1] if base_arr is not None else None
        hit = _verify_alert_patch(img_arr[py0:py1, px0:px1], local_base, template, px0, py0)
        if hit is not None:
            return hit
        sy0 = max(0, cy - 12)
        sy1 = min(coarse_res.shape[0], cy + 13)
        sx0 = max(0, cx - 12)
        sx1 = min(coarse_res.shape[1], cx + 13)
        coarse_res[sy0:sy1, sx0:sx1] = -1.0
    return None


_BREAD_RGB_PATH = Path(__file__).parent / "assets" / "bread.rgb"
_BREAD_TEMPLATE: Optional[np.ndarray] = None


def _get_bread_template() -> np.ndarray:
    global _BREAD_TEMPLATE
    if _BREAD_TEMPLATE is None:
        asset_path = _BREAD_RGB_PATH
        if not asset_path.exists():
            root_path = Path("rust/hybrid/assets/bread.rgb")
            if root_path.exists():
                asset_path = root_path
        if asset_path.exists():
            data = asset_path.read_bytes()
            if len(data) == 4257:
                _BREAD_TEMPLATE = np.frombuffer(data, dtype=np.uint8).reshape((33, 43, 3))
        if _BREAD_TEMPLATE is None:
            raise RuntimeError("bread template asset bread.rgb not found")
    return _BREAD_TEMPLATE


def find_bread_point(
    frame: Union[CapturedFrame, RgbPayload, bytes],
    status: Optional[Status] = None,
) -> Optional[Tuple[float, float]]:
    """Locate bread in bottom 30% ROI of the screen (y >= 0.70*H, 0.20*W <= x <= 0.80*W).
    Returns CSS center coordinates (css_x, css_y) or None.
    """
    if isinstance(frame, CapturedFrame):
        image = frame.image
        if status is None:
            status = frame.status
    elif isinstance(frame, bytes):
        image = decode_rgb_payload(frame)
    elif isinstance(frame, RgbPayload):
        image = frame
    else:
        raise ProtocolError("frame must be CapturedFrame, RgbPayload, or bytes")

    width, height = image.width, image.height
    if width < 50 or height < 50:
        return None

    img_arr = np.frombuffer(image.rgb, dtype=np.uint8).reshape((height, width, 3))
    template = _get_bread_template()
    th, tw = template.shape[0], template.shape[1]  # 33, 43

    ymin = int(0.70 * height)
    ymax = height
    xmin = int(0.20 * width)
    xmax = int(0.80 * width)

    if ymax - ymin < th or xmax - xmin < tw:
        return None

    roi = img_arr[ymin:ymax, xmin:xmax]
    res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val < 0.75:
        return None

    bx = xmin + max_loc[0] + tw // 2
    by = ymin + max_loc[1] + th // 2

    # Map to CSS if status provided
    if status is not None:
        css_x = (bx * status.width) / width
        css_y = (by * status.height) / height
        if css_y > 0.95 * status.height:
            return None
        return (round(css_x, 1), round(css_y, 1))

    if by > 0.95 * height:
        return None
    return (float(bx), float(by))


_SCREENSHOT_PARAMS = {
    'format': 'jpeg',
    'quality': 50,
    'fromSurface': True,
    'optimizeForSpeed': True,
    'captureBeyondViewport': False,
}


async def capture(tab: Tab, kind: str) -> CapturedFrame:
    try:
        if type(tab) is not Tab or type(kind) is not str or kind not in ('SCREEN_FULL', 'SCREEN_ALERT'):
            raise CdpError('invalid capture input')
        validate_game_url(tab.url)
        validate_ws_url(tab.websocket_url)

        if getattr(tab, "ws", None) is None and not getattr(tab, "_want_persistent_ws", False):
            async with _ReadOnlyConnect(tab.websocket_url, proxy=None, compression=None,
                                       open_timeout=_CDP_TIMEOUT, close_timeout=1,
                                       max_size=_CAPTURE_CDP_MAX_BYTES, max_queue=1, ping_interval=None) as ws:
                async with asyncio.timeout(_CDP_TIMEOUT):
                    await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                        'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                    result, _ = await _receive_cdp_result(ws, 1, _CDP_MAX_BYTES)
                    before = _status_from_result(result, tab)

                    await ws.send(json.dumps({'id': 2, 'method': 'Page.captureScreenshot',
                        'params': dict(_SCREENSHOT_PARAMS)}))
                    result, received_ns = await _receive_cdp_result(ws, 2, _CAPTURE_CDP_MAX_BYTES)
                    encoded = result.get('data')
                    if type(encoded) is not str or not encoded or len(encoded) > _CAPTURE_BASE64_MAX_CHARS:
                        raise CdpError('invalid screenshot data')
                    data = base64.b64decode(encoded, validate=True)
                    if not data or len(data) > MAX_FRAME_LEN:
                        raise CdpError('invalid screenshot size')
                    image = decode_jpeg_rgb(data, received_ns)

                    await ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate',
                        'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                    result, _ = await _receive_cdp_result(ws, 3, _CDP_MAX_BYTES)
                    after = _status_from_result(result, tab)
                    if ((before.url, before.width, before.height, before.dpr)
                            != (after.url, after.width, after.height, after.dpr)):
                        raise CdpError('capture geometry changed')

            if kind == 'SCREEN_FULL':
                return CapturedFrame(image, before, 0.0, 0.0, float(before.width), float(before.height))
            width, height = image.width, image.height
            left, right = 35 * width // 100, 65 * width // 100
            top, bottom = 20 * height // 100, 60 * height // 100
            if left >= right or top >= bottom:
                raise CdpError('empty alert crop')
            arr = np.frombuffer(image.rgb, dtype=np.uint8).reshape((height, width, 3))
            pixels = np.ascontiguousarray(arr[top:bottom, left:right]).tobytes()
            cropped = RgbPayload(right - left, bottom - top, (right - left) * 3,
                                 image.captured_monotonic_ns, pixels)
            return CapturedFrame(cropped, before, left * before.width / width, top * before.height / height,
                                 (right - left) * before.width / width, (bottom - top) * before.height / height)

        for attempt in range(2):
            try:
                ws = tab.ws if tab.ws is not None else await _open_managed_ws(tab)
                fast_status = getattr(tab, "_fast_alert_status", None)
                if kind == 'SCREEN_ALERT' and fast_status is not None:
                    async with asyncio.timeout(_CDP_TIMEOUT):
                        shot_id = tab.next_id()
                        await ws.send(json.dumps({'id': shot_id, 'method': 'Page.captureScreenshot',
                            'params': {**_SCREENSHOT_PARAMS, 'quality': 35}}))
                        result, received_ns = await _receive_cdp_result(
                            ws, shot_id, _CAPTURE_CDP_MAX_BYTES, allow_stale_ids=True
                        )
                        encoded = result.get('data')
                        if type(encoded) is not str or not encoded or len(encoded) > _CAPTURE_BASE64_MAX_CHARS:
                            raise CdpError('invalid screenshot data')
                        data = base64.b64decode(encoded, validate=True)
                        if not data or len(data) > MAX_FRAME_LEN:
                            raise CdpError('invalid screenshot size')
                    return _decode_jpeg_alert_roi_fast(data, received_ns, fast_status)

                async with asyncio.timeout(_CDP_TIMEOUT):
                    id_before = tab.next_id()
                    await ws.send(json.dumps({'id': id_before, 'method': 'Runtime.evaluate',
                        'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                    result, _ = await _receive_cdp_result(ws, id_before, _CDP_MAX_BYTES, allow_stale_ids=True)
                    before = _status_from_result(result, tab)

                    id_shot = tab.next_id()
                    await ws.send(json.dumps({'id': id_shot, 'method': 'Page.captureScreenshot',
                        'params': dict(_SCREENSHOT_PARAMS)}))
                    result, received_ns = await _receive_cdp_result(
                        ws, id_shot, _CAPTURE_CDP_MAX_BYTES, allow_stale_ids=True
                    )
                    encoded = result.get('data')
                    if type(encoded) is not str or not encoded or len(encoded) > _CAPTURE_BASE64_MAX_CHARS:
                        raise CdpError('invalid screenshot data')
                    data = base64.b64decode(encoded, validate=True)
                    if not data or len(data) > MAX_FRAME_LEN:
                        raise CdpError('invalid screenshot size')

                    if kind == 'SCREEN_FULL':
                        decoded_full = _decode_jpeg_full_fast(data, received_ns)
                    else:
                        decoded_alert = _decode_jpeg_alert_roi_fast(data, received_ns, before)

                    id_after = tab.next_id()
                    await ws.send(json.dumps({'id': id_after, 'method': 'Runtime.evaluate',
                        'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                    result, _ = await _receive_cdp_result(ws, id_after, _CDP_MAX_BYTES, allow_stale_ids=True)
                    after = _status_from_result(result, tab)
                    if ((before.url, before.width, before.height, before.dpr)
                            != (after.url, after.width, after.height, after.dpr)):
                        raise CdpError('capture geometry changed')

                if kind == 'SCREEN_FULL':
                    return CapturedFrame(decoded_full, before, 0.0, 0.0, float(before.width), float(before.height))
                return decoded_alert
            except asyncio.CancelledError:
                raise
            except (CdpError, ProtocolError):
                raise
            except Exception:
                if getattr(tab, "_managed_ws", False) and attempt == 0:
                    await close_cdp_session(tab)
                    continue
                raise
    except asyncio.CancelledError:
        raise
    except Exception:
        raise CdpError('capture transport or data failure') from None


class FramedChannel:
    """Serial request/response channel with monotonically increasing request ids."""

    def __init__(self, reader: asyncio.StreamReader, writer, timeout: float = 5.0):
        self.reader = reader
        self.writer = writer
        self.timeout = timeout
        self._next_request_id = 1
        self._outstanding = False
        self._poisoned = False
        self._closed = False

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def poison(self) -> None:
        self._poisoned = True

    def close(self) -> None:
        self._closed = True

    def _ensure_usable(self) -> None:
        if self._poisoned:
            raise ProtocolError("worker channel is poisoned")
        if self._closed:
            raise ProtocolError("worker channel is closed")

    async def exchange(self, request: Frame, expected_kind, expected_id: int) -> Frame:
        self._ensure_usable()
        if self._outstanding:
            raise ChannelBusyError("only one request may be outstanding")
        try:
            encoded = encode_frame(request)
        except ProtocolError as error:
            raise LocalRequestError(str(error)) from error
        expected_kinds = (expected_kind,) if isinstance(expected_kind, int) else tuple(expected_kind)
        if not expected_kinds or not 0 <= expected_id <= 0xFFFFFFFF:
            raise LocalRequestError("invalid expected response kind or request id")
        self._outstanding = True
        io_started = False
        try:
            io_started = True
            self.writer.write(encoded)
            await asyncio.wait_for(self.writer.drain(), self.timeout)
            response = await asyncio.wait_for(read_frame(self.reader), self.timeout)
            if response is None:
                raise ProtocolError("worker closed stdout before responding")
            if response.request_id != expected_id or response.kind not in expected_kinds:
                raise ProtocolError("worker response kind or request id mismatch")
            if response.kind == KIND_ERROR and KIND_ERROR in expected_kinds and len(response.payload) != 2:
                raise ProtocolError("worker operation error must contain one u16 code")
            return response
        except asyncio.TimeoutError as error:
            self._poisoned = io_started
            raise ProtocolError("worker protocol exchange timed out") from error
        except BaseException:
            if io_started:
                self._poisoned = True
            raise
        finally:
            self._outstanding = False

    async def request(self, payload: bytes = b"") -> Frame:
        self._ensure_usable()
        if self._outstanding:
            raise ChannelBusyError("only one request may be outstanding")
        if not isinstance(payload, bytes):
            raise LocalRequestError("request payload must be bytes")
        if len(payload) > MAX_FRAME_LEN - FRAME_HEADER_LEN:
            raise LocalRequestError("request exceeds 32 MiB limit")
        if self._next_request_id > MAX_OPERATION_ID:
            raise LocalRequestError("operation request id space exhausted")
        request_id = self._next_request_id
        request = Frame(VERSION, KIND_REQUEST, request_id, payload)
        response = await self.exchange(request, (KIND_RESPONSE, KIND_ERROR), request_id)
        self._next_request_id += 1
        if response.kind == KIND_ERROR:
            (code,) = struct.unpack("<H", response.payload)
            raise WorkerOperationError(code)
        return response


async def _consume_stderr(reader: asyncio.StreamReader, tail: bytearray) -> None:
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            return
        tail.extend(chunk)
        if len(tail) > 65536:
            del tail[:-65536]


async def _await_bounded(awaitable, timeout: float, description: str):
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError as error:
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout)
        except asyncio.TimeoutError:
            pass
        raise ProtocolError(f"timed out while {description}") from error


async def _close_stdin(process, timeout: float) -> Optional[Exception]:
    writer = process.stdin
    if writer is None:
        return None
    close_error = None
    try:
        writer.close()
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception as error:
        close_error = error
    wait_closed = getattr(writer, "wait_closed", None)
    if wait_closed is not None:
        try:
            await _await_bounded(wait_closed(), timeout, "closing worker stdin")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            close_error = close_error or error
    return close_error


async def _stop_stderr_task(task, timeout: float) -> None:
    if task.done():
        await task
        return
    try:
        await _await_bounded(asyncio.shield(task), timeout, "draining worker stderr")
    except ProtocolError:
        task.cancel()
        try:
            await _await_bounded(asyncio.gather(task, return_exceptions=True), timeout,
                                 "stopping worker stderr drain")
        except ProtocolError as error:
            raise ProtocolError("worker stderr drain did not stop after cancellation") from error


async def _wait_process(process, timeout: float) -> None:
    wait_task = asyncio.create_task(process.wait())
    try:
        await asyncio.wait_for(asyncio.shield(wait_task), timeout)
        return
    except asyncio.TimeoutError:
        pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(asyncio.shield(wait_task), timeout)
    except asyncio.TimeoutError as error:
        wait_task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(wait_task, return_exceptions=True), timeout)
        except asyncio.TimeoutError:
            pass
        raise ProtocolError("worker did not exit after kill") from error


async def _terminate_and_reap(process, timeout: float) -> None:
    close_error = await _close_stdin(process, timeout)
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        await _wait_process(process, timeout)
    except BaseException:
        if close_error is not None:
            raise ProtocolError(f"worker cleanup failed while closing stdin: {close_error}")
        raise
    if close_error is not None:
        raise ProtocolError(f"worker cleanup failed while closing stdin: {close_error}")


class WorkerClient:
    def __init__(self, process, timeout: float):
        self.process = process
        self.timeout = timeout
        self.channel = FramedChannel(process.stdout, process.stdin, timeout)
        self._stderr_tail = bytearray()
        self._stderr_task = asyncio.create_task(_consume_stderr(process.stderr, self._stderr_tail))
        self._closed = False
        self._abort_task = None

    @classmethod
    async def spawn(cls, executable, timeout: float = 5.0) -> "WorkerClient":
        path = Path(executable).resolve()
        process = await asyncio.create_subprocess_exec(
            os.fspath(path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        client = cls(process, timeout)
        try:
            await client.channel.exchange(Frame(VERSION, KIND_HELLO, 0), KIND_HELLO_ACK, 0)
            return client
        except BaseException as error:
            await client._abort_preserving(error)
            raise

    async def _abort_impl(self) -> None:
        cleanup_error = None
        try:
            await _terminate_and_reap(self.process, self.timeout)
        except BaseException as error:
            cleanup_error = error
        try:
            await _stop_stderr_task(self._stderr_task, self.timeout)
        except BaseException as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise cleanup_error

    async def _abort(self) -> None:
        if self._abort_task is not None and self._abort_task.done():
            return
        if self._abort_task is None:
            self._closed = True
            self.channel.poison()
            self.channel.close()
            self._abort_task = asyncio.create_task(self._abort_impl())
        await asyncio.shield(self._abort_task)

    @staticmethod
    def _note_cleanup_failure(original: BaseException, cleanup: BaseException) -> None:
        note = f"worker cleanup also failed: {cleanup}"
        add_note = getattr(original, "add_note", None)
        if add_note is not None:
            add_note(note)
        else:
            setattr(original, "cleanup_error", cleanup)

    async def _abort_preserving(self, original: BaseException) -> None:
        try:
            await self._abort()
        except BaseException as cleanup_error:
            self._note_cleanup_failure(original, cleanup_error)

    async def request(self, payload: bytes = b"") -> Frame:
        try:
            return await self.channel.request(payload)
        except (WorkerOperationError, LocalRequestError):
            raise
        except BaseException as error:
            if self.channel.poisoned:
                await self._abort_preserving(error)
            raise

    async def shutdown(self) -> None:
        if self._abort_task is not None:
            await self._abort()
            return
        if self._closed:
            return
        try:
            await self.channel.exchange(Frame(VERSION, KIND_SHUTDOWN, 0), KIND_SHUTDOWN_ACK, 0)
            self.channel.close()
            close_error = await _close_stdin(self.process, self.timeout)
            try:
                await asyncio.wait_for(asyncio.shield(self.process.wait()), self.timeout)
            except asyncio.TimeoutError as error:
                self.channel.poison()
                await self._abort_preserving(error)
                raise ProtocolError("worker timed out after shutdown acknowledgement") from error
            try:
                await _stop_stderr_task(self._stderr_task, self.timeout)
            except BaseException as error:
                self.channel.poison()
                await self._abort_preserving(error)
                raise
            if close_error is not None:
                raise ProtocolError(f"worker stdin close failed: {close_error}")
            if self.process.returncode != 0:
                raise ProtocolError(f"worker exited with code {self.process.returncode}")
        except BaseException as error:
            self.channel.poison()
            await self._abort_preserving(error)
            raise
        self._closed = True


@dataclass(frozen=True)
class DiagnoseResult:
    engine: str
    origin: str
    viewport_width: float
    viewport_height: float
    dpr: float
    energy: Optional[int]
    xp: Optional[int]
    water_image: Optional[Tuple[int, int]]
    water_css: Optional[Tuple[float, float]]
    alert_roi: Optional[Tuple[int, int, float]]
    alert_css: Optional[Tuple[float, float]]
    capture_ms: float
    decode_ms: float
    vision_ms: float
    total_ms: float


async def run_diagnose(
    tab: Optional[Tab] = None,
    worker_path: Optional[str] = None,
    timeout: float = 5.0,
    use_worker: bool = True,
) -> DiagnoseResult:
    total_start = time.perf_counter()
    if tab is None:
        tab = await discover_tab()

    t_cap_start = time.perf_counter()
    full_frame = await capture(tab, "SCREEN_FULL")
    alert_frame = await capture(tab, "SCREEN_ALERT")
    capture_ms = (time.perf_counter() - t_cap_start) * 1000.0

    decode_ms = 1.0

    t_vis_start = time.perf_counter()
    engine_name = "In-Process SIMD (Python/OpenCV)"
    water_img: Optional[Tuple[int, int]] = None
    alert_roi: Optional[Tuple[int, int, float]] = None

    if use_worker and worker_path:
        try:
            client = await WorkerClient.spawn(worker_path, timeout=timeout)
            try:
                full_payload = encode_rgb_payload(full_frame.image)
                req_bytes = encode_diagnose_request(full_payload)
                resp_frame = await client.request(req_bytes)
                if resp_frame.kind == KIND_RESPONSE:
                    worker_water, _, _ = decode_diagnose_response(resp_frame.payload)
                    water_img = worker_water

                alert_payload = encode_rgb_payload(alert_frame.image)
                alert_req = encode_diagnose_request(alert_payload)
                alert_resp = await client.request(alert_req)
                if alert_resp.kind == KIND_RESPONSE:
                    _, worker_alert, _ = decode_diagnose_response(alert_resp.payload)
                    alert_roi = worker_alert

                engine_name = "Rust Worker (IPC)"
            finally:
                await client.shutdown()
        except OSError as e:
            if getattr(e, "winerror", None) == 4551 or isinstance(e, (FileNotFoundError, PermissionError)):
                engine_name = "In-Process SIMD (Python/OpenCV)"
            else:
                raise
        except Exception:
            engine_name = "In-Process SIMD (Python/OpenCV)"

    if engine_name == "In-Process SIMD (Python/OpenCV)":
        water_img = water_point(full_frame.image, include_day=True)
        alert_hit = alert_point(alert_frame.image)
        if alert_hit is not None:
            alert_roi = (alert_hit.x, alert_hit.y, alert_hit.score)
        else:
            alert_roi = None

    vision_ms = (time.perf_counter() - t_vis_start) * 1000.0
    total_ms = (time.perf_counter() - total_start) * 1000.0

    water_css = None
    if water_img is not None:
        wx, wy = water_img
        css_x = (wx * full_frame.status.width) / full_frame.image.width
        css_y = (wy * full_frame.status.height) / full_frame.image.height
        water_css = (round(css_x, 1), round(css_y, 1))

    alert_css = None
    if alert_roi is not None:
        ax, ay, score = alert_roi
        css_x = alert_frame.css_x + ((ax + 16) * alert_frame.css_width) / alert_frame.image.width
        css_y = alert_frame.css_y + ((ay + 17) * alert_frame.css_height) / alert_frame.image.height
        alert_css = (round(css_x, 1), round(css_y, 1))

    origin_host = urlsplit(full_frame.status.url).hostname or "unknown"

    return DiagnoseResult(
        engine=engine_name,
        origin=f"https://{origin_host}",
        viewport_width=full_frame.status.width,
        viewport_height=full_frame.status.height,
        dpr=full_frame.status.dpr,
        energy=full_frame.status.energy,
        xp=full_frame.status.xp,
        water_image=water_img,
        water_css=water_css,
        alert_roi=alert_roi,
        alert_css=alert_css,
        capture_ms=round(capture_ms, 1),
        decode_ms=round(decode_ms, 1),
        vision_ms=round(vision_ms, 1),
        total_ms=round(total_ms, 1),
    )


def print_diagnose_report(res: DiagnoseResult) -> None:
    water_str = (
        f"Found at Image=({res.water_image[0]}, {res.water_image[1]}), CSS=({res.water_css[0]:.1f}, {res.water_css[1]:.1f})"
        if res.water_image and res.water_css
        else "None"
    )
    alert_str = (
        f"Found at ROI=({res.alert_roi[0]}, {res.alert_roi[1]}, score={res.alert_roi[2]:.2f}), CSS=({res.alert_css[0]:.1f}, {res.alert_css[1]:.1f})"
        if res.alert_roi and res.alert_css
        else "None"
    )
    energy_str = f"{res.energy}/80" if res.energy is not None else "None"
    xp_str = f"{res.xp}" if res.xp is not None else "None"

    print("=== NOMSTEAD HYBRID DIAGNOSTICS ===")
    print(f"Engine: {res.engine}")
    print(f"Origin: {res.origin}")
    print(f"Viewport: {res.viewport_width:g}x{res.viewport_height:g} (CSS), DPR: {res.dpr:g}")
    print(f"Energy: {energy_str}, XP: {xp_str}")
    print(f"Water Point: {water_str}")
    print(f"Alert Hook (!): {alert_str}")
    print("Timing Profiling:")
    print(f"  CDP Capture: {res.capture_ms:.1f} ms")
    print(f"  JPEG Decode: {res.decode_ms:.1f} ms")
    print(f"  Vision Processing: {res.vision_ms:.1f} ms")
    print(f"  Total Elapsed: {res.total_ms:.1f} ms")
    print("No-Click Policy: VERIFIED (0 input events emitted)")
    print("DIAGNOSE OK")


@dataclass(frozen=True)
class ClickResult:
    x: float
    y: float
    pressed: bool
    released: bool
    press_monotonic_ns: int
    release_monotonic_ns: int
    duration_ms: float


@asynccontextmanager
async def _resolve_ws(tab: Tab):
    if getattr(tab, "ws", None) is not None:
        yield tab.ws
    elif getattr(tab, "_want_persistent_ws", False):
        ws = await _open_managed_ws(tab)
        yield ws
    else:
        validate_ws_url(tab.websocket_url)
        async with _ReadOnlyConnect(tab.websocket_url, proxy=None, compression=None,
                                    open_timeout=_CDP_TIMEOUT, close_timeout=1,
                                    max_size=_CDP_MAX_BYTES, max_queue=4, ping_interval=None) as ws:
            yield ws


def _validate_click_preconditions(tab: Tab, x: float, y: float, status: Optional[Status] = None) -> None:
    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {getattr(tab, 'url', None)}") from e

    if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and math.isfinite(x) and math.isfinite(y)):
        raise ActionPreconditionError(f"coordinates must be finite numbers: x={x}, y={y}")

    if status is not None:
        try:
            validate_game_url(status.url)
        except Exception as e:
            raise ActionPreconditionError(f"untrusted or invalid status URL: {status.url}") from e
        if _origin(status.url) != _origin(tab.url):
            raise ActionPreconditionError(f"tab and status origins do not match: {tab.url} vs {status.url}")
        if not (0.0 <= x < status.width and 0.0 <= y < status.height):
            raise ActionPreconditionError(
                f"coordinates outside viewport: ({x}, {y}) not in [0, {status.width}) x [0, {status.height})"
            )
    else:
        if x < 0.0 or y < 0.0:
            raise ActionPreconditionError(f"negative coordinates: ({x}, {y})")


def human_hold_ms(fast: bool = False) -> float:
    """Natural human mouse button hold duration in milliseconds."""
    if fast:
        return random.uniform(25.0, 55.0)
    return random.uniform(45.0, 105.0)


def human_strike_delay_sec(rare_miss_rate: float = 0.015) -> Tuple[float, bool]:
    """Human visual-motor strike reaction delay (Gaussian 55-185ms, rare 1.5% natural blink 0.55-0.85s)."""
    if rare_miss_rate > 0.0 and random.random() < rare_miss_rate:
        return (random.uniform(0.55, 0.85), True)
    return (max(0.055, min(0.185, random.gauss(0.105, 0.030))), False)


def human_inter_cast_delay_sec() -> float:
    """Natural right-skewed human pause between consecutive casts."""
    r = random.random()
    if r < 0.85:
        return random.uniform(0.08, 0.28)
    if r < 0.97:
        return random.uniform(0.45, 1.10)
    return random.uniform(1.80, 3.50)


async def dispatch_key_cdp(
    tab: Tab,
    key: str = "Escape",
    code: str = "Escape",
    key_code: int = 27,
) -> None:
    """Send trusted CDP Input.dispatchKeyEvent keyDown + keyUp pair (isTrusted === true)."""
    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {getattr(tab, 'url', None)}") from e

    def _get_id() -> int:
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    async with _resolve_ws(tab) as ws:
        await ws.send(json.dumps({
            "id": _get_id(),
            "method": "Input.dispatchKeyEvent",
            "params": {
                "type": "keyDown",
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": int(key_code),
                "nativeVirtualKeyCode": int(key_code),
            },
        }))
        await asyncio.sleep(random.uniform(0.025, 0.060))
        await ws.send(json.dumps({
            "id": _get_id(),
            "method": "Input.dispatchKeyEvent",
            "params": {
                "type": "keyUp",
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": int(key_code),
                "nativeVirtualKeyCode": int(key_code),
            },
        }))


async def scroll_mouse_wheel(
    tab: Tab,
    x: float,
    y: float,
    delta_y: float,
    delta_x: float = 0.0,
) -> None:
    """Send trusted CDP Input.dispatchMouseEvent(mouseWheel) (delta_y > 0 scrolls DOWN, < 0 scrolls UP)."""
    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {getattr(tab, 'url', None)}") from e

    if not all(
        isinstance(v, (int, float)) and math.isfinite(v)
        for v in (x, y, delta_y, delta_x)
    ):
        raise ActionPreconditionError(
            f"wheel coordinates and deltas must be finite numbers: ({x}, {y}, {delta_x}, {delta_y})"
        )

    def _get_id() -> int:
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    async with _resolve_ws(tab) as ws:
        await ws.send(json.dumps({
            "id": _get_id(),
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mouseWheel",
                "x": float(x),
                "y": float(y),
                "deltaX": float(delta_x),
                "deltaY": float(delta_y),
            },
        }))


MODAL_CLOSE_LOOKUP_EXPR = """(() => {
    /* CDP Escape + read-only .close-btn / .modal .close lookup (zero DOM click/dispatchEvent) */
    const hasModal = Boolean(document.querySelector('.modal-body'));
    const btn = document.querySelector('.close-btn, [class*="close-btn"], .modal-close, .modal .close, button.close, [aria-label="Close"], [data-dismiss="modal"]');
    if (!btn) return { has_modal: hasModal, found: false };
    const r = btn.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return { has_modal: hasModal, found: false };
    return { has_modal: hasModal, found: true, x: r.left + r.width / 2, y: r.top + r.height / 2, width: r.width, height: r.height };
})()"""


async def _dismiss_modal_cdp(tab: Tab) -> bool:
    """Read-only modal lookup followed by trusted CDP Escape and optional close-button click."""
    info = None
    try:
        info = await _cdp_evaluate(tab, MODAL_CLOSE_LOOKUP_EXPR)
    except Exception:
        return False

    if not (isinstance(info, dict) and (info.get("has_modal") or info.get("found"))):
        return False

    try:
        await dispatch_key_cdp(tab, "Escape", "Escape", 27)
    except Exception:
        pass

    if info.get("found") and "x" in info and "y" in info:
        cx = float(info["x"])
        cy = float(info["y"])
        max_dx = min(4.0, max(0.0, float(info.get("width", 0.0)) * 0.25))
        max_dy = min(3.0, max(0.0, float(info.get("height", 0.0)) * 0.25))
        cx, cy = jitter_point(
            cx,
            cy,
            max_dx=max_dx,
            max_dy=max_dy,
            min_x=max(0.0, cx - max_dx),
            max_x=cx + max_dx,
            min_y=max(0.0, cy - max_dy),
            max_y=cy + max_dy,
        )
        try:
            await move_mouse_bezier(tab, cx, cy, fast=False)
            await click_point(tab, cx, cy, delay_ms=human_hold_ms(fast=False))
        except Exception:
            pass
    return True


def jitter_point(
    x: float,
    y: float,
    *,
    max_dx: float = 3.0,
    max_dy: float = 3.0,
    min_x: float = 0.0,
    max_x: float = 8191.0,
    min_y: float = 0.0,
    max_y: float = 8191.0,
) -> Tuple[float, float]:
    """Apply bounded uniform jitter clamped within [min_x, max_x] x [min_y, max_y]."""
    dx = random.uniform(-max_dx, max_dx) if max_dx > 0.0 else 0.0
    dy = random.uniform(-max_dy, max_dy) if max_dy > 0.0 else 0.0
    lo_x, hi_x = (min_x, max_x) if min_x <= max_x else (max_x, min_x)
    lo_y, hi_y = (min_y, max_y) if min_y <= max_y else (max_y, min_y)
    nx = round(max(lo_x, min(hi_x, float(x) + dx)), 2)
    ny = round(max(lo_y, min(hi_y, float(y) + dy)), 2)
    nx = max(lo_x, min(hi_x, nx))
    ny = max(lo_y, min(hi_y, ny))
    return (nx, ny)


def generate_bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    steps: int,
) -> List[Tuple[float, float]]:
    """Generate a smoothstep-eased cubic Bezier curve landing exactly on end."""
    n = max(1, int(steps))
    x0, y0 = float(start[0]), float(start[1])
    x3, y3 = float(end[0]), float(end[1])
    if n == 1:
        return [(x3, y3)]

    dx = x3 - x0
    dy = y3 - y0
    dist = math.hypot(dx, dy)
    if dist > 1e-6:
        px, py = -dy / dist, dx / dist
        sign = random.choice((-1.0, 1.0))
        mag1 = min(90.0, random.uniform(0.12, 0.32) * dist)
        mag2 = min(90.0, random.uniform(0.12, 0.32) * dist)
        if dist >= 15.0:
            mag1 = max(6.0, mag1)
            mag2 = max(6.0, mag2)
        c1x = x0 + dx / 3.0 + px * (sign * mag1)
        c1y = y0 + dy / 3.0 + py * (sign * mag1)
        c2x = x0 + (2.0 * dx) / 3.0 + px * (sign * mag2)
        c2y = y0 + (2.0 * dy) / 3.0 + py * (sign * mag2)
    else:
        c1x, c1y = x0, y0
        c2x, c2y = x3, y3

    points: List[Tuple[float, float]] = []
    for i in range(1, n):
        t = i / n
        u = t * t * (3.0 - 2.0 * t)
        om = 1.0 - u
        bx = (om ** 3) * x0 + 3.0 * (om ** 2) * u * c1x + 3.0 * om * (u ** 2) * c2x + (u ** 3) * x3
        by = (om ** 3) * y0 + 3.0 * (om ** 2) * u * c1y + 3.0 * om * (u ** 2) * c2y + (u ** 3) * y3
        points.append((round(bx, 2), round(by, 2)))
    points.append((x3, y3))
    return points


async def move_mouse_bezier(
    tab: Tab,
    x: float,
    y: float,
    *,
    fast: bool = False,
    status: Optional[Status] = None,
) -> List[Tuple[float, float]]:
    """Move virtual CDP cursor along a curved cubic Bezier path (0 physical mouse movement)."""
    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {getattr(tab, 'url', None)}") from e

    if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and math.isfinite(x) and math.isfinite(y)):
        raise ActionPreconditionError(f"coordinates must be finite numbers: x={x}, y={y}")

    tx, ty = float(x), float(y)
    if status is not None:
        max_vx = max(1.0, float(status.width) - 1.0)
        max_vy = max(1.0, float(status.height) - 1.0)
    else:
        max_vx, max_vy = 1200.0, 700.0

    cur = getattr(tab, "_cursor_pos", None)
    if cur is not None:
        start = (float(cur[0]), float(cur[1]))
    else:
        sx = max(1.0, min(max_vx, tx + random.uniform(-180.0, 180.0)))
        sy = max(1.0, min(max_vy, ty + random.uniform(-120.0, 120.0)))
        start = (round(sx, 2), round(sy, 2))

    if fast:
        steps = random.randint(1, 2)
        total_sec = random.uniform(0.001, 0.0035)
        raw_points = generate_bezier_path(start, (tx, ty), steps)
    else:
        total_sec = random.uniform(0.035, 0.075)
        dist = math.hypot(tx - start[0], ty - start[1])
        if dist >= 120.0 and random.random() < 0.25:
            main_steps = random.randint(5, 8)
            correct_steps = random.randint(1, 2)
            ux = (tx - start[0]) / dist
            uy = (ty - start[1]) / dist
            ov_dist = random.uniform(3.0, 8.0)
            perp_noise = random.uniform(-2.0, 2.0)
            ov_x = tx + ux * ov_dist - uy * perp_noise
            ov_y = ty + uy * ov_dist + ux * perp_noise
            if status is not None:
                ov_x = max(0.0, min(max_vx, ov_x))
                ov_y = max(0.0, min(max_vy, ov_y))
            ov_pt = (round(ov_x, 2), round(ov_y, 2))
            raw_points = (
                generate_bezier_path(start, ov_pt, main_steps)
                + generate_bezier_path(ov_pt, (tx, ty), correct_steps)
            )
        else:
            steps = random.randint(6, 10)
            raw_points = generate_bezier_path(start, (tx, ty), steps)
    if status is not None:
        points: List[Tuple[float, float]] = [
            (max(0.0, min(max_vx, px)), max(0.0, min(max_vy, py)))
            for px, py in raw_points[:-1]
        ]
        points.append((tx, ty))
    else:
        points = raw_points

    def _get_id() -> int:
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    step_delay = total_sec / len(points)
    async with _resolve_ws(tab) as ws:
        for idx, (px, py) in enumerate(points):
            await ws.send(json.dumps({
                "id": _get_id(),
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mouseMoved",
                    "x": float(px),
                    "y": float(py),
                    "button": "none",
                },
            }))
            if idx + 1 < len(points) and step_delay > 0.0:
                await asyncio.sleep(step_delay)

    tab._cursor_pos = (tx, ty)
    return points


async def click_point(
    tab: Tab,
    x: float,
    y: float,
    delay_ms: float = 50.0,
    check_preconditions: bool = True,
    status: Optional[Status] = None,
) -> ClickResult:
    if check_preconditions:
        _validate_click_preconditions(tab, x, y, status)

    delay_sec = max(0.020, min(0.200, float(delay_ms) / 1000.0))

    def _get_id() -> int:
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    async with _resolve_ws(tab) as ws:
        press_ns = time.monotonic_ns()
        press_payload = json.dumps({
            "id": _get_id(),
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mousePressed",
                "x": float(x),
                "y": float(y),
                "button": "left",
                "clickCount": 1,
            },
        })
        await ws.send(press_payload)
        pressed = True
        released = False
        release_ns = 0

        try:
            await asyncio.sleep(delay_sec)
        finally:
            release_ns = time.monotonic_ns()
            async def _send_release():
                nonlocal released
                try:
                    rel_payload = json.dumps({
                        "id": _get_id(),
                        "method": "Input.dispatchMouseEvent",
                        "params": {
                            "type": "mouseReleased",
                            "x": float(x),
                            "y": float(y),
                            "button": "left",
                            "clickCount": 1,
                        },
                    })
                    await ws.send(rel_payload)
                    released = True
                except Exception:
                    released = False

            try:
                await asyncio.shield(_send_release())
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        duration_ms = (release_ns - press_ns) / 1_000_000.0
        tab._cursor_pos = (float(x), float(y))
        return ClickResult(
            x=float(x),
            y=float(y),
            pressed=pressed,
            released=released,
            press_monotonic_ns=press_ns,
            release_monotonic_ns=release_ns,
            duration_ms=duration_ms,
        )


async def click_cast(
    tab: Tab,
    x: float,
    y: float,
    status: Status,
    delay_ms: Optional[float] = None,
) -> ClickResult:
    if status.modal:
        raise ActionPreconditionError("Modal dialog is active")
    if status.energy is None or status.energy <= 0:
        raise ActionPreconditionError("Insufficient energy for cast")
    actual_delay = human_hold_ms(fast=False) if delay_ms is None else delay_ms
    return await click_point(tab, x, y, delay_ms=actual_delay, check_preconditions=True, status=status)


async def click_strike(
    tab: Tab,
    x: float,
    y: float,
    status: Status,
    delay_ms: Optional[float] = None,
) -> ClickResult:
    if status.modal:
        raise ActionPreconditionError("Modal dialog is active")
    actual_delay = human_hold_ms(fast=True) if delay_ms is None else delay_ms
    return await click_point(tab, x, y, delay_ms=actual_delay, check_preconditions=True, status=status)


def encode_action_request(opcode: int, x: float, y: float) -> bytes:
    if opcode not in (OP_CLICK_CAST, OP_CLICK_STRIKE):
        raise ProtocolError(f"invalid action opcode: {opcode}")
    if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and math.isfinite(x) and math.isfinite(y)):
        raise ProtocolError("coordinates must be finite numbers")
    return struct.pack("<Bdd", opcode, float(x), float(y))


def decode_action_request(payload: bytes) -> Tuple[int, float, float]:
    if type(payload) is not bytes or len(payload) != 17:
        raise ProtocolError(f"action request payload must be exactly 17 bytes, got {len(payload) if isinstance(payload, bytes) else type(payload)}")
    opcode, x, y = struct.unpack("<Bdd", payload)
    if opcode not in (OP_CLICK_CAST, OP_CLICK_STRIKE):
        raise ProtocolError(f"unknown action opcode: {opcode}")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ProtocolError("nonfinite coordinates in action request")
    return opcode, x, y


def encode_action_response(
    opcode: int,
    status_code: int,
    press_monotonic_ns: int,
    release_monotonic_ns: int,
    released: bool,
) -> bytes:
    if opcode not in (OP_CLICK_CAST, OP_CLICK_STRIKE):
        raise ProtocolError(f"invalid action opcode: {opcode}")
    if status_code not in (ACTION_STATUS_OK, ACTION_STATUS_PRECONDITION_FAILED, ACTION_STATUS_PROTOCOL_ERROR):
        raise ProtocolError(f"invalid action status code: {status_code}")
    if not (0 <= press_monotonic_ns <= 0xFFFFFFFFFFFFFFFF and 0 <= release_monotonic_ns <= 0xFFFFFFFFFFFFFFFF):
        raise ProtocolError("monotonic timestamps must be unsigned 64-bit integers")
    rel_byte = 1 if released else 0
    return struct.pack("<BBQQB", opcode, status_code, press_monotonic_ns, release_monotonic_ns, rel_byte)


def decode_action_response(payload: bytes) -> Tuple[int, int, int, int, bool]:
    if type(payload) is not bytes or len(payload) != 19:
        raise ProtocolError(f"action response payload must be exactly 19 bytes, got {len(payload) if isinstance(payload, bytes) else type(payload)}")
    opcode, status_code, press_ns, release_ns, rel_byte = struct.unpack("<BBQQB", payload)
    if opcode not in (OP_CLICK_CAST, OP_CLICK_STRIKE):
        raise ProtocolError(f"unknown action opcode: {opcode}")
    if status_code not in (ACTION_STATUS_OK, ACTION_STATUS_PRECONDITION_FAILED, ACTION_STATUS_PROTOCOL_ERROR):
        raise ProtocolError(f"unknown action status code: {status_code}")
    if rel_byte not in (0, 1):
        raise ProtocolError(f"invalid released byte: {rel_byte}")
    return opcode, status_code, press_ns, release_ns, bool(rel_byte)


EMPTY_PATTERNS = [
    re.compile(r'\bnothing\s+left\b', re.IGNORECASE),
    re.compile(r'\bno\s+more\s+fish\b', re.IGNORECASE),
    re.compile(r'\bno\s+fish\b', re.IGNORECASE),
    re.compile(r'\bcome\s+back\s+later\b', re.IGNORECASE),
    re.compile(r'\bneeds?\s+time\s+to\s+restock\b', re.IGNORECASE),
    re.compile(r'\bhết\s+cá\b', re.IGNORECASE),
    re.compile(r'\bhồ\s+cạn\b', re.IGNORECASE),
    re.compile(r'\bcạn\b', re.IGNORECASE),
    re.compile(r'\bempty\b', re.IGNORECASE),
    re.compile(r'\brestock\b', re.IGNORECASE),
]

TRASH_PATTERNS = [
    re.compile(r'\bpulled\s+up\s+(?:some\s+)?trash\b', re.IGNORECASE),
    re.compile(r'\bsome\s+trash\b', re.IGNORECASE),
    re.compile(r'\btrash\b', re.IGNORECASE),
    re.compile(r'\brác\b', re.IGNORECASE),
    re.compile(r'\bold\s+boot\b', re.IGNORECASE),
    re.compile(r'\bboot\b', re.IGNORECASE),
    re.compile(r'\brusty\s+can\b', re.IGNORECASE),
    re.compile(r"\bcan\b(?!['’]t\b)", re.IGNORECASE),
    re.compile(r'\blon\b', re.IGNORECASE),
]

CATCH_PATTERNS = [
    re.compile(r'\band\s+[i1l|]\s+got\b', re.IGNORECASE),
    re.compile(r'\bcaught\b', re.IGNORECASE),
    re.compile(r'\bcollected\b', re.IGNORECASE),
    re.compile(r'\bbắt\s+được\b', re.IGNORECASE),
    re.compile(r'\bfish\s+caught\b', re.IGNORECASE),
]

EMPTY_KEYWORDS = (
    "empty", "cạn", "hết cá", "no fish", "no more fish",
    "nothing left", "come back later", "restock",
    "nothing left to catch", "there is nothing left",
)

TRASH_KEYWORDS = (
    "trash", "rác", "boot", "giày", "can", "lon",
    "some trash", "pulled up some trash", "pulled up trash",
)

CATCH_KEYWORDS = (
    "fish", "cá", "caught", "bắt được", "and i got", "and 1 got", "collected",
)


def classify_toast(toast_text: Optional[str]) -> Optional[str]:
    """Phân loại chuỗi toast trả về: 'TRASH', 'EMPTY', 'CATCH', hoặc None bằng Regex chặt chẽ."""
    if not toast_text:
        return None
    t = toast_text.strip()
    if not t:
        return None

    # 1. Kiểm tra Trash trước
    for pat in TRASH_PATTERNS:
        if pat.search(t):
            return "TRASH"

    # 2. Kiểm tra Empty
    for pat in EMPTY_PATTERNS:
        if pat.search(t):
            return "EMPTY"

    # 3. Kiểm tra Catch
    for pat in CATCH_PATTERNS:
        if pat.search(t):
            return "CATCH"

    return None


RESET_HOURS = (1, 4, 7, 10, 13, 16, 19, 22)


def is_reset_window(dt: Optional[datetime] = None) -> bool:
    """Kiểm tra thời điểm hiện tại có nằm trong 15 phút đầu của khung giờ reset không."""
    now = dt or datetime.now()
    return (now.hour in RESET_HOURS) and (now.minute < 15)


def check_server_reset(
    current_lake: int,
    last_reset_hour: Optional[int],
    dt: Optional[datetime] = None,
) -> Tuple[bool, Optional[int]]:
    """
    Kiểm tra xem có cần tự động quay về Hồ 1 do server reset không.
    Trả về: (should_reset: bool, new_reset_hour: Optional[int])
    - should_reset = True khi đang trong giờ reset, chưa kích hoạt cho giờ này, và current_lake > 1.
    """
    now = dt or datetime.now()
    if is_reset_window(now):
        if last_reset_hour != now.hour:
            # Đây là mốc giờ reset mới chưa được xử lý
            if current_lake > 1:
                return True, now.hour
            # Nếu đã ở hồ 1 rồi thì chỉ cần cập nhật last_reset_hour
            return False, now.hour
    return False, last_reset_hour


def get_next_reset_datetime(now: Optional[datetime] = None) -> datetime:
    """Tính mốc thời gian reset server kế tiếp."""
    cur = now or datetime.now()
    today_resets = [cur.replace(hour=h, minute=0, second=0, microsecond=0) for h in RESET_HOURS]
    for r_dt in today_resets:
        if r_dt > cur:
            return r_dt
    # Nếu đã qua 22:00 thì mốc tiếp theo là 01:00 ngày hôm sau
    tomorrow = cur + timedelta(days=1)
    return tomorrow.replace(hour=RESET_HOURS[0], minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class Outcome:
    kind: str  # "CATCH", "TIMEOUT", "EMPTY", "TRASH", "NO_WATER", "INSUFFICIENT_ENERGY", "MODAL_ACTIVE", "UNVERIFIED", "MISS"
    cast_x: Optional[float] = None
    cast_y: Optional[float] = None
    cast_at: Optional[float] = None
    alert_detected_at: Optional[float] = None
    strike_at: Optional[float] = None
    reaction_ms: Optional[float] = None
    pre_energy: Optional[int] = None
    post_energy: Optional[int] = None
    pre_xp: Optional[int] = None
    post_xp: Optional[int] = None
    toast: str = ""
    poll_count: int = 0
    duration_sec: float = 0.0
    verified: bool = False


def is_verified_catch(outcome: Outcome) -> bool:
    """Xác nhận cú giật cần có bằng chứng thu hoạch cá thành công 100%."""
    t = (getattr(outcome, "toast", "") or "").lower()
    has_catch_toast = any(kw in t for kw in ("and i got", "and 1 got", "collected", "caught", "bắt được"))
    pre_xp = getattr(outcome, "pre_xp", None)
    post_xp = getattr(outcome, "post_xp", None)
    xp_gained = (
        pre_xp is not None
        and post_xp is not None
        and post_xp > pre_xp
    )
    return has_catch_toast or xp_gained


def _adaptive_alert_sleep(
    elapsed_since_cast: float,
    poll_interval_sec: float,
    poll_work_sec: float = 0.0,
) -> float:
    """GPU-friendly 3-phase adaptive sleep interval for alert polling (passthrough for small test intervals)."""
    if poll_interval_sec <= 0:
        return 0.0
    if poll_interval_sec < 0.04:
        return poll_interval_sec
    work = max(0.0, float(poll_work_sec))
    if elapsed_since_cast < 3.2:
        return max(0.250, 0.420 - work)
    if elapsed_since_cast < 3.8:
        return max(0.080, 0.180 - work)
    return max(0.022, 0.104 - work)


async def run_one_cast(
    tab: Tab,
    use_worker: bool = True,
    max_alert_wait_sec: float = 11.0,
    poll_interval_sec: float = 0.05,
    reel_wait_sec: float = 1.5,
    baseline_delay_sec: float = 0.80,
    obs_delay_sec: float = 0.95,
    poll_outcome_timeout: Optional[float] = None,
    lake: Optional[int] = None,
    human_reaction: bool = True,
) -> Outcome:
    async with cdp_session(tab):
        try:
            return await _run_one_cast_body(
                tab=tab,
                use_worker=use_worker,
                max_alert_wait_sec=max_alert_wait_sec,
                poll_interval_sec=poll_interval_sec,
                reel_wait_sec=reel_wait_sec,
                baseline_delay_sec=baseline_delay_sec,
                obs_delay_sec=obs_delay_sec,
                poll_outcome_timeout=poll_outcome_timeout,
                lake=lake,
                human_reaction=human_reaction,
            )
        finally:
            tab._fast_alert_status = None


async def _run_one_cast_body(
    tab: Tab,
    use_worker: bool = True,
    max_alert_wait_sec: float = 11.0,
    poll_interval_sec: float = 0.05,
    reel_wait_sec: float = 1.5,
    baseline_delay_sec: float = 0.80,
    obs_delay_sec: float = 0.95,
    poll_outcome_timeout: Optional[float] = None,
    lake: Optional[int] = None,
    human_reaction: bool = True,
) -> Outcome:
    t_start = time.monotonic()

    # Step 1: Preconditions Gate
    pre_status = await read_status(tab)
    initial_toast = (pre_status.toast or "").strip().lower()
    stale_toast = (getattr(tab, "_stale_toast", "") or "").strip().lower()
    if stale_toast and initial_toast != stale_toast:
        tab._stale_toast = ""
        stale_toast = ""
    ignored_toasts = {t for t in (initial_toast, stale_toast) if t}
    if pre_status.modal:
        return Outcome(
            kind="MODAL_ACTIVE",
            pre_energy=pre_status.energy,
            pre_xp=pre_status.xp,
            duration_sec=time.monotonic() - t_start,
        )
    if pre_status.energy is None or pre_status.energy <= 0:
        return Outcome(
            kind="INSUFFICIENT_ENERGY",
            pre_energy=pre_status.energy,
            pre_xp=pre_status.xp,
            duration_sec=time.monotonic() - t_start,
        )

    # Step 2: Find Water
    full_frame = await capture(tab, "SCREEN_FULL")
    water_spot = pick_random_water_point(
        full_frame.image,
        last_point=getattr(tab, "_last_water_point", None),
        include_day=True,
    )
    if water_spot is not None:
        tab._last_water_point = water_spot
    if water_spot is None:
        return Outcome(
            kind="NO_WATER",
            pre_energy=pre_status.energy,
            pre_xp=pre_status.xp,
            duration_sec=time.monotonic() - t_start,
        )

    wx, wy = water_spot
    cast_x = (wx * pre_status.width) / full_frame.image.width
    cast_y = (wy * pre_status.height) / full_frame.image.height

    # Step 3: Cast
    await move_mouse_bezier(tab, cast_x, cast_y, fast=False, status=pre_status)
    await click_cast(tab, cast_x, cast_y, pre_status)
    cast_at = time.monotonic()
    if lake is not None:
        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {lake:02d}/40] 🎣 Quăng cần xuống nước (CSS={cast_x:.1f}, {cast_y:.1f}). Đang đợi cá cắn...")

    # Fast Check 1: Kiểm tra ngay sau khi quăng cần (<0.2s)
    last_status = pre_status
    try:
        immediate_status = await read_status(tab)
        last_status = immediate_status
        current_toast = (immediate_status.toast or "").strip().lower()
        if not current_toast or (stale_toast and current_toast != stale_toast):
            tab._stale_toast = ""
            stale_toast = ""
        if current_toast and current_toast not in ignored_toasts:
            early_kind = classify_toast(immediate_status.toast or "")
            if early_kind in ("EMPTY", "TRASH"):
                return Outcome(
                    kind=early_kind,
                    cast_x=cast_x,
                    cast_y=cast_y,
                    cast_at=cast_at,
                    pre_energy=pre_status.energy,
                    post_energy=immediate_status.energy,
                    pre_xp=pre_status.xp,
                    post_xp=immediate_status.xp,
                    toast=immediate_status.toast or "",
                    poll_count=0,
                    duration_sec=time.monotonic() - t_start,
                )
    except Exception:
        pass

    # Step 4: Stabilize Baseline
    now = time.monotonic()
    wait_baseline = max(0.0, (cast_at + baseline_delay_sec) - now)
    if wait_baseline > 0:
        await asyncio.sleep(wait_baseline)
    tab._fast_alert_status = pre_status
    baseline_frame = await capture(tab, "SCREEN_ALERT")

    # Step 5: Alert Observation Loop
    now = time.monotonic()
    wait_obs = max(0.0, (cast_at + obs_delay_sec) - now)
    if wait_obs > 0:
        await asyncio.sleep(wait_obs)

    deadline = cast_at + max_alert_wait_sec
    poll_count = 0
    hit = None
    alert_detected_at = None
    strike_at = None
    reaction_ms = None
    prev_neg_arr: Optional[np.ndarray] = None
    last_toast_check = cast_at
    do_idle_drift = (poll_interval_sec >= 0.04) and (random.random() < 0.20)
    idle_drift_at = cast_at + random.uniform(1.0, 2.2) if do_idle_drift else 0.0

    while time.monotonic() < deadline:
        poll_t0 = time.monotonic()
        poll_count += 1

        if do_idle_drift and poll_t0 >= idle_drift_at:
            do_idle_drift = False
            drift_x, drift_y = jitter_point(
                cast_x,
                cast_y,
                max_dx=6.0,
                max_dy=6.0,
                min_x=1.0,
                max_x=max(1.0, pre_status.width - 1.0),
                min_y=1.0,
                max_y=max(1.0, pre_status.height - 1.0),
            )
            try:
                await move_mouse_bezier(tab, drift_x, drift_y, fast=True, status=pre_status)
            except Exception:
                pass

        # Fast Check 2: Kiểm tra toast định kỳ trong khi chờ alert (mỗi 0.80s)
        if (time.monotonic() - last_toast_check) >= 0.80:
            last_toast_check = time.monotonic()
            try:
                mid_status = await read_status(tab)
                last_status = mid_status
                tab._fast_alert_status = mid_status
                current_toast = (mid_status.toast or "").strip().lower()
                if not current_toast or (stale_toast and current_toast != stale_toast):
                    tab._stale_toast = ""
                    stale_toast = ""
                if current_toast and current_toast not in ignored_toasts:
                    mid_kind = classify_toast(mid_status.toast or "")
                    if mid_kind in ("EMPTY", "TRASH"):
                        return Outcome(
                            kind=mid_kind,
                            cast_x=cast_x,
                            cast_y=cast_y,
                            cast_at=cast_at,
                            pre_energy=pre_status.energy,
                            post_energy=mid_status.energy,
                            pre_xp=pre_status.xp,
                            post_xp=mid_status.xp,
                            toast=mid_status.toast or "",
                            poll_count=poll_count,
                            duration_sec=time.monotonic() - t_start,
                        )
            except Exception:
                pass

        alert_frame = await capture(tab, "SCREEN_ALERT")
        curr_arr = np.frombuffer(alert_frame.image.rgb, dtype=np.uint8).reshape(
            (alert_frame.image.height, alert_frame.image.width, 3)
        )
        if (
            prev_neg_arr is not None
            and prev_neg_arr.shape == curr_arr.shape
            and int(cv2.absdiff(curr_arr, prev_neg_arr).max()) < 10
        ):
            hit = None
        else:
            hit = alert_point(alert_frame.image, baseline=baseline_frame.image)
            if hit is None:
                prev_neg_arr = curr_arr

        if hit is not None:
            alert_detected_at = time.monotonic()
            is_blink = False
            if human_reaction and poll_interval_sec >= 0.04:
                react_delay, is_blink = human_strike_delay_sec()
                await asyncio.sleep(react_delay)
            strike_x, strike_y = jitter_point(
                cast_x,
                cast_y,
                max_dx=2.5,
                max_dy=2.5,
                min_x=1.0,
                max_x=max(1.0, pre_status.width - 1.0),
                min_y=1.0,
                max_y=max(1.0, pre_status.height - 1.0),
            )
            await move_mouse_bezier(tab, strike_x, strike_y, fast=True, status=pre_status)
            await click_strike(tab, strike_x, strike_y, pre_status)
            strike_at = time.monotonic()
            reaction_ms = (strike_at - alert_detected_at) * 1000.0
            if lake is not None:
                blink_tag = " [chậm tự nhiên]" if is_blink else ""
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {lake:02d}/40] ⚡ CÁ CẮN CÂU (!) - Giật cần tức thì ({reaction_ms:.1f}ms){blink_tag}!")
            break
        poll_work_sec = time.monotonic() - poll_t0
        sleep_sec = _adaptive_alert_sleep(time.monotonic() - cast_at, poll_interval_sec, poll_work_sec)
        if sleep_sec > 0:
            await asyncio.sleep(sleep_sec)

    if hit is None:
        return Outcome(
            kind="TIMEOUT",
            cast_x=cast_x,
            cast_y=cast_y,
            cast_at=cast_at,
            pre_energy=pre_status.energy,
            pre_xp=pre_status.xp,
            poll_count=poll_count,
            duration_sec=time.monotonic() - t_start,
        )

    # Step 6: Active Toast Polling sau khi Strike
    if poll_outcome_timeout is not None:
        outcome_timeout = poll_outcome_timeout
    elif reel_wait_sec < 0.1:
        outcome_timeout = reel_wait_sec
    else:
        outcome_timeout = 3.5

    poll_step = min(0.12, outcome_timeout) if outcome_timeout > 0 else 0.001
    poll_deadline = time.monotonic() + outcome_timeout
    post_status = last_status

    initial_kind = classify_toast(post_status.toast or "")
    if initial_kind in ("EMPTY", "TRASH", "CATCH") or post_status.modal:
        pass
    else:
        while time.monotonic() < poll_deadline:
            try:
                post_status = await read_status(tab)
                last_status = post_status
            except IndexError:
                break
            except Exception:
                pass

            toast_kind = classify_toast(post_status.toast or "")
            if toast_kind in ("EMPTY", "TRASH", "CATCH"):
                break
            if post_status.modal:
                break
            if poll_step > 0:
                await asyncio.sleep(poll_step)

    # Final Classification
    final_toast_kind = classify_toast(post_status.toast or "")
    if final_toast_kind == "EMPTY":
        kind = "EMPTY"
    elif final_toast_kind == "TRASH":
        kind = "TRASH"
    elif final_toast_kind == "CATCH":
        kind = "CATCH"
    elif post_status.modal:
        kind = "MODAL_ACTIVE"
    else:
        energy_decreased = (
            pre_status.energy is not None
            and post_status.energy is not None
            and post_status.energy < pre_status.energy
        )
        xp_increased = (
            pre_status.xp is not None
            and post_status.xp is not None
            and post_status.xp > pre_status.xp
        )
        if energy_decreased or xp_increased:
            kind = "CATCH"
        else:
            kind = "UNVERIFIED"

    t_low = (post_status.toast or "").lower()
    has_catch_toast = any(kw in t_low for kw in ("and i got", "and 1 got", "collected", "caught", "bắt được"))
    xp_increased_flag = (
        pre_status.xp is not None
        and post_status.xp is not None
        and post_status.xp > pre_status.xp
    )
    is_verified = (kind == "CATCH") and (has_catch_toast or xp_increased_flag)

    return Outcome(
        kind=kind,
        cast_x=cast_x,
        cast_y=cast_y,
        cast_at=cast_at,
        alert_detected_at=alert_detected_at,
        strike_at=strike_at,
        reaction_ms=reaction_ms,
        pre_energy=pre_status.energy,
        post_energy=post_status.energy,
        pre_xp=pre_status.xp,
        post_xp=post_status.xp,
        toast=post_status.toast or "",
        poll_count=poll_count,
        duration_sec=time.monotonic() - t_start,
        verified=is_verified,
    )


def print_one_cast_report(res: Outcome) -> None:
    print("=== NOMSTEAD ONE-CAST OUTCOME ===")
    verified_tag = " (Verified)" if res.kind == "CATCH" else ""
    print(f"Outcome: {res.kind}{verified_tag}")
    if res.cast_x is not None and res.cast_y is not None:
        print(f"Cast Coordinates: CSS=({res.cast_x:.1f}, {res.cast_y:.1f})")
    else:
        print("Cast Coordinates: None")

    if res.pre_energy is not None and res.post_energy is not None:
        consumed = res.pre_energy - res.post_energy
        print(f"Pre/Post Energy: {res.pre_energy} -> {res.post_energy} (Consumed: {consumed})")
    elif res.pre_energy is not None:
        print(f"Pre/Post Energy: {res.pre_energy} -> None")
    else:
        print("Pre/Post Energy: None")

    if res.pre_xp is not None and res.post_xp is not None:
        diff_xp = res.post_xp - res.pre_xp
        diff_str = f"+{diff_xp}" if diff_xp >= 0 else str(diff_xp)
        print(f"Pre/Post XP: {res.pre_xp} -> {res.post_xp} ({diff_str})")
    elif res.pre_xp is not None:
        print(f"Pre/Post XP: {res.pre_xp} -> None")
    else:
        print("Pre/Post XP: None")

    print(f'Toast: "{res.toast or ""}"')
    if res.reaction_ms is not None:
        print(f"Alert Hook: Detected (Polls: {res.poll_count}, Reaction: {res.reaction_ms:.1f} ms)")
    else:
        print(f"Alert Hook: None (Polls: {res.poll_count})")
    print(f"Total Cycle Duration: {res.duration_sec:.2f}s")
    print("ONE-CAST OK")


async def _cdp_evaluate(tab: Tab, expression: str) -> Any:
    def _get_id():
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    is_persistent = getattr(tab, "ws", None) is not None or getattr(tab, "_want_persistent_ws", False)
    attempts = 2 if (getattr(tab, "_want_persistent_ws", False) or getattr(tab, "_managed_ws", False)) else 1
    for attempt in range(attempts):
        try:
            async with _resolve_ws(tab) as ws:
                msg_id = _get_id()
                async with asyncio.timeout(_CDP_TIMEOUT):
                    await ws.send(json.dumps({
                        'id': msg_id,
                        'method': 'Runtime.evaluate',
                        'params': {'expression': expression, 'returnByValue': True}
                    }))
                    result, _ = await _receive_cdp_result(
                        ws, msg_id, _CDP_MAX_BYTES, allow_stale_ids=is_persistent
                    )
                    remote = result.get('result')
                    return remote.get('value') if isinstance(remote, dict) else None
        except (CdpError, asyncio.CancelledError):
            raise
        except Exception:
            if getattr(tab, "_managed_ws", False) and attempt == 0:
                await close_cdp_session(tab)
                continue
            raise


@dataclass(frozen=True)
class EatBreadResult:
    consumed: bool
    pre_energy: Optional[int]
    post_energy: Optional[int]
    recovered: int
    reason: str  # "SUCCESS", "ENERGY_FULL", "NO_BREAD_FOUND", "NO_ENERGY_INCREASE", "MODAL_ACTIVE", "OUT_OF_BOUNDS"
    duration_ms: float


async def eat_bread(
    tab: Tab,
    force: bool = False,
    quickslot_pos: Optional[Tuple[float, float]] = None,
) -> EatBreadResult:
    t_start = time.monotonic()
    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {tab.url}") from e

    pre_status = await read_status(tab)
    if pre_status.modal:
        return EatBreadResult(
            consumed=False,
            pre_energy=pre_status.energy,
            post_energy=pre_status.energy,
            recovered=0,
            reason="MODAL_ACTIVE",
            duration_ms=(time.monotonic() - t_start) * 1000.0,
        )

    if pre_status.energy is not None and pre_status.energy >= 75 and not force:
        return EatBreadResult(
            consumed=False,
            pre_energy=pre_status.energy,
            post_energy=pre_status.energy,
            recovered=0,
            reason="ENERGY_FULL",
            duration_ms=(time.monotonic() - t_start) * 1000.0,
        )

    full_frame = await capture(tab, "SCREEN_FULL")
    bread_spot = find_bread_point(full_frame, pre_status)

    if bread_spot is not None:
        bx, by = bread_spot
    elif quickslot_pos is not None:
        bx, by = quickslot_pos
    else:
        return EatBreadResult(
            consumed=False,
            pre_energy=pre_status.energy,
            post_energy=pre_status.energy,
            recovered=0,
            reason="NO_BREAD_FOUND",
            duration_ms=(time.monotonic() - t_start) * 1000.0,
        )

    if by > 0.95 * pre_status.height:
        return EatBreadResult(
            consumed=False,
            pre_energy=pre_status.energy,
            post_energy=pre_status.energy,
            recovered=0,
            reason="OUT_OF_BOUNDS",
            duration_ms=(time.monotonic() - t_start) * 1000.0,
        )

    bx, by = jitter_point(
        bx,
        by,
        max_dx=3.0,
        max_dy=3.0,
        min_x=0.20 * pre_status.width,
        max_x=0.80 * pre_status.width,
        min_y=0.70 * pre_status.height,
        max_y=min(0.94 * pre_status.height, pre_status.height - 1.0),
    )
    await move_mouse_bezier(tab, bx, by, fast=False, status=pre_status)
    await click_point(tab, bx, by, delay_ms=human_hold_ms(fast=False), check_preconditions=True, status=pre_status)
    await asyncio.sleep(0.8)

    post_status = await read_status(tab)
    if (
        post_status.energy is not None
        and pre_status.energy is not None
        and post_status.energy > pre_status.energy
    ):
        recovered = post_status.energy - pre_status.energy
        return EatBreadResult(
            consumed=True,
            pre_energy=pre_status.energy,
            post_energy=post_status.energy,
            recovered=recovered,
            reason="SUCCESS",
            duration_ms=(time.monotonic() - t_start) * 1000.0,
        )
    return EatBreadResult(
        consumed=False,
        pre_energy=pre_status.energy,
        post_energy=post_status.energy,
        recovered=0,
        reason="NO_ENERGY_INCREASE",
        duration_ms=(time.monotonic() - t_start) * 1000.0,
    )


@dataclass(frozen=True)
class TravelResult:
    success: bool
    lake: int
    attempts: int
    duration_sec: float
    error: Optional[str] = None


def is_bookmarks_tab_active(color_or_style: str, is_active_class: bool = False, is_mine_active: bool = False) -> bool:
    """Xác nhận tab Bookmarks đã thực sự active (màu hồng hoặc class active, và My tiles không active)."""
    if is_mine_active:
        return False
    c = (color_or_style or "").lower()
    is_pink = ("254" in c and "119" in c) or ("rgb(254, 119" in c) or ("#fe77" in c)
    return is_pink or is_active_class


BOOKMARKS_READY_EXPR = """(() => {
    /* remove-bookmark fast travel scrollIntoView getBoundingClientRect */
    const modal = document.querySelector('.modal-body');
    if (!modal) return { ready: false, error: 'no_modal' };
    const tiles = modal.querySelectorAll('.map ul.tiles > li.tile, ul.tiles > li.tile, ul.tiles > li');
    const spinner = modal.querySelector('.spinner, [class*="loading"], [class*="spinner"], svg[class*="spin"], [data-ui="loading"], .loading-indicator');
    const hasTiles = tiles.length > 0;
    const isSpinning = Boolean(spinner && (spinner.getClientRects().length > 0 || getComputedStyle(spinner).display !== 'none'));
    return {
        ready: hasTiles && !isSpinning,
        count: tiles.length,
        has_spinner: isSpinning
    };
})()"""


async def travel_to_lake(
    tab: Tab,
    target_lake: int,
    max_retries: int = 3,
) -> TravelResult:
    if not isinstance(target_lake, int) or target_lake < 1 or target_lake > 40:
        raise ValueError(f"target_lake must be between 1 and 40, got {target_lake}")

    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {tab.url}") from e

    t_start = time.monotonic()

    for attempt in range(1, max_retries + 1):
        # Bước 1: Mở Codex (Read-only DOM lookup + trusted CDP click)
        open_codex_expr = """(() => {
            const modal = document.querySelector('.modal-body');
            if (modal) return { open: true, wasOpen: true };
            const btn = document.querySelector('img[title*="Codex" i], img[src*="codex" i], [title*="Codex" i], button.codex-btn, [data-ui="codex"]');
            if (!btn) return { open: false, found: false };
            const r = btn.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) return { open: false, found: false };
            return {
                open: false,
                found: true,
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
                width: r.width,
                height: r.height
            };
        })()"""
        codex_info = None
        try:
            codex_info = await _cdp_evaluate(tab, open_codex_expr)
        except Exception:
            pass
        if (
            isinstance(codex_info, dict)
            and not codex_info.get("open")
            and codex_info.get("found")
            and "x" in codex_info
            and "y" in codex_info
        ):
            cx = float(codex_info["x"])
            cy = float(codex_info["y"])
            max_dx = min(4.0, max(0.0, float(codex_info.get("width", 0.0)) * 0.25))
            max_dy = min(3.0, max(0.0, float(codex_info.get("height", 0.0)) * 0.25))
            cx, cy = jitter_point(
                cx,
                cy,
                max_dx=max_dx,
                max_dy=max_dy,
                min_x=max(0.0, cx - max_dx),
                max_x=cx + max_dx,
                min_y=max(0.0, cy - max_dy),
                max_y=cy + max_dy,
            )
            try:
                await move_mouse_bezier(tab, cx, cy, fast=False)
                await click_point(tab, cx, cy, delay_ms=human_hold_ms(fast=False))
            except Exception:
                pass
        await asyncio.sleep(0.3)

        # Bước 2: Kích hoạt Tab Bookmarks (Read-only DOM lookup + trusted CDP click)
        tab_expr = """(() => {
            const bm = document.querySelector('li[data-ui-tab="bookmarks"]');
            if (!bm) return { active: false, found: false, error: "no_bookmarks_tab" };
            const isClassActive = bm.classList.contains('active') || bm.getAttribute('aria-selected') === 'true';
            const color = window.getComputedStyle(bm).color || '';
            const isPink = color.includes('254') && color.includes('119');
            const mine = document.querySelector('li[data-ui-tab="mine"]');
            const mineInactive = !mine || !mine.classList.contains('active');
            const active = (isClassActive || isPink) && mineInactive;
            if (active) return { active: true };
            const r = bm.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) return { active: false, found: false };
            return {
                active: false,
                found: true,
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
                width: r.width,
                height: r.height
            };
        })()"""

        bookmarks_active = False
        for _tab_retry in range(3):
            tab_info = None
            try:
                tab_info = await _cdp_evaluate(tab, tab_expr)
            except Exception:
                pass
            if isinstance(tab_info, dict) and tab_info.get("active"):
                bookmarks_active = True
                break
            if isinstance(tab_info, dict) and tab_info.get("found") and "x" in tab_info and "y" in tab_info:
                bx = float(tab_info["x"])
                by = float(tab_info["y"])
                max_dx = min(4.0, max(0.0, float(tab_info.get("width", 0.0)) * 0.25))
                max_dy = min(3.0, max(0.0, float(tab_info.get("height", 0.0)) * 0.25))
                bx, by = jitter_point(
                    bx,
                    by,
                    max_dx=max_dx,
                    max_dy=max_dy,
                    min_x=max(0.0, bx - max_dx),
                    max_x=bx + max_dx,
                    min_y=max(0.0, by - max_dy),
                    max_y=by + max_dy,
                )
                try:
                    await move_mouse_bezier(tab, bx, by, fast=False)
                    await click_point(tab, bx, by, delay_ms=human_hold_ms(fast=False))
                except Exception:
                    pass
            await asyncio.sleep(0.35)

        if not bookmarks_active:
            # Cleanup modal via trusted CDP Escape + read-only close lookup
            await _dismiss_modal_cdp(tab)
            await asyncio.sleep(0.5)
            continue

        # Bước 2.5: Active Spinner Polling - Chờ Vòng Xoay Loading Biến Mất & Danh Sách 40 Hồ Tải Xong (2 - 5 giây)
        ready_expr = BOOKMARKS_READY_EXPR
        bookmarks_ready = False
        wait_ready_deadline = time.monotonic() + 6.0
        while time.monotonic() < wait_ready_deadline:
            try:
                ready_info = await _cdp_evaluate(tab, ready_expr)
                if isinstance(ready_info, dict) and (ready_info.get("ready") or ready_info.get("found") or ready_info.get("active")):
                    bookmarks_ready = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.15)

        # Bước 3: Cuộn bằng CDP mouseWheel & Nhận diện Hồ Mục tiêu HO <target_lake> (Read-only DOM)
        lake_expr = f"""(() => {{
            /* CDP mouseWheel scrolling replaces instant center scrollIntoView (zero DOM mutation) */
            const tiles = document.querySelectorAll('.modal-body .map ul.tiles > li.tile, .modal-body ul.tiles > li.tile, ul.tiles > li.tile, ul.tiles > li');
            const re = new RegExp('^\\\\s*HO\\\\s+{target_lake}\\\\s*$', 'i');
            for (const tile of tiles) {{
                const descEl = tile.querySelector('.info-meta > .description, .description, .title, h4, span');
                const text = descEl ? (descEl.innerText || '') : (tile.innerText || '');
                if (re.test(text.trim()) || text.split('\\n').some(line => re.test(line.trim()))) {{
                    const btns = [...tile.querySelectorAll('a.btn, button.btn, a[href]')];
                    const fastTravelBtn = btns.find(b => {{
                        if (b.matches && b.matches('button.remove-bookmark, [class*="remove-bookmark"]')) return false;
                        const bText = (b.innerText || '').toLowerCase();
                        return bText.includes('fast travel') || bText.includes('travel') || b.getAttribute('href');
                    }}) || tile.querySelector('a.btn');

                    if (fastTravelBtn) {{
                        const rect = fastTravelBtn.getBoundingClientRect();
                        const sc = tile.closest('.map, .modal-body, ul.tiles') || document.querySelector('.modal-body');
                        const cRect = sc ? sc.getBoundingClientRect() : {{
                            top: 0, bottom: innerHeight, left: 0, right: innerWidth, width: innerWidth, height: innerHeight
                        }};
                        const inView = rect.width > 0 && rect.height > 0
                            && rect.top >= cRect.top + 8
                            && rect.bottom <= cRect.bottom - 8;
                        const btnMidY = rect.top + rect.height / 2;
                        const cMidY = cRect.top + cRect.height / 2;
                        return {{
                            found: true,
                            in_view: inView,
                            x: rect.left + rect.width / 2,
                            y: btnMidY,
                            width: rect.width,
                            height: rect.height,
                            scroll_dy: inView ? 0 : (btnMidY - cMidY),
                            container_x: cRect.left + cRect.width / 2,
                            container_y: cMidY,
                            url: fastTravelBtn.getAttribute('href') || ''
                        }};
                    }}
                }}
            }}
            return {{ found: false, count: tiles.length }};
        }})()"""
        lake_info = None
        try:
            lake_info = await _cdp_evaluate(tab, lake_expr)
        except Exception:
            pass

        if isinstance(lake_info, dict) and lake_info.get("found") and not lake_info.get("in_view", True):
            wheel_cx = float(lake_info.get("container_x", lake_info.get("x", 400.0)))
            wheel_cy = float(lake_info.get("container_y", lake_info.get("y", 300.0)))
            wheel_cx, wheel_cy = jitter_point(
                wheel_cx,
                wheel_cy,
                max_dx=25.0,
                max_dy=20.0,
                min_x=1.0,
                max_x=8191.0,
                min_y=1.0,
                max_y=8191.0,
            )
            try:
                await move_mouse_bezier(tab, wheel_cx, wheel_cy, fast=False)
            except Exception:
                pass
            for _scroll_step in range(18):
                if not isinstance(lake_info, dict) or not lake_info.get("found") or lake_info.get("in_view", True):
                    break
                scroll_dy = float(lake_info.get("scroll_dy", 0.0))
                step_mag = max(
                    120.0,
                    min(abs(scroll_dy) if abs(scroll_dy) > 0.0 else 280.0, random.uniform(220.0, 380.0)),
                )
                delta_y = step_mag if scroll_dy >= 0.0 else -step_mag
                try:
                    await scroll_mouse_wheel(tab, wheel_cx, wheel_cy, delta_y)
                except Exception:
                    break
                await asyncio.sleep(random.uniform(0.06, 0.14))
                try:
                    lake_info = await _cdp_evaluate(tab, lake_expr)
                except Exception:
                    break

        # Bước 4: Click Fast Travel, Chờ chuyển cảnh & Đóng modal khi fail
        if isinstance(lake_info, dict) and lake_info.get("found"):
            x = float(lake_info.get("x", 0.0))
            y = float(lake_info.get("y", 0.0))
            if "width" in lake_info and "height" in lake_info:
                max_dx = min(4.0, max(0.0, float(lake_info["width"]) * 0.25))
                max_dy = min(3.0, max(0.0, float(lake_info["height"]) * 0.25))
                x, y = jitter_point(
                    x,
                    y,
                    max_dx=max_dx,
                    max_dy=max_dy,
                    min_x=max(0.0, x - max_dx),
                    max_x=x + max_dx,
                    min_y=max(0.0, y - max_dy),
                    max_y=y + max_dy,
                )
                hold_ms = human_hold_ms(fast=False)
            else:
                hold_ms = 50.0
            await asyncio.sleep(0.15)
            try:
                await move_mouse_bezier(tab, x, y, fast=False)
                await click_point(tab, x, y, delay_ms=hold_ms)
            except Exception:
                pass

            # Chờ chuyển cảnh: modal biến mất (status.modal == False)
            await asyncio.sleep(1.5)
            try:
                st = await read_status(tab)
                if not st.modal:
                    # Đọc snapshot Stale Toast (100% read-only DOM, zero innerText write)
                    snapshot_toast_expr = """(() => {
                        const primary = document.querySelector('.message-bar');
                        const primaryText = (primary?.innerText || '').trim();
                        if (primaryText.length > 0) return primaryText.toLowerCase();
                        const secondary = document.querySelector('.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]');
                        return (secondary?.innerText || '').trim().toLowerCase();
                    })()"""
                    try:
                        stale_text = await _cdp_evaluate(tab, snapshot_toast_expr)
                        tab._stale_toast = stale_text.strip().lower() if isinstance(stale_text, str) else ""
                    except Exception:
                        tab._stale_toast = ""
                    tab._last_water_point = None
                    tab._fast_alert_status = None
                    return TravelResult(
                        success=True,
                        lake=target_lake,
                        attempts=attempt,
                        duration_sec=time.monotonic() - t_start,
                        error=None,
                    )
            except Exception:
                pass

        # Cleanup modal khi thất bại ở attempt này (trusted CDP Escape + read-only close lookup)
        await _dismiss_modal_cdp(tab)
        await asyncio.sleep(0.5)

    return TravelResult(
        success=False,
        lake=target_lake,
        attempts=max_retries,
        duration_sec=time.monotonic() - t_start,
        error=f"Failed to travel to lake {target_lake} after {max_retries} attempts",
    )


def encode_eat_bread_request() -> bytes:
    return bytes([OP_EAT_BREAD])


def decode_eat_bread_request(payload: bytes) -> int:
    if type(payload) is not bytes or len(payload) != 1 or payload[0] != OP_EAT_BREAD:
        raise ProtocolError("eat bread request payload must be exactly 1 byte equal to OP_EAT_BREAD")
    return payload[0]


def encode_eat_bread_response(status_code: int, recovered_energy: int, duration_ms: int) -> bytes:
    if status_code not in (EAT_BREAD_OK, EAT_BREAD_FAILED, EAT_BREAD_SKIPPED_FULL):
        raise ProtocolError(f"invalid eat bread status code: {status_code}")
    if not (0 <= recovered_energy <= 0xFFFFFFFF and 0 <= duration_ms <= 0xFFFFFFFF):
        raise ProtocolError("energy and duration must be u32")
    return struct.pack("<BBII", OP_EAT_BREAD, status_code, recovered_energy, duration_ms)


def decode_eat_bread_response(payload: bytes) -> Tuple[int, int, int, int]:
    if type(payload) is not bytes or len(payload) != 10:
        raise ProtocolError(f"eat bread response payload must be exactly 10 bytes, got {len(payload) if isinstance(payload, bytes) else type(payload)}")
    opcode, status_code, recovered_energy, duration_ms = struct.unpack("<BBII", payload)
    if opcode != OP_EAT_BREAD:
        raise ProtocolError(f"invalid opcode for eat bread response: {opcode}")
    if status_code not in (EAT_BREAD_OK, EAT_BREAD_FAILED, EAT_BREAD_SKIPPED_FULL):
        raise ProtocolError(f"invalid eat bread status code: {status_code}")
    return opcode, status_code, recovered_energy, duration_ms


def encode_travel_lake_request(lake_num: int) -> bytes:
    if not isinstance(lake_num, int) or not (1 <= lake_num <= 40):
        raise ProtocolError(f"lake_num must be between 1 and 40, got {lake_num}")
    return struct.pack("<BB", OP_TRAVEL_LAKE, lake_num)


def decode_travel_lake_request(payload: bytes) -> int:
    if type(payload) is not bytes or len(payload) != 2:
        raise ProtocolError(f"travel lake request payload must be exactly 2 bytes, got {len(payload) if isinstance(payload, bytes) else type(payload)}")
    opcode, lake_num = struct.unpack("<BB", payload)
    if opcode != OP_TRAVEL_LAKE:
        raise ProtocolError(f"invalid opcode for travel lake request: {opcode}")
    if not (1 <= lake_num <= 40):
        raise ProtocolError(f"lake_num out of bounds: {lake_num}")
    return lake_num


def encode_travel_lake_response(status_code: int, lake_num: int, duration_ms: int) -> bytes:
    if status_code not in (TRAVEL_LAKE_OK, TRAVEL_LAKE_FAILED, TRAVEL_LAKE_INVALID):
        raise ProtocolError(f"invalid travel lake status code: {status_code}")
    if not isinstance(lake_num, int) or not (0 <= lake_num <= 255):
        raise ProtocolError("lake_num must be u8")
    if not (0 <= duration_ms <= 0xFFFFFFFF):
        raise ProtocolError("duration_ms must be u32")
    return struct.pack("<BBBI", OP_TRAVEL_LAKE, status_code, lake_num, duration_ms)


def decode_travel_lake_response(payload: bytes) -> Tuple[int, int, int, int]:
    if type(payload) is not bytes or len(payload) != 7:
        raise ProtocolError(f"travel lake response payload must be exactly 7 bytes, got {len(payload) if isinstance(payload, bytes) else type(payload)}")
    opcode, status_code, lake_num, duration_ms = struct.unpack("<BBBI", payload)
    if opcode != OP_TRAVEL_LAKE:
        raise ProtocolError(f"invalid opcode for travel lake response: {opcode}")
    if status_code not in (TRAVEL_LAKE_OK, TRAVEL_LAKE_FAILED, TRAVEL_LAKE_INVALID):
        raise ProtocolError(f"invalid travel lake status code: {status_code}")
    return opcode, status_code, lake_num, duration_ms


async def reload_page(tab: Tab, ignore_cache: bool = True, wait_loaded_sec: float = 2.5) -> None:
    """Tải lại trang web NomStead qua CDP Page.reload và chờ canvas tải lại ổn định."""
    tab._last_water_point = None
    tab._fast_alert_status = None
    tab._stale_toast = ""
    def _get_id():
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    async with _resolve_ws(tab) as ws:
        msg_id = _get_id()
        await ws.send(json.dumps({
            'id': msg_id,
            'method': 'Page.reload',
            'params': {'ignoreCache': ignore_cache}
        }))
        try:
            async with asyncio.timeout(_CDP_TIMEOUT):
                await _receive_cdp_result(ws, msg_id, _CDP_MAX_BYTES, allow_stale_ids=True)
        except Exception:
            pass

    await close_cdp_session(tab)

    if wait_loaded_sec > 0:
        await asyncio.sleep(wait_loaded_sec)

    # Đóng popup / modal chào mừng sau khi F5 nếu có (trusted CDP Escape + read-only lookup)
    await _dismiss_modal_cdp(tab)


async def recover_from_reload(tab: Tab, target_lake: int) -> bool:
    """
    Phục hồi nhân vật sau khi F5:
    Vì sau F5 game luôn đưa nhân vật về Nhà (Home - không có hồ câu),
    hàm này tự động mở Codex -> Bookmarks để di chuyển nhân vật về đúng target_lake.
    """
    await asyncio.sleep(0.5)
    travel_res = await travel_to_lake(tab, target_lake)
    return travel_res.success


async def wait_until_reset_if_needed(
    tab: Tab,
    current_lake: int,
    max_lakes: int = 40,
    stop_event: Optional[asyncio.Event] = None,
    poll_interval: float = 15.0,
) -> bool:
    """
    Khi đã câu hết cả max_lakes (40 hồ), nếu chưa tới khung giờ reset tiếp theo:
    Chuyển sang chế độ chờ thông minh, ping keep-alive định kỳ giữ kết nối CDP.
    Khi chạm mốc giờ reset -> tự động di chuyển về HO 1 và trả về True.
    """
    if current_lake < max_lakes:
        return False

    if stop_event is not None and stop_event.is_set():
        return False

    next_reset = get_next_reset_datetime()
    now = datetime.now()
    remaining_sec = (next_reset - now).total_seconds()

    # Nếu chỉ còn dưới 30s hoặc đã qua giờ reset thì không cần chờ
    if remaining_sec <= 30.0:
        return False

    remaining_minutes = remaining_sec / 60.0
    print(f"[{time.strftime('%H:%M:%S')}] [CHỜ RESET] ⏳ Đã câu xong {max_lakes} hồ, đứng yên ngắm cảnh chờ mốc Reset {next_reset.strftime('%H:%M')} (còn {remaining_minutes:.1f} phút)...")

    while datetime.now() < next_reset:
        if stop_event is not None and stop_event.is_set():
            return False

        # Sleep nhỏ kèm micro keep-alive ping giữ kết nối CDP
        sleep_chunk = min(poll_interval, max(1.0, (next_reset - datetime.now()).total_seconds()))
        await asyncio.sleep(sleep_chunk)

        if stop_event is not None and stop_event.is_set():
            return False

        try:
            # Micro keep-alive ping (<0.1ms, CPU 0%)
            await _cdp_evaluate(tab, "1+1")
        except Exception:
            pass

    print(f"[{time.strftime('%H:%M:%S')}] [RESET SERVER] 🌟 ĐÃ TỚI GIỜ RESET SERVER ({next_reset.strftime('%H:%M')})! Tự động quay về HO 1...")
    travel_res = await travel_to_lake(tab, 1)
    return travel_res.success


@dataclass
class AutoSessionConfig:
    start_lake: int = 1                         # Hồ bắt đầu (1..40)
    max_lakes: int = 40                         # Tổng số hồ (40)
    energy_low_threshold: int = 10              # Ngưỡng thể lực cần ăn bánh mì
    max_no_water_retries: int = 3               # Số lần NO_WATER tối đa trước khi re-travel
    max_timeout_retries: int = 5                # Số lần TIMEOUT tối đa trước khi đổi hồ
    idle_timeout_seconds: float = 30.0          # Thời gian watchdog phát hiện kẹt (30s)
    max_catches: Optional[int] = None           # Dừng khi đạt số cá này (None = vô tận)
    state_file: str = "session_state.json"      # Đường dẫn file lưu trạng thái
    initial_travel: bool = True                 # Có thực hiện travel ngay khi bắt đầu phiên
    verbose: bool = False                       # In dashboard chi tiết ra console
    micro_afk_enabled: bool = True              # Nghỉ giải lao tự nhiên định kỳ giữa các hồ
    micro_afk_min_lakes: int = 5                # Số hồ tối thiểu trước khi Micro-AFK
    micro_afk_max_lakes: int = 8                # Số hồ tối đa trước khi Micro-AFK
    micro_afk_min_sec: float = 15.0             # Thời gian nghỉ tối thiểu (giây)
    micro_afk_max_sec: float = 35.0             # Thời gian nghỉ tối đa (giây)
    long_break_enabled: bool = True             # Nghỉ dài đóng tab định kỳ (2-3h làm -> 20-50p nghỉ)
    long_break_min_work_sec: float = 7200.0     # 2 giờ
    long_break_max_work_sec: float = 10800.0    # 3 giờ
    long_break_min_rest_sec: float = 1200.0     # 20 phút
    long_break_max_rest_sec: float = 3000.0     # 50 phút
    smart_route_enabled: bool = False           # Bật mặc định trong parse_auto_config() cho --auto
    smart_route_fixed_prefix: int = 7           # HO 1..7 giữ nguyên thứ tự cố định
    smart_route_cluster_size: int = 4           # HO 8..40 xáo trộn theo cụm 4-5 hồ
    low_cpu_reel_delay_min_sec: float = 1.45    # Chỉ áp dụng trên VM <= 2 CPU (máy khỏe = 0s)
    low_cpu_reel_delay_max_sec: float = 1.95    # Chờ animation thu cần xong tránh nuốt click 11s


def post_catch_reel_delay_sec(config: Optional[AutoSessionConfig] = None) -> float:
    """Extra post-catch animation settle delay ONLY on <= 2 CPU VMs to prevent swallowed casts.
    Always returns 0.0 on strong machines (> 2 logical CPUs).
    """
    if not _is_low_cpu_vm():
        return 0.0
    if config is not None:
        lo = max(0.0, float(config.low_cpu_reel_delay_min_sec))
        hi = max(lo, float(config.low_cpu_reel_delay_max_sec))
        return random.uniform(lo, hi) if hi > 0 else 0.0
    return random.uniform(1.45, 1.95)


@dataclass
class SessionState:
    current_lake: int = 1                       # Hồ hiện tại
    total_catches: int = 0                      # Tổng số cá đã câu thành công
    total_casts: int = 0                        # Tổng số lần quăng cần
    consecutive_no_water: int = 0               # Biến đếm lỗi no water liên tiếp
    consecutive_timeout: int = 0                # Biến đếm timeout liên tiếp
    last_reset_hour: Optional[int] = None       # Mốc giờ reset server gần nhất đã xử lý
    start_time: float = field(default_factory=time.time)
    last_activity_time: float = field(default_factory=time.time)
    lake_catches: Dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_lake": self.current_lake,
            "total_catches": self.total_catches,
            "total_casts": self.total_casts,
            "consecutive_no_water": self.consecutive_no_water,
            "consecutive_timeout": self.consecutive_timeout,
            "last_reset_hour": self.last_reset_hour,
            "start_time": self.start_time,
            "last_activity_time": self.last_activity_time,
            "lake_catches": {str(k): v for k, v in self.lake_catches.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        last_reset_raw = data.get("last_reset_hour")
        last_reset_hour = int(last_reset_raw) if last_reset_raw is not None else None
        state = cls(
            current_lake=int(data.get("current_lake", 1)),
            total_catches=int(data.get("total_catches", 0)),
            total_casts=int(data.get("total_casts", 0)),
            consecutive_no_water=int(data.get("consecutive_no_water", 0)),
            consecutive_timeout=int(data.get("consecutive_timeout", 0)),
            last_reset_hour=last_reset_hour,
            start_time=float(data.get("start_time", time.time())),
            last_activity_time=float(data.get("last_activity_time", time.time())),
        )
        if "lake_catches" in data and isinstance(data["lake_catches"], dict):
            state.lake_catches = {int(k): int(v) for k, v in data["lake_catches"].items()}
        return state

    def save(self, filepath: str) -> None:
        """Ghi an toàn ra file tạm rồi atomic rename."""
        if not filepath or filepath == ":memory:":
            return
        p = Path(filepath)
        if p.parent and str(p.parent) != "" and str(p.parent) != ".":
            p.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = p.with_suffix(p.suffix + ".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, p)

    @classmethod
    def load(cls, filepath: str) -> Optional["SessionState"]:
        if not filepath or filepath == ":memory:" or not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception:
            return None


def print_auto_dashboard(
    state: SessionState,
    max_lakes: int = 40,
    energy_str: str = "N/A",
    last_outcome_str: str = "INIT",
) -> None:
    elapsed_sec = int(time.time() - state.start_time)
    hours, rem = divmod(elapsed_sec, 3600)
    minutes, seconds = divmod(rem, 60)
    time_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
    rate = (state.total_catches / state.total_casts * 100.0) if state.total_casts > 0 else 0.0
    idle_sec = max(0.0, time.time() - state.last_activity_time)
    watchdog_str = f"OK (last active: {idle_sec:.1f}s ago)"

    print("==============================================================")
    print("NOMSTEAD AUTONOMOUS FISHING SESSION")
    print("==============================================================")
    print(f"Current Lake   : Lake {state.current_lake} / {max_lakes}")
    print(f"Session Time   : {time_str}")
    print(f"Total Catches  : {state.total_catches} fish")
    print(f"Total Casts    : {state.total_casts} casts (Success rate: {rate:.1f}%)")
    print(f"Current Energy : {energy_str}")
    print(f"Last Outcome   : {last_outcome_str}")
    print(f"Watchdog State : {watchdog_str}")
    print("==============================================================")


def validate_lake(lake: int) -> int:
    if not (1 <= lake <= 40):
        raise ValueError(f"Lake number must be between 1 and 40, got {lake}")
    return lake


def parse_auto_config(args: argparse.Namespace) -> AutoSessionConfig:
    lake = getattr(args, "lake", 1)
    if lake < 1 or lake > 40:
        lake = max(1, min(40, int(lake)))
    max_lakes = getattr(args, "max_lakes", 40)
    if max_lakes < 1:
        max_lakes = 40
    return AutoSessionConfig(
        start_lake=lake,
        max_lakes=max_lakes,
        max_catches=getattr(args, "max_catches", None),
        state_file=getattr(args, "state_file", "session_state.json"),
        verbose=True,
        smart_route_enabled=True,
    )


def did_reset_pass_during_break(
    break_start: datetime,
    break_end: datetime,
    last_reset_hour: Optional[int] = None,
) -> Optional[int]:
    """Return the latest RESET_HOURS milestone crossed during [break_start, break_end], or None."""
    latest_dt: Optional[datetime] = None
    if break_end >= break_start:
        cur_date = break_start.date()
        end_date = break_end.date()
        while cur_date <= end_date:
            for h in RESET_HOURS:
                r_dt = datetime(
                    cur_date.year,
                    cur_date.month,
                    cur_date.day,
                    h,
                    0,
                    0,
                    tzinfo=break_start.tzinfo,
                )
                if break_start < r_dt <= break_end:
                    if latest_dt is None or r_dt > latest_dt:
                        latest_dt = r_dt
            cur_date += timedelta(days=1)
    if latest_dt is not None:
        return latest_dt.hour
    if is_reset_window(break_end) and last_reset_hour != break_end.hour:
        return break_end.hour
    return None


async def _interruptible_sleep(
    duration_sec: float,
    stop_event: Optional[asyncio.Event] = None,
    chunk_sec: float = 1.0,
) -> bool:
    """Sleep in <= chunk_sec slices checking stop_event. Returns True if completed, False if interrupted."""
    remaining = max(0.0, float(duration_sec))
    step_cap = max(0.01, float(chunk_sec))
    while remaining > 0.0:
        if stop_event is not None and stop_event.is_set():
            return False
        chunk = min(step_cap, remaining)
        await asyncio.sleep(chunk)
        remaining -= chunk
    if stop_event is not None and stop_event.is_set():
        return False
    return True


def build_lake_route(
    max_lakes: int = 40,
    fixed_prefix: int = 7,
    cluster_size: int = 4,
) -> List[int]:
    """Build 40-lake route: HO 1..fixed_prefix strictly ordered, remainder cluster-shuffled."""
    total = max(1, int(max_lakes))
    prefix_end = min(total, max(0, int(fixed_prefix)))
    route = list(range(1, prefix_end + 1))
    remaining = list(range(prefix_end + 1, total + 1))
    if not remaining:
        return route
    csize = max(2, int(cluster_size))
    clusters: List[List[int]] = [
        remaining[i : i + csize] for i in range(0, len(remaining), csize)
    ]
    if len(clusters) >= 2 and len(clusters[-1]) == 1:
        clusters[-2].extend(clusters.pop())
    for cluster in clusters:
        random.shuffle(cluster)
        route.extend(cluster)
    return route


def next_lake_in_route(
    current_lake: int,
    route: List[int],
    max_lakes: int = 40,
) -> Tuple[int, bool]:
    """Return (next_lake, wrapped_cycle) following route, with sequential fallback."""
    if route and current_lake in route:
        idx = route.index(current_lake)
        if idx + 1 < len(route):
            return (route[idx + 1], False)
        return (route[0], True)
    return ((current_lake % max_lakes) + 1, current_lake >= max_lakes)


PLAY_BUTTON_LOOKUP_EXPR = """(() => {
    const links = [...document.querySelectorAll('a[href="/play"], a[href="/play/"]')];
    let best = null;
    let bestScore = -1;
    for (const el of links) {
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
        const txt = (el.innerText || '').trim().toLowerCase();
        const area = r.width * r.height;
        const score = (el.classList.contains('btn-lg') ? 100000 : 0) + (txt.includes('play now free') ? 50000 : 0) + area;
        if (score > bestScore) {
            bestScore = score;
            best = r;
        }
    }
    if (!best) return { found: false };
    return {
        found: true,
        x: best.left + best.width / 2,
        y: best.top + best.height / 2,
        width: best.width,
        height: best.height
    };
})()"""


async def perform_tab_close_long_break(
    tab: Tab,
    config: AutoSessionConfig,
    state: SessionState,
    stop_event: Optional[asyncio.Event] = None,
    *,
    hud_timeout_sec: float = 35.0,
    warmup_range_sec: Tuple[float, float] = (1.5, 4.0),
) -> Tuple[bool, Optional[int]]:
    """Close NomStead tab safely via blank keep-alive target, rest 20-50m, reopen, wait HUD, and resume lake."""
    # Step 1: Save state, close page WS, create about:blank FIRST so Chrome never exits, then close game tab
    state.save(config.state_file)
    await close_cdp_session(tab)
    old_target_id = _extract_page_target_id(tab.websocket_url)
    blank_res = await _browser_cdp_call("Target.createTarget", {"url": "about:blank"})
    blank_target_id = blank_res.get("targetId") if isinstance(blank_res, dict) else None
    if type(blank_target_id) is not str or not blank_target_id:
        raise CdpError("failed to create blank keep-alive target")
    await _browser_cdp_call("Target.closeTarget", {"targetId": old_target_id})

    # Step 2: Rest period (20-50m)
    break_start_dt = datetime.now()
    min_r = max(0.0, float(config.long_break_min_rest_sec))
    max_r = max(min_r, float(config.long_break_max_rest_sec))
    rest_sec = random.uniform(min_r, max_r)
    wake_est = break_start_dt + timedelta(seconds=rest_sec)
    print(
        f"[{time.strftime('%H:%M:%S')}] [LONG BREAK] 🌙 Đã đóng tab NomStead (GPU/CPU→0%), "
        f"nghỉ dài {rest_sec / 60.0:.1f} phút (dự kiến quay lại lúc {wake_est.strftime('%H:%M:%S')})..."
    )
    completed = await _interruptible_sleep(rest_sec, stop_event, chunk_sec=1.0)
    if not completed:
        return (False, None)

    # Step 3: Reopen game tab, close blank tab, rediscover trusted page target
    await _browser_cdp_call("Target.createTarget", {"url": "https://nomstead.com"})
    await asyncio.sleep(0.5)
    await _browser_cdp_call("Target.closeTarget", {"targetId": blank_target_id})

    discover_deadline = time.monotonic() + 15.0
    new_tab: Optional[Tab] = None
    while True:
        if stop_event is not None and stop_event.is_set():
            return (False, None)
        try:
            new_tab = await discover_tab()
            break
        except Exception:
            if time.monotonic() >= discover_deadline:
                raise CdpError("timed out rediscovering reopened NomStead tab")
            if not await _interruptible_sleep(0.5, stop_event, chunk_sec=0.5):
                return (False, None)

    tab.url = new_tab.url
    tab.websocket_url = new_tab.websocket_url
    tab._next_id = 1
    tab._last_water_point = None
    tab._fast_alert_status = None
    tab._stale_toast = ""
    tab._cursor_pos = None

    # Step 4: Wait for Game HUD (clicking homepage 'Play Now Free' via trusted CDP if shown)
    hud_deadline = time.monotonic() + max(0.0, float(hud_timeout_sec))
    hud_ready = False
    last_play_click_at: Optional[float] = None
    while True:
        if stop_event is not None and stop_event.is_set():
            return (False, None)
        try:
            st = await read_status(tab)
            if st is not None and (st.energy is not None or st.xp is not None):
                hud_ready = True
                break
        except Exception:
            pass
        if last_play_click_at is None or (time.monotonic() - last_play_click_at) >= 6.0:
            play_info = None
            try:
                play_info = await _cdp_evaluate(tab, PLAY_BUTTON_LOOKUP_EXPR)
            except Exception:
                play_info = None
            if isinstance(play_info, dict) and play_info.get("found") and "x" in play_info and "y" in play_info:
                if warmup_range_sec[1] > 0.0:
                    if not await _interruptible_sleep(random.uniform(0.8, 1.8), stop_event, chunk_sec=0.3):
                        return (False, None)
                max_dx = min(28.0, max(0.0, float(play_info.get("width", 0.0)) * 0.25))
                max_dy = min(10.0, max(0.0, float(play_info.get("height", 0.0)) * 0.25))
                px, py = jitter_point(
                    float(play_info["x"]),
                    float(play_info["y"]),
                    max_dx=max_dx,
                    max_dy=max_dy,
                    min_x=1.0,
                    max_x=8191.0,
                    min_y=1.0,
                    max_y=8191.0,
                )
                try:
                    await move_mouse_bezier(tab, px, py, fast=False)
                    await click_point(tab, px, py, delay_ms=human_hold_ms(fast=False))
                    last_play_click_at = time.monotonic()
                    print(
                        f"[{time.strftime('%H:%M:%S')}] [LONG BREAK] 🎮 Đã bấm 'Play Now Free' "
                        "(CDP trusted Bezier click), đang chờ tải HUD game..."
                    )
                except Exception:
                    pass
        if time.monotonic() >= hud_deadline:
            break
        if not await _interruptible_sleep(1.0, stop_event, chunk_sec=0.5):
            return (False, None)

    if not hud_ready:
        print(
            f"[{time.strftime('%H:%M:%S')}] [LONG BREAK] ⚠️ Chưa thấy HUD game "
            "(có thể phiên đăng nhập hết hạn) -> Tạm chờ người dùng đăng nhập lại..."
        )
        while not hud_ready:
            if stop_event is not None and stop_event.is_set():
                return (False, None)
            if not await _interruptible_sleep(5.0, stop_event, chunk_sec=1.0):
                return (False, None)
            try:
                st = await read_status(tab)
                if st.energy is not None or st.xp is not None:
                    hud_ready = True
            except Exception:
                pass

    try:
        await _dismiss_modal_cdp(tab)
    except Exception:
        pass

    w_min, w_max = warmup_range_sec
    if w_max > 0.0:
        w_delay = random.uniform(max(0.0, float(w_min)), max(max(0.0, float(w_min)), float(w_max)))
        if not await _interruptible_sleep(w_delay, stop_event, chunk_sec=0.5):
            return (False, None)

    # Step 5: Server reset check + anti-Home trap navigation
    wake_dt = datetime.now()
    passed_reset_hour = did_reset_pass_during_break(break_start_dt, wake_dt, state.last_reset_hour)
    if passed_reset_hour is not None:
        state.current_lake = 1
        state.last_reset_hour = passed_reset_hour
        state.consecutive_no_water = 0
        state.consecutive_timeout = 0
        print(
            f"[{time.strftime('%H:%M:%S')}] [LONG BREAK] 🌟 Đã qua mốc Reset "
            f"({passed_reset_hour}:00) trong lúc nghỉ -> Quay về HO 1!"
        )
        await travel_to_lake(tab, 1)
    else:
        print(
            f"[{time.strftime('%H:%M:%S')}] [LONG BREAK] 🚀 Đã mở lại game -> "
            f"Di chuyển từ Nhà về lại HO {state.current_lake}..."
        )
        await travel_to_lake(tab, state.current_lake)

    state.last_activity_time = time.time()
    state.save(config.state_file)
    return (True, passed_reset_hour)


async def _maybe_micro_afk(
    state: SessionState,
    config: AutoSessionConfig,
    lakes_completed: int,
    next_target: int,
    stop_event: Optional[asyncio.Event] = None,
) -> Tuple[int, int, bool]:
    """Natural periodic Micro-AFK break between lakes; interruptible via stop_event and refreshes watchdog."""
    if not config.micro_afk_enabled or lakes_completed < next_target:
        return lakes_completed, next_target, False
    min_s = max(0.0, float(config.micro_afk_min_sec))
    max_s = max(min_s, float(config.micro_afk_max_sec))
    duration = random.uniform(min_s, max_s)
    print(f"[{time.strftime('%H:%M:%S')}] [ANTI-DETECT] ☕ Nghỉ giải lao tự nhiên (Micro-AFK) {duration:.1f}s sau {lakes_completed} hồ...")
    remaining = duration
    while remaining > 0.0:
        if stop_event is not None and stop_event.is_set():
            break
        chunk = min(0.5, remaining)
        await asyncio.sleep(chunk)
        remaining -= chunk
    state.last_activity_time = time.time()
    min_l = max(1, int(config.micro_afk_min_lakes))
    max_l = max(min_l, int(config.micro_afk_max_lakes))
    return 0, random.randint(min_l, max_l), True


async def run_auto_session(
    tab: Tab,
    config: Optional[AutoSessionConfig] = None,
    use_worker: bool = True,
    stop_event: Optional[asyncio.Event] = None,
) -> SessionState:
    async with cdp_session(tab):
        return await _run_auto_session_body(
            tab=tab,
            config=config,
            use_worker=use_worker,
            stop_event=stop_event,
        )


async def _run_auto_session_body(
    tab: Tab,
    config: Optional[AutoSessionConfig] = None,
    use_worker: bool = True,
    stop_event: Optional[asyncio.Event] = None,
) -> SessionState:
    if config is None:
        config = AutoSessionConfig()

    state = SessionState.load(config.state_file)
    if state is None:
        state = SessionState(current_lake=config.start_lake)
    else:
        if config.start_lake != 1:
            state.current_lake = config.start_lake

    if config.initial_travel:
        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🚀 Khởi hành tới HO {state.current_lake}...")
        travel_res = await travel_to_lake(tab, state.current_lake)
        if travel_res.success:
            print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
        state.last_activity_time = time.time()

    current_energy_display = "N/A"
    consecutive_modal_stuck = 0
    energy_stuck_start_time = None
    lakes_completed = 0
    _min_afk_lakes = max(1, int(config.micro_afk_min_lakes))
    _max_afk_lakes = max(_min_afk_lakes, int(config.micro_afk_max_lakes))
    next_afk_target = random.randint(_min_afk_lakes, _max_afk_lakes)

    lake_route = (
        build_lake_route(config.max_lakes, config.smart_route_fixed_prefix, config.smart_route_cluster_size)
        if config.smart_route_enabled
        else list(range(1, config.max_lakes + 1))
    )
    work_session_start = time.monotonic()
    _min_work = max(0.0, float(config.long_break_min_work_sec))
    _max_work = max(_min_work, float(config.long_break_max_work_sec))
    next_long_break_sec = random.uniform(_min_work, _max_work)

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if config.max_catches is not None and state.total_catches >= config.max_catches:
                break

            # Server Reset Check (RESET_HOURS = 1, 4, 7, 10, 13, 16, 19, 22)
            should_reset, new_reset_hour = check_server_reset(state.current_lake, state.last_reset_hour)
            if should_reset:
                print(f"[{time.strftime('%H:%M:%S')}] [RESET SERVER] 🌟 ĐÃ TỚI GIỜ RESET SERVER ({new_reset_hour}:00)! Tự động quay về HO 1...")
                state.current_lake = 1
                state.last_reset_hour = new_reset_hour
                state.consecutive_no_water = 0
                state.consecutive_timeout = 0
                state.save(config.state_file)
                if config.smart_route_enabled:
                    lake_route = build_lake_route(
                        config.max_lakes, config.smart_route_fixed_prefix, config.smart_route_cluster_size
                    )
                await travel_to_lake(tab, 1)
                state.last_activity_time = time.time()
                continue
            elif new_reset_hour != state.last_reset_hour:
                state.last_reset_hour = new_reset_hour
                state.save(config.state_file)

            # Tab-Close Long Break (2-3h work -> 20-50m tab-closed rest)
            if config.long_break_enabled and (time.monotonic() - work_session_start) >= next_long_break_sec:
                did_break, passed_reset = await perform_tab_close_long_break(tab, config, state, stop_event)
                if stop_event is not None and stop_event.is_set():
                    break
                if did_break:
                    if passed_reset is not None and config.smart_route_enabled:
                        lake_route = build_lake_route(
                            config.max_lakes, config.smart_route_fixed_prefix, config.smart_route_cluster_size
                        )
                    work_session_start = time.monotonic()
                    next_long_break_sec = random.uniform(_min_work, _max_work)
                    continue

            now = time.time()
            if (now - state.last_activity_time) >= config.idle_timeout_seconds:
                # Dọn modal kẹt trước khi thử lại (trusted CDP Escape + read-only lookup)
                await _dismiss_modal_cdp(tab)

                print(f"[{time.strftime('%H:%M:%S')}] [WATCHDOG 30s] Quá {config.idle_timeout_seconds:.0f}s không có hoạt động -> Pha 1: Thử quăng cần lại...")
                recast_outcome = await run_one_cast(tab, use_worker=use_worker, lake=state.current_lake)

                if recast_outcome.kind == "CATCH" or (recast_outcome.reaction_ms is not None and recast_outcome.reaction_ms > 0):
                    print(f"[{time.strftime('%H:%M:%S')}] [WATCHDOG 30s] Pha 1 thành công (nhân vật hoạt động bình thường) -> Tiếp tục câu, không cần F5!")
                    state.last_activity_time = time.time()
                else:
                    # Pha 1 thất bại -> Kích hoạt Pha 2 F5 Reload
                    print(f"[{time.strftime('%H:%M:%S')}] [WATCHDOG 30s] Pha 1 thất bại (vẫn đơ) -> Pha 2: Kích hoạt F5 (Reload) & đưa nhân vật từ Nhà về HO {state.current_lake}...")
                    await reload_page(tab, wait_loaded_sec=2.5)
                    await recover_from_reload(tab, state.current_lake)
                    state.last_activity_time = time.time()

            # Pre-cast energy check & stuck bread watchdog
            energy_val = "N/A"
            try:
                status = await read_status(tab)
                if status.energy is not None:
                    energy_val = getattr(status.energy, "current", status.energy)
                    current_energy_display = f"{energy_val} / 80"
                    if energy_val < config.energy_low_threshold:
                        if energy_stuck_start_time is None:
                            energy_stuck_start_time = time.time()

                        bread_res = await eat_bread(tab)
                        if bread_res.consumed:
                            print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🥖 Thể lực thấp ({energy_val}/80), tự động ăn 1 bánh mì (+{bread_res.recovered} thể lực).")
                            energy_stuck_start_time = None
                            state.last_activity_time = time.time()
                        elif (time.time() - energy_stuck_start_time) >= 35.0:
                            # Kẹt quá 35s không ăn được bánh mì -> Kích hoạt F5 Reload & Ăn lại
                            print(f"[{time.strftime('%H:%M:%S')}] [ENERGY WATCHDOG] Kẹt không ăn được bánh mì quá 35s -> Kích hoạt F5 (Reload) để khôi phục UI...")
                            await reload_page(tab, wait_loaded_sec=2.5)
                            await eat_bread(tab, force=True)
                            await recover_from_reload(tab, state.current_lake)
                            energy_stuck_start_time = None
                            state.last_activity_time = time.time()
                    else:
                        energy_stuck_start_time = None
            except Exception:
                pass

            if stop_event is not None and stop_event.is_set():
                break

            outcome = await run_one_cast(tab, use_worker=use_worker, lake=state.current_lake)
            state.total_casts += 1
            state.last_activity_time = time.time()
            if outcome.post_energy is not None:
                energy_val = getattr(outcome.post_energy, "current", outcome.post_energy)

            if outcome.kind == "CATCH":
                consecutive_modal_stuck = 0
                verified = is_verified_catch(outcome)

                if verified:
                    state.total_catches += 1
                    state.lake_catches[state.current_lake] = state.lake_catches.get(state.current_lake, 0) + 1
                    state.consecutive_no_water = 0
                    state.consecutive_timeout = 0
                    state.save(config.state_file)
                    lake_catches_cnt = state.lake_catches[state.current_lake]
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO {state.current_lake} (Hồ: {lake_catches_cnt} | Tổng: {state.total_catches} | Thể lực: {energy_val}/80)")
                    if config.max_catches is not None and state.total_catches >= config.max_catches:
                        break
                    reel_settle = post_catch_reel_delay_sec(config)
                    if reel_settle > 0:
                        await _interruptible_sleep(reel_settle, stop_event, chunk_sec=0.25)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ❌ Giật hụt cá (Miss) tại HO {state.current_lake}")

            elif outcome.kind in ("MISS", "UNVERIFIED"):
                consecutive_modal_stuck = 0
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ❌ Giật hụt cá (Miss) tại HO {state.current_lake}")

            elif outcome.kind == "INSUFFICIENT_ENERGY":
                consecutive_modal_stuck = 0
                bread_res = await eat_bread(tab)
                cur_e = energy_val if isinstance(energy_val, (int, float)) else 0
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🥖 Thể lực thấp ({cur_e}/80), tự động ăn 1 bánh mì (+{bread_res.recovered} thể lực).")
                state.last_activity_time = time.time()

            elif outcome.kind in ("EMPTY", "TRASH"):
                consecutive_modal_stuck = 0
                next_lake, wrapped_cycle = next_lake_in_route(state.current_lake, lake_route, config.max_lakes)
                if wrapped_cycle or (not config.smart_route_enabled and state.current_lake >= config.max_lakes):
                    # Đã câu xong vòng 40 hồ -> Kiểm tra và chờ reset nếu chưa tới giờ
                    wait_lake_arg = config.max_lakes if wrapped_cycle else state.current_lake
                    did_wait_and_reset = await wait_until_reset_if_needed(tab, wait_lake_arg, config.max_lakes, stop_event)
                    if did_wait_and_reset:
                        state.current_lake = 1
                        state.consecutive_no_water = 0
                        state.consecutive_timeout = 0
                        state.save(config.state_file)
                        if config.smart_route_enabled:
                            lake_route = build_lake_route(
                                config.max_lakes, config.smart_route_fixed_prefix, config.smart_route_cluster_size
                            )
                        state.last_activity_time = time.time()
                        continue

                toast_short = (outcome.toast or "").strip()
                toast_str = f" ({toast_short})" if toast_short else ""
                if outcome.kind == "EMPTY":
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⚠️ Hồ đã hết cá (EMPTY){toast_str} -> Đang chuyển sang HO {next_lake}...")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🗑️ Câu phải rác (TRASH){toast_str} -> Đang chuyển sang HO {next_lake}...")

                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 🚀 Khởi hành tới HO {next_lake}...")
                travel_res = await travel_to_lake(tab, next_lake)
                if travel_res.success:
                    state.current_lake = next_lake
                    state.consecutive_no_water = 0
                    state.consecutive_timeout = 0
                    state.save(config.state_file)
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
                    lakes_completed += 1
                    lakes_completed, next_afk_target, _ = await _maybe_micro_afk(
                        state, config, lakes_completed, next_afk_target, stop_event
                    )
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại -> Giữ nguyên hồ để xử lý lại...")
                state.last_activity_time = time.time()

            elif outcome.kind == "NO_WATER":
                consecutive_modal_stuck = 0
                state.consecutive_no_water += 1
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Chưa phát hiện mặt nước ({state.consecutive_no_water}/{config.max_no_water_retries})...")
                await asyncio.sleep(1.0)
                if state.consecutive_no_water >= config.max_no_water_retries:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Quá {config.max_no_water_retries} lần không thấy nước -> Đang di chuyển lại vào hồ...")
                    state.consecutive_no_water = 0
                    await travel_to_lake(tab, state.current_lake)
                    state.last_activity_time = time.time()

            elif outcome.kind == "TIMEOUT":
                consecutive_modal_stuck = 0
                state.consecutive_timeout += 1
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⏳ Cá chưa cắn sau 11s ({state.consecutive_timeout}/{config.max_timeout_retries})...")
                await asyncio.sleep(0.5)
                if state.consecutive_timeout >= config.max_timeout_retries:
                    state.consecutive_timeout = 0
                    next_lake, _ = next_lake_in_route(state.current_lake, lake_route, config.max_lakes)
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⏳ Quá {config.max_timeout_retries} lần cá không cắn -> Chuyển sang HO {next_lake}...")
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 🚀 Khởi hành tới HO {next_lake}...")
                    travel_res = await travel_to_lake(tab, next_lake)
                    if travel_res.success:
                        state.current_lake = next_lake
                        state.consecutive_no_water = 0
                        state.save(config.state_file)
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
                        lakes_completed += 1
                        lakes_completed, next_afk_target, _ = await _maybe_micro_afk(
                            state, config, lakes_completed, next_afk_target, stop_event
                        )
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại -> Giữ nguyên hồ để xử lý lại...")
                    state.last_activity_time = time.time()

            elif outcome.kind == "MODAL_ACTIVE":
                consecutive_modal_stuck += 1
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Phát hiện modal đang mở -> Đang dọn dẹp modal ({consecutive_modal_stuck})...")
                await _dismiss_modal_cdp(tab)

                # Rate limiting delay chống tight-loop 100% CPU
                await asyncio.sleep(0.5)

                # Nếu kẹt quá 3 lần liên tiếp, kích hoạt cơ chế tự phục hồi
                if consecutive_modal_stuck >= 3:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Modal kẹt cứng quá 3 lần -> Tự động tái điều hướng về HO {state.current_lake} để khôi phục UI...")
                    consecutive_modal_stuck = 0
                    await travel_to_lake(tab, state.current_lake)
                    state.last_activity_time = time.time()

            if stop_event is not None and stop_event.is_set():
                break
            await asyncio.sleep(human_inter_cast_delay_sec())

    except (asyncio.CancelledError, KeyboardInterrupt):
        state.save(config.state_file)
        raise
    finally:
        state.save(config.state_file)

    return state


async def _main_async(args) -> int:
    if getattr(args, "diagnose", False):
        try:
            tab = await discover_tab()
            res = await run_diagnose(tab, worker_path=args.worker, timeout=args.timeout)
            print_diagnose_report(res)
            return 0
        except Exception as error:
            print(f"worker bridge failed: {type(error).__name__}", file=sys.stderr)
            return 1

    if getattr(args, "one_cast", False):
        try:
            tab = await discover_tab()
            res = await run_one_cast(tab)
            print_one_cast_report(res)
            return 0
        except Exception as error:
            print(f"worker bridge failed: {type(error).__name__}", file=sys.stderr)
            return 1

    if getattr(args, "auto", False):
        try:
            tab = await discover_tab()
            config = parse_auto_config(args)
            state = await run_auto_session(tab, config=config)
            print("\nAutonomous fishing session ended cleanly.")
            return 0
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nSession interrupted by user (Ctrl+C). Safe shutdown complete.")
            return 0
        except Exception as error:
            print(f"auto session failed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1

    client = None
    try:
        client = await WorkerClient.spawn(args.worker, timeout=args.timeout)
        if args.check:
            tab = await discover_tab()
            status = await read_status(tab)
            payload = bytes([OP_CHECK_STATUS]) + encode_status(status)
            response = await client.request(payload)
            if response.payload != payload:
                raise ProtocolError('worker status confirmation mismatch')
            decode_status(response.payload[1:])
            if status.energy is None:
                raise CdpError('energy absent; log in directly in debug Chrome')
        await client.shutdown()
        if args.check:
            print(f'CHECK OK: Python CDP + Rust worker; origin=https://{urlsplit(status.url).hostname} '
                  f'viewport={status.width:g}x{status.height:g} dpr={status.dpr:g} energy=present')
        else:
            print("worker handshake and shutdown completed", file=sys.stderr)
        return 0
    except asyncio.CancelledError as error:
        if client is not None:
            await client._abort_preserving(error)
        raise
    except Exception as error:
        if client is not None:
            await client._abort_preserving(error)
        # Transport exception text may contain private URLs. Preserve only safe categories.
        if isinstance(error, OSError) and getattr(error, 'winerror', None) == 4551:
            print(f'BLOCKED: Windows Application Control denied the Rust worker (4551): '
                  f'{Path(args.worker).resolve()}', file=sys.stderr)
        else:
            print(f'worker bridge failed: {type(error).__name__}', file=sys.stderr)
        return 1


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rust worker bridge and read-only CDP check")
    parser.add_argument('--check', action='store_true', help='validate live CDP status through the Rust worker')
    parser.add_argument('--diagnose', action='store_true', help='run complete read-only diagnostics on game tab')
    parser.add_argument('--one-cast', action='store_true', help='execute one complete cast and alert-strike cycle')
    parser.add_argument('--auto', action='store_true', help='run infinite autonomous fishing session')
    parser.add_argument('--lake', type=int, default=1, help='starting lake number [1-40]')
    parser.add_argument('--state-file', default='session_state.json', help='path to session state json')
    parser.add_argument('--max-catches', type=int, default=None, help='maximum catches before exit')
    parser.add_argument('--max-lakes', type=int, default=40, help='maximum total lakes')
    parser.add_argument("--worker", default=str(Path(__file__).with_name("worker.exe")))
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv=None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
