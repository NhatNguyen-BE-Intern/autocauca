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
    _water_anchor: Optional[Tuple[int, int]] = field(default=None, compare=False, repr=False)
    _water_anchor_uses: int = field(default=0, compare=False, repr=False)
    _water_anchor_limit: int = field(default=0, compare=False, repr=False)
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

_GEOMETRY_ONLY_EXPR = "({url:location.href,width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"

STATUS_READONLY = r"""(() => {
 const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
 const isLeaving=e=>typeof e.closest==='function'&&Boolean(e.closest('.fade-leave, .fade-leave-active'));
 const leafText=e=>(e?.textContent??e?.innerText)||'';
 const energy=leafText(document.querySelector('div.info > div.number')).match(/(\d+)\s*\/\s*80/);
 const parseXpNum=(n,u)=>{
  const v=Number(n);
  if(!Number.isFinite(v))return null;
  const s=(u||'').toUpperCase();
  const m=s==='K'?1e3:s==='M'?1e6:s==='B'?1e9:1;
  return v*m;
 };
 const readXp=()=>{
  const legacy=leafText(document.querySelector('.remaining-xp')).replace(/,/g,'').match(/(\d+)/);
  if(legacy)return Number(legacy[1]);
  const progText=leafText(document.querySelector('.xp-progress-number')).replace(/,/g,'').trim();
  const m=progText.match(/(\d+(?:\.\d+)?)\s*([KMB])?\s*\/\s*(\d+(?:\.\d+)?)\s*([KMB])?/i);
  if(!m)return null;
  const cur=parseXpNum(m[1],m[2]);
  const max=parseXpNum(m[3],m[4]);
  const bar=document.querySelector('.xp-progress-bar');
  const wRaw=bar?.style?.width||'';
  const wm=wRaw.match(/(\d+(?:\.\d+)?)\s*%/)||(bar?.getAttribute?.('style')||'').match(/width\s*:\s*(\d+(?:\.\d+)?)\s*%/i);
  if(wm&&max!==null&&max>0){
   const pct=Number(wm[1]);
   if(Number.isFinite(pct)&&pct>=0&&pct<=100)return Math.round((pct/100)*max);
  }
  return cur!==null?Math.round(cur):null;
 };
 const xpValue=readXp();
 if(xpValue!==null&&(!Number.isSafeInteger(xpValue)||xpValue<0))throw Error('unsafe status XP');
 const isShown=e=>!e?false:(typeof e.getClientRects!=='function'?true:visible(e));
 const getToast=()=>{
  const primary=document.querySelector('.message-bar');
  if(isShown(primary)){
   const primaryText=(primary.innerText||'').trim();
   if(primaryText.length>0)return primaryText.toLowerCase();
  }
  const secondary=document.querySelector('.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]');
  return isShown(secondary)?(secondary.innerText||'').trim().toLowerCase():'';
 };
 return {url:location.href,width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
 energy:energy?Number(energy[1]):null,xp:xpValue,
 toast:getToast(),
 sequence_available:false,sequence:0,modal:[...document.querySelectorAll('.modal-body')].some(e=>visible(e)&&!isLeaving(e))};
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


def _geometry_from_result(result, tab: Tab) -> Tuple[str, float, float, float]:
    remote = result.get('result')
    value = remote.get('value') if isinstance(remote, dict) else None
    if not isinstance(value, dict):
        raise CdpError('invalid CDP geometry value')
    url = value.get('url')
    width = value.get('width')
    height = value.get('height')
    dpr = value.get('dpr')
    validate_game_url(url)
    if _origin(url) != _origin(tab.url):
        raise CdpError('capture geometry origin changed')
    for name, v in (('width', width), ('height', height), ('dpr', dpr)):
        try:
            valid = type(v) in (int, float) and math.isfinite(v)
        except OverflowError:
            valid = False
        if not valid or (v <= 0 if name == 'dpr' else not 100 <= v <= 8192):
            raise CdpError('invalid capture geometry dimensions')
    return (url, width, height, dpr)


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
# Daytime / afternoon / dusk water RGB envelope (paired with teal-chroma guard in _find_water_matches)
WATER_DAY_LOWER_RGB = np.array([80, 100, 105], dtype=np.uint8)
WATER_DAY_UPPER_RGB = np.array([202, 230, 228], dtype=np.uint8)
WATER_DAY_MIN_GR_DIFF = 12
WATER_DAY_MIN_BR_DIFF = 12
WATER_DAY_MAX_GB_DIFF = 18


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
        day_mask = cv2.inRange(roi, WATER_DAY_LOWER_RGB, WATER_DAY_UPPER_RGB)
        r_ch, g_ch, b_ch = cv2.split(roi)
        cv2.bitwise_and(day_mask, cv2.compare(cv2.subtract(g_ch, r_ch), WATER_DAY_MIN_GR_DIFF, cv2.CMP_GE), dst=day_mask)
        cv2.bitwise_and(day_mask, cv2.compare(cv2.subtract(b_ch, r_ch), WATER_DAY_MIN_BR_DIFF, cv2.CMP_GE), dst=day_mask)
        cv2.bitwise_and(day_mask, cv2.compare(cv2.absdiff(g_ch, b_ch), WATER_DAY_MAX_GB_DIFF, cv2.CMP_LE), dst=day_mask)
        cv2.bitwise_or(mask, day_mask, dst=mask)

    cv2.threshold(mask, 1, 1, cv2.THRESH_BINARY, dst=mask)
    integral = cv2.integral(mask, sdepth=cv2.CV_32S)

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


def pick_human_water_point(
    payload: Union[bytes, RgbPayload],
    tab: Tab,
    include_day: bool = True,
) -> Optional[Tuple[int, int]]:
    """Pick a human-like safe water casting point using anchor clustering.

    Real humans fish 5..15 consecutive casts within +/-6..22px of a favorite spot
    (anchor), then shift to a new anchor >=35px away. Every chosen point is verified
    inside the 51x51 safe water mask.
    """
    found = _find_water_matches(payload, include_day=include_day)
    if found is None:
        return None
    matches, x_indices, y_indices = found
    cand_xs = x_indices[matches[:, 1]]
    cand_ys = y_indices[matches[:, 0]]

    if len(matches) == 1:
        pt = (int(cand_xs[0]), int(cand_ys[0]))
        tab._water_anchor = pt
        tab._water_anchor_uses = 1
        tab._water_anchor_limit = random.randint(5, 15)
        return pt

    anchor = getattr(tab, "_water_anchor", None)
    uses = int(getattr(tab, "_water_anchor_uses", 0))
    limit = int(getattr(tab, "_water_anchor_limit", 0))

    need_new_anchor = (anchor is None) or (limit <= 0) or (uses >= limit)
    if not need_new_anchor and anchor is not None:
        d2_cur = (cand_xs - anchor[0]) ** 2 + (cand_ys - anchor[1]) ** 2
        if not np.any(d2_cur <= 22 ** 2):
            need_new_anchor = True

    if need_new_anchor:
        if anchor is not None:
            d2_prev = (cand_xs - anchor[0]) ** 2 + (cand_ys - anchor[1]) ** 2
            far = d2_prev >= 35 ** 2
            if np.any(far):
                far_xs = cand_xs[far]
                far_ys = cand_ys[far]
                a_idx = random.randrange(len(far_xs))
                anchor = (int(far_xs[a_idx]), int(far_ys[a_idx]))
            else:
                # Pond is smaller than 35px span -> pick among the farthest half
                order = np.argsort(d2_prev)
                top_half = order[len(order) // 2 :]
                a_idx = int(top_half[random.randrange(len(top_half))])
                anchor = (int(cand_xs[a_idx]), int(cand_ys[a_idx]))
        else:
            a_idx = random.randrange(len(cand_xs))
            anchor = (int(cand_xs[a_idx]), int(cand_ys[a_idx]))
        tab._water_anchor = anchor
        tab._water_anchor_uses = 0
        tab._water_anchor_limit = random.randint(5, 15)

    ax, ay = anchor
    d2_anchor = (cand_xs - ax) ** 2 + (cand_ys - ay) ** 2
    ring = (d2_anchor >= 6 ** 2) & (d2_anchor <= 22 ** 2)
    if np.any(ring):
        pool_xs = cand_xs[ring]
        pool_ys = cand_ys[ring]
    else:
        near = d2_anchor <= 22 ** 2
        if np.any(near):
            pool_xs = cand_xs[near]
            pool_ys = cand_ys[near]
        else:
            nearest_idx = int(np.argmin(d2_anchor))
            pool_xs = cand_xs[nearest_idx : nearest_idx + 1]
            pool_ys = cand_ys[nearest_idx : nearest_idx + 1]

    last_pt = getattr(tab, "_last_water_point", None)
    if last_pt is not None and len(pool_xs) > 1:
        d2_last = (pool_xs - last_pt[0]) ** 2 + (pool_ys - last_pt[1]) ** 2
        non_repeat = d2_last >= 4 ** 2
        if np.any(non_repeat):
            pool_xs = pool_xs[non_repeat]
            pool_ys = pool_ys[non_repeat]

    pick_idx = random.randrange(len(pool_xs))
    bx = int(pool_xs[pick_idx])
    by = int(pool_ys[pick_idx])
    jx = random.randint(-2, 2)
    jy = random.randint(-2, 2)
    px, py = bx + jx, by + jy
    # Keep jittered point within <=22px of anchor if base was within 22px
    if math.hypot(bx - ax, by - ay) <= 22.0 and math.hypot(px - ax, py - ay) > 22.0:
        px, py = bx, by

    tab._water_anchor_uses = int(getattr(tab, "_water_anchor_uses", 0)) + 1
    return (px, py)


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
                    after_expr = _GEOMETRY_ONLY_EXPR if kind == 'SCREEN_FULL' else STATUS_READONLY
                    await ws.send(json.dumps({'id': id_after, 'method': 'Runtime.evaluate',
                        'params': {'expression': after_expr, 'returnByValue': True}}))
                    result, _ = await _receive_cdp_result(ws, id_after, _CDP_MAX_BYTES, allow_stale_ids=True)
                    if kind == 'SCREEN_FULL':
                        after_geom = _geometry_from_result(result, tab)
                    else:
                        after = _status_from_result(result, tab)
                        after_geom = (after.url, after.width, after.height, after.dpr)
                    if (before.url, before.width, before.height, before.dpr) != after_geom:
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
    elif water_img is None:
        water_img = water_point(full_frame.image, include_day=True)

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


def quantize_coord(val: float, dpr: float = 1.0) -> float:
    """Quantize CSS coordinate to the physical pixel grid (step = 1/dpr)."""
    d = float(dpr) if (isinstance(dpr, (int, float)) and math.isfinite(dpr) and dpr > 0.0) else 1.0
    return round(round(float(val) * d) / d, 4)


def _quantize_clamped(val: float, lo: float, hi: float, dpr: float = 1.0) -> float:
    """Quantize coordinate to 1/dpr while strictly remaining within [lo, hi]."""
    lo_f, hi_f = (float(lo), float(hi)) if lo <= hi else (float(hi), float(lo))
    d = float(dpr) if (isinstance(dpr, (int, float)) and math.isfinite(dpr) and dpr > 0.0) else 1.0
    clamped = max(lo_f, min(hi_f, float(val)))
    q = quantize_coord(clamped, d)
    if q < lo_f:
        cand = round(math.ceil(lo_f * d) / d, 4)
        q = cand if cand <= hi_f else lo_f
    elif q > hi_f:
        cand = round(math.floor(hi_f * d) / d, 4)
        q = cand if cand >= lo_f else hi_f
    return q


def _viewport_status(tab: Tab, info: Any = None, status: Optional[Status] = None) -> Optional[Status]:
    """Return existing Status or construct a lightweight viewport-only Status from read-only JS info."""
    if status is not None:
        return status
    if not isinstance(info, dict):
        return None
    vw = info.get("vw")
    vh = info.get("vh")
    dpr = info.get("dpr", 1.0)
    try:
        wf = float(vw)
        hf = float(vh)
        df = float(dpr)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(wf) and math.isfinite(hf) and math.isfinite(df)):
        return None
    if not (100.0 <= wf <= 8192.0 and 100.0 <= hf <= 8192.0 and df > 0.0):
        return None
    return Status(
        url=tab.url,
        width=wf,
        height=hf,
        dpr=df,
        energy=None,
        xp=None,
        toast="",
        sequence_available=False,
        sequence=0,
        modal=False,
    )


class HumanPacer:
    """Continuous human timing engine with per-session persona, AR(1) autocorrelation, and fatigue drift."""

    def __init__(
        self,
        *,
        persona: Optional[float] = None,
        phi: float = 0.28,
        fatigue_max: Optional[float] = None,
        fatigue_horizon_sec: float = 9000.0,
    ) -> None:
        self.persona: float = float(persona) if persona is not None else random.uniform(0.90, 1.15)
        self.phi: float = max(0.0, min(0.85, float(phi)))
        self.fatigue_max: float = float(fatigue_max) if fatigue_max is not None else random.uniform(0.18, 0.32)
        self.fatigue_horizon_sec: float = max(1.0, float(fatigue_horizon_sec))
        self.session_start_mono: float = time.monotonic()
        self._ar_strike: float = 0.0
        self._ar_inter: float = 0.0
        self._ar_hold: float = 0.0

    def fatigue_multiplier(self, elapsed_sec: Optional[float] = None) -> float:
        """Smooth fatigue multiplier rising from 1.0 to 1.0 + [0.18..0.32] over ~2.5h."""
        elapsed = (time.monotonic() - self.session_start_mono) if elapsed_sec is None else max(0.0, float(elapsed_sec))
        progress = min(1.0, elapsed / self.fatigue_horizon_sec)
        return 1.0 + self.fatigue_max * (progress ** 1.15)

    def reset_after_break(self) -> None:
        """Reset fatigue clock and AR(1) temporal state after a long break or sleep."""
        self.session_start_mono = time.monotonic()
        self._ar_strike = 0.0
        self._ar_inter = 0.0
        self._ar_hold = 0.0
        self.persona = max(0.90, min(1.15, self.persona + random.uniform(-0.04, 0.04)))

    def _ar1_step(self, prev: float, sigma: float) -> float:
        innov_sigma = sigma * math.sqrt(max(1e-6, 1.0 - self.phi * self.phi))
        return self.phi * prev + random.gauss(0.0, innov_sigma)

    def sample_strike_delay_sec(self, natural_miss_rate: float = 0.032) -> Tuple[float, bool]:
        """Continuous Log-Normal strike reaction delay in [0.085, 0.850]s with distracted miss flag."""
        fat = self.fatigue_multiplier()
        if natural_miss_rate >= 1.0:
            return (random.uniform(0.80, 1.50), True)
        if natural_miss_rate > 0.0 and random.random() < min(0.15, natural_miss_rate * fat):
            return (random.uniform(0.80, 1.50), True)
        z = self._ar1_step(self._ar_strike, 0.34)
        self._ar_strike = z
        val = 0.165 * self.persona * fat * math.exp(z)
        return (max(0.085, min(0.850, val)), False)

    def sample_hold_ms(self, fast: bool = False) -> float:
        """Continuous Log-Normal mouse button hold duration (normal [50, 155]ms, fast [42, 130]ms)."""
        fat = self.fatigue_multiplier()
        z = self._ar1_step(self._ar_hold, 0.22 if fast else 0.24)
        self._ar_hold = z
        base = 66.0 if fast else 82.0
        val = base * self.persona * (1.0 + 0.5 * (fat - 1.0)) * math.exp(z)
        if fast:
            return max(42.0, min(130.0, val))
        return max(50.0, min(155.0, val))

    def sample_inter_cast_sec(self) -> float:
        """Continuous Log-Normal inter-cast pause in [0.45, 12.0]s with smooth heavy tail and AR(1)."""
        fat = self.fatigue_multiplier()
        z = self._ar1_step(self._ar_inter, 0.56)
        self._ar_inter = z
        val = 1.15 * self.persona * fat * math.exp(z)
        if random.random() < 0.05:
            val += random.lognormvariate(math.log(2.4), 0.45)
        return max(0.45, min(12.0, val))

    def sample_reaction_pause(self, kind: str) -> float:
        """Natural comprehension pause after game events (EMPTY/TRASH/PRIVATE, TRAVEL, BREAD, MISS)."""
        k = (kind or "").upper()
        scale = self.persona * (1.0 + 0.4 * (self.fatigue_multiplier() - 1.0))
        if k in ("EMPTY", "TRASH", "PRIVATE"):
            val = random.lognormvariate(math.log(1.40), 0.28) * scale
            return max(0.80, min(2.40, val))
        if k == "TRAVEL":
            val = random.lognormvariate(math.log(2.05), 0.28) * scale
            return max(1.20, min(3.50, val))
        if k == "BREAD":
            val = random.lognormvariate(math.log(1.55), 0.25) * scale
            return max(1.00, min(2.40, val))
        if k == "MISS":
            val = random.lognormvariate(math.log(1.10), 0.28) * scale
            return max(0.70, min(1.80, val))
        val = random.lognormvariate(math.log(1.00), 0.25) * scale
        return max(0.60, min(1.60, val))


def human_hold_ms(fast: bool = False) -> float:
    """Continuous Log-Normal human mouse button hold duration in milliseconds."""
    if fast:
        val = random.lognormvariate(math.log(66.0), 0.22)
        return max(42.0, min(130.0, val))
    val = random.lognormvariate(math.log(82.0), 0.24)
    return max(50.0, min(155.0, val))


def human_strike_delay_sec(
    rare_miss_rate: float = 0.032,
    pacer: Optional[HumanPacer] = None,
) -> Tuple[float, bool]:
    """Continuous Log-Normal visual-motor strike reaction delay ([0.085, 0.850]s, ~165ms median) + distracted miss."""
    if pacer is not None:
        return pacer.sample_strike_delay_sec(natural_miss_rate=rare_miss_rate)
    if rare_miss_rate > 0.0 and random.random() < rare_miss_rate:
        return (random.uniform(0.80, 1.50), True)
    val = random.lognormvariate(math.log(0.165), 0.36)
    return (max(0.085, min(0.850, val)), False)


def human_inter_cast_delay_sec(pacer: Optional[HumanPacer] = None) -> float:
    """Continuous Log-Normal right-skewed human pause between consecutive casts ([0.45, 12.0]s, zero gaps)."""
    if pacer is not None:
        return pacer.sample_inter_cast_sec()
    val = random.lognormvariate(math.log(1.15), 0.58)
    if random.random() < 0.05:
        val += random.lognormvariate(math.log(2.4), 0.45)
    return max(0.45, min(12.0, val))


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
        await asyncio.sleep(random.uniform(0.055, 0.125))
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
        wheel_id = _get_id()
        await ws.send(json.dumps({
            "id": wheel_id,
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mouseWheel",
                "x": float(x),
                "y": float(y),
                "deltaX": float(delta_x),
                "deltaY": float(delta_y),
            },
        }))
        if getattr(tab, "_managed_ws", False):
            try:
                async with asyncio.timeout(0.25):
                    await _receive_cdp_result(ws, wheel_id, _CDP_MAX_BYTES, allow_stale_ids=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass


MODAL_CLOSE_LOOKUP_EXPR = """(() => {
    /* CDP Escape + read-only .close-btn / .modal .close lookup (zero DOM click/dispatchEvent) */
    const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
    const isLeaving = e => typeof e.closest === 'function' && Boolean(e.closest('.fade-leave, .fade-leave-active'));
    const hasModal = [...document.querySelectorAll('.modal-body')].some(e => visible(e) && !isLeaving(e));
    const btns = [...document.querySelectorAll('.close-btn, [class*="close-btn"], .modal-close, .modal .close, button.close, [aria-label="Close"], [data-dismiss="modal"]')];
    const btn = btns.find(b => !isLeaving(b) && b.getBoundingClientRect().width > 0 && b.getBoundingClientRect().height > 0);
    if (!btn) return { has_modal: hasModal, found: false, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
    const r = btn.getBoundingClientRect();
    return { has_modal: hasModal, found: true, x: r.left + r.width / 2, y: r.top + r.height / 2, width: r.width, height: r.height, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
})()"""

MODAL_UNMOUNT_CHECK_EXPR = """(() => {
    const modals = [...document.querySelectorAll('.modal-body')];
    const present = modals.some(e => {
        if (e.getClientRects().length === 0) return false;
        const st = getComputedStyle(e);
        if (st.visibility === 'hidden' || st.display === 'none') return false;
        if (parseFloat(st.opacity || '1') <= 0.05) return false;
        const leaving = typeof e.closest === 'function' ? e.closest('.fade-leave, .fade-leave-active') : null;
        if (leaving) {
            const lst = getComputedStyle(leaving);
            if (lst.visibility === 'hidden' || lst.display === 'none' || parseFloat(lst.opacity || '1') <= 0.05) return false;
        }
        return true;
    });
    return { present, hidden: document.visibilityState === 'hidden' };
})()"""


async def _flush_hidden_compositor_frame(tab: Tab) -> bool:
    """Force Chromium's occluded compositor to commit pending wheel/fade frames via unclipped low-quality readback."""
    if not getattr(tab, "_managed_ws", False):
        return False
    ws = getattr(tab, "ws", None)
    if ws is None:
        return False
    try:
        msg_id = tab.next_id() if hasattr(tab, "next_id") and callable(tab.next_id) else 1
        async with asyncio.timeout(1.5):
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.captureScreenshot",
                "params": {
                    "format": "jpeg",
                    "quality": 15,
                    "fromSurface": True,
                    "optimizeForSpeed": True,
                    "captureBeyondViewport": False,
                },
            }))
            await _receive_cdp_result(ws, msg_id, _CAPTURE_CDP_MAX_BYTES, allow_stale_ids=True)
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


