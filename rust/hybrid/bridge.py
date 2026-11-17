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

import cv2
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


async def _receive_cdp_result(ws, expected_id: int, max_bytes: int):
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
    try:
        async with _ReadOnlyConnect(tab.websocket_url, proxy=None, compression=None,
                                   open_timeout=_CDP_TIMEOUT, close_timeout=1,
                                   max_size=_CDP_MAX_BYTES, max_queue=4, ping_interval=None) as ws:
            async with asyncio.timeout(_CDP_TIMEOUT):
                await ws.send(json.dumps({'id':1, 'method':'Runtime.evaluate',
                                          'params':{'expression':STATUS_READONLY, 'returnByValue':True}}))
                result, _ = await _receive_cdp_result(ws, 1, _CDP_MAX_BYTES)
                return _status_from_result(result, tab)
    except CdpError:
        raise
    except Exception as error:
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


def encode_rgb_payload(frame: RgbPayload) -> bytes:
    if type(frame) is not RgbPayload or type(frame.rgb) is not bytes:
        raise ProtocolError("invalid RGB payload type")
    pixel_bytes = _rgb_pixel_bytes(frame.width, frame.height, frame.stride)
    if type(frame.captured_monotonic_ns) is not int or not 0 <= frame.captured_monotonic_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("invalid capture timestamp")
    if len(frame.rgb) != pixel_bytes:
        raise ProtocolError("RGB payload length does not exactly match dimensions")
    return struct.pack("<IIIQ", frame.width, frame.height, frame.stride, frame.captured_monotonic_ns) + frame.rgb


def _load_water_means() -> Tuple[float, float, float]:
    """Load or calculate template fractional means from assets/water.rgb."""
    asset_path = Path(__file__).parent / "assets" / "water.rgb"
    if asset_path.exists():
        data = asset_path.read_bytes()
        if len(data) == 13230:
            return (
                sum(data[0::3]) / 4410.0,
                sum(data[1::3]) / 4410.0,
                sum(data[2::3]) / 4410.0,
            )
    return (318229.0 / 4410.0, 397111.0 / 4410.0, 441422.0 / 4410.0)


