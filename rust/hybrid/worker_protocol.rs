use std::io::{self, Read, Write};

pub const VERSION: u8 = 1;
pub const MAX_FRAME_LEN: usize = 32 * 1024 * 1024;
pub const FRAME_HEADER_LEN: usize = 8;
const RGB_HEADER_LEN: usize = 20;
pub const MAX_DIMENSION: u32 = 8192;

pub const KIND_HELLO: u8 = 1;
pub const KIND_HELLO_ACK: u8 = 2;
pub const KIND_REQUEST: u8 = 3;
pub const KIND_RESPONSE: u8 = 4;
pub const KIND_ERROR: u8 = 5;
pub const KIND_SHUTDOWN: u8 = 6;
pub const KIND_SHUTDOWN_ACK: u8 = 7;
pub const KIND_RGB: u8 = 8;
pub const ERROR_UNSUPPORTED_TASK1: u16 = 1;

pub const OP_CLICK_CAST: u8 = 3;
pub const OP_CLICK_STRIKE: u8 = 4;
pub const ACTION_STATUS_OK: u8 = 0;
pub const ACTION_STATUS_PRECONDITION_FAILED: u8 = 1;
pub const ACTION_STATUS_PROTOCOL_ERROR: u8 = 2;

pub const OP_EAT_BREAD: u8 = 5;
pub const OP_TRAVEL_LAKE: u8 = 6;
pub const EAT_BREAD_OK: u8 = 0;
pub const EAT_BREAD_FAILED: u8 = 1;
pub const EAT_BREAD_SKIPPED_FULL: u8 = 2;
pub const TRAVEL_LAKE_OK: u8 = 0;
pub const TRAVEL_LAKE_FAILED: u8 = 1;
pub const TRAVEL_LAKE_INVALID: u8 = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    pub version: u8,
    pub kind: u8,
    pub request_id: u32,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RgbPayload<'a> {
    pub width: u32,
    pub height: u32,
    pub stride: u32,
    pub captured_monotonic_ns: u64,
    pub rgb: &'a [u8],
}

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

fn valid_kind(kind: u8) -> bool {
    matches!(kind, KIND_HELLO | KIND_HELLO_ACK | KIND_REQUEST | KIND_RESPONSE
        | KIND_ERROR | KIND_SHUTDOWN | KIND_SHUTDOWN_ACK | KIND_RGB)
}

fn validate_header(version: u8, kind: u8, reserved: u16, request_id: u32) -> io::Result<()> {
    if version != VERSION { return Err(invalid("unsupported protocol version")); }
    if reserved != 0 { return Err(invalid("reserved bits must be zero")); }
    if !valid_kind(kind) { return Err(invalid("unknown frame kind")); }
    let requires_zero_id = matches!(kind, KIND_HELLO | KIND_HELLO_ACK | KIND_SHUTDOWN | KIND_SHUTDOWN_ACK);
    if requires_zero_id && request_id != 0 { return Err(invalid("control frame request id must be zero")); }
    if !requires_zero_id && request_id == 0 { return Err(invalid("operation frame request id must be nonzero")); }
    Ok(())
}

fn validate_frame(frame: &Frame) -> io::Result<()> {
    validate_header(frame.version, frame.kind, 0, frame.request_id)?;
    let body_len = FRAME_HEADER_LEN.checked_add(frame.payload.len()).ok_or_else(|| invalid("frame length overflow"))?;
    if body_len > MAX_FRAME_LEN { return Err(invalid("frame exceeds 32 MiB limit")); }
    Ok(())
}

fn read_up_to<R: Read>(reader: &mut R, buffer: &mut [u8], clean_eof_allowed: bool) -> io::Result<bool> {
    let mut used = 0;
    while used < buffer.len() {
        match reader.read(&mut buffer[used..]) {
            Ok(0) if used == 0 && clean_eof_allowed => return Ok(false),
            Ok(0) => return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "truncated frame")),
            Ok(count) => used += count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(true)
}

pub fn read_frame<R: Read>(reader: &mut R) -> io::Result<Option<Frame>> {
    let mut prefix = [0u8; 4];
    if !read_up_to(reader, &mut prefix, true)? { return Ok(None); }
    let body_len = u32::from_le_bytes(prefix) as usize;
    if body_len < FRAME_HEADER_LEN { return Err(invalid("frame shorter than fixed header")); }
    if body_len > MAX_FRAME_LEN { return Err(invalid("frame exceeds 32 MiB limit")); }

    let mut body = vec![0u8; body_len];
    read_up_to(reader, &mut body, false)?;
    let version = body[0];
    let kind = body[1];
    let reserved = u16::from_le_bytes([body[2], body[3]]);
    let request_id = u32::from_le_bytes([body[4], body[5], body[6], body[7]]);
    validate_header(version, kind, reserved, request_id)?;
    Ok(Some(Frame { version, kind, request_id, payload: body[FRAME_HEADER_LEN..].to_vec() }))
}

