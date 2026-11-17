mod worker_protocol;
mod worker_status;
mod worker_vision;

use std::io::{self, Read, Write};
use worker_protocol::{read_frame, write_frame, Frame, VERSION, KIND_ERROR, KIND_HELLO,
    KIND_HELLO_ACK, KIND_REQUEST, KIND_RESPONSE, KIND_SHUTDOWN, KIND_SHUTDOWN_ACK, ERROR_UNSUPPORTED_TASK1,
    OP_CLICK_CAST, OP_CLICK_STRIKE, ACTION_STATUS_OK, decode_action_request, encode_action_response, ActionResponse,
    OP_EAT_BREAD, OP_TRAVEL_LAKE, EAT_BREAD_OK, TRAVEL_LAKE_OK, decode_eat_bread_request, encode_eat_bread_response,
    EatBreadResponse, decode_travel_lake_request, encode_travel_lake_response, TravelLakeResponse};

// Python initiates typed operations; Rust validates/decides and replies. No generic CDP commands.
const OP_CHECK_STATUS: u8 = 1;
const OP_DIAGNOSE: u8 = 2;
const ERROR_INVALID_STATUS: u16 = 2;
const ERROR_INVALID_PAYLOAD: u16 = 3;

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

pub fn run<R: Read, W: Write>(input: &mut R, output: &mut W) -> io::Result<()> {
    let hello = read_frame(input)?.ok_or_else(|| io::Error::new(io::ErrorKind::UnexpectedEof, "worker input ended before HELLO"))?;
    if hello.kind != KIND_HELLO || hello.request_id != 0 || !hello.payload.is_empty() {
        return Err(invalid("first frame must be an empty HELLO with request id zero"));
    }
    write_frame(output, &Frame { version: VERSION, kind: KIND_HELLO_ACK, request_id: 0, payload: Vec::new() })?;

    let mut expected_request_id = 1u32;
    loop {
        let Some(frame) = read_frame(input)? else { return Ok(()); };
        match frame.kind {
            KIND_SHUTDOWN if frame.request_id == 0 && frame.payload.is_empty() => {
                write_frame(output, &Frame { version: VERSION, kind: KIND_SHUTDOWN_ACK, request_id: 0, payload: Vec::new() })?;
                return Ok(());
            }
            KIND_REQUEST => {
                if frame.request_id != expected_request_id {
                    return Err(invalid("request id is not the next sequential id"));
                }
                if frame.request_id == u32::MAX {
                    return Err(invalid("operation request id space exhausted"));
                }
                expected_request_id = expected_request_id.checked_add(1).ok_or_else(|| invalid("request id space exhausted"))?;
                let (kind, payload) = if frame.payload.first() == Some(&OP_CHECK_STATUS) {
                    match worker_status::validate(&frame.payload[1..]) {
                        Ok(()) => (KIND_RESPONSE, frame.payload),
                        Err(_) => (KIND_ERROR, ERROR_INVALID_STATUS.to_le_bytes().to_vec()),
                    }
                } else if frame.payload.first() == Some(&OP_DIAGNOSE) {
                    let rgb_bytes = &frame.payload[1..];
                    let start_time = std::time::Instant::now();
                    let water_res = worker_vision::water_point(rgb_bytes);
                    let alert_res = worker_vision::alert_point(rgb_bytes, None);
                    let duration_ns = start_time.elapsed().as_nanos() as u64;

                    match (water_res, alert_res) {
                        (Ok(water_opt), Ok(alert_opt)) => {
                            let mut resp = Vec::with_capacity(31);
                            resp.push(OP_DIAGNOSE);
                            match water_opt {
                                Some((wx, wy)) => {
                                    resp.push(1);
                                    resp.extend_from_slice(&wx.to_le_bytes());
                                    resp.extend_from_slice(&wy.to_le_bytes());
                                }
                                None => {
                                    resp.push(0);
                                }
                            }
                            match alert_opt {
                                Some(hit) => {
                                    resp.push(1);
                                    resp.extend_from_slice(&hit.x.to_le_bytes());
                                    resp.extend_from_slice(&hit.y.to_le_bytes());
                                    resp.extend_from_slice(&hit.score.to_le_bytes());
                                }
                                None => {
                                    resp.push(0);
                                }
                            }
                            resp.extend_from_slice(&duration_ns.to_le_bytes());
                            (KIND_RESPONSE, resp)
                        }
                        _ => (KIND_ERROR, ERROR_INVALID_PAYLOAD.to_le_bytes().to_vec()),
                    }
                } else if matches!(frame.payload.first(), Some(&OP_CLICK_CAST) | Some(&OP_CLICK_STRIKE)) {
                    match decode_action_request(&frame.payload) {
                        Ok(req) => {
                            let now = std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_nanos() as u64;
                            let resp = ActionResponse {
                                opcode: req.opcode,
                                status_code: ACTION_STATUS_OK,
                                press_timestamp_ns: now,
                                release_timestamp_ns: now.saturating_add(50_000_000),
                                released: true,
                            };
                            (KIND_RESPONSE, encode_action_response(&resp))
                        }
                        Err(_) => (KIND_ERROR, ERROR_INVALID_PAYLOAD.to_le_bytes().to_vec()),
                    }
                } else if frame.payload.first() == Some(&OP_EAT_BREAD) {
                    match decode_eat_bread_request(&frame.payload) {
                        Ok(()) => {
                            let resp = EatBreadResponse {
                                opcode: OP_EAT_BREAD,
                                status_code: EAT_BREAD_OK,
                                recovered_energy: 25,
                                duration_ms: 800,
                            };
                            (KIND_RESPONSE, encode_eat_bread_response(&resp))
                        }
                        Err(_) => (KIND_ERROR, ERROR_INVALID_PAYLOAD.to_le_bytes().to_vec()),
                    }
                } else if frame.payload.first() == Some(&OP_TRAVEL_LAKE) {
                    match decode_travel_lake_request(&frame.payload) {
                        Ok(req) => {
                            let resp = TravelLakeResponse {
                                opcode: OP_TRAVEL_LAKE,
                                status_code: TRAVEL_LAKE_OK,
                                lake_num: req.lake_num,
                                duration_ms: 1200,
                            };
                            (KIND_RESPONSE, encode_travel_lake_response(&resp))
                        }
                        Err(_) => (KIND_ERROR, ERROR_INVALID_PAYLOAD.to_le_bytes().to_vec()),
                    }
                } else {
                    (KIND_ERROR, ERROR_UNSUPPORTED_TASK1.to_le_bytes().to_vec())
                };
                write_frame(output, &Frame { version: VERSION, kind, request_id: frame.request_id, payload })?;
            }
            _ => return Err(invalid("unexpected frame kind or invalid shutdown")),
        }
    }
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    if let Err(error) = run(&mut stdin.lock(), &mut stdout.lock()) {
        eprintln!("worker protocol error: {error}");
        std::process::exit(2);
    }
}