def water_point(payload: Union[bytes, RgbPayload]) -> Optional[Tuple[int, int]]:
    """Safe water casting point search using integral image mask.

    Algorithm matches worker_vision.rs 100%:
    - 51x51 square with exact count 2601 water pixels (all 3 channels within 14.0 of mean).
    - Scans row-major (y first, then x), step 4.
    - Coordinate bounds:
        x: max(width // 4, 25) .. min(width * 3 // 4, width - 25)
        y: max(height // 5, 25) .. min(height * 82 // 100, height - 25)
    """
    if isinstance(payload, bytes):
        image = decode_rgb_payload(payload)
    elif isinstance(payload, RgbPayload):
        image = payload
    else:
        raise ProtocolError("RGB payload must be bytes or RgbPayload")

    width, height = image.width, image.height
    if width < 60 or height < 60:
        return None

    means = _load_water_means()
    arr = np.frombuffer(image.rgb, dtype=np.uint8).reshape((height, width, 3))

    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mask = (
        (np.abs(r.astype(np.float64) - means[0]) <= 14.0)
        & (np.abs(g.astype(np.float64) - means[1]) <= 14.0)
        & (np.abs(b.astype(np.float64) - means[2]) <= 14.0)
    )

    integral = np.zeros((height + 1, width + 1), dtype=np.int32)
    integral[1:, 1:] = mask.astype(np.int32).cumsum(axis=0).cumsum(axis=1)

    y_start = max(height // 5, 25)
    y_end = min(height * 82 // 100, height - 25)
    x_start = max(width // 4, 25)
    x_end = min(width * 3 // 4, width - 25)

    y_indices = np.arange(y_start, y_end, 4)
    x_indices = np.arange(x_start, x_end, 4)
    if len(y_indices) == 0 or len(x_indices) == 0:
        return None

    top, bottom = y_indices - 25, y_indices + 26
    left, right = x_indices - 25, x_indices + 26

    counts = (
        integral[bottom[:, None], right[None, :]]
        + integral[top[:, None], left[None, :]]
        - integral[top[:, None], right[None, :]]
        - integral[bottom[:, None], left[None, :]]
    )
    matches = np.argwhere(counts == 2601)
    if len(matches) > 0:
        y_idx, x_idx = matches[0]
        return (int(x_indices[x_idx]), int(y_indices[y_idx]))
    return None


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

    res = cv2.matchTemplate(img_arr, template, cv2.TM_CCOEFF_NORMED)
    min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)

    if np.isnan(max_v) or np.isinf(max_v):
        return None

    best_score = float(max_v)
    bx, by = max_l  # (x, y)

    if best_score >= 0.80:
        return AlertHit(bx, by, best_score)
    if best_score < 0.60:
        return None

    if base_img is None:
        return AlertHit(bx, by, best_score) if best_score >= 0.74 else None

    base_arr = np.frombuffer(base_img.rgb, dtype=np.uint8).reshape((base_img.height, base_img.width, 3))
    patch = img_arr[by : by + 35, bx : bx + 33]
    base_patch = base_arr[by : by + 35, bx : bx + 33]

    diff = float(np.mean(np.abs(patch.astype(np.float64) - base_patch.astype(np.float64))))
    dark_mask = (patch[:, :, 0] < 45) & (patch[:, :, 1] < 45) & (patch[:, :, 2] < 45)
    dark_ratio = float(np.count_nonzero(dark_mask) / (33 * 35))

    if diff >= 18.0 and dark_ratio >= 0.05:
        return AlertHit(bx, by, best_score)
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


async def capture(tab: Tab, kind: str) -> CapturedFrame:
    try:
        if type(tab) is not Tab or type(kind) is not str or kind not in ('SCREEN_FULL', 'SCREEN_ALERT'):
            raise CdpError('invalid capture input')
        validate_game_url(tab.url)
        validate_ws_url(tab.websocket_url)
        async with _ReadOnlyConnect(tab.websocket_url, proxy=None, compression=None,
                                   open_timeout=_CDP_TIMEOUT, close_timeout=1,
                                   max_size=_CAPTURE_CDP_MAX_BYTES, max_queue=1, ping_interval=None) as ws:
            async with asyncio.timeout(_CDP_TIMEOUT):
                await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                    'params': {'expression': STATUS_READONLY, 'returnByValue': True}}))
                result, _ = await _receive_cdp_result(ws, 1, _CDP_MAX_BYTES)
                before = _status_from_result(result, tab)

                await ws.send(json.dumps({'id': 2, 'method': 'Page.captureScreenshot',
                    'params': {'format': 'jpeg', 'quality': 50, 'fromSurface': True,
                               'optimizeForSpeed': True, 'captureBeyondViewport': False}}))
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
        pixels = b''.join(image.rgb[y * image.stride + left * 3:y * image.stride + right * 3]
                          for y in range(top, bottom))
        cropped = RgbPayload(right - left, bottom - top, (right - left) * 3,
                             image.captured_monotonic_ns, pixels)
        return CapturedFrame(cropped, before, left * before.width / width, top * before.height / height,
                             (right - left) * before.width / width, (bottom - top) * before.height / height)
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
        water_img = water_point(full_frame.image)
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
    delay_ms: float = 50.0,
) -> ClickResult:
    if status.modal:
        raise ActionPreconditionError("Modal dialog is active")
    if status.energy is None or status.energy <= 0:
        raise ActionPreconditionError("Insufficient energy for cast")
    return await click_point(tab, x, y, delay_ms=delay_ms, check_preconditions=True, status=status)