pub fn write_frame<W: Write>(writer: &mut W, frame: &Frame) -> io::Result<()> {
    validate_frame(frame)?;
    let body_len = FRAME_HEADER_LEN + frame.payload.len();
    writer.write_all(&(body_len as u32).to_le_bytes())?;
    writer.write_all(&[frame.version, frame.kind, 0, 0])?;
    writer.write_all(&frame.request_id.to_le_bytes())?;
    writer.write_all(&frame.payload)?;
    writer.flush()
}

pub fn validate_rgb_payload(payload: &[u8]) -> io::Result<RgbPayload<'_>> {
    if payload.len() < RGB_HEADER_LEN { return Err(invalid("RGB payload is shorter than its header")); }
    let width = u32::from_le_bytes(payload[0..4].try_into().unwrap());
    let height = u32::from_le_bytes(payload[4..8].try_into().unwrap());
    let stride = u32::from_le_bytes(payload[8..12].try_into().unwrap());
    let captured_monotonic_ns = u64::from_le_bytes(payload[12..20].try_into().unwrap());
    if width == 0 || height == 0 || width > MAX_DIMENSION || height > MAX_DIMENSION {
        return Err(invalid("RGB dimensions outside 1..8192"));
    }
    let expected_stride = width.checked_mul(3).ok_or_else(|| invalid("RGB stride overflow"))?;
    if stride != expected_stride { return Err(invalid("RGB stride does not equal width times three")); }
    let pixel_bytes = (stride as usize).checked_mul(height as usize).ok_or_else(|| invalid("RGB byte count overflow"))?;
    let expected_len = RGB_HEADER_LEN.checked_add(pixel_bytes).ok_or_else(|| invalid("RGB payload length overflow"))?;
    if expected_len > MAX_FRAME_LEN - FRAME_HEADER_LEN { return Err(invalid("RGB frame exceeds 32 MiB limit")); }
    if payload.len() != expected_len { return Err(invalid("RGB payload length does not exactly match dimensions")); }
    Ok(RgbPayload { width, height, stride, captured_monotonic_ns, rgb: &payload[RGB_HEADER_LEN..] })
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ActionRequest {
    pub opcode: u8,
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ActionResponse {
    pub opcode: u8,
    pub status_code: u8,
    pub press_timestamp_ns: u64,
    pub release_timestamp_ns: u64,
    pub released: bool,
}

pub fn decode_action_request(payload: &[u8]) -> io::Result<ActionRequest> {
    if payload.len() != 17 {
        return Err(invalid("action request payload must be exactly 17 bytes"));
    }
    let opcode = payload[0];
    if opcode != OP_CLICK_CAST && opcode != OP_CLICK_STRIKE {
        return Err(invalid("unknown action opcode"));
    }
    let x = f64::from_le_bytes(payload[1..9].try_into().unwrap());
    let y = f64::from_le_bytes(payload[9..17].try_into().unwrap());
    if !x.is_finite() || !y.is_finite() {
        return Err(invalid("action coordinates must be finite"));
    }
    Ok(ActionRequest { opcode, x, y })
}

pub fn encode_action_response(resp: &ActionResponse) -> Vec<u8> {
    let mut buf = Vec::with_capacity(19);
    buf.push(resp.opcode);
    buf.push(resp.status_code);
    buf.extend_from_slice(&resp.press_timestamp_ns.to_le_bytes());
    buf.extend_from_slice(&resp.release_timestamp_ns.to_le_bytes());
    buf.push(if resp.released { 1 } else { 0 });
    buf
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EatBreadResponse {
    pub opcode: u8,
    pub status_code: u8,
    pub recovered_energy: u32,
    pub duration_ms: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TravelLakeRequest {
    pub opcode: u8,
    pub lake_num: u8,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TravelLakeResponse {
    pub opcode: u8,
    pub status_code: u8,
    pub lake_num: u8,
    pub duration_ms: u32,
}

pub fn decode_eat_bread_request(payload: &[u8]) -> io::Result<()> {
    if payload.len() != 1 || payload[0] != OP_EAT_BREAD {
        return Err(invalid("eat bread request must be opcode 5"));
    }
    Ok(())
}

pub fn encode_eat_bread_response(resp: &EatBreadResponse) -> Vec<u8> {
    let mut buf = Vec::with_capacity(10);
    buf.push(resp.opcode);
    buf.push(resp.status_code);
    buf.extend_from_slice(&resp.recovered_energy.to_le_bytes());
    buf.extend_from_slice(&resp.duration_ms.to_le_bytes());
    buf
}

pub fn decode_travel_lake_request(payload: &[u8]) -> io::Result<TravelLakeRequest> {
    if payload.len() != 2 || payload[0] != OP_TRAVEL_LAKE {
        return Err(invalid("travel lake request must be 2 bytes starting with opcode 6"));
    }
    let lake_num = payload[1];
    if !(1..=40).contains(&lake_num) {
        return Err(invalid("lake number must be between 1 and 40"));
    }
    Ok(TravelLakeRequest { opcode: OP_TRAVEL_LAKE, lake_num })
}

pub fn encode_travel_lake_response(resp: &TravelLakeResponse) -> Vec<u8> {
    let mut buf = Vec::with_capacity(7);
    buf.push(resp.opcode);
    buf.push(resp.status_code);
    buf.push(resp.lake_num);
    buf.extend_from_slice(&resp.duration_ms.to_le_bytes());
    buf
}