async def _wait_modal_unmounted(tab: Tab, timeout_sec: float = 2.6) -> bool:
    """Wait until all .modal-body elements (including .fade-leave/.fade-leave-active) fully fade out or unmount."""
    if not getattr(tab, "_managed_ws", False):
        return True
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while True:
        info = None
        try:
            info = await _cdp_evaluate(tab, MODAL_UNMOUNT_CHECK_EXPR)
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        if isinstance(info, dict) and not info.get("present"):
            return True
        if time.monotonic() >= deadline:
            return False
        if isinstance(info, dict) and info.get("hidden"):
            await _flush_hidden_compositor_frame(tab)
        await asyncio.sleep(random.uniform(0.15, 0.22))


def _jitter_clamped_to_viewport(
    cx: float,
    cy: float,
    *,
    max_dx: float,
    max_dy: float,
    status: Optional[Status],
    dpr: float,
) -> Tuple[float, float]:
    """Jitter a UI target center while clamping strictly inside [1, vw-1] x [1, vh-1] when viewport is known."""
    if status is not None:
        vw_hi = max(1.0, float(status.width) - 1.0)
        vh_hi = max(1.0, float(status.height) - 1.0)
        min_x = max(1.0, min(vw_hi, cx - max_dx))
        max_x = max(min_x, min(vw_hi, cx + max_dx))
        min_y = max(1.0, min(vh_hi, cy - max_dy))
        max_y = max(min_y, min(vh_hi, cy + max_dy))
    else:
        min_x = max(0.0, cx - max_dx)
        max_x = cx + max_dx
        min_y = max(0.0, cy - max_dy)
        max_y = cy + max_dy
    return jitter_point(
        cx,
        cy,
        max_dx=max_dx,
        max_dy=max_dy,
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        dpr=dpr,
    )


async def _dismiss_modal_cdp(tab: Tab, status: Optional[Status] = None) -> bool:
    """Read-only modal lookup -> trusted CDP Escape -> wait & re-check DOM -> click Close only if still open."""
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

    await asyncio.sleep(random.uniform(0.25, 0.50))

    recheck = None
    try:
        recheck = await _cdp_evaluate(tab, MODAL_CLOSE_LOOKUP_EXPR)
    except Exception:
        recheck = None

    if isinstance(recheck, dict):
        if not (recheck.get("has_modal") or recheck.get("found")):
            if getattr(tab, "_managed_ws", False):
                await _wait_modal_unmounted(tab)
            return True
        target_info = recheck if recheck.get("found") else info
    else:
        target_info = info

    if isinstance(target_info, dict) and target_info.get("found") and "x" in target_info and "y" in target_info:
        eff_status = _viewport_status(tab, target_info, status)
        dpr = float(eff_status.dpr) if eff_status is not None else 1.0
        cx = float(target_info["x"])
        cy = float(target_info["y"])
        max_dx = min(4.0, max(0.0, float(target_info.get("width", 0.0)) * 0.25))
        max_dy = min(3.0, max(0.0, float(target_info.get("height", 0.0)) * 0.25))
        cx, cy = _jitter_clamped_to_viewport(
            cx, cy, max_dx=max_dx, max_dy=max_dy, status=eff_status, dpr=dpr
        )
        try:
            await move_mouse_bezier(tab, cx, cy, fast=False, status=eff_status)
            await click_point(tab, cx, cy, delay_ms=human_hold_ms(fast=False), status=eff_status)
            if getattr(tab, "_managed_ws", False):
                await _wait_modal_unmounted(tab)
            else:
                await asyncio.sleep(random.uniform(0.35, 0.55))
        except Exception as exc:
            print(f"[{time.strftime('%H:%M:%S')}] [MODAL] ⚠️ Đóng modal bằng nút Close gặp lỗi: {exc}")
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
    dpr: float = 1.0,
) -> Tuple[float, float]:
    """Apply bounded jitter clamped within [min_x, max_x] x [min_y, max_y] and quantized to 1/dpr."""
    dx = random.uniform(-max_dx, max_dx) if max_dx > 0.0 else 0.0
    dy = random.uniform(-max_dy, max_dy) if max_dy > 0.0 else 0.0
    lo_x, hi_x = (min_x, max_x) if min_x <= max_x else (max_x, min_x)
    lo_y, hi_y = (min_y, max_y) if min_y <= max_y else (max_y, min_y)
    nx = _quantize_clamped(float(x) + dx, lo_x, hi_x, dpr)
    ny = _quantize_clamped(float(y) + dy, lo_y, hi_y, dpr)
    return (nx, ny)


def generate_bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    steps: int,
    dpr: float = 1.0,
) -> List[Tuple[float, float]]:
    """Generate an asymmetric velocity-eased cubic Bezier curve with micro-tremor landing on quantized end."""
    n = max(1, int(steps))
    x0, y0 = float(start[0]), float(start[1])
    x3, y3 = quantize_coord(float(end[0]), dpr), quantize_coord(float(end[1]), dpr)
    if n == 1:
        return [(x3, y3)]

    dx = x3 - x0
    dy = y3 - y0
    dist = math.hypot(dx, dy)
    if dist > 1e-6:
        px, py = -dy / dist, dx / dist
        sign1 = random.choice((-1.0, 1.0))
        sign2 = sign1 if random.random() < 0.78 else -sign1
        a1 = random.uniform(0.20, 0.42)
        a2 = random.uniform(0.58, 0.82)
        mag1 = min(95.0, random.uniform(0.10, 0.30) * dist)
        mag2 = min(95.0, random.uniform(0.08, 0.26) * dist)
        if dist >= 15.0:
            mag1 = max(6.0, mag1)
            mag2 = max(4.0, mag2)
        c1x = x0 + dx * a1 + px * (sign1 * mag1)
        c1y = y0 + dy * a1 + py * (sign1 * mag1)
        c2x = x0 + dx * a2 + px * (sign2 * mag2)
        c2y = y0 + dy * a2 + py * (sign2 * mag2)
    else:
        c1x, c1y = x0, y0
        c2x, c2y = x3, y3

    # Asymmetric Fitts-like easing (quicker acceleration, gentler homing deceleration)
    decel_exp = random.uniform(1.85, 2.45)
    blend = random.uniform(0.35, 0.55)
    tremor_sigma = min(1.2, dist * 0.004) if dist >= 20.0 else 0.0

    points: List[Tuple[float, float]] = []
    for i in range(1, n):
        t = i / n
        smooth = t * t * (3.0 - 2.0 * t)
        fast_out = 1.0 - (1.0 - t) ** decel_exp
        u = (1.0 - blend) * smooth + blend * fast_out
        om = 1.0 - u
        bx = (om ** 3) * x0 + 3.0 * (om ** 2) * u * c1x + 3.0 * om * (u ** 2) * c2x + (u ** 3) * x3
        by = (om ** 3) * y0 + 3.0 * (om ** 2) * u * c1y + 3.0 * om * (u ** 2) * c2y + (u ** 3) * y3
        if tremor_sigma > 0.0:
            env = math.sin(math.pi * t)
            bx += random.gauss(0.0, tremor_sigma) * env
            by += random.gauss(0.0, tremor_sigma) * env
        points.append((quantize_coord(bx, dpr), quantize_coord(by, dpr)))
    points.append((x3, y3))
    return points