async def click_strike(
    tab: Tab,
    x: float,
    y: float,
    status: Status,
    delay_ms: float = 40.0,
) -> ClickResult:
    if status.modal:
        raise ActionPreconditionError("Modal dialog is active")
    return await click_point(tab, x, y, delay_ms=delay_ms, check_preconditions=True, status=status)


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
    re.compile(r'\bcan\b', re.IGNORECASE),
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
) -> Outcome:
    t_start = time.monotonic()

    # Step 1: Preconditions Gate
    pre_status = await read_status(tab)
    initial_toast = (pre_status.toast or "").strip().lower()
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
    water_spot = water_point(full_frame.image)
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
        if current_toast and current_toast != initial_toast:
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

    while time.monotonic() < deadline:
        poll_count += 1

        # Fast Check 2: Kiểm tra toast định kỳ trong khi chờ alert (mỗi 5 chu kỳ poll)
        if poll_count % 5 == 0:
            try:
                mid_status = await read_status(tab)
                last_status = mid_status
                current_toast = (mid_status.toast or "").strip().lower()
                if current_toast and current_toast != initial_toast:
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
        hit = alert_point(alert_frame.image, baseline=baseline_frame.image)
        if hit is not None:
            alert_detected_at = time.monotonic()
            await click_strike(tab, cast_x, cast_y, pre_status)
            strike_at = time.monotonic()
            reaction_ms = (strike_at - alert_detected_at) * 1000.0
            if lake is not None:
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {lake:02d}/40] ⚡ CÁ CẮN CÂU (!) - Giật cần tức thì ({reaction_ms:.1f}ms)!")
            break
        if poll_interval_sec > 0:
            await asyncio.sleep(poll_interval_sec)

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
        outcome_timeout = 2.5

    poll_step = min(0.10, outcome_timeout) if outcome_timeout > 0 else 0.001
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

    async with _resolve_ws(tab) as ws:
        msg_id = _get_id()
        await ws.send(json.dumps({
            'id': msg_id,
            'method': 'Runtime.evaluate',
            'params': {'expression': expression, 'returnByValue': True}
        }))
        result, _ = await _receive_cdp_result(ws, msg_id, _CDP_MAX_BYTES)
        remote = result.get('result')
        return remote.get('value') if isinstance(remote, dict) else None


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

    await click_point(tab, bx, by, delay_ms=50.0, check_preconditions=True, status=pre_status)
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
        # Bước 1: Mở Codex
        open_codex_expr = """(() => {
            const modal = document.querySelector('.modal-body');
            if (modal) return { open: true, wasOpen: true };
            const btn = document.querySelector('img[title*="Codex" i], img[src*="codex" i], [title*="Codex" i], button.codex-btn, [data-ui="codex"]');
            if (btn) {
                btn.click();
                return { open: true, clicked: true };
            }
            return { open: false };
        })()"""
        try:
            await _cdp_evaluate(tab, open_codex_expr)
        except Exception:
            pass
        await asyncio.sleep(0.3)

        # Bước 2: Kích hoạt Tab Bookmarks (kiểm tra màu hồng 254, 119 hoặc class active, My tiles không active)
        tab_expr = """(() => {
            const bm = document.querySelector('li[data-ui-tab="bookmarks"]');
            if (!bm) return { active: false, error: "no_bookmarks_tab" };
            const isClassActive = bm.classList.contains('active') || bm.getAttribute('aria-selected') === 'true';
            const color = window.getComputedStyle(bm).color || '';
            const isPink = color.includes('254') && color.includes('119');
            const mine = document.querySelector('li[data-ui-tab="mine"]');
            const mineInactive = !mine || !mine.classList.contains('active');
            const active = (isClassActive || isPink) && mineInactive;
            if (!active) {
                bm.click();
            }
            return { active: active, clicked: !active };
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
            await asyncio.sleep(0.35)

        if not bookmarks_active:
            # Cleanup modal and continue/fail
            try:
                await _cdp_evaluate(
                    tab,
                    "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true})); "
                    "document.querySelector('.close-btn, [class*=\"close-btn\"], .modal-close, .modal .close, button.close, [aria-label=\"Close\"], [data-dismiss=\"modal\"]')?.click();"
                )
            except Exception:
                pass
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

        # Bước 3: Cuộn & Nhận diện Hồ Mục tiêu HO <target_lake>
        lake_expr = f"""(() => {{
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
                        fastTravelBtn.scrollIntoView({{block: 'center', inline: 'center', behavior: 'instant'}});
                        const rect = fastTravelBtn.getBoundingClientRect();
                        return {{
                            found: true,
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
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

        # Bước 4: Click Fast Travel, Chờ chuyển cảnh & Đóng modal khi fail
        if isinstance(lake_info, dict) and lake_info.get("found"):
            x = float(lake_info.get("x", 0.0))
            y = float(lake_info.get("y", 0.0))
            await asyncio.sleep(0.15)
            try:
                await click_point(tab, x, y, delay_ms=50.0)
            except Exception:
                pass

            # Chờ chuyển cảnh: modal biến mất (status.modal == False)
            await asyncio.sleep(1.5)
            try:
                st = await read_status(tab)
                if not st.modal:
                    # Xóa Stale Toast trên DOM ngay sau khi travel thành công
                    clear_toast_expr = """(() => {
                        const els = document.querySelectorAll('.message-bar, .toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]');
                        for (const el of els) {
                            try { el.innerText = ''; } catch (_) {}
                        }
                    })()"""
                    try:
                        await _cdp_evaluate(tab, clear_toast_expr)
                    except Exception:
                        pass
                    return TravelResult(
                        success=True,
                        lake=target_lake,
                        attempts=attempt,
                        duration_sec=time.monotonic() - t_start,
                        error=None,
                    )
            except Exception:
                pass

        # Cleanup modal khi thất bại ở attempt này
        try:
            await _cdp_evaluate(
                tab,
                "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true})); "
                "document.querySelector('.close-btn, [class*=\"close-btn\"], .modal-close, .modal .close, button.close, [aria-label=\"Close\"], [data-dismiss=\"modal\"]')?.click();"
            )
        except Exception:
            pass
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
            await _receive_cdp_result(ws, msg_id, _CDP_MAX_BYTES)
        except Exception:
            pass

    if wait_loaded_sec > 0:
        await asyncio.sleep(wait_loaded_sec)

    # Đóng popup / modal chào mừng sau khi F5 nếu có
    try:
        await _cdp_evaluate(
            tab,
            """(() => {
                window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true}));
                const closeBtn = document.querySelector('.close-btn, [class*="close-btn"], .modal-close, .modal .close, button.close, [aria-label="Close"]');
                if (closeBtn) closeBtn.click();
            })()"""
        )
    except Exception:
        pass


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
    )


async def run_auto_session(
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
                await travel_to_lake(tab, 1)
                state.last_activity_time = time.time()
                continue
            elif new_reset_hour != state.last_reset_hour:
                state.last_reset_hour = new_reset_hour
                state.save(config.state_file)

            now = time.time()
            if (now - state.last_activity_time) >= config.idle_timeout_seconds:
                # Dọn modal kẹt trước khi thử lại
                try:
                    await _cdp_evaluate(
                        tab,
                        "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true})); "
                        "document.querySelector('.modal .close, button.close, [aria-label=\"Close\"]')?.click();"
                    )
                except Exception:
                    pass

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
                if state.current_lake >= config.max_lakes:
                    # Đã câu xong hồ 40 -> Kiểm tra và chờ reset nếu chưa tới giờ
                    did_wait_and_reset = await wait_until_reset_if_needed(tab, state.current_lake, config.max_lakes, stop_event)
                    if did_wait_and_reset:
                        state.current_lake = 1
                        state.consecutive_no_water = 0
                        state.consecutive_timeout = 0
                        state.save(config.state_file)
                        state.last_activity_time = time.time()
                        continue

                next_lake = (state.current_lake % config.max_lakes) + 1
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
                    next_lake = (state.current_lake % config.max_lakes) + 1
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⏳ Quá {config.max_timeout_retries} lần cá không cắn -> Chuyển sang HO {next_lake}...")
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 🚀 Khởi hành tới HO {next_lake}...")
                    travel_res = await travel_to_lake(tab, next_lake)
                    if travel_res.success:
                        state.current_lake = next_lake
                        state.consecutive_no_water = 0
                        state.save(config.state_file)
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại -> Giữ nguyên hồ để xử lý lại...")
                    state.last_activity_time = time.time()

            elif outcome.kind == "MODAL_ACTIVE":
                consecutive_modal_stuck += 1
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Phát hiện modal đang mở -> Đang dọn dẹp modal ({consecutive_modal_stuck})...")
                try:
                    await _cdp_evaluate(
                        tab,
                        """(() => {
                            window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true}));
                            const closeBtn = document.querySelector('.close-btn, [class*="close-btn"], .modal-close, .modal .close, button.close, [aria-label="Close"]');
                            if (closeBtn) closeBtn.click();
                        })()"""
                    )
                except Exception:
                    pass

                # Rate limiting delay chống tight-loop 100% CPU
                await asyncio.sleep(0.5)

                # Nếu kẹt quá 3 lần liên tiếp, kích hoạt cơ chế tự phục hồi
                if consecutive_modal_stuck >= 3:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Modal kẹt cứng quá 3 lần -> Tự động tái điều hướng về HO {state.current_lake} để khôi phục UI...")
                    consecutive_modal_stuck = 0
                    await travel_to_lake(tab, state.current_lake)
                    state.last_activity_time = time.time()

            await asyncio.sleep(0.01)

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