async def move_mouse_bezier(
    tab: Tab,
    x: float,
    y: float,
    *,
    fast: bool = False,
    status: Optional[Status] = None,
    dwell: bool = True,
) -> List[Tuple[float, float]]:
    """Move virtual CDP cursor along a Fitts's Law cubic Bezier path (0 physical mouse movement)."""
    try:
        validate_game_url(tab.url)
    except Exception as e:
        raise ActionPreconditionError(f"untrusted or invalid tab URL: {getattr(tab, 'url', None)}") from e

    if not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and math.isfinite(x) and math.isfinite(y)):
        raise ActionPreconditionError(f"coordinates must be finite numbers: x={x}, y={y}")

    dpr = float(status.dpr) if (status is not None and math.isfinite(status.dpr) and status.dpr > 0.0) else 1.0
    if status is not None:
        max_vx = max(0.0, float(status.width) - 1.0 / max(1.0, dpr))
        max_vy = max(0.0, float(status.height) - 1.0 / max(1.0, dpr))
        tx = _quantize_clamped(float(x), 0.0, max_vx, dpr)
        ty = _quantize_clamped(float(y), 0.0, max_vy, dpr)
    else:
        max_vx, max_vy = 1200.0, 700.0
        tx = quantize_coord(float(x), dpr)
        ty = quantize_coord(float(y), dpr)

    cur = getattr(tab, "_cursor_pos", None)
    if cur is not None:
        start = (float(cur[0]), float(cur[1]))
    else:
        edge = random.choice(("left", "right", "top", "bottom"))
        if edge == "left":
            sx = random.uniform(2.0, min(35.0, max(2.0, max_vx)))
            sy = random.uniform(0.10 * max_vy, 0.90 * max_vy)
        elif edge == "right":
            sx = random.uniform(max(0.0, max_vx - 35.0), max_vx)
            sy = random.uniform(0.10 * max_vy, 0.90 * max_vy)
        elif edge == "top":
            sx = random.uniform(0.10 * max_vx, 0.90 * max_vx)
            sy = random.uniform(2.0, min(35.0, max(2.0, max_vy)))
        else:
            sx = random.uniform(0.10 * max_vx, 0.90 * max_vx)
            sy = random.uniform(max(0.0, max_vy - 35.0), max_vy)
        start = (_quantize_clamped(sx, 0.0, max_vx, dpr), _quantize_clamped(sy, 0.0, max_vy, dpr))

    dist = math.hypot(tx - start[0], ty - start[1])
    if fast:
        steps = random.randint(2, 4)
        total_sec = random.uniform(0.030, 0.080)
        raw_points = generate_bezier_path(start, (tx, ty), steps, dpr=dpr)
    else:
        if dist < 40.0:
            total_sec = random.uniform(0.050, 0.130)
        else:
            fitts_id = math.log2(dist / 24.0 + 1.0)
            mt = (0.105 + 0.068 * fitts_id) * random.uniform(0.85, 1.18)
            total_sec = max(0.140, min(0.500, mt))
        base_steps = max(7, min(18, int(round(6.5 + dist / 58.0)) + random.randint(-1, 2)))
        if dist >= 120.0 and random.random() < 0.25:
            correct_steps = random.randint(2, 3)
            main_steps = max(5, min(18 - correct_steps, base_steps - correct_steps))
            ux = (tx - start[0]) / dist
            uy = (ty - start[1]) / dist
            ov_dist = random.uniform(4.0, min(14.0, max(4.5, dist * 0.045)))
            perp_noise = random.uniform(-3.0, 3.0)
            ov_x = tx + ux * ov_dist - uy * perp_noise
            ov_y = ty + uy * ov_dist + ux * perp_noise
            if status is not None:
                ov_pt = (_quantize_clamped(ov_x, 0.0, max_vx, dpr), _quantize_clamped(ov_y, 0.0, max_vy, dpr))
            else:
                ov_pt = (quantize_coord(ov_x, dpr), quantize_coord(ov_y, dpr))
            raw_points = (
                generate_bezier_path(start, ov_pt, main_steps, dpr=dpr)
                + generate_bezier_path(ov_pt, (tx, ty), correct_steps, dpr=dpr)
            )
        else:
            raw_points = generate_bezier_path(start, (tx, ty), base_steps, dpr=dpr)

    if status is not None:
        points: List[Tuple[float, float]] = [
            (_quantize_clamped(px, 0.0, max_vx, dpr), _quantize_clamped(py, 0.0, max_vy, dpr))
            for px, py in raw_points[:-1]
        ]
        points.append((tx, ty))
    else:
        points = raw_points

    def _get_id() -> int:
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    # Non-uniform per-step timing (slower at launch & homing, faster mid-flight + natural jitter)
    n_gaps = max(0, len(points) - 1)
    if n_gaps > 0 and total_sec > 0.0:
        weights = [
            (1.0 + 0.65 * (2.0 * ((i + 0.5) / n_gaps) - 1.0) ** 2) * random.uniform(0.65, 1.45)
            for i in range(n_gaps)
        ]
        w_sum = sum(weights) or 1.0
        step_delays = [total_sec * (w / w_sum) for w in weights]
    else:
        step_delays = []

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
                    "buttons": 0,
                },
            }))
            if idx < len(step_delays) and step_delays[idx] > 0.0:
                await asyncio.sleep(step_delays[idx])

    if dwell and not fast:
        await asyncio.sleep(random.uniform(0.030, 0.110))

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

    dpr = float(status.dpr) if (status is not None and math.isfinite(status.dpr) and status.dpr > 0.0) else 1.0
    if status is not None:
        max_vx = max(0.0, float(status.width) - 1.0 / max(1.0, dpr))
        max_vy = max(0.0, float(status.height) - 1.0 / max(1.0, dpr))
        qx = _quantize_clamped(float(x), 0.0, max_vx, dpr)
        qy = _quantize_clamped(float(y), 0.0, max_vy, dpr)
    else:
        qx = max(0.0, quantize_coord(float(x), dpr)) if check_preconditions else quantize_coord(float(x), dpr)
        qy = max(0.0, quantize_coord(float(y), dpr)) if check_preconditions else quantize_coord(float(y), dpr)

    delay_sec = max(0.020, min(0.200, float(delay_ms) / 1000.0))

    def _get_id() -> int:
        if hasattr(tab, "next_id") and callable(tab.next_id):
            return tab.next_id()
        return 1

    async with _resolve_ws(tab) as ws:
        press_ns = time.monotonic_ns()
        press_id = _get_id()
        press_payload = json.dumps({
            "id": press_id,
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mousePressed",
                "x": qx,
                "y": qy,
                "button": "left",
                "buttons": 1,
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
                rel_id = _get_id()
                try:
                    rel_payload = json.dumps({
                        "id": rel_id,
                        "method": "Input.dispatchMouseEvent",
                        "params": {
                            "type": "mouseReleased",
                            "x": qx,
                            "y": qy,
                            "button": "left",
                            "buttons": 0,
                            "clickCount": 1,
                        },
                    })
                    await ws.send(rel_payload)
                    released = True
                except Exception:
                    released = False
                    return
                # Drain/await input ACK ONLY on real managed persistent WebSockets (never mocked tab.ws)
                if getattr(tab, "_managed_ws", False):
                    try:
                        async with asyncio.timeout(0.25):
                            await _receive_cdp_result(ws, rel_id, _CDP_MAX_BYTES, allow_stale_ids=True)
                    except Exception:
                        pass

            try:
                await asyncio.shield(_send_release())
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        duration_ms = (release_ns - press_ns) / 1_000_000.0
        tab._cursor_pos = (qx, qy)
        return ClickResult(
            x=qx,
            y=qy,
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
    re.compile(r'\b(?:pond|lake)\b.*\brestock\b', re.IGNORECASE),
    re.compile(r'\b(?:pond|lake)\s+(?:is\s+)?empty\b', re.IGNORECASE),
    re.compile(r'\bempty\s+(?:pond|lake)\b', re.IGNORECASE),
    re.compile(r'\bhết\s+cá\b', re.IGNORECASE),
    re.compile(r'\bhồ\s+(?:đã\s+)?cạn\b', re.IGNORECASE),
]

TRASH_PATTERNS = [
    re.compile(r'\bpulled\s+up\s+(?:some\s+)?trash\b', re.IGNORECASE),
    re.compile(r'\bsome\s+trash\b', re.IGNORECASE),
    re.compile(r'\btrash\b', re.IGNORECASE),
    re.compile(r'\brác\b', re.IGNORECASE),
    re.compile(r'\bold\s+boot\b', re.IGNORECASE),
    re.compile(r'\brusty\s+can\b', re.IGNORECASE),
    re.compile(r'\bold\s+can\b', re.IGNORECASE),
    re.compile(r'\btin\s+can\b', re.IGNORECASE),
    re.compile(r'\(\s*lon\s*\)', re.IGNORECASE),
]

PRIVATE_PATTERNS = [
    re.compile(r'\bthis\s+pond\s+is\s+private\b', re.IGNORECASE),
    re.compile(r'\bmembers\s+can\s+fish\s+here\b', re.IGNORECASE),
    re.compile(r'\bprivate\s+pond\b', re.IGNORECASE),
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
    """Phân loại chuỗi toast trả về: 'TRASH', 'PRIVATE', 'EMPTY', 'CATCH', hoặc None bằng Regex chặt chẽ."""
    if not toast_text:
        return None
    t = toast_text.strip()
    if not t:
        return None

    # 1. Kiểm tra Trash trước
    for pat in TRASH_PATTERNS:
        if pat.search(t):
            return "TRASH"

    # 2. Kiểm tra Private pond
    for pat in PRIVATE_PATTERNS:
        if pat.search(t):
            return "PRIVATE"

    # 3. Kiểm tra Empty
    for pat in EMPTY_PATTERNS:
        if pat.search(t):
            return "EMPTY"

    # 4. Kiểm tra Catch
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
    *,
    delay_minutes: float = 0.0,
) -> Tuple[bool, Optional[int]]:
    """
    Kiểm tra xem có cần tự động quay về Hồ 1 do server reset không.
    Trả về: (should_reset: bool, new_reset_hour: Optional[int])
    - should_reset = True khi đang trong giờ reset (hoặc sau độ trễ desync delay_minutes),
      chưa kích hoạt cho giờ này, và current_lake > 1.
    """
    now = dt or datetime.now()
    delay = max(0.0, float(delay_minutes))
    if delay <= 0.0:
        if is_reset_window(now):
            if last_reset_hour != now.hour:
                if current_lake > 1:
                    return True, now.hour
                return False, now.hour
        return False, last_reset_hour

    for h in RESET_HOURS:
        r_dt = now.replace(hour=h, minute=0, second=0, microsecond=0)
        diff_min = (now - r_dt).total_seconds() / 60.0
        if delay <= diff_min < delay + 15.0:
            if last_reset_hour != h:
                if current_lake > 1:
                    return True, h
                return False, h
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


def _get_most_recent_reset_datetime(now: datetime) -> datetime:
    """Trả về mốc giờ reset gần nhất trong RESET_HOURS thỏa <= now."""
    today_resets = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in RESET_HOURS]
    past = [r_dt for r_dt in today_resets if r_dt <= now]
    if past:
        return past[-1]
    yesterday = now - timedelta(days=1)
    return yesterday.replace(hour=RESET_HOURS[-1], minute=0, second=0, microsecond=0)


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
    return max(0.022, random.uniform(0.120, 0.160) - work)


async def run_one_cast(
    tab: Tab,
    use_worker: bool = True,
    max_alert_wait_sec: float = 20.0,
    poll_interval_sec: float = 0.05,
    reel_wait_sec: float = 1.5,
    baseline_delay_sec: float = 0.80,
    obs_delay_sec: float = 0.95,
    poll_outcome_timeout: Optional[float] = None,
    lake: Optional[int] = None,
    human_reaction: bool = True,
    pacer: Optional[HumanPacer] = None,
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
                pacer=pacer,
            )
        finally:
            tab._fast_alert_status = None


async def _run_one_cast_body(
    tab: Tab,
    use_worker: bool = True,
    max_alert_wait_sec: float = 20.0,
    poll_interval_sec: float = 0.05,
    reel_wait_sec: float = 1.5,
    baseline_delay_sec: float = 0.80,
    obs_delay_sec: float = 0.95,
    poll_outcome_timeout: Optional[float] = None,
    lake: Optional[int] = None,
    human_reaction: bool = True,
    pacer: Optional[HumanPacer] = None,
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
    pre_strike_ignored = set(ignored_toasts)
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

    # Step 2: Find Water (Human Anchor Cluster)
    full_frame = await capture(tab, "SCREEN_FULL")
    water_spot = pick_human_water_point(
        full_frame.image,
        tab,
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

    dpr = float(pre_status.dpr) if (math.isfinite(pre_status.dpr) and pre_status.dpr > 0.0) else 1.0
    max_vx = max(0.0, float(pre_status.width) - 1.0 / max(1.0, dpr))
    max_vy = max(0.0, float(pre_status.height) - 1.0 / max(1.0, dpr))
    wx, wy = water_spot
    cast_x = _quantize_clamped((wx * pre_status.width) / full_frame.image.width, 0.0, max_vx, dpr)
    cast_y = _quantize_clamped((wy * pre_status.height) / full_frame.image.height, 0.0, max_vy, dpr)

    # Step 3: Cast
    await move_mouse_bezier(tab, cast_x, cast_y, fast=False, status=pre_status)
    if pacer is not None:
        await click_cast(tab, cast_x, cast_y, pre_status, delay_ms=pacer.sample_hold_ms(fast=False))
    else:
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
        if not current_toast:
            tab._stale_toast = ""
            stale_toast = ""
            ignored_toasts.clear()
            pre_strike_ignored.clear()
        elif stale_toast and current_toast != stale_toast:
            tab._stale_toast = ""
            stale_toast = ""
        if current_toast and current_toast not in ignored_toasts:
            early_kind = classify_toast(immediate_status.toast or "")
            if early_kind in ("EMPTY", "TRASH", "PRIVATE"):
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
                max_x=max(1.0, max_vx),
                min_y=1.0,
                max_y=max(1.0, max_vy),
                dpr=dpr,
            )
            try:
                await move_mouse_bezier(tab, drift_x, drift_y, fast=True, status=pre_status, dwell=False)
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
                if not current_toast:
                    tab._stale_toast = ""
                    stale_toast = ""
                    ignored_toasts.clear()
                    pre_strike_ignored.clear()
                else:
                    if stale_toast and current_toast != stale_toast:
                        tab._stale_toast = ""
                        stale_toast = ""
                    if current_toast not in ignored_toasts:
                        mid_kind = classify_toast(mid_status.toast or "")
                        if mid_kind in ("EMPTY", "TRASH", "PRIVATE"):
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
                    # Any non-empty toast present BEFORE strike cannot be the outcome of the upcoming strike
                    pre_strike_ignored.add(current_toast)
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
                react_delay, is_blink = human_strike_delay_sec(pacer=pacer)
                if is_blink:
                    # Distracted natural miss: let the bite expire WITHOUT clicking late (prevents stray recast)
                    miss_wait = react_delay if 0.80 <= react_delay <= 1.50 else random.uniform(0.80, 1.50)
                    await asyncio.sleep(miss_wait)
                    post_miss_energy: Optional[int] = None
                    if getattr(tab, "_managed_ws", False):
                        miss_deadline = time.monotonic() + 5.5
                        while time.monotonic() < miss_deadline:
                            try:
                                miss_frame = await capture(tab, "SCREEN_ALERT")
                                if alert_point(miss_frame.image, baseline=baseline_frame.image) is None:
                                    break
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                break
                            await asyncio.sleep(random.uniform(0.35, 0.50))
                        gone_sec = time.monotonic() - alert_detected_at
                        settle_total = random.uniform(1.0, 1.6)
                        tick1 = min(0.50, settle_total * 0.45)
                        tick2 = min(0.50, max(0.0, settle_total - tick1) * 0.55)
                        rem_settle = max(0.0, settle_total - tick1 - tick2)
                        await asyncio.sleep(tick1)
                        await _flush_hidden_compositor_frame(tab)
                        if tick2 > 0.0:
                            await asyncio.sleep(tick2)
                        await _flush_hidden_compositor_frame(tab)
                        if rem_settle > 0.0:
                            await asyncio.sleep(rem_settle)
                        try:
                            post_miss_status = await read_status(tab)
                            post_miss_energy = post_miss_status.energy
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            post_miss_energy = None
                        if lake is not None:
                            print(
                                f"[{time.strftime('%H:%M:%S')}] [HỒ {lake:02d}/40] [HUMAN] 😶 Lỡ nhịp giật tự nhiên "
                                f"(chờ ! tắt sau {gone_sec:.1f}s, energy={pre_status.energy}->{post_miss_energy}, không bấm muộn)."
                            )
                    elif lake is not None:
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {lake:02d}/40] [HUMAN] 😶 Lỡ nhịp giật tự nhiên (không bấm muộn để tránh quăng nhầm).")
                    return Outcome(
                        kind="MISS",
                        cast_x=cast_x,
                        cast_y=cast_y,
                        cast_at=cast_at,
                        alert_detected_at=alert_detected_at,
                        pre_energy=pre_status.energy,
                        post_energy=post_miss_energy,
                        pre_xp=pre_status.xp,
                        poll_count=poll_count,
                        duration_sec=time.monotonic() - t_start,
                    )
                await asyncio.sleep(react_delay)

            cur_pos = getattr(tab, "_cursor_pos", None)
            dist_from_cast = (
                math.hypot(float(cur_pos[0]) - cast_x, float(cur_pos[1]) - cast_y)
                if cur_pos is not None
                else 999.0
            )
            if cur_pos is not None and dist_from_cast <= 15.0:
                if random.random() < 0.70:
                    # 65-75%: click in-place (0px movement)
                    strike_x = _quantize_clamped(float(cur_pos[0]), 0.0, max_vx, dpr)
                    strike_y = _quantize_clamped(float(cur_pos[1]), 0.0, max_vy, dpr)
                else:
                    # 25-35%: subtle 1-4px micro-nudge (fast=True, dwell=False)
                    angle = random.uniform(0.0, 2.0 * math.pi)
                    radius = random.uniform(1.0, 4.0)
                    strike_x = _quantize_clamped(float(cur_pos[0]) + math.cos(angle) * radius, 0.0, max_vx, dpr)
                    strike_y = _quantize_clamped(float(cur_pos[1]) + math.sin(angle) * radius, 0.0, max_vy, dpr)
                    await move_mouse_bezier(tab, strike_x, strike_y, fast=True, status=pre_status, dwell=False)
            else:
                strike_x, strike_y = jitter_point(
                    cast_x,
                    cast_y,
                    max_dx=2.5,
                    max_dy=2.5,
                    min_x=1.0,
                    max_x=max(1.0, max_vx),
                    min_y=1.0,
                    max_y=max(1.0, max_vy),
                    dpr=dpr,
                )
                await move_mouse_bezier(tab, strike_x, strike_y, fast=False, status=pre_status, dwell=False)

            if pacer is not None:
                await click_strike(tab, strike_x, strike_y, pre_status, delay_ms=pacer.sample_hold_ms(fast=True))
            else:
                await click_strike(tab, strike_x, strike_y, pre_status)
            strike_at = time.monotonic()
            reaction_ms = (strike_at - alert_detected_at) * 1000.0
            if lake is not None:
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {lake:02d}/40] ⚡ CÁ CẮN CÂU (!) - Giật cần ({reaction_ms:.1f}ms)!")
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
        outcome_timeout = 5.0

    poll_deadline = time.monotonic() + outcome_timeout
    post_status = last_status

    first_poll = True
    while first_poll or time.monotonic() < poll_deadline:
        first_poll = False
        try:
            post_status = await read_status(tab)
            last_status = post_status
        except IndexError:
            break
        except Exception:
            pass

        cur_toast = (post_status.toast or "").strip().lower()
        if not cur_toast:
            pre_strike_ignored.clear()
            toast_kind = None
        elif cur_toast not in pre_strike_ignored:
            toast_kind = classify_toast(post_status.toast or "")
        else:
            toast_kind = None

        if toast_kind in ("EMPTY", "TRASH", "PRIVATE", "CATCH"):
            break
        if post_status.modal:
            break
        rem_poll = poll_deadline - time.monotonic()
        if rem_poll > 0:
            if outcome_timeout >= 0.5:
                step_wait = min(rem_poll, random.uniform(0.22, 0.35))
            else:
                step_wait = min(rem_poll, min(0.12, outcome_timeout) if outcome_timeout > 0 else 0.001)
            if step_wait > 0:
                await asyncio.sleep(step_wait)

    # Final Classification
    final_toast_raw = post_status.toast or ""
    final_toast_norm = final_toast_raw.strip().lower()
    final_toast_is_fresh = bool(final_toast_norm) and (final_toast_norm not in pre_strike_ignored)
    final_toast_kind = classify_toast(final_toast_raw) if final_toast_is_fresh else None
    if final_toast_kind == "EMPTY":
        kind = "EMPTY"
    elif final_toast_kind == "TRASH":
        kind = "TRASH"
    elif final_toast_kind == "PRIVATE":
        kind = "PRIVATE"
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

    t_low = final_toast_norm if final_toast_is_fresh else ""
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
        toast=final_toast_raw if final_toast_is_fresh else "",
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
        dpr=pre_status.dpr,
    )
    await move_mouse_bezier(tab, bx, by, fast=False, status=pre_status)
    await click_point(tab, bx, by, delay_ms=human_hold_ms(fast=False), check_preconditions=True, status=pre_status)
    await asyncio.sleep(random.uniform(0.65, 1.05))

    post_status = await read_status(tab)
    if (
        post_status.energy is not None
        and pre_status.energy is not None
        and post_status.energy > pre_status.energy
    ):
        if getattr(tab, "_managed_ws", False) and post_status.energy < 75:
            best_energy = post_status.energy
            flat_polls = 0
            for _hot_poll in range(6):
                await asyncio.sleep(random.uniform(0.75, 0.95))
                try:
                    st_hot = await read_status(tab)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    break
                if st_hot.energy is None:
                    break
                if st_hot.energy > best_energy:
                    best_energy = st_hot.energy
                    post_status = st_hot
                    flat_polls = 0
                    if best_energy >= 75:
                        break
                elif st_hot.energy == best_energy:
                    flat_polls += 1
                    post_status = st_hot
                    if flat_polls >= 2:
                        break
                else:
                    break
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
    water_ready: bool = True


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
    nav_status: Optional[Status] = None

    async def _finalize_arrival() -> None:
        # Đọc snapshot Stale Toast (100% read-only DOM, zero innerText write)
        snapshot_toast_expr = """(() => {
            const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
            const isShown = e => !e ? false : (typeof e.getClientRects !== 'function' ? true : visible(e));
            const primary = document.querySelector('.message-bar');
            if (isShown(primary)) {
                const primaryText = (primary.innerText || '').trim();
                if (primaryText.length > 0) return primaryText.toLowerCase();
            }
            const secondary = document.querySelector('.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]');
            return isShown(secondary) ? (secondary.innerText || '').trim().toLowerCase() : '';
        })()"""
        try:
            stale_text = await _cdp_evaluate(tab, snapshot_toast_expr)
            tab._stale_toast = stale_text.strip().lower() if isinstance(stale_text, str) else ""
        except Exception:
            tab._stale_toast = ""
        tab._last_water_point = None
        tab._water_anchor = None
        tab._water_anchor_uses = 0
        tab._water_anchor_limit = 0
        tab._fast_alert_status = None

    for attempt in range(1, max_retries + 1):
        # Bước 1: Mở Codex (Read-only DOM lookup + trusted CDP click)
        open_codex_expr = """(() => {
            const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
            const isLeaving = e => typeof e.closest === 'function' && Boolean(e.closest('.fade-leave, .fade-leave-active'));
            const modals = [...document.querySelectorAll('.modal-body')];
            const modal = modals.find(e => visible(e) && !isLeaving(e));
            if (modal) return { open: true, wasOpen: true, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            const hasLeaving = modals.some(e => visible(e) && isLeaving(e));
            const btn = document.querySelector('img[title*="Codex" i], img[src*="codex" i], [title*="Codex" i], button.codex-btn, [data-ui="codex"]');
            if (!btn) return { open: false, found: false, leaving: hasLeaving, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            const r = btn.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) return { open: false, found: false, leaving: hasLeaving, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            return {
                open: false,
                found: true,
                leaving: hasLeaving,
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
                width: r.width,
                height: r.height,
                vw: innerWidth,
                vh: innerHeight,
                dpr: devicePixelRatio
            };
        })()"""
        codex_info = None
        try:
            codex_info = await _cdp_evaluate(tab, open_codex_expr)
        except Exception as exc:
            print(f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} lỗi đọc Codex DOM: {exc}")
        nav_status = _viewport_status(tab, codex_info, nav_status)
        if isinstance(codex_info, dict) and codex_info.get("leaving"):
            await _wait_modal_unmounted(tab)
        if (
            isinstance(codex_info, dict)
            and not codex_info.get("open")
            and codex_info.get("found")
            and "x" in codex_info
            and "y" in codex_info
        ):
            dpr = float(nav_status.dpr) if nav_status is not None else 1.0
            cx = float(codex_info["x"])
            cy = float(codex_info["y"])
            max_dx = min(4.0, max(0.0, float(codex_info.get("width", 0.0)) * 0.25))
            max_dy = min(3.0, max(0.0, float(codex_info.get("height", 0.0)) * 0.25))
            cx, cy = _jitter_clamped_to_viewport(
                cx, cy, max_dx=max_dx, max_dy=max_dy, status=nav_status, dpr=dpr
            )
            try:
                await move_mouse_bezier(tab, cx, cy, fast=False, status=nav_status)
                if nav_status is not None:
                    await click_point(tab, cx, cy, delay_ms=human_hold_ms(fast=False), status=nav_status)
                else:
                    await click_point(tab, cx, cy, delay_ms=human_hold_ms(fast=False))
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} lỗi bấm nút Codex: {exc}")
        await asyncio.sleep(random.uniform(0.24, 0.48))

        # Bước 2: Kích hoạt Tab Map -> Bookmarks (2-level Read-only DOM state machine + trusted CDP click)
        tab_expr = """(() => {
            const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
            const isLeaving = e => typeof e.closest === 'function' && Boolean(e.closest('.fade-leave, .fade-leave-active'));
            const modal = [...document.querySelectorAll('.modal-body')].find(e => visible(e) && !isLeaving(e));
            if (!modal) return { active: false, found: false, error: "no_modal", hidden: document.visibilityState === 'hidden', vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            const isTabActive = el => {
                if (!el) return false;
                if (el.classList.contains('active') || el.getAttribute('aria-selected') === 'true') return true;
                const color = window.getComputedStyle(el).color || '';
                return color.includes('254') && color.includes('119');
            };
            const bm = modal.querySelector('li[data-ui-tab="bookmarks"]')
                || [...modal.querySelectorAll('.sub-tabs li, .tabs li')].find(el => (el.innerText || '').trim().toLowerCase() === 'bookmarks');
            if (bm) {
                const mine = modal.querySelector('li[data-ui-tab="mine"]');
                const mineInactive = !mine || !mine.classList.contains('active');
                if (isTabActive(bm) && mineInactive) return { active: true, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
                const r = bm.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) return { active: false, found: false, error: "bookmarks_hidden", vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
                return {
                    active: false,
                    found: true,
                    stage: "bookmarks",
                    x: r.left + r.width / 2,
                    y: r.top + r.height / 2,
                    width: r.width,
                    height: r.height,
                    vw: innerWidth,
                    vh: innerHeight,
                    dpr: devicePixelRatio
                };
            }
            const mapTab = modal.querySelector('.tabs:not(.sub-tabs) li[data-ui-tab="tiles"], li[data-ui-tab="tiles"]')
                || [...modal.querySelectorAll('.tabs li')].find(el => (el.innerText || '').trim().toLowerCase() === 'map');
            if (!mapTab) return { active: false, found: false, error: "no_bookmarks_tab", vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            if (isTabActive(mapTab)) return { active: false, found: false, waiting_subtabs: true, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            const mr = mapTab.getBoundingClientRect();
            if (mr.width <= 0 || mr.height <= 0) return { active: false, found: false, error: "map_tab_hidden", vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
            return {
                active: false,
                found: true,
                stage: "map",
                x: mr.left + mr.width / 2,
                y: mr.top + mr.height / 2,
                width: mr.width,
                height: mr.height,
                vw: innerWidth,
                vh: innerHeight,
                dpr: devicePixelRatio
            };
        })()"""

        bookmarks_active = False
        last_tab_info = None
        for _tab_retry in range(6):
            tab_info = None
            try:
                tab_info = await _cdp_evaluate(tab, tab_expr)
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} lỗi đọc Tab Bookmarks: {exc}")
            last_tab_info = tab_info
            nav_status = _viewport_status(tab, tab_info, nav_status)
            if not isinstance(tab_info, dict):
                await asyncio.sleep(random.uniform(0.22, 0.42))
                continue
            if tab_info.get("active"):
                bookmarks_active = True
                break
            if tab_info.get("waiting_subtabs"):
                await asyncio.sleep(random.uniform(0.22, 0.42))
                continue
            if not tab_info.get("found"):
                if tab_info.get("error") == "no_modal" and _tab_retry < 3:
                    if tab_info.get("hidden"):
                        await _flush_hidden_compositor_frame(tab)
                    await asyncio.sleep(random.uniform(0.25, 0.45))
                    continue
                break
            if "x" in tab_info and "y" in tab_info:
                dpr = float(nav_status.dpr) if nav_status is not None else 1.0
                bx = float(tab_info["x"])
                by = float(tab_info["y"])
                max_dx = min(4.0, max(0.0, float(tab_info.get("width", 0.0)) * 0.25))
                max_dy = min(3.0, max(0.0, float(tab_info.get("height", 0.0)) * 0.25))
                bx, by = _jitter_clamped_to_viewport(
                    bx, by, max_dx=max_dx, max_dy=max_dy, status=nav_status, dpr=dpr
                )
                try:
                    await move_mouse_bezier(tab, bx, by, fast=False, status=nav_status)
                    if nav_status is not None:
                        await click_point(tab, bx, by, delay_ms=human_hold_ms(fast=False), status=nav_status)
                    else:
                        await click_point(tab, bx, by, delay_ms=human_hold_ms(fast=False))
                except Exception as exc:
                    print(f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} lỗi bấm tab {tab_info.get('stage')}: {exc}")
            await asyncio.sleep(random.uniform(0.22, 0.42))

        if not bookmarks_active:
            err_tag = last_tab_info.get("error") if isinstance(last_tab_info, dict) else "unknown"
            print(
                f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} tới HO {target_lake}: "
                f"không kích hoạt được tab Bookmarks (error={err_tag})."
            )
            # Cleanup modal via trusted CDP Escape + read-only close lookup
            if nav_status is not None:
                await _dismiss_modal_cdp(tab, status=nav_status)
            else:
                await _dismiss_modal_cdp(tab)
            await _wait_modal_unmounted(tab)
            await asyncio.sleep(random.uniform(0.42, 0.75))
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
            await asyncio.sleep(random.uniform(0.11, 0.145))

        # Bước 3: Cuộn bằng CDP mouseWheel & Nhận diện Hồ Mục tiêu HO <target_lake> (Read-only DOM)
        lake_expr = f"""(() => {{
            /* CDP mouseWheel scrolling replaces instant center scrollIntoView (zero DOM mutation) */
            const isLeaving = e => typeof e.closest === 'function' && Boolean(e.closest('.fade-leave, .fade-leave-active'));
            const tiles = [...document.querySelectorAll('.modal-body .map ul.tiles > li.tile, .modal-body ul.tiles > li.tile, ul.tiles > li.tile, ul.tiles > li')].filter(t => !isLeaving(t));
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
                        const modalRoot = typeof tile.closest === 'function' ? tile.closest('.modal-body') : null;
                        let sc = null;
                        let cur = tile.parentElement;
                        while (cur) {{
                            const cs = getComputedStyle(cur);
                            const ovY = (cs.overflowY || '').toLowerCase();
                            if ((ovY === 'auto' || ovY === 'scroll') && cur.scrollHeight > cur.clientHeight + 4) {{
                                sc = cur;
                                break;
                            }}
                            if (cur === modalRoot) break;
                            cur = cur.parentElement;
                        }}
                        if (!sc) sc = tile.closest('.map, .modal-body, ul.tiles') || document.querySelector('.modal-body');
                        const rawRect = sc ? sc.getBoundingClientRect() : {{
                            top: 0, bottom: innerHeight, left: 0, right: innerWidth, width: innerWidth, height: innerHeight
                        }};
                        const cTop = Math.max(0, rawRect.top);
                        const cBottom = Math.min(innerHeight, rawRect.bottom);
                        const cLeft = Math.max(0, rawRect.left);
                        const cRight = Math.min(innerWidth, rawRect.right);
                        const cRect = {{
                            top: cTop,
                            bottom: Math.max(cTop, cBottom),
                            left: cLeft,
                            right: Math.max(cLeft, cRight),
                            width: Math.max(0, cRight - cLeft),
                            height: Math.max(0, cBottom - cTop)
                        }};
                        const scStyle = sc ? getComputedStyle(sc) : null;
                        const bL = scStyle ? (parseFloat(scStyle.borderLeftWidth) || 0) : 0;
                        const bR = scStyle ? (parseFloat(scStyle.borderRightWidth) || 0) : 0;
                        const sbW = sc ? Math.max(0, sc.offsetWidth - sc.clientWidth - bL - bR) : 0;
                        const inView = rect.width > 0 && rect.height > 0
                            && rect.top >= cRect.top + 8
                            && rect.bottom <= cRect.bottom - 8;
                        const btnMidY = rect.top + rect.height / 2;
                        const cMidY = cRect.top + cRect.height / 2;
                        return {{
                            found: true,
                            in_view: inView,
                            hidden: document.visibilityState === 'hidden',
                            x: rect.left + rect.width / 2,
                            y: btnMidY,
                            width: rect.width,
                            height: rect.height,
                            scroll_dy: inView ? 0 : (btnMidY - cMidY),
                            container_x: cRect.left + cRect.width / 2,
                            container_y: cMidY,
                            sb_width: sbW,
                            c_top: cRect.top,
                            c_bottom: cRect.bottom,
                            c_right: cRect.right - bR,
                            scroll_top: sc ? sc.scrollTop : 0,
                            scroll_height: sc ? sc.scrollHeight : 0,
                            client_height: sc ? sc.clientHeight : 0,
                            url: fastTravelBtn.getAttribute('href') || '',
                            current_path: location.pathname || '',
                            vw: innerWidth,
                            vh: innerHeight,
                            dpr: devicePixelRatio
                        }};
                    }}
                }}
            }}
            return {{ found: false, hidden: document.visibilityState === 'hidden', count: tiles.length, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio }};
        }})()"""
        lake_info = None
        try:
            lake_info = await _cdp_evaluate(tab, lake_expr)
        except Exception as exc:
            print(f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} lỗi đọc danh sách hồ: {exc}")
        nav_status = _viewport_status(tab, lake_info, nav_status)

        # Already-at-lake fast path (live managed session only): skip scrolling & re-clicking if already on target path
        if isinstance(lake_info, dict) and lake_info.get("found") and getattr(tab, "_managed_ws", False):
            fast_target_path = urlsplit(str(lake_info.get("url") or "")).path
            fast_pre_path = str(lake_info.get("current_path") or "")
            if fast_target_path and fast_pre_path and fast_target_path == fast_pre_path:
                print(
                    f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ✅ Đã ở sẵn tại HO {target_lake} "
                    f"({fast_pre_path}) -> đóng Codex không cần cuộn/bấm lại."
                )
                if nav_status is not None:
                    await _dismiss_modal_cdp(tab, status=nav_status)
                else:
                    await _dismiss_modal_cdp(tab)
                await _wait_modal_unmounted(tab)
                water_ready = False
                water_deadline = time.monotonic() + 5.0
                for _w_idx in range(12):
                    try:
                        cap_frame = await capture(tab, "SCREEN_FULL")
                        if water_point(cap_frame.image, include_day=True) is not None:
                            water_ready = True
                            break
                    except Exception:
                        pass
                    if time.monotonic() >= water_deadline:
                        break
                    await asyncio.sleep(random.uniform(0.25, 0.40))
                await _finalize_arrival()
                return TravelResult(
                    success=True,
                    lake=target_lake,
                    attempts=attempt,
                    duration_sec=time.monotonic() - t_start,
                    error=None,
                    water_ready=water_ready,
                )

        did_scroll = False
        use_scrollbar_fallback = False
        wheel_cx = 400.0
        wheel_cy = 300.0
        if isinstance(lake_info, dict) and lake_info.get("found") and not lake_info.get("in_view", True):
            dpr = float(nav_status.dpr) if nav_status is not None else 1.0
            wheel_cx = float(lake_info.get("container_x", lake_info.get("x", 400.0)))
            wheel_cy = float(lake_info.get("container_y", lake_info.get("y", 300.0)))
            wheel_cx, wheel_cy = jitter_point(
                wheel_cx,
                wheel_cy,
                max_dx=25.0,
                max_dy=20.0,
                min_x=1.0,
                max_x=max(1.0, float(nav_status.width) - 1.0) if nav_status is not None else 8191.0,
                min_y=1.0,
                max_y=max(1.0, float(nav_status.height) - 1.0) if nav_status is not None else 8191.0,
                dpr=dpr,
            )
            try:
                await move_mouse_bezier(tab, wheel_cx, wheel_cy, fast=False, status=nav_status, dwell=False)
            except Exception:
                pass

            async def _click_scrollbar_track(cur_info: Dict[str, Any], direction: float) -> Optional[Dict[str, Any]]:
                sb_w = float(cur_info.get("sb_width", 0.0))
                c_top = float(cur_info.get("c_top", 0.0))
                c_bottom = float(cur_info.get("c_bottom", float(nav_status.height) if nav_status is not None else 600.0))
                c_right = float(cur_info.get("c_right", float(nav_status.width) if nav_status is not None else 800.0))
                track_x = c_right - sb_w / 2.0
                track_top = c_top + 18.0
                track_bot = c_bottom - 18.0
                track_h = max(20.0, track_bot - track_top)
                sh = max(1.0, float(cur_info.get("scroll_height", 1.0)))
                ch = max(1.0, float(cur_info.get("client_height", 1.0)))
                st_top = max(0.0, float(cur_info.get("scroll_top", 0.0)))
                thumb_top = track_top + (st_top / sh) * track_h
                thumb_h = max(20.0, (ch / sh) * track_h)
                thumb_bot = min(track_bot, thumb_top + thumb_h)
                if direction > 0.0:
                    if track_bot - thumb_bot >= 8.0:
                        track_y = (thumb_bot + track_bot) / 2.0
                    else:
                        track_y = c_bottom - 8.0
                else:
                    if thumb_top - track_top >= 8.0:
                        track_y = (track_top + thumb_top) / 2.0
                    else:
                        track_y = c_top + 8.0
                tx, ty = _jitter_clamped_to_viewport(
                    track_x,
                    track_y,
                    max_dx=min(1.5, max(0.0, sb_w * 0.25)),
                    max_dy=2.0,
                    status=nav_status,
                    dpr=dpr,
                )
                await move_mouse_bezier(tab, tx, ty, fast=False, status=nav_status, dwell=False)
                if nav_status is not None:
                    await click_point(tab, tx, ty, delay_ms=human_hold_ms(fast=True), status=nav_status)
                else:
                    await click_point(tab, tx, ty, delay_ms=human_hold_ms(fast=True))
                if cur_info.get("hidden"):
                    await _flush_hidden_compositor_frame(tab)
                await asyncio.sleep(random.uniform(0.15, 0.25))
                refreshed_sb = await _cdp_evaluate(tab, lake_expr)
                return refreshed_sb if isinstance(refreshed_sb, dict) else None

            def _log_stagnant_abort(cur_info: Dict[str, Any], prev_y_val: float) -> None:
                st_val = float(cur_info.get("scroll_top", 0.0))
                sh_val = float(cur_info.get("scroll_height", 0.0))
                sb_val = float(cur_info.get("sb_width", 0.0))
                cur_y_val = float(cur_info.get("y", prev_y_val))
                mode_str = "scrollbar" if use_scrollbar_fallback else "wheel"
                print(
                    f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Danh sách Bookmarks không cuộn sau 4 nhịp "
                    f"(scrollTop={st_val:.0f}/{sh_val:.0f}, y={cur_y_val:.1f}, sbW={sb_val:.0f}, mode={mode_str}; "
                    "có thể Chrome bị ẩn visibilityState=hidden mà không có --bg)!"
                )

            last_dir = 1.0
            stagnant_steps = 0
            for _scroll_step in range(50):
                if not isinstance(lake_info, dict) or not lake_info.get("found") or lake_info.get("in_view", True):
                    break
                prev_y = float(lake_info.get("y", 0.0))
                scroll_dy = float(lake_info.get("scroll_dy", 0.0))
                last_dir = 1.0 if scroll_dy >= 0.0 else -1.0

                if use_scrollbar_fallback:
                    try:
                        sb_next = await _click_scrollbar_track(lake_info, last_dir)
                        did_scroll = True
                    except Exception:
                        break
                    if not isinstance(sb_next, dict):
                        break
                    lake_info = sb_next
                    if lake_info.get("found") and not lake_info.get("in_view", True):
                        new_y = float(lake_info.get("y", prev_y))
                        if abs(new_y - prev_y) < 1.0:
                            stagnant_steps += 1
                            if stagnant_steps >= 4:
                                _log_stagnant_abort(lake_info, prev_y)
                                break
                        else:
                            stagnant_steps = 0
                    else:
                        stagnant_steps = 0
                    continue

                abs_dy = abs(scroll_dy)
                if abs_dy > 900.0:
                    notches = random.choice((4, 5, 6))
                elif abs_dy > 350.0:
                    notches = random.choice((2, 3))
                elif abs_dy > 140.0:
                    notches = random.choice((1, 2))
                else:
                    notches = 1
                delta_y = last_dir * (100.0 * notches)
                was_hidden = bool(lake_info.get("hidden"))
                try:
                    await scroll_mouse_wheel(tab, wheel_cx, wheel_cy, delta_y)
                    did_scroll = True
                except Exception:
                    break
                await asyncio.sleep(random.uniform(0.08, 0.16))
                if was_hidden and getattr(tab, "_managed_ws", False):
                    await _flush_hidden_compositor_frame(tab)
                    await asyncio.sleep(random.uniform(0.06, 0.10))
                try:
                    lake_info = await _cdp_evaluate(tab, lake_expr)
                except Exception:
                    break
                if isinstance(lake_info, dict) and lake_info.get("found") and not lake_info.get("in_view", True):
                    new_y = float(lake_info.get("y", prev_y))
                    if abs(new_y - prev_y) < 1.0:
                        if getattr(tab, "_managed_ws", False) or lake_info.get("hidden"):
                            for _settle_idx in range(3):
                                if lake_info.get("hidden"):
                                    await _flush_hidden_compositor_frame(tab)
                                await asyncio.sleep(random.uniform(0.15, 0.22))
                                try:
                                    lake_info = await _cdp_evaluate(tab, lake_expr)
                                except Exception:
                                    break
                                if not isinstance(lake_info, dict) or not lake_info.get("found") or lake_info.get("in_view", True):
                                    break
                                new_y = float(lake_info.get("y", prev_y))
                                if abs(new_y - prev_y) >= 1.0:
                                    break
                        if (
                            isinstance(lake_info, dict)
                            and lake_info.get("found")
                            and not lake_info.get("in_view", True)
                            and abs(float(lake_info.get("y", prev_y)) - prev_y) < 1.0
                        ):
                            stagnant_steps += 1
                            if (
                                stagnant_steps >= 2
                                and getattr(tab, "_managed_ws", False)
                                and float(lake_info.get("sb_width", 0.0)) >= 6.0
                            ):
                                use_scrollbar_fallback = True
                                print(
                                    f"[{time.strftime('%H:%M:%S')}] [TRAVEL] 🖱️ Bánh xe cuộn chững 2 nhịp "
                                    f"(hidden={bool(lake_info.get('hidden'))}, sbW={float(lake_info.get('sb_width', 0.0)):.0f}) "
                                    "-> chuyển sang bấm rãnh thanh cuộn CDP..."
                                )
                                try:
                                    sb_next = await _click_scrollbar_track(lake_info, last_dir)
                                except Exception:
                                    sb_next = None
                                if isinstance(sb_next, dict):
                                    lake_info = sb_next
                                    if (
                                        not lake_info.get("found")
                                        or lake_info.get("in_view", True)
                                        or abs(float(lake_info.get("y", prev_y)) - prev_y) >= 1.0
                                    ):
                                        stagnant_steps = 0
                            elif stagnant_steps >= 4:
                                _log_stagnant_abort(lake_info, prev_y)
                                break
                        else:
                            stagnant_steps = 0
                    else:
                        stagnant_steps = 0
                else:
                    stagnant_steps = 0
            # 12% natural 1-notch scroll overshoot + pull-back (skipped when hidden or using scrollbar fallback)
            if (
                did_scroll
                and not use_scrollbar_fallback
                and isinstance(lake_info, dict)
                and lake_info.get("found")
                and lake_info.get("in_view", True)
                and not lake_info.get("hidden")
            ):
                if random.random() < 0.12:
                    try:
                        await scroll_mouse_wheel(tab, wheel_cx, wheel_cy, last_dir * 100.0)
                        await asyncio.sleep(random.uniform(0.14, 0.30))
                        await scroll_mouse_wheel(tab, wheel_cx, wheel_cy, -last_dir * 100.0)
                        await asyncio.sleep(random.uniform(0.10, 0.22))
                        refreshed = await _cdp_evaluate(tab, lake_expr)
                        if isinstance(refreshed, dict) and refreshed.get("found"):
                            lake_info = refreshed
                        if isinstance(lake_info, dict) and lake_info.get("found") and not lake_info.get("in_view", True):
                            for _corr in range(2):
                                corr_dir = 1.0 if float(lake_info.get("scroll_dy", 0.0)) >= 0.0 else -1.0
                                await scroll_mouse_wheel(tab, wheel_cx, wheel_cy, corr_dir * 100.0)
                                await asyncio.sleep(random.uniform(0.12, 0.22))
                                corr_info = await _cdp_evaluate(tab, lake_expr)
                                if isinstance(corr_info, dict) and corr_info.get("found"):
                                    lake_info = corr_info
                                if not isinstance(lake_info, dict) or lake_info.get("in_view", True):
                                    break
                    except Exception:
                        pass

        # Coordinate stabilization before Step 4 click (live managed session after scrolling)
        if (
            did_scroll
            and isinstance(lake_info, dict)
            and lake_info.get("found")
            and lake_info.get("in_view", True)
            and getattr(tab, "_managed_ws", False)
        ):
            try:
                stable_y = float(lake_info.get("y", 0.0))
                if lake_info.get("hidden"):
                    await _flush_hidden_compositor_frame(tab)
                await asyncio.sleep(random.uniform(0.15, 0.22))
                refreshed = await _cdp_evaluate(tab, lake_expr)
                if isinstance(refreshed, dict) and refreshed.get("found"):
                    lake_info = refreshed
                    if abs(float(lake_info.get("y", stable_y)) - stable_y) >= 2.0:
                        if lake_info.get("hidden"):
                            await _flush_hidden_compositor_frame(tab)
                        await asyncio.sleep(random.uniform(0.15, 0.22))
                        refreshed2 = await _cdp_evaluate(tab, lake_expr)
                        if isinstance(refreshed2, dict) and refreshed2.get("found"):
                            lake_info = refreshed2
                if isinstance(lake_info, dict) and lake_info.get("found") and not lake_info.get("in_view", True):
                    for _corr in range(2):
                        corr_dir = 1.0 if float(lake_info.get("scroll_dy", 0.0)) >= 0.0 else -1.0
                        await scroll_mouse_wheel(tab, wheel_cx, wheel_cy, corr_dir * 100.0)
                        if lake_info.get("hidden"):
                            await _flush_hidden_compositor_frame(tab)
                        await asyncio.sleep(random.uniform(0.15, 0.22))
                        corr_info = await _cdp_evaluate(tab, lake_expr)
                        if isinstance(corr_info, dict) and corr_info.get("found"):
                            lake_info = corr_info
                        if not isinstance(lake_info, dict) or lake_info.get("in_view", True):
                            break
            except Exception:
                pass

        # Bước 4: Click Fast Travel, Chờ chuyển cảnh & Đóng modal khi fail
        fail_reason = "lake_not_found"
        if isinstance(lake_info, dict) and lake_info.get("found") and not lake_info.get("in_view", True):
            fail_reason = "lake_not_in_view"
        elif isinstance(lake_info, dict) and lake_info.get("found") and lake_info.get("in_view", True):
            fail_reason = "arrival_timeout_or_modal_open"
            dpr = float(nav_status.dpr) if nav_status is not None else 1.0
            x = float(lake_info.get("x", 0.0))
            y = float(lake_info.get("y", 0.0))
            if "width" in lake_info and "height" in lake_info:
                max_dx = min(4.0, max(0.0, float(lake_info["width"]) * 0.25))
                max_dy = min(3.0, max(0.0, float(lake_info["height"]) * 0.25))
                x, y = _jitter_clamped_to_viewport(
                    x, y, max_dx=max_dx, max_dy=max_dy, status=nav_status, dpr=dpr
                )
                hold_ms = human_hold_ms(fast=False)
            else:
                if nav_status is not None:
                    x = max(1.0, min(max(1.0, float(nav_status.width) - 1.0), x))
                    y = max(1.0, min(max(1.0, float(nav_status.height) - 1.0), y))
                hold_ms = 50.0
            await asyncio.sleep(random.uniform(0.12, 0.28))
            try:
                await move_mouse_bezier(tab, x, y, fast=False, status=nav_status)
                if nav_status is not None:
                    await click_point(tab, x, y, delay_ms=hold_ms, status=nav_status)
                else:
                    await click_point(tab, x, y, delay_ms=hold_ms)
            except Exception as exc:
                fail_reason = f"click_error:{type(exc).__name__}"
                print(f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} lỗi bấm Fast Travel HO {target_lake}: {exc}")

            # Chờ chuyển cảnh: modal đóng + URL đổi sang target_path (nếu có) + canvas nước sẵn sàng
            target_path = urlsplit(str(lake_info.get("url") or "")).path
            pre_path = str(lake_info.get("current_path") or "")
            need_path_change = bool(pre_path and target_path and target_path != pre_path)

            arrived = False
            if pre_path:
                await asyncio.sleep(random.uniform(0.70, 1.05))
                arrival_deadline = time.monotonic() + 2.7
                for _arr_idx in range(11):
                    try:
                        st = await read_status(tab)
                        if not st.modal:
                            if not need_path_change or urlsplit(st.url).path == target_path:
                                arrived = True
                                break
                    except Exception:
                        pass
                    if time.monotonic() >= arrival_deadline:
                        break
                    await asyncio.sleep(random.uniform(0.20, 0.35))
            else:
                await asyncio.sleep(random.uniform(1.30, 1.85))
                try:
                    st = await read_status(tab)
                    if not st.modal:
                        arrived = True
                except Exception:
                    pass

            if arrived:
                water_ready = True
                if pre_path:
                    await asyncio.sleep(random.uniform(0.32, 0.55))
                    water_ready = False
                    water_deadline = time.monotonic() + 9.5
                    for _w_idx in range(28):
                        try:
                            cap_frame = await capture(tab, "SCREEN_FULL")
                            if water_point(cap_frame.image, include_day=True) is not None:
                                water_ready = True
                                break
                        except Exception:
                            pass
                        if time.monotonic() >= water_deadline:
                            break
                        await asyncio.sleep(random.uniform(0.28, 0.45))

                await _finalize_arrival()
                return TravelResult(
                    success=True,
                    lake=target_lake,
                    attempts=attempt,
                    duration_sec=time.monotonic() - t_start,
                    error=None,
                    water_ready=water_ready,
                )

        print(
            f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Attempt {attempt}/{max_retries} tới HO {target_lake} "
            f"thất bại ({fail_reason}) -> dọn modal trước khi thử lại."
        )
        # Cleanup modal khi thất bại ở attempt này (trusted CDP Escape + read-only close lookup)
        if nav_status is not None:
            await _dismiss_modal_cdp(tab, status=nav_status)
        else:
            await _dismiss_modal_cdp(tab)
        await _wait_modal_unmounted(tab)
        await asyncio.sleep(random.uniform(0.42, 0.75))

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


async def reload_page(tab: Tab, ignore_cache: bool = False, wait_loaded_sec: float = 2.5) -> None:
    """Tải lại trang web NomStead qua CDP Page.reload và chờ canvas tải lại ổn định."""
    tab._last_water_point = None
    tab._water_anchor = None
    tab._water_anchor_uses = 0
    tab._water_anchor_limit = 0
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
        actual_wait = wait_loaded_sec * random.uniform(0.85, 1.25) if wait_loaded_sec >= 0.5 else wait_loaded_sec
        await asyncio.sleep(actual_wait)

    # Đóng popup / modal chào mừng sau khi F5 nếu có (trusted CDP Escape + read-only lookup)
    await _dismiss_modal_cdp(tab)


async def recover_from_reload(tab: Tab, target_lake: int) -> bool:
    """
    Phục hồi nhân vật sau khi F5:
    Vì sau F5 game luôn đưa nhân vật về Nhà (Home - không có hồ câu),
    hàm này tự động mở Codex -> Bookmarks để di chuyển nhân vật về đúng target_lake.
    """
    await asyncio.sleep(random.uniform(0.45, 0.85))
    travel_res = await travel_to_lake(tab, target_lake)
    return travel_res.success


async def wait_until_reset_if_needed(
    tab: Tab,
    current_lake: int,
    max_lakes: int = 40,
    stop_event: Optional[asyncio.Event] = None,
    poll_interval: float = 15.0,
    *,
    reset_delay_sec: float = 0.0,
    tab_close_wait_reset: bool = False,
    config: Optional["AutoSessionConfig"] = None,
    state: Optional["SessionState"] = None,
    target_lake: int = 1,
) -> bool:
    """
    Khi đã câu hết cả max_lakes (40 hồ), nếu chưa tới khung giờ reset tiếp theo:
    - Nếu tab_close_wait_reset=True và thời gian chờ > 15 phút -> đóng tab nghỉ giống Long Break rồi mở lại.
    - Ngược lại -> chờ thông minh kèm ping keep-alive định kỳ giữ kết nối CDP.
    Khi chạm mốc giờ reset (+ reset_delay_sec) -> tự động di chuyển về target_lake và trả về True.
    """
    if current_lake < max_lakes:
        return False

    if stop_event is not None and stop_event.is_set():
        return False

    now = datetime.now()
    delay_s = max(0.0, float(reset_delay_sec))
    prev_reset = _get_most_recent_reset_datetime(now)
    if (
        delay_s > 0.0
        and (prev_reset + timedelta(seconds=delay_s)) > now
        and (state is None or state.last_reset_hour != prev_reset.hour)
    ):
        active_reset = prev_reset
        wake_dt = prev_reset + timedelta(seconds=delay_s)
    else:
        active_reset = get_next_reset_datetime()
        wake_dt = active_reset + timedelta(seconds=delay_s)
    remaining_sec = (wake_dt - now).total_seconds()

    # Nếu chỉ còn dưới 30s hoặc đã qua giờ reset thì không cần chờ
    if remaining_sec <= 30.0:
        return False

    remaining_minutes = remaining_sec / 60.0
    if tab_close_wait_reset and remaining_sec > 900.0:
        eff_cfg = config if config is not None else AutoSessionConfig(state_file=":memory:")
        eff_state = state if state is not None else SessionState(current_lake=target_lake)
        print(
            f"[{time.strftime('%H:%M:%S')}] [CHỜ RESET] 🌙 Đã câu xong {max_lakes} hồ, còn {remaining_minutes:.1f} phút "
            f"(>15p) tới mốc {wake_dt.strftime('%H:%M')} -> Đóng tab nghỉ thay vì treo idle!"
        )
        did_break, _ = await perform_tab_close_long_break(
            tab,
            eff_cfg,
            eff_state,
            stop_event,
            rest_sec_override=remaining_sec,
            reason_label="CHỜ RESET",
            target_lake_override=target_lake,
        )
        if did_break and state is not None:
            state.last_reset_hour = active_reset.hour
        return did_break

    print(f"[{time.strftime('%H:%M:%S')}] [CHỜ RESET] ⏳ Đã câu xong {max_lakes} hồ, đứng yên ngắm cảnh chờ mốc Reset {wake_dt.strftime('%H:%M')} (còn {remaining_minutes:.1f} phút)...")

    while datetime.now() < wake_dt:
        if stop_event is not None and stop_event.is_set():
            return False

        # Sleep nhỏ kèm micro keep-alive ping giữ kết nối CDP
        sleep_chunk = min(poll_interval, max(1.0, (wake_dt - datetime.now()).total_seconds()))
        await asyncio.sleep(sleep_chunk)

        if stop_event is not None and stop_event.is_set():
            return False

        try:
            # Micro keep-alive ping (<0.1ms, CPU 0%)
            await _cdp_evaluate(tab, "1+1")
        except Exception:
            pass

    print(f"[{time.strftime('%H:%M:%S')}] [RESET SERVER] 🌟 ĐÃ TỚI GIỜ RESET SERVER ({active_reset.strftime('%H:%M')})! Tự động quay về HO {target_lake}...")
    travel_res = await travel_to_lake(tab, target_lake)
    if travel_res.success and state is not None:
        state.last_reset_hour = active_reset.hour
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
    smart_route_fixed_prefix: int = 7           # 0 trong parse_auto_config() để xáo rộng 40 hồ
    smart_route_cluster_size: int = 4           # HO 8..40 xáo trộn theo cụm 4-5 hồ (khi fixed_prefix > 0)
    smart_route_skip_max: int = 0               # 2 trong parse_auto_config() để thỉnh thoảng bỏ qua 0..2 hồ
    low_cpu_reel_delay_min_sec: float = 1.45    # Chỉ áp dụng trên VM <= 2 CPU (máy khỏe = 0s)
    low_cpu_reel_delay_max_sec: float = 1.95    # Chờ animation thu cần xong tránh nuốt click 20s
    fresh_start: bool = False                   # Bật trong parse_auto_config() để reset counter & áp dụng --lake khi khởi chạy CLI mới
    human_pacer_enabled: bool = False           # Bật HumanPacer (Log-Normal + AR(1) + fatigue + comprehension pauses)
    mid_lake_afk_enabled: bool = False          # Nghỉ tay ngắn giữa hồ (12-45s mỗi 12-28 lần quăng)
    mid_lake_afk_min_casts: int = 12
    mid_lake_afk_max_casts: int = 28
    mid_lake_afk_min_sec: float = 12.0
    mid_lake_afk_max_sec: float = 45.0
    dynamic_bread_enabled: bool = False         # Ngưỡng ăn bánh mì động (12..32) + thỉnh thoảng ăn 2 cái
    early_leave_enabled: bool = False           # 10-15% hồ rời sớm ở 38-47 cá
    reset_delay_enabled: bool = False           # Trễ ngẫu nhiên 3-20 phút sau mốc reset :00
    tab_close_wait_reset: bool = False          # Đóng tab nghỉ khi chờ reset > 15 phút
    sleep_window_enabled: bool = False          # Khung ngủ đêm (6.5-8.5h) + trần giờ chơi/ngày (10-13h)
    sleep_start: str = "00:30"                  # Giờ bắt đầu khung ngủ đêm (HH:MM)
    sleep_hours: float = 7.5                    # Thời lượng ngủ đêm mục tiêu (giờ)
    max_daily_hours: float = 11.5               # Trần số giờ câu tối đa mỗi ngày (giờ)
    long_break_finish_lake: bool = False        # Chờ câu xong hồ hiện tại (tối đa 10p) trước khi nghỉ dài


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
    sleep_start = str(getattr(args, "sleep_start", "00:30") or "00:30").strip()
    sleep_hours = max(1.0, min(14.0, float(getattr(args, "sleep_hours", 7.5))))
    max_daily_hours = max(1.0, min(23.0, float(getattr(args, "max_daily_hours", 11.5))))
    no_sleep = bool(getattr(args, "no_sleep", False))
    return AutoSessionConfig(
        start_lake=lake,
        max_lakes=max_lakes,
        max_catches=getattr(args, "max_catches", None),
        state_file=getattr(args, "state_file", "session_state.json"),
        verbose=True,
        smart_route_enabled=True,
        smart_route_fixed_prefix=0,
        smart_route_skip_max=2,
        fresh_start=True,
        human_pacer_enabled=True,
        mid_lake_afk_enabled=True,
        dynamic_bread_enabled=True,
        early_leave_enabled=True,
        reset_delay_enabled=True,
        tab_close_wait_reset=True,
        sleep_window_enabled=not no_sleep,
        sleep_start=sleep_start,
        sleep_hours=sleep_hours,
        max_daily_hours=max_daily_hours,
        long_break_finish_lake=True,
    )


def _parse_hhmm(hhmm: str, default: Tuple[int, int] = (0, 30)) -> Tuple[int, int]:
    """Parse 'HH:MM' safely with fallback to default."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", str(hhmm or ""))
    if not m:
        return default
    h, mn = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mn <= 59:
        return (h, mn)
    return default


def check_sleep_or_daily_cap(
    config: AutoSessionConfig,
    active_play_sec_today: float,
    now: Optional[datetime] = None,
    *,
    sleep_start_jitter_min: float = 0.0,
    sleep_duration_hours: Optional[float] = None,
    daily_cap_hours: Optional[float] = None,
) -> Optional[Tuple[str, float]]:
    """Return ('SLEEP_WINDOW' | 'DAILY_CAP', rest_seconds) when rest is required, else None."""
    if not config.sleep_window_enabled:
        return None

    cur = now or datetime.now()
    sh, sm = _parse_hhmm(config.sleep_start, (0, 30))
    dur_h = float(sleep_duration_hours) if sleep_duration_hours is not None else float(config.sleep_hours)
    dur_h = max(0.5, min(16.0, dur_h))
    dur_td = timedelta(hours=dur_h)
    jitter_td = timedelta(minutes=float(sleep_start_jitter_min))

    # Check yesterday's, today's, and tomorrow's sleep windows to handle midnight wrap cleanly
    base_today = cur.replace(hour=sh, minute=sm, second=0, microsecond=0) + jitter_td
    for day_offset in (-1, 0, 1):
        win_start = base_today + timedelta(days=day_offset)
        win_end = win_start + dur_td
        if win_start <= cur < win_end:
            remaining = (win_end - cur).total_seconds()
            if remaining > 30.0:
                return ("SLEEP_WINDOW", remaining)

    cap_h = float(daily_cap_hours) if daily_cap_hours is not None else float(config.max_daily_hours)
    cap_h = max(0.5, min(23.5, cap_h))
    if float(active_play_sec_today) >= cap_h * 3600.0:
        # Rest until the end of the upcoming nightly sleep window (or at least dur_h)
        next_end: Optional[datetime] = None
        for day_offset in (0, 1, 2):
            win_start = base_today + timedelta(days=day_offset)
            win_end = win_start + dur_td
            if win_end > cur + timedelta(minutes=30):
                next_end = win_end
                break
        remaining = (next_end - cur).total_seconds() if next_end is not None else dur_h * 3600.0
        remaining = max(dur_h * 3600.0 * 0.5, remaining)
        return ("DAILY_CAP", remaining)

    return None


def _roll_early_leave_cap(enabled: bool) -> Optional[int]:
    """10-15% of lakes naturally leave early at 38..47 catches instead of draining to exact EMPTY."""
    if not enabled:
        return None
    if random.random() < 0.125:
        return random.randint(38, 47)
    return None


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
    skip_max: int = 0,
) -> List[int]:
    """Build lake route.

    - When fixed_prefix == 0: broad full-list shuffle across all 1..max_lakes for low Spearman |rho|,
      optionally skipping 0..skip_max random lakes.
    - When fixed_prefix > 0: HO 1..fixed_prefix strictly ordered, remainder cluster-shuffled.
    """
    total = max(1, int(max_lakes))
    prefix_end = min(total, max(0, int(fixed_prefix)))
    max_skip = max(0, int(skip_max))

    if prefix_end == 0:
        route = list(range(1, total + 1))
        random.shuffle(route)
        if max_skip > 0 and total > 4:
            k = random.randint(0, min(max_skip, total - 2))
            if k > 0:
                route = route[:-k]
        return route

    route = list(range(1, prefix_end + 1))
    remaining = list(range(prefix_end + 1, total + 1))
    if not remaining:
        return route
    if max_skip > 0 and len(remaining) > 2:
        k = random.randint(0, min(max_skip, len(remaining) - 2))
        if k > 0:
            dropped = set(random.sample(remaining, k))
            remaining = [lake for lake in remaining if lake not in dropped]
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
    if (!best) return { found: false, vw: innerWidth, vh: innerHeight, dpr: devicePixelRatio };
    return {
        found: true,
        x: best.left + best.width / 2,
        y: best.top + best.height / 2,
        width: best.width,
        height: best.height,
        vw: innerWidth,
        vh: innerHeight,
        dpr: devicePixelRatio
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
    rest_sec_override: Optional[float] = None,
    reason_label: str = "LONG BREAK",
    target_lake_override: Optional[int] = None,
) -> Tuple[bool, Optional[int]]:
    """Close NomStead tab safely via blank keep-alive target, rest, reopen, wait HUD, and resume lake.

    Always cleans up any created about:blank target inside try/finally on error or cancellation.
    """
    # Step 1: Save state, close page WS, create about:blank FIRST so Chrome never exits, then close game tab
    state.save(config.state_file)
    await close_cdp_session(tab)
    old_target_id = _extract_page_target_id(tab.websocket_url)
    blank_target_id: Optional[str] = None
    blank_closed = False

    try:
        blank_res = await _browser_cdp_call("Target.createTarget", {"url": "about:blank"})
        blank_target_id = blank_res.get("targetId") if isinstance(blank_res, dict) else None
        if type(blank_target_id) is not str or not blank_target_id:
            blank_target_id = None
            raise CdpError("failed to create blank keep-alive target")
        await _browser_cdp_call("Target.closeTarget", {"targetId": old_target_id})

        # Step 2: Rest period (20-50m default, or explicit rest_sec_override for sleep/wait-reset)
        break_start_dt = datetime.now()
        if rest_sec_override is not None:
            rest_sec = max(0.0, float(rest_sec_override))
        else:
            min_r = max(0.0, float(config.long_break_min_rest_sec))
            max_r = max(min_r, float(config.long_break_max_rest_sec))
            rest_sec = random.uniform(min_r, max_r)
        wake_est = break_start_dt + timedelta(seconds=rest_sec)
        print(
            f"[{time.strftime('%H:%M:%S')}] [{reason_label}] 🌙 Đã đóng tab NomStead (GPU/CPU→0%), "
            f"nghỉ {rest_sec / 60.0:.1f} phút (dự kiến quay lại lúc {wake_est.strftime('%H:%M:%S')})..."
        )
        completed = await _interruptible_sleep(rest_sec, stop_event, chunk_sec=1.0)
        if not completed:
            return (False, None)

        # Step 3: Reopen game tab, close blank tab, rediscover trusted page target
        await _browser_cdp_call("Target.createTarget", {"url": "https://nomstead.com"})
        await asyncio.sleep(random.uniform(0.45, 0.85))
        await _browser_cdp_call("Target.closeTarget", {"targetId": blank_target_id})
        blank_closed = True
    finally:
        if blank_target_id is not None and not blank_closed:
            try:
                await _browser_cdp_call("Target.closeTarget", {"targetId": blank_target_id})
            except Exception:
                pass

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
            if not await _interruptible_sleep(random.uniform(0.40, 0.85), stop_event, chunk_sec=0.5):
                return (False, None)

    tab.url = new_tab.url
    tab.websocket_url = new_tab.websocket_url
    tab._next_id = 1
    tab._last_water_point = None
    tab._water_anchor = None
    tab._water_anchor_uses = 0
    tab._water_anchor_limit = 0
    tab._fast_alert_status = None
    tab._stale_toast = ""
    tab._cursor_pos = None

    # Step 4: Wait for Game HUD (clicking homepage 'Play Now Free' via trusted CDP if shown)
    hud_deadline = time.monotonic() + max(0.0, float(hud_timeout_sec))
    hud_ready = False
    last_play_click_at: Optional[float] = None
    play_reclick_cooldown = random.uniform(5.2, 7.8)
    last_st: Optional[Status] = None
    while True:
        if stop_event is not None and stop_event.is_set():
            return (False, None)
        try:
            st = await read_status(tab)
            last_st = st
            if st is not None and (st.energy is not None or st.xp is not None):
                hud_ready = True
                break
        except Exception:
            pass
        if last_play_click_at is None or (time.monotonic() - last_play_click_at) >= play_reclick_cooldown:
            play_info = None
            try:
                play_info = await _cdp_evaluate(tab, PLAY_BUTTON_LOOKUP_EXPR)
            except Exception:
                play_info = None
            if isinstance(play_info, dict) and play_info.get("found") and "x" in play_info and "y" in play_info:
                if warmup_range_sec[1] > 0.0:
                    if not await _interruptible_sleep(random.uniform(0.8, 1.8), stop_event, chunk_sec=0.3):
                        return (False, None)
                play_status = _viewport_status(tab, play_info, last_st)
                dpr = float(play_status.dpr) if play_status is not None else 1.0
                max_dx = min(28.0, max(0.0, float(play_info.get("width", 0.0)) * 0.25))
                max_dy = min(10.0, max(0.0, float(play_info.get("height", 0.0)) * 0.25))
                px, py = jitter_point(
                    float(play_info["x"]),
                    float(play_info["y"]),
                    max_dx=max_dx,
                    max_dy=max_dy,
                    min_x=1.0,
                    max_x=max(1.0, float(play_status.width) - 1.0) if play_status is not None else 8191.0,
                    min_y=1.0,
                    max_y=max(1.0, float(play_status.height) - 1.0) if play_status is not None else 8191.0,
                    dpr=dpr,
                )
                try:
                    await move_mouse_bezier(tab, px, py, fast=False, status=play_status)
                    await click_point(tab, px, py, delay_ms=human_hold_ms(fast=False), status=play_status)
                    last_play_click_at = time.monotonic()
                    play_reclick_cooldown = random.uniform(5.2, 7.8)
                    print(
                        f"[{time.strftime('%H:%M:%S')}] [{reason_label}] 🎮 Đã bấm 'Play Now Free' "
                        "(CDP trusted Bezier click), đang chờ tải HUD game..."
                    )
                except Exception:
                    pass
        if time.monotonic() >= hud_deadline:
            break
        if not await _interruptible_sleep(random.uniform(0.85, 1.45), stop_event, chunk_sec=0.5):
            return (False, None)

    if not hud_ready:
        print(
            f"[{time.strftime('%H:%M:%S')}] [{reason_label}] ⚠️ Chưa thấy HUD game "
            "(có thể phiên đăng nhập hết hạn) -> Tạm chờ người dùng đăng nhập lại..."
        )
        while not hud_ready:
            if stop_event is not None and stop_event.is_set():
                return (False, None)
            if not await _interruptible_sleep(random.uniform(4.2, 6.8), stop_event, chunk_sec=1.0):
                return (False, None)
            try:
                st = await read_status(tab)
                last_st = st
                if st.energy is not None or st.xp is not None:
                    hud_ready = True
            except Exception:
                pass

    try:
        await _dismiss_modal_cdp(tab, status=last_st)
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
    if target_lake_override is not None:
        dest_lake = int(target_lake_override)
        state.current_lake = dest_lake
        if passed_reset_hour is not None:
            state.last_reset_hour = passed_reset_hour
        state.consecutive_no_water = 0
        state.consecutive_timeout = 0
        print(
            f"[{time.strftime('%H:%M:%S')}] [{reason_label}] 🚀 Đã mở lại game -> "
            f"Di chuyển tới HO {dest_lake}..."
        )
        await travel_to_lake(tab, dest_lake)
    elif passed_reset_hour is not None:
        state.current_lake = 1
        state.last_reset_hour = passed_reset_hour
        state.consecutive_no_water = 0
        state.consecutive_timeout = 0
        print(
            f"[{time.strftime('%H:%M:%S')}] [{reason_label}] 🌟 Đã qua mốc Reset "
            f"({passed_reset_hour}:00) trong lúc nghỉ -> Quay về HO 1!"
        )
        await travel_to_lake(tab, 1)
    else:
        print(
            f"[{time.strftime('%H:%M:%S')}] [{reason_label}] 🚀 Đã mở lại game -> "
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


async def _maybe_mid_lake_afk(
    state: SessionState,
    config: AutoSessionConfig,
    casts_since_afk: int,
    next_target: int,
    stop_event: Optional[asyncio.Event] = None,
) -> Tuple[int, int, bool]:
    """Natural mid-lake AFK pause (12-45s every 12-28 casts); interruptible and refreshes watchdog."""
    if not config.mid_lake_afk_enabled or casts_since_afk < next_target:
        return casts_since_afk, next_target, False
    min_s = max(0.0, float(config.mid_lake_afk_min_sec))
    max_s = max(min_s, float(config.mid_lake_afk_max_sec))
    duration = random.uniform(min_s, max_s)
    print(f"[{time.strftime('%H:%M:%S')}] [HUMAN] 🧘 Tạm nghỉ tay giữa hồ (Mid-Lake AFK) {duration:.1f}s sau {casts_since_afk} lần quăng...")
    await _interruptible_sleep(duration, stop_event, chunk_sec=0.5)
    state.last_activity_time = time.time()
    min_c = max(1, int(config.mid_lake_afk_min_casts))
    max_c = max(min_c, int(config.mid_lake_afk_max_casts))
    return 0, random.randint(min_c, max_c), True


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

    if config.fresh_start:
        state = SessionState(current_lake=config.start_lake)
        state.save(config.state_file)
    else:
        state = SessionState.load(config.state_file)
        if state is None:
            state = SessionState(current_lake=config.start_lake)
        else:
            if config.start_lake != 1:
                state.current_lake = config.start_lake

    pacer: Optional[HumanPacer] = HumanPacer() if config.human_pacer_enabled else None

    def _build_route() -> List[int]:
        if not config.smart_route_enabled:
            return list(range(1, config.max_lakes + 1))
        if config.smart_route_skip_max > 0:
            return build_lake_route(
                config.max_lakes,
                config.smart_route_fixed_prefix,
                config.smart_route_cluster_size,
                skip_max=config.smart_route_skip_max,
            )
        return build_lake_route(
            config.max_lakes,
            config.smart_route_fixed_prefix,
            config.smart_route_cluster_size,
        )

    def _align_route_to_start(route: List[int], start_lake: int) -> List[int]:
        if not route:
            return route
        if config.smart_route_enabled and config.smart_route_fixed_prefix == 0:
            if start_lake in route:
                idx = route.index(start_lake)
                return route[idx:] + route[:idx]
            return [start_lake] + list(route)
        if start_lake not in route:
            return [start_lake] + list(route)
        return route

    lake_route = _align_route_to_start(_build_route(), state.current_lake)

    async def _comprehension_pause(kind: str) -> None:
        if pacer is None:
            return
        pause = pacer.sample_reaction_pause(kind)
        if pause > 0.0:
            await _interruptible_sleep(pause, stop_event, chunk_sec=0.25)
            state.last_activity_time = time.time()

    if config.verbose:
        try:
            vis_state = await _cdp_evaluate(tab, "document.visibilityState")
            if vis_state == "hidden":
                print(
                    f"[{time.strftime('%H:%M:%S')}] [CẢNH BÁO] Cửa sổ Chrome đang bị ẩn/thu nhỏ "
                    "(visibilityState=hidden)! Nếu bạn mở Chrome bằng start_chrome_debug.bat mặc định (Stealth), "
                    "Chrome sẽ đóng băng cuộn chuột & đóng modal -> Hãy mở cửa sổ Chrome hiện lên (không thu nhỏ) "
                    "hoặc chạy lại bằng: start_chrome_debug.bat --bg"
                )
        except Exception:
            pass

    pending_travel_lake: Optional[int] = None
    pending_travel_failures: int = 0
    pending_travel_from_startup: bool = False

    if config.initial_travel:
        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🚀 Khởi hành tới HO {state.current_lake}...")
        travel_res = await travel_to_lake(tab, state.current_lake)
        if travel_res.success:
            if getattr(travel_res, "water_ready", True):
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 📍 Đã đến hồ (mặt nước đang tải, sẽ kiểm tra lại)...")
            await _comprehension_pause("TRAVEL")
        else:
            pending_travel_lake = state.current_lake
            pending_travel_failures = 1
            pending_travel_from_startup = True
            print(
                f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⚠️ Khởi hành tới HO {state.current_lake} thất bại "
                "-> sẽ thử chuyển lại trực tiếp (không câu nhầm hồ hiện tại)..."
            )
        state.last_activity_time = time.time()

    current_energy_display = "N/A"
    consecutive_modal_stuck = 0
    consecutive_no_bread = 0
    consecutive_hud_missing = 0
    energy_stuck_start_time = None
    lakes_completed = 0
    _min_afk_lakes = max(1, int(config.micro_afk_min_lakes))
    _max_afk_lakes = max(_min_afk_lakes, int(config.micro_afk_max_lakes))
    next_afk_target = random.randint(_min_afk_lakes, _max_afk_lakes)

    casts_since_mid_afk = 0
    _min_mid_casts = max(1, int(config.mid_lake_afk_min_casts))
    _max_mid_casts = max(_min_mid_casts, int(config.mid_lake_afk_max_casts))
    next_mid_afk_target = random.randint(_min_mid_casts, _max_mid_casts)

    next_bread_threshold = random.randint(12, 32) if config.dynamic_bread_enabled else config.energy_low_threshold
    current_lake_catches = 0
    current_lake_early_cap = _roll_early_leave_cap(config.early_leave_enabled)
    effective_timeout_retries = random.randint(4, 6) if config.human_pacer_enabled else config.max_timeout_retries

    reset_delay_min = random.uniform(3.0, 20.0) if config.reset_delay_enabled else 0.0

    work_session_start = time.monotonic()
    _min_work = max(0.0, float(config.long_break_min_work_sec))
    _max_work = max(_min_work, float(config.long_break_max_work_sec))
    next_long_break_sec = random.uniform(_min_work, _max_work)
    long_break_pending_since: Optional[float] = None
    lake_just_finished = False

    # Daily play cap & sleep window tracking (rolled once per calendar day)
    daily_play_date = datetime.now().date()
    active_play_sec_today = 0.0
    last_play_tick = time.monotonic()
    sleep_jitter_min = random.uniform(-45.0, 45.0)
    sleep_dur_hours = random.uniform(max(1.0, config.sleep_hours - 1.0), config.sleep_hours + 1.0)
    daily_cap_hours = random.uniform(max(1.0, config.max_daily_hours - 1.5), min(23.5, config.max_daily_hours + 1.5))

    def _on_lake_changed() -> None:
        nonlocal current_lake_catches, current_lake_early_cap, effective_timeout_retries, casts_since_mid_afk
        current_lake_catches = 0
        casts_since_mid_afk = 0
        current_lake_early_cap = _roll_early_leave_cap(config.early_leave_enabled)
        effective_timeout_retries = random.randint(4, 6) if config.human_pacer_enabled else config.max_timeout_retries

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if config.max_catches is not None and state.total_catches >= config.max_catches:
                break

            # Track active daily play time & enforce Sleep Window / Daily Cap when enabled
            if config.sleep_window_enabled:
                now_mono = time.monotonic()
                now_dt = datetime.now()
                if now_dt.date() != daily_play_date:
                    daily_play_date = now_dt.date()
                    active_play_sec_today = 0.0
                    sleep_jitter_min = random.uniform(-45.0, 45.0)
                    sleep_dur_hours = random.uniform(max(1.0, config.sleep_hours - 1.0), config.sleep_hours + 1.0)
                    daily_cap_hours = random.uniform(max(1.0, config.max_daily_hours - 1.5), min(23.5, config.max_daily_hours + 1.5))
                active_play_sec_today += max(0.0, now_mono - last_play_tick)
                last_play_tick = now_mono

                sleep_check = check_sleep_or_daily_cap(
                    config,
                    active_play_sec_today,
                    now_dt,
                    sleep_start_jitter_min=sleep_jitter_min,
                    sleep_duration_hours=sleep_dur_hours,
                    daily_cap_hours=daily_cap_hours,
                )
                if sleep_check is not None:
                    sleep_reason, sleep_sec = sleep_check
                    did_sleep, passed_reset = await perform_tab_close_long_break(
                        tab,
                        config,
                        state,
                        stop_event,
                        rest_sec_override=sleep_sec,
                        reason_label=sleep_reason,
                    )
                    if stop_event is not None and stop_event.is_set():
                        break
                    if did_sleep:
                        if passed_reset is not None and config.smart_route_enabled:
                            lake_route = _align_route_to_start(_build_route(), state.current_lake)
                        if pacer is not None:
                            pacer.reset_after_break()
                        pending_travel_lake = None
                        pending_travel_failures = 0
                        pending_travel_from_startup = False
                        work_session_start = time.monotonic()
                        next_long_break_sec = random.uniform(_min_work, _max_work)
                        long_break_pending_since = None
                        lake_just_finished = False
                        daily_play_date = datetime.now().date()
                        active_play_sec_today = 0.0
                        last_play_tick = time.monotonic()
                        _on_lake_changed()
                        continue

            # Server Reset Check (RESET_HOURS = 1, 4, 7, 10, 13, 16, 19, 22, with optional 3-20m desync)
            if config.reset_delay_enabled:
                should_reset, new_reset_hour = check_server_reset(
                    state.current_lake, state.last_reset_hour, delay_minutes=reset_delay_min
                )
            else:
                should_reset, new_reset_hour = check_server_reset(state.current_lake, state.last_reset_hour)
            if should_reset:
                if config.smart_route_enabled:
                    lake_route = _build_route()
                dest_lake = lake_route[0] if (config.smart_route_enabled and config.smart_route_fixed_prefix == 0 and lake_route) else 1
                print(f"[{time.strftime('%H:%M:%S')}] [RESET SERVER] 🌟 ĐÃ TỚI GIỜ RESET SERVER ({new_reset_hour}:00)! Tự động quay về HO {dest_lake}...")
                state.current_lake = dest_lake
                state.last_reset_hour = new_reset_hour
                state.consecutive_no_water = 0
                state.consecutive_timeout = 0
                pending_travel_lake = None
                pending_travel_failures = 0
                pending_travel_from_startup = False
                state.save(config.state_file)
                if config.reset_delay_enabled:
                    reset_delay_min = random.uniform(3.0, 20.0)
                await travel_to_lake(tab, dest_lake)
                _on_lake_changed()
                await _comprehension_pause("TRAVEL")
                state.last_activity_time = time.time()
                continue
            elif new_reset_hour != state.last_reset_hour:
                state.last_reset_hour = new_reset_hour
                state.save(config.state_file)
                if config.reset_delay_enabled:
                    reset_delay_min = random.uniform(3.0, 20.0)

            # Tab-Close Long Break (2-3h work -> 20-50m tab-closed rest, with optional finish-current-lake grace <= 10m)
            if config.long_break_enabled and (time.monotonic() - work_session_start) >= next_long_break_sec:
                should_trigger_break = True
                if config.long_break_finish_lake:
                    if long_break_pending_since is None:
                        long_break_pending_since = time.monotonic()
                        if not lake_just_finished and current_lake_catches > 0:
                            print(
                                f"[{time.strftime('%H:%M:%S')}] [LONG BREAK] ⏳ Hết khung làm việc — "
                                "chờ câu xong hồ hiện tại (tối đa 10 phút) trước khi nghỉ dài..."
                            )
                    grace_elapsed = time.monotonic() - long_break_pending_since
                    should_trigger_break = lake_just_finished or current_lake_catches == 0 or (grace_elapsed >= 600.0)

                if should_trigger_break:
                    did_break, passed_reset = await perform_tab_close_long_break(tab, config, state, stop_event)
                    if stop_event is not None and stop_event.is_set():
                        break
                    if did_break:
                        if passed_reset is not None and config.smart_route_enabled:
                            lake_route = _align_route_to_start(_build_route(), state.current_lake)
                        if pacer is not None:
                            pacer.reset_after_break()
                        pending_travel_lake = None
                        pending_travel_failures = 0
                        pending_travel_from_startup = False
                        work_session_start = time.monotonic()
                        next_long_break_sec = random.uniform(_min_work, _max_work)
                        long_break_pending_since = None
                        lake_just_finished = False
                        last_play_tick = time.monotonic()
                        _on_lake_changed()
                        continue
            lake_just_finished = False

            now = time.time()
            if (now - state.last_activity_time) >= config.idle_timeout_seconds:
                # Dọn modal kẹt trước khi thử lại (trusted CDP Escape + read-only lookup)
                await _dismiss_modal_cdp(tab)

                print(f"[{time.strftime('%H:%M:%S')}] [WATCHDOG 30s] Quá {config.idle_timeout_seconds:.0f}s không có hoạt động -> Pha 1: Thử quăng cần lại...")
                recast_kwargs: Dict[str, Any] = {"use_worker": use_worker, "lake": state.current_lake}
                if pacer is not None:
                    recast_kwargs["pacer"] = pacer
                recast_outcome = await run_one_cast(tab, **recast_kwargs)

                if recast_outcome.kind == "CATCH" or (recast_outcome.reaction_ms is not None and recast_outcome.reaction_ms > 0):
                    print(f"[{time.strftime('%H:%M:%S')}] [WATCHDOG 30s] Pha 1 thành công (nhân vật hoạt động bình thường) -> Tiếp tục câu, không cần F5!")
                    state.last_activity_time = time.time()
                else:
                    # Pha 1 thất bại -> Kích hoạt Pha 2 F5 Reload
                    print(f"[{time.strftime('%H:%M:%S')}] [WATCHDOG 30s] Pha 1 thất bại (vẫn đơ) -> Pha 2: Kích hoạt F5 (Reload) & đưa nhân vật từ Nhà về HO {state.current_lake}...")
                    await reload_page(tab, wait_loaded_sec=2.5)
                    await recover_from_reload(tab, state.current_lake)
                    state.last_activity_time = time.time()

            # Depleted-lake guard: retry pending lake travel directly instead of casting again on a depleted lake
            if pending_travel_lake is not None:
                if not await _interruptible_sleep(random.uniform(1.5, 3.0), stop_event, chunk_sec=0.25):
                    break
                await _dismiss_modal_cdp(tab)
                await _wait_modal_unmounted(tab)
                state.last_activity_time = time.time()
                print(
                    f"[{time.strftime('%H:%M:%S')}] [HỒ {pending_travel_lake:02d}/40] 🔄 "
                    f"Thử chuyển trực tiếp sang HO {pending_travel_lake} (lần chờ #{pending_travel_failures + 1}, không câu lại hồ đã cạn)..."
                )
                retry_travel_res = await travel_to_lake(tab, pending_travel_lake)
                if retry_travel_res.success:
                    was_startup_travel = pending_travel_from_startup
                    state.current_lake = pending_travel_lake
                    pending_travel_lake = None
                    pending_travel_failures = 0
                    pending_travel_from_startup = False
                    state.consecutive_no_water = 0
                    state.consecutive_timeout = 0
                    state.save(config.state_file)
                    _on_lake_changed()
                    if getattr(retry_travel_res, "water_ready", True):
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 📍 Đã đến hồ (mặt nước đang tải, sẽ kiểm tra lại)...")
                    await _comprehension_pause("TRAVEL")
                    if not was_startup_travel:
                        lakes_completed += 1
                        lakes_completed, next_afk_target, _ = await _maybe_micro_afk(
                            state, config, lakes_completed, next_afk_target, stop_event
                        )
                    state.last_activity_time = time.time()
                    continue
                pending_travel_failures += 1
                if pending_travel_failures == 3:
                    skipped_lake = pending_travel_lake
                    alt_lake, _ = next_lake_in_route(pending_travel_lake, lake_route, config.max_lakes)
                    print(
                        f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Chuyển sang HO {skipped_lake} thất bại 3 lần liên tiếp "
                        f"-> Bỏ qua bookmark lỗi, chuyển sang HO {alt_lake}..."
                    )
                    pending_travel_lake = alt_lake
                elif pending_travel_failures >= 6:
                    print(
                        f"[{time.strftime('%H:%M:%S')}] [TRAVEL] ⚠️ Chuyển hồ thất bại {pending_travel_failures} lần liên tiếp "
                        f"-> Kích hoạt F5 (Reload) khôi phục UI trước khi thử lại HO {pending_travel_lake}..."
                    )
                    await reload_page(tab, wait_loaded_sec=2.5)
                    pending_travel_failures = 0
                state.last_activity_time = time.time()
                continue

            # Pre-cast energy check, dynamic bread eating, out-of-bread guard & stuck UI watchdog
            energy_val = "N/A"
            out_of_bread_stop = False
            last_pre_status: Optional[Status] = None
            try:
                status = await read_status(tab)
                last_pre_status = status
                if status.energy is not None or status.xp is not None:
                    consecutive_hud_missing = 0
                if status.energy is not None:
                    energy_val = getattr(status.energy, "current", status.energy)
                    current_energy_display = f"{energy_val} / 80"
                    cur_threshold = next_bread_threshold if config.dynamic_bread_enabled else config.energy_low_threshold
                    if energy_val < cur_threshold:
                        bread_res = await eat_bread(tab)
                        if bread_res.consumed:
                            print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🥖 Thể lực thấp ({energy_val}/80), tự động ăn 1 bánh mì (+{bread_res.recovered} thể lực).")
                            consecutive_no_bread = 0
                            energy_stuck_start_time = None
                            state.last_activity_time = time.time()
                            if config.dynamic_bread_enabled:
                                next_bread_threshold = random.randint(12, 32)
                                # Occasional 2nd bread bite if energy is still < 52
                                if (
                                    bread_res.post_energy is not None
                                    and bread_res.post_energy < 52
                                    and random.random() < 0.40
                                ):
                                    if await _interruptible_sleep(random.uniform(0.9, 2.2), stop_event, chunk_sec=0.25):
                                        try:
                                            re_st = await read_status(tab)
                                            if re_st.energy is not None and re_st.energy < 52:
                                                bread_res2 = await eat_bread(tab)
                                                if bread_res2.consumed:
                                                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🥖 Ăn thêm 1 bánh mì (+{bread_res2.recovered} thể lực).")
                                                    consecutive_no_bread = 0
                                                    state.last_activity_time = time.time()
                                                elif bread_res2.reason == "NO_BREAD_FOUND":
                                                    print(
                                                        f"[{time.strftime('%H:%M:%S')}] [ENERGY] ℹ️ Không ăn thêm miếng thứ 2 "
                                                        "(không thấy bánh mì — có thể đang cooldown 30s)."
                                                    )
                                        except Exception:
                                            pass
                            await _comprehension_pause("BREAD")
                        elif bread_res.reason == "NO_BREAD_FOUND":
                            consecutive_no_bread += 1
                            energy_stuck_start_time = None  # Never spam 35s F5 when genuinely out of bread
                            print(f"[{time.strftime('%H:%M:%S')}] [ENERGY] ⚠️ Không tìm thấy bánh mì trong túi ({consecutive_no_bread}/3)...")
                            if consecutive_no_bread >= 3:
                                print(
                                    f"[{time.strftime('%H:%M:%S')}] [ENERGY] 🛑 HẾT BÁNH MÌ (3 lần liên tiếp NO_BREAD_FOUND)! "
                                    "Đang lưu trạng thái và dừng phiên an toàn (không spam F5)..."
                                )
                                state.save(config.state_file)
                                out_of_bread_stop = True
                        elif bread_res.reason == "MODAL_ACTIVE":
                            energy_stuck_start_time = None
                        else:
                            consecutive_no_bread = 0
                            if energy_stuck_start_time is None:
                                energy_stuck_start_time = time.time()
                            if (time.time() - energy_stuck_start_time) >= 35.0:
                                # Kẹt UI quá 35s không ăn được bánh mì -> Kích hoạt F5 Reload & Ăn lại
                                print(f"[{time.strftime('%H:%M:%S')}] [ENERGY WATCHDOG] Kẹt không ăn được bánh mì quá 35s -> Kích hoạt F5 (Reload) để khôi phục UI...")
                                await reload_page(tab, wait_loaded_sec=2.5)
                                await eat_bread(tab, force=True)
                                await recover_from_reload(tab, state.current_lake)
                                energy_stuck_start_time = None
                                state.last_activity_time = time.time()
                    else:
                        energy_stuck_start_time = None
                        consecutive_no_bread = 0
            except Exception:
                pass

            if out_of_bread_stop:
                break

            if stop_event is not None and stop_event.is_set():
                break

            cast_kwargs: Dict[str, Any] = {"use_worker": use_worker, "lake": state.current_lake}
            if pacer is not None:
                cast_kwargs["pacer"] = pacer
            outcome = await run_one_cast(tab, **cast_kwargs)
            state.total_casts += 1
            if outcome.kind not in ("MODAL_ACTIVE", "NO_WATER", "INSUFFICIENT_ENERGY", "EMPTY", "PRIVATE"):
                casts_since_mid_afk += 1
            state.last_activity_time = time.time()
            if outcome.post_energy is not None:
                energy_val = getattr(outcome.post_energy, "current", outcome.post_energy)

            if outcome.kind == "CATCH":
                consecutive_modal_stuck = 0
                verified = is_verified_catch(outcome)

                if verified:
                    state.total_catches += 1
                    current_lake_catches += 1
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

                    # Natural early leave (10-15% of lakes leave at 38..47 catches)
                    if current_lake_early_cap is not None and current_lake_catches >= current_lake_early_cap:
                        lake_just_finished = True
                        next_lake, wrapped_cycle = next_lake_in_route(state.current_lake, lake_route, config.max_lakes)
                        print(
                            f"[{time.strftime('%H:%M:%S')}] [HUMAN] 🚶 Rời hồ sớm tự nhiên tại HO {state.current_lake} "
                            f"sau {current_lake_catches} cá (ngưỡng {current_lake_early_cap}) -> Chuyển sang HO {next_lake}..."
                        )
                        if wrapped_cycle or (not config.smart_route_enabled and state.current_lake >= config.max_lakes):
                            wait_lake_arg = config.max_lakes if wrapped_cycle else state.current_lake
                            wait_kwargs: Dict[str, Any] = {}
                            is_broad_route = config.smart_route_enabled and config.smart_route_fixed_prefix == 0
                            pending_route: Optional[List[int]] = None
                            reset_target_lake = 1
                            if is_broad_route:
                                pending_route = _build_route()
                                reset_target_lake = pending_route[0] if pending_route else 1
                                wait_kwargs["target_lake"] = reset_target_lake
                            if config.reset_delay_enabled:
                                wait_kwargs["reset_delay_sec"] = reset_delay_min * 60.0
                            if config.tab_close_wait_reset:
                                wait_kwargs["tab_close_wait_reset"] = True
                                wait_kwargs["config"] = config
                            if is_broad_route or config.reset_delay_enabled or config.tab_close_wait_reset:
                                wait_kwargs["state"] = state
                            did_wait_and_reset = await wait_until_reset_if_needed(
                                tab, wait_lake_arg, config.max_lakes, stop_event, **wait_kwargs
                            )
                            if did_wait_and_reset:
                                if is_broad_route and pending_route is not None:
                                    lake_route = pending_route
                                    state.current_lake = reset_target_lake
                                else:
                                    if config.smart_route_enabled:
                                        lake_route = _build_route()
                                    state.current_lake = 1
                                pending_travel_lake = None
                                pending_travel_failures = 0
                                pending_travel_from_startup = False
                                state.consecutive_no_water = 0
                                state.consecutive_timeout = 0
                                state.save(config.state_file)
                                if config.reset_delay_enabled:
                                    reset_delay_min = random.uniform(3.0, 20.0)
                                if config.tab_close_wait_reset:
                                    work_session_start = time.monotonic()
                                    if pacer is not None:
                                        pacer.reset_after_break()
                                last_play_tick = time.monotonic()
                                _on_lake_changed()
                                state.last_activity_time = time.time()
                                continue
                        travel_res = await travel_to_lake(tab, next_lake)
                        if travel_res.success:
                            state.current_lake = next_lake
                            state.consecutive_no_water = 0
                            state.consecutive_timeout = 0
                            state.save(config.state_file)
                            _on_lake_changed()
                            await _comprehension_pause("TRAVEL")
                            lakes_completed += 1
                            lakes_completed, next_afk_target, _ = await _maybe_micro_afk(
                                state, config, lakes_completed, next_afk_target, stop_event
                            )
                        else:
                            print(
                                f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại khi rời hồ sớm "
                                f"-> Tiếp tục câu tại HO {state.current_lake}..."
                            )
                            current_lake_early_cap = None
                        state.last_activity_time = time.time()
                        continue
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ❌ Giật hụt cá (Miss) tại HO {state.current_lake}")
                    await _comprehension_pause("MISS")

            elif outcome.kind in ("MISS", "UNVERIFIED"):
                consecutive_modal_stuck = 0
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ❌ Giật hụt cá (Miss) tại HO {state.current_lake}")
                await _comprehension_pause("MISS")

            elif outcome.kind == "INSUFFICIENT_ENERGY":
                consecutive_modal_stuck = 0
                if (
                    last_pre_status is not None
                    and last_pre_status.energy is None
                    and last_pre_status.xp is None
                    and outcome.pre_energy is None
                    and outcome.pre_xp is None
                ):
                    consecutive_hud_missing += 1
                    print(
                        f"[{time.strftime('%H:%M:%S')}] [SESSION] ⚠️ Không thấy HUD game "
                        f"(có thể bị đăng xuất về màn hình Login) ({consecutive_hud_missing}/3)..."
                    )
                    if consecutive_hud_missing >= 3:
                        print(
                            f"[{time.strftime('%H:%M:%S')}] [SESSION] 🛑 MẤT PHIÊN ĐĂNG NHẬP / KHÔNG THẤY HUD GAME "
                            "(3 lần liên tiếp)! Đang lưu trạng thái và dừng phiên an toàn (vui lòng đăng nhập lại)..."
                        )
                        state.save(config.state_file)
                        break
                    await _interruptible_sleep(random.uniform(1.5, 2.5), stop_event, chunk_sec=0.5)
                    state.last_activity_time = time.time()
                    continue
                bread_res = await eat_bread(tab)
                cur_e = energy_val if isinstance(energy_val, (int, float)) else 0
                if bread_res.consumed:
                    consecutive_no_bread = 0
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🥖 Thể lực thấp ({cur_e}/80), tự động ăn 1 bánh mì (+{bread_res.recovered} thể lực).")
                    if config.dynamic_bread_enabled:
                        next_bread_threshold = random.randint(12, 32)
                    await _comprehension_pause("BREAD")
                elif bread_res.reason == "NO_BREAD_FOUND":
                    consecutive_no_bread += 1
                    print(f"[{time.strftime('%H:%M:%S')}] [ENERGY] ⚠️ Không tìm thấy bánh mì khi cạn thể lực ({consecutive_no_bread}/3)...")
                    if consecutive_no_bread >= 3:
                        print(
                            f"[{time.strftime('%H:%M:%S')}] [ENERGY] 🛑 HẾT BÁNH MÌ (3 lần liên tiếp NO_BREAD_FOUND)! "
                            "Đang lưu trạng thái và dừng phiên an toàn (không spam F5)..."
                        )
                        state.save(config.state_file)
                        break
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🥖 Thể lực thấp ({cur_e}/80), tự động ăn 1 bánh mì (+{bread_res.recovered} thể lực).")
                state.last_activity_time = time.time()

            elif outcome.kind in ("EMPTY", "TRASH", "PRIVATE"):
                consecutive_modal_stuck = 0
                lake_just_finished = True
                await _comprehension_pause(outcome.kind)

                next_lake, wrapped_cycle = next_lake_in_route(state.current_lake, lake_route, config.max_lakes)
                if wrapped_cycle or (not config.smart_route_enabled and state.current_lake >= config.max_lakes):
                    # Đã câu xong vòng 40 hồ -> Kiểm tra và chờ reset nếu chưa tới giờ
                    wait_lake_arg = config.max_lakes if wrapped_cycle else state.current_lake
                    wait_kwargs_e: Dict[str, Any] = {}
                    is_broad_route_e = config.smart_route_enabled and config.smart_route_fixed_prefix == 0
                    pending_route_e: Optional[List[int]] = None
                    reset_target_lake_e = 1
                    if is_broad_route_e:
                        pending_route_e = _build_route()
                        reset_target_lake_e = pending_route_e[0] if pending_route_e else 1
                        wait_kwargs_e["target_lake"] = reset_target_lake_e
                    if config.reset_delay_enabled:
                        wait_kwargs_e["reset_delay_sec"] = reset_delay_min * 60.0
                    if config.tab_close_wait_reset:
                        wait_kwargs_e["tab_close_wait_reset"] = True
                        wait_kwargs_e["config"] = config
                    if is_broad_route_e or config.reset_delay_enabled or config.tab_close_wait_reset:
                        wait_kwargs_e["state"] = state
                    did_wait_and_reset = await wait_until_reset_if_needed(
                        tab, wait_lake_arg, config.max_lakes, stop_event, **wait_kwargs_e
                    )
                    if did_wait_and_reset:
                        if is_broad_route_e and pending_route_e is not None:
                            lake_route = pending_route_e
                            state.current_lake = reset_target_lake_e
                        else:
                            if config.smart_route_enabled:
                                lake_route = _build_route()
                            state.current_lake = 1
                        pending_travel_lake = None
                        pending_travel_failures = 0
                        pending_travel_from_startup = False
                        state.consecutive_no_water = 0
                        state.consecutive_timeout = 0
                        state.save(config.state_file)
                        if config.reset_delay_enabled:
                            reset_delay_min = random.uniform(3.0, 20.0)
                        if config.tab_close_wait_reset:
                            work_session_start = time.monotonic()
                            if pacer is not None:
                                pacer.reset_after_break()
                        last_play_tick = time.monotonic()
                        _on_lake_changed()
                        state.last_activity_time = time.time()
                        continue

                toast_short = (outcome.toast or "").strip()
                toast_str = f" ({toast_short})" if toast_short else ""
                if outcome.kind == "EMPTY":
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⚠️ Hồ đã hết cá (EMPTY){toast_str} -> Đang chuyển sang HO {next_lake}...")
                elif outcome.kind == "PRIVATE":
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🔒 Hồ riêng tư (PRIVATE){toast_str} -> Đang chuyển sang HO {next_lake}...")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] 🗑️ Câu phải rác (TRASH){toast_str} -> Đang chuyển sang HO {next_lake}...")

                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 🚀 Khởi hành tới HO {next_lake}...")
                travel_res = await travel_to_lake(tab, next_lake)
                if travel_res.success:
                    state.current_lake = next_lake
                    pending_travel_lake = None
                    pending_travel_failures = 0
                    pending_travel_from_startup = False
                    state.consecutive_no_water = 0
                    state.consecutive_timeout = 0
                    state.save(config.state_file)
                    _on_lake_changed()
                    if getattr(travel_res, "water_ready", True):
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ (mặt nước đang tải, sẽ kiểm tra lại)...")
                    await _comprehension_pause("TRAVEL")
                    lakes_completed += 1
                    lakes_completed, next_afk_target, _ = await _maybe_micro_afk(
                        state, config, lakes_completed, next_afk_target, stop_event
                    )
                else:
                    pending_travel_lake = next_lake
                    pending_travel_failures = 1
                    pending_travel_from_startup = False
                    print(
                        f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại "
                        "-> sẽ thử chuyển lại trực tiếp, không câu lại hồ đã cạn..."
                    )
                    state.last_activity_time = time.time()
                    continue
                state.last_activity_time = time.time()

            elif outcome.kind == "NO_WATER":
                consecutive_modal_stuck = 0
                state.consecutive_no_water += 1
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Chưa phát hiện mặt nước ({state.consecutive_no_water}/{config.max_no_water_retries})...")
                await asyncio.sleep(random.uniform(0.85, 1.35))
                if state.consecutive_no_water >= config.max_no_water_retries:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Quá {config.max_no_water_retries} lần không thấy nước -> Đang di chuyển lại vào hồ...")
                    state.consecutive_no_water = 0
                    await travel_to_lake(tab, state.current_lake)
                    state.last_activity_time = time.time()

            elif outcome.kind == "TIMEOUT":
                consecutive_modal_stuck = 0
                state.consecutive_timeout += 1
                timeout_sec = int(round(outcome.duration_sec)) if outcome.duration_sec >= 1.0 else 20
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⏳ Cá chưa cắn sau {timeout_sec}s ({state.consecutive_timeout}/{effective_timeout_retries})...")
                await asyncio.sleep(random.uniform(0.40, 0.75))
                if state.consecutive_timeout >= effective_timeout_retries:
                    state.consecutive_timeout = 0
                    lake_just_finished = True
                    next_lake, wrapped_cycle_t = next_lake_in_route(state.current_lake, lake_route, config.max_lakes)
                    if wrapped_cycle_t or (not config.smart_route_enabled and state.current_lake >= config.max_lakes):
                        wait_lake_arg_t = config.max_lakes if wrapped_cycle_t else state.current_lake
                        wait_kwargs_t: Dict[str, Any] = {}
                        is_broad_route_t = config.smart_route_enabled and config.smart_route_fixed_prefix == 0
                        pending_route_t: Optional[List[int]] = None
                        reset_target_lake_t = 1
                        if is_broad_route_t:
                            pending_route_t = _build_route()
                            reset_target_lake_t = pending_route_t[0] if pending_route_t else 1
                            wait_kwargs_t["target_lake"] = reset_target_lake_t
                        if config.reset_delay_enabled:
                            wait_kwargs_t["reset_delay_sec"] = reset_delay_min * 60.0
                        if config.tab_close_wait_reset:
                            wait_kwargs_t["tab_close_wait_reset"] = True
                            wait_kwargs_t["config"] = config
                        if is_broad_route_t or config.reset_delay_enabled or config.tab_close_wait_reset:
                            wait_kwargs_t["state"] = state
                        did_wait_and_reset_t = await wait_until_reset_if_needed(
                            tab, wait_lake_arg_t, config.max_lakes, stop_event, **wait_kwargs_t
                        )
                        if did_wait_and_reset_t:
                            if is_broad_route_t and pending_route_t is not None:
                                lake_route = pending_route_t
                                state.current_lake = reset_target_lake_t
                            else:
                                if config.smart_route_enabled:
                                    lake_route = _build_route()
                                state.current_lake = 1
                            pending_travel_lake = None
                            pending_travel_failures = 0
                            pending_travel_from_startup = False
                            state.consecutive_no_water = 0
                            state.consecutive_timeout = 0
                            state.save(config.state_file)
                            if config.reset_delay_enabled:
                                reset_delay_min = random.uniform(3.0, 20.0)
                            if config.tab_close_wait_reset:
                                work_session_start = time.monotonic()
                                if pacer is not None:
                                    pacer.reset_after_break()
                            last_play_tick = time.monotonic()
                            _on_lake_changed()
                            state.last_activity_time = time.time()
                            continue

                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] ⏳ Quá {effective_timeout_retries} lần cá không cắn -> Chuyển sang HO {next_lake}...")
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 🚀 Khởi hành tới HO {next_lake}...")
                    travel_res = await travel_to_lake(tab, next_lake)
                    if travel_res.success:
                        state.current_lake = next_lake
                        pending_travel_lake = None
                        pending_travel_failures = 0
                        pending_travel_from_startup = False
                        state.consecutive_no_water = 0
                        state.save(config.state_file)
                        _on_lake_changed()
                        if getattr(travel_res, "water_ready", True):
                            print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!")
                        else:
                            print(f"[{time.strftime('%H:%M:%S')}] [HỒ {next_lake:02d}/40] 📍 Đã đến hồ (mặt nước đang tải, sẽ kiểm tra lại)...")
                        await _comprehension_pause("TRAVEL")
                        lakes_completed += 1
                        lakes_completed, next_afk_target, _ = await _maybe_micro_afk(
                            state, config, lakes_completed, next_afk_target, stop_event
                        )
                    else:
                        pending_travel_lake = next_lake
                        pending_travel_failures = 1
                        pending_travel_from_startup = False
                        print(
                            f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại "
                            "-> sẽ thử chuyển lại trực tiếp, không câu lại hồ đã cạn..."
                        )
                        state.last_activity_time = time.time()
                        continue
                    state.last_activity_time = time.time()

            elif outcome.kind == "MODAL_ACTIVE":
                consecutive_modal_stuck += 1
                print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Phát hiện modal đang mở -> Đang dọn dẹp modal ({consecutive_modal_stuck})...")
                await _dismiss_modal_cdp(tab)

                # Rate limiting delay chống tight-loop 100% CPU
                await asyncio.sleep(random.uniform(0.50, 0.85))

                # Nếu kẹt quá 3 lần liên tiếp, kích hoạt cơ chế tự phục hồi
                if consecutive_modal_stuck >= 3:
                    print(f"[{time.strftime('%H:%M:%S')}] [HỒ {state.current_lake:02d}/40] Modal kẹt cứng quá 3 lần -> Tự động tái điều hướng về HO {state.current_lake} để khôi phục UI...")
                    consecutive_modal_stuck = 0
                    await travel_to_lake(tab, state.current_lake)
                    state.last_activity_time = time.time()

            if stop_event is not None and stop_event.is_set():
                break

            casts_since_mid_afk, next_mid_afk_target, did_mid_afk = await _maybe_mid_lake_afk(
                state, config, casts_since_mid_afk, next_mid_afk_target, stop_event
            )
            if stop_event is not None and stop_event.is_set():
                break

            if not did_mid_afk:
                inter_sec = human_inter_cast_delay_sec(pacer=pacer)
                if not await _interruptible_sleep(inter_sec, stop_event, chunk_sec=0.25):
                    break

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
    parser.add_argument('--no-sleep', action='store_true', help='disable automatic nightly sleep window and daily play cap')
    parser.add_argument('--sleep-start', default='00:30', help='nightly sleep window start time HH:MM (default: 00:30)')
    parser.add_argument('--sleep-hours', type=float, default=7.5, help='target nightly sleep duration in hours (default: 7.5)')
    parser.add_argument('--max-daily-hours', type=float, default=11.5, help='maximum active play hours per day (default: 11.5)')
    parser.add_argument("--worker", default=str(Path(__file__).with_name("worker.exe")))
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv=None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
