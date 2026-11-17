#[path = "../worker_protocol.rs"]
mod worker_protocol;
#[path = "../worker.rs"]
mod worker;
#[path = "../worker_vision.rs"]
mod worker_vision;

use std::io::{self, Cursor, Read, Write};
use worker_protocol::{Frame, RgbPayload, MAX_FRAME_LEN, VERSION, KIND_ERROR, KIND_HELLO,
    KIND_HELLO_ACK, KIND_REQUEST, KIND_RESPONSE, KIND_SHUTDOWN, KIND_SHUTDOWN_ACK,
    read_frame, write_frame, validate_rgb_payload};

fn frame(kind: u8, id: u32, payload: &[u8]) -> Frame {
    Frame { version: VERSION, kind, request_id: id, payload: payload.to_vec() }
}

fn raw_frame(version: u8, kind: u8, reserved: u16, id: u32, payload: &[u8]) -> Vec<u8> {
    let len = 8usize + payload.len();
    let mut bytes = Vec::with_capacity(4 + len);
    bytes.extend_from_slice(&(len as u32).to_le_bytes());
    bytes.push(version);
    bytes.push(kind);
    bytes.extend_from_slice(&reserved.to_le_bytes());
    bytes.extend_from_slice(&id.to_le_bytes());
    bytes.extend_from_slice(payload);
    bytes
}

struct ChunkReader { bytes: Cursor<Vec<u8>>, max_chunk: usize }
impl Read for ChunkReader {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        let limit = out.len().min(self.max_chunk);
        self.bytes.read(&mut out[..limit])
    }
}

#[test]
fn frame_round_trip_and_two_consecutive_frames() {
    let first = frame(KIND_REQUEST, 1, b"one");
    let second = frame(KIND_REQUEST, 2, b"two");
    let mut bytes = Vec::new();
    write_frame(&mut bytes, &first).unwrap();
    write_frame(&mut bytes, &second).unwrap();
    let mut input = Cursor::new(bytes);
    assert_eq!(read_frame(&mut input).unwrap(), Some(first));
    assert_eq!(read_frame(&mut input).unwrap(), Some(second));
    assert_eq!(read_frame(&mut input).unwrap(), None);
}

#[test]
fn reader_handles_short_reads_across_prefix_header_and_payload() {
    let expected = frame(KIND_RESPONSE, 9, b"partial reads are normal");
    let bytes = raw_frame(VERSION, KIND_RESPONSE, 0, 9, &expected.payload);
    let mut input = ChunkReader { bytes: Cursor::new(bytes), max_chunk: 1 };
    assert_eq!(read_frame(&mut input).unwrap(), Some(expected));
}

#[test]
fn clean_eof_differs_from_truncated_length_and_frame() {
    assert_eq!(read_frame(&mut Cursor::new(Vec::<u8>::new())).unwrap(), None);
    let prefix = [12u32.to_le_bytes()[0], 12u32.to_le_bytes()[1]];
    assert_eq!(read_frame(&mut Cursor::new(prefix)).unwrap_err().kind(), io::ErrorKind::UnexpectedEof);
    let mut truncated = raw_frame(VERSION, KIND_RESPONSE, 0, 1, b"abc");
    truncated.pop();
    assert_eq!(read_frame(&mut Cursor::new(truncated)).unwrap_err().kind(), io::ErrorKind::UnexpectedEof);
}

#[test]
fn rejects_length_below_header_and_above_32_mib_before_reading_body() {
    for length in [7u32, (MAX_FRAME_LEN as u32) + 1] {
        let mut input = Cursor::new(length.to_le_bytes().to_vec());
        assert_eq!(read_frame(&mut input).unwrap_err().kind(), io::ErrorKind::InvalidData);
        assert_eq!(input.position(), 4, "must reject using only the length prefix");
    }
}

#[test]
fn rejects_invalid_version_reserved_bits_and_request_ids() {
    for bytes in [
        raw_frame(2, KIND_REQUEST, 0, 1, b""),
        raw_frame(VERSION, KIND_REQUEST, 1, 1, b""),
        raw_frame(VERSION, KIND_REQUEST, 0, 0, b""),
        raw_frame(VERSION, KIND_HELLO, 0, 1, b""),
        raw_frame(VERSION, KIND_SHUTDOWN, 0, 2, b""),
    ] {
        assert_eq!(read_frame(&mut Cursor::new(bytes)).unwrap_err().kind(), io::ErrorKind::InvalidData);
    }
}

fn rgb_payload(width: u32, height: u32, stride: u32, timestamp: u64, pixels: &[u8]) -> Vec<u8> {
    let mut payload = Vec::new();
    payload.extend_from_slice(&width.to_le_bytes());
    payload.extend_from_slice(&height.to_le_bytes());
    payload.extend_from_slice(&stride.to_le_bytes());
    payload.extend_from_slice(&timestamp.to_le_bytes());
    payload.extend_from_slice(pixels);
    payload
}

#[test]
fn rgb_payload_validates_exact_dimensions_overflow_and_trailing_bytes() {
    let pixels = [1, 2, 3, 4, 5, 6];
    let payload = rgb_payload(2, 1, 6, 55, &pixels);
    let parsed: RgbPayload<'_> = validate_rgb_payload(&payload).unwrap();
    assert_eq!((parsed.width, parsed.height, parsed.stride, parsed.captured_monotonic_ns), (2, 1, 6, 55));
    assert_eq!(parsed.rgb, &pixels);

    assert_eq!(validate_rgb_payload(&rgb_payload(u32::MAX, 1, u32::MAX, 0, &[])).unwrap_err().kind(), io::ErrorKind::InvalidData);
    assert_eq!(validate_rgb_payload(&rgb_payload(8192, 8192, 8192 * 3, 0, &[])).unwrap_err().kind(), io::ErrorKind::InvalidData);
    assert_eq!(validate_rgb_payload(&rgb_payload(2, 1, 6, 0, &[1, 2, 3, 4, 5, 6, 7])).unwrap_err().kind(), io::ErrorKind::InvalidData);
    assert_eq!(validate_rgb_payload(&rgb_payload(2, 1, 5, 0, &pixels)).unwrap_err().kind(), io::ErrorKind::InvalidData);
}

#[test]
fn worker_handshake_requests_sequential_ids_and_shutdown_without_actions() {
    let mut input = Vec::new();
    write_frame(&mut input, &frame(KIND_HELLO, 0, &[])).unwrap();
    write_frame(&mut input, &frame(KIND_REQUEST, 1, b"no action dispatch in task 1")).unwrap();
    write_frame(&mut input, &frame(KIND_REQUEST, 2, b"still no action dispatch")).unwrap();
    write_frame(&mut input, &frame(KIND_SHUTDOWN, 0, &[])).unwrap();

    let mut output = Vec::new();
    worker::run(&mut Cursor::new(input), &mut output).unwrap();
    let mut output = Cursor::new(output);
    let hello = read_frame(&mut output).unwrap().unwrap();
    assert_eq!((hello.kind, hello.request_id), (KIND_HELLO_ACK, 0));
    let err1 = read_frame(&mut output).unwrap().unwrap();
    let err2 = read_frame(&mut output).unwrap().unwrap();
    assert_eq!((err1.kind, err1.request_id), (KIND_ERROR, 1));
    assert_eq!((err2.kind, err2.request_id), (KIND_ERROR, 2));
    assert_eq!(read_frame(&mut output).unwrap().unwrap().kind, KIND_SHUTDOWN_ACK);
    assert_eq!(read_frame(&mut output).unwrap(), None);
}

#[test]
fn worker_rejects_wrong_request_id_before_any_dispatch_response() {
    let mut input = Vec::new();
    write_frame(&mut input, &frame(KIND_HELLO, 0, &[])).unwrap();
    write_frame(&mut input, &frame(KIND_REQUEST, 2, b"must not dispatch")).unwrap();
    let mut output = Vec::new();
    assert_eq!(worker::run(&mut Cursor::new(input), &mut output).unwrap_err().kind(), io::ErrorKind::InvalidData);
    let mut output = Cursor::new(output);
    assert_eq!(read_frame(&mut output).unwrap().unwrap().kind, KIND_HELLO_ACK);
    assert_eq!(read_frame(&mut output).unwrap(), None, "invalid id emits no operation response");
}

// Independently assembled golden status payload shared with Python's documented v1 layout.
fn golden_status() -> Vec<u8> {
    let url = b"https://nomstead.com/qn";
    let mut bytes = (url.len() as u32).to_le_bytes().to_vec();
    bytes.extend_from_slice(url);
    for n in [800.0f64, 600.0, 1.25] { bytes.extend_from_slice(&n.to_le_bytes()); }
    bytes.push(1); bytes.extend_from_slice(&70u32.to_le_bytes());
    bytes.push(1); bytes.extend_from_slice(&u64::MAX.to_le_bytes());
    bytes.extend_from_slice(&0u32.to_le_bytes()); // empty toast
    bytes.push(0); bytes.extend_from_slice(&0u64.to_le_bytes()); bytes.push(0);
    bytes
}

fn status_request(payload: &[u8]) -> Frame {
    let mut bytes = vec![1]; bytes.extend_from_slice(payload);
    let mut input = Vec::new();
    write_frame(&mut input, &frame(KIND_HELLO, 0, &[])).unwrap();
    write_frame(&mut input, &frame(KIND_REQUEST, 1, &bytes)).unwrap();
    write_frame(&mut input, &frame(KIND_SHUTDOWN, 0, &[])).unwrap();
    let mut output = Vec::new();
    worker::run(&mut Cursor::new(input), &mut output).unwrap();
    let mut output = Cursor::new(output);
    read_frame(&mut output).unwrap();
    read_frame(&mut output).unwrap().unwrap()
}

#[test]
fn status_codec_golden_and_every_truncation() {
    let golden = golden_status();
    let reply = status_request(&golden);
    assert_eq!(reply.kind, KIND_RESPONSE);
    assert_eq!(&reply.payload[1..], &golden);
    for end in 0..golden.len() {
        let reply = status_request(&golden[..end]);
        assert_eq!(reply.kind, KIND_ERROR, "accepted truncated offset {end}");
        assert_eq!(reply.payload, 2u16.to_le_bytes());
    }
    let mut trailing = golden.clone(); trailing.push(0);
    assert_eq!(status_request(&trailing).kind, KIND_ERROR);
    let mut deceptive = golden; deceptive[12] = b'X';
    assert_eq!(status_request(&deceptive).kind, KIND_ERROR);
}

const SAFE_WATER: [u8; 3] = [72, 90, 100];
const DRY: [u8; 3] = [200, 30, 5];

fn reference_water_pixel(pixel: &[u8]) -> bool {
    let means = [318229.0 / 4410.0, 397111.0 / 4410.0, 441422.0 / 4410.0];
    (0..3).all(|channel| (f64::from(pixel[channel]) - means[channel]).abs() <= 14.0)
}

fn direct_water_reference(width: usize, height: usize, pixels: &[u8]) -> Option<(u32, u32)> {
    if width < 60 || height < 60 { return None; }
    let mut y = (height / 5).max(25);
    while y < (height * 82 / 100).min(height - 25) {
        let mut x = (width / 4).max(25);
        while x < (width * 3 / 4).min(width - 25) {
            let mut safe = true;
            'square: for row in y - 25..=y + 25 {
                for column in x - 25..=x + 25 {
                    let offset = (row * width + column) * 3;
                    if !reference_water_pixel(&pixels[offset..offset + 3]) {
                        safe = false;
                        break 'square;
                    }
                }
            }
            if safe { return Some((x as u32, y as u32)); }
            x += 4;
        }
        y += 4;
    }
    None
}

fn paint_water_square(pixels: &mut [u8], width: usize, x: usize, y: usize) {
    for row in y - 25..=y + 25 {
        for column in x - 25..=x + 25 {
            let offset = (row * width + column) * 3;
            pixels[offset..offset + 3].copy_from_slice(&SAFE_WATER);
        }
    }
}

fn compare_water_reference(width: usize, height: usize, pixels: &[u8]) -> Option<(u32, u32)> {
    let expected = direct_water_reference(width, height, pixels);
    let payload = rgb_payload(width as u32, height as u32, (width * 3) as u32,
                              0x0102030405060708, pixels);
    let actual = worker_vision::water_point(&payload).unwrap();
    assert_eq!(actual, expected, "reference mismatch for {width}x{height}");
    if let Some((x, y)) = actual {
        for row in y as usize - 25..=y as usize + 25 {
            for column in x as usize - 25..=x as usize + 25 {
                let offset = (row * width + column) * 3;
                assert!(reference_water_pixel(&pixels[offset..offset + 3]), "unsafe returned square");
            }
        }
    }
    actual
}

#[test]
fn water_asset_embedded_bytes_have_independent_channel_sums() {
    let water: &[u8; 13230] = include_bytes!("../assets/water.rgb");
    let mut sums = [0u32; 3];
    for pixel in water.chunks_exact(3) {
        for channel in 0..3 { sums[channel] += u32::from(pixel[channel]); }
    }
    assert_eq!(sums, [318229, 397111, 441422]);
}

#[test]
fn water_all_safe_first_points_dry_and_minimum_dimensions() {
    for (width, height, expected) in [(60, 60, Some((25, 25))), (100, 100, Some((25, 25))),
            (120, 100, Some((30, 25))), (59, 60, None), (60, 59, None)] {
        let pixels = SAFE_WATER.repeat(width * height);
        assert_eq!(compare_water_reference(width, height, &pixels), expected);
    }
    assert_eq!(compare_water_reference(100, 100, &DRY.repeat(10000)), None);
    for timestamp in [0, u64::MAX] {
        let payload = rgb_payload(60, 60, 180, timestamp, &SAFE_WATER.repeat(3600));
        assert_eq!(worker_vision::water_point(&payload).unwrap(), Some((25, 25)));
    }
}

#[test]
fn water_search_is_row_major_then_left_to_right() {
    for (centers, expected) in [([(124, 44), (64, 104)], (124, 44)),
                                ([(64, 44), (124, 44)], (64, 44))] {
        let mut pixels = DRY.repeat(240 * 200);
        for (x, y) in centers { paint_water_square(&mut pixels, 240, x, y); }
        assert_eq!(compare_water_reference(240, 200, &pixels), Some(expected));
    }
}

#[test]
fn water_last_candidate_exclusive_bounds_and_off_grid() {
    for (width, height, center, expected) in [(100, 100, (73, 73), Some((73, 73))),
            (120, 200, (90, 40), None), (120, 200, (30, 164), None),
            (100, 100, (74, 25), None)] {
        let mut pixels = DRY.repeat(width * height);
        paint_water_square(&mut pixels, width, center.0, center.1);
        assert_eq!(compare_water_reference(width, height, &pixels), expected);
    }
}

#[test]
fn water_checks_every_interior_edge_and_corner_pixel() {
    let mut pixels = DRY.repeat(10000);
    paint_water_square(&mut pixels, 100, 25, 25);
    assert_eq!(compare_water_reference(100, 100, &pixels), Some((25, 25)));
    for (x, y) in [(25, 25), (0, 0), (25, 0), (50, 50), (50, 25)] {
        let mut defective = pixels.clone();
        let offset = (y * 100 + x) * 3;
        defective[offset..offset + 3].copy_from_slice(&DRY);
        assert_eq!(compare_water_reference(100, 100, &defective), None);
    }
    for y in 1..50 {
        for x in 1..50 {
            let offset = (y * 100 + x) * 3;
            pixels[offset..offset + 3].copy_from_slice(&DRY);
        }
    }
    assert_eq!(compare_water_reference(100, 100, &pixels), None, "perimeter alone is insufficient");
}

#[test]
fn water_fractional_mean_thresholds_check_each_rgb_channel() {
    for (channel, lower, upper) in [(0, 59, 86), (1, 77, 104), (2, 87, 114)] {
        for (value, expected) in [(lower, Some((25, 25))), (upper, Some((25, 25))),
                                  (lower - 1, None), (upper + 1, None)] {
            let mut color = SAFE_WATER;
            color[channel] = value;
            assert_eq!(compare_water_reference(60, 60, &color.repeat(3600)), expected,
                       "channel {channel}, value {value}");
        }
    }
}

#[test]
fn water_integral_mask_matches_direct_reference_on_seeded_mixed_frames() {
    for (width, height) in [(61, 63), (76, 84), (100, 100), (120, 100), (120, 200)] {
        for seed in 0..6u32 {
            let mut state = seed + 3103;
            let mut pixels = Vec::with_capacity(width * height * 3);
            for _ in 0..width * height {
                state = state.wrapping_mul(1664525).wrapping_add(1013904223);
                pixels.extend_from_slice(if state >> 30 == 0 { &DRY } else { &SAFE_WATER });
            }
            let (x, y) = ((width / 4).max(25), (height / 5).max(25));
            if seed % 3 == 0 { paint_water_square(&mut pixels, width, x, y); }
            if seed % 3 == 1 { paint_water_square(&mut pixels, width, width / 2, height / 2); }
            if seed % 3 == 2 {
                paint_water_square(&mut pixels, width, x, y);
                let offset = (y * width + x) * 3;
                pixels[offset..offset + 3].copy_from_slice(&DRY);
            }
            compare_water_reference(width, height, &pixels);
        }
    }
}

#[test]
fn water_rejects_malformed_rgb_before_mask_allocation() {
    let valid = rgb_payload(60, 60, 180, 0, &SAFE_WATER.repeat(3600));
    let mut malformed: Vec<Vec<u8>> = (0..20).map(|end| valid[..end].to_vec()).collect();
    for (width, height, stride) in [(0, 60, 0), (60, 0, 180), (8193, 1, 24579),
            (1, 8193, 3), (60, 60, 179), (8192, 8192, 24576)] {
        malformed.push(rgb_payload(width, height, stride, 0, &[]));
    }
    malformed.push(valid[..valid.len() - 1].to_vec());
    let mut trailing = valid;
    trailing.push(0);
    malformed.push(trailing);
    for payload in malformed {
        let expected = validate_rgb_payload(&payload).unwrap_err();
        let actual = worker_vision::water_point(&payload).unwrap_err();
        assert_eq!(actual.kind(), io::ErrorKind::InvalidData);
        assert_eq!(actual.to_string(), expected.to_string());
    }
}

const ALERT_TEMPLATE_RGB: &[u8; 3465] = include_bytes!("../assets/alert.rgb");

fn paint_alert_template(pixels: &mut [u8], width: usize, x: usize, y: usize) {
    let mut t_idx = 0;
    for py in 0..35 {
        let row_offset = (y + py) * width * 3 + x * 3;
        for px in 0..33 {
            let offset = row_offset + px * 3;
            pixels[offset..offset + 3].copy_from_slice(&ALERT_TEMPLATE_RGB[t_idx..t_idx + 3]);
            t_idx += 3;
        }
    }
}

#[test]
fn alert_asset_embedded_bytes_have_independent_channel_sums() {
    let alert: &[u8; 3465] = include_bytes!("../assets/alert.rgb");
    let mut sums = [0u32; 3];
    for pixel in alert.chunks_exact(3) {
        for channel in 0..3 { sums[channel] += u32::from(pixel[channel]); }
    }
    assert_eq!(sums, [73027, 87730, 97704]);
}

#[test]
fn alert_exact_match_on_flat_background() {
    let width = 50;
    let height = 50;
    let mut pixels = vec![128u8; width * height * 3];
    paint_alert_template(&mut pixels, width, 10, 10);
    let payload = rgb_payload(width as u32, height as u32, (width * 3) as u32, 0, &pixels);
    let hit = worker_vision::alert_point(&payload, None).unwrap().expect("expected exact match");
    assert_eq!((hit.x, hit.y), (10, 10));
    assert!(hit.score > 0.999, "score must be near 1.0, got {}", hit.score);
}

#[test]
fn alert_zero_variance_frame_returns_none() {
    for fill in [0u8, 255u8] {
        let pixels = vec![fill; 50 * 50 * 3];
        let payload = rgb_payload(50, 50, 150, 0, &pixels);
        assert_eq!(worker_vision::alert_point(&payload, None).unwrap(), None);
    }
}

#[test]
fn alert_undersized_dimensions_rejected() {
    for (width, height) in [(32, 35), (33, 34), (10, 10)] {
        let pixels = vec![0u8; (width * height * 3) as usize];
        let payload = rgb_payload(width, height, width * 3, 0, &pixels);
        assert_eq!(worker_vision::alert_point(&payload, None).unwrap(), None);
    }
}

#[test]
fn alert_high_confidence_returns_hit_without_baseline() {
    let width = 40;
    let height = 40;
    let mut pixels = vec![50u8; width * height * 3];
    paint_alert_template(&mut pixels, width, 2, 2);
    let payload = rgb_payload(width as u32, height as u32, (width * 3) as u32, 0, &pixels);
    let hit = worker_vision::alert_point(&payload, None).unwrap().expect("high confidence hit");
    assert_eq!((hit.x, hit.y), (2, 2));
    assert!(hit.score >= 0.80);
}

#[test]
fn alert_sub_threshold_returns_none() {
    let width = 40;
    let height = 40;
    let pixels = vec![200u8; width * height * 3];
    let payload = rgb_payload(width as u32, height as u32, (width * 3) as u32, 0, &pixels);
    assert_eq!(worker_vision::alert_point(&payload, None).unwrap(), None);
}

#[test]
fn alert_double_verification_with_baseline_diff_and_dark() {
    let width = 40;
    let height = 40;
    let base_pixels = vec![200u8; width * height * 3];
    let base_payload = rgb_payload(width as u32, height as u32, (width * 3) as u32, 0, &base_pixels);

    let mut img_pixels = base_pixels.clone();
    paint_alert_template(&mut img_pixels, width, 2, 2);
    let img_payload = rgb_payload(width as u32, height as u32, (width * 3) as u32, 0, &img_pixels);

    let hit = worker_vision::alert_point(&img_payload, Some(&base_payload)).unwrap().expect("must hit with valid baseline");
    assert_eq!((hit.x, hit.y), (2, 2));
}

#[test]
fn alert_rejects_malformed_payload_and_baseline() {
    let valid = rgb_payload(40, 40, 120, 0, &vec![0u8; 40 * 40 * 3]);
    let mut malformed: Vec<Vec<u8>> = (0..20).map(|end| valid[..end].to_vec()).collect();
    malformed.push(valid[..valid.len() - 1].to_vec());
    let mut trailing = valid.clone();
    trailing.push(0);
    malformed.push(trailing);

    for payload in malformed {
        assert!(worker_vision::alert_point(&payload, None).is_err());
        assert!(worker_vision::alert_point(&valid, Some(&payload)).is_err());
    }

    let mismatched_base = rgb_payload(35, 40, 105, 0, &vec![0u8; 35 * 40 * 3]);
    let mut img_pixels = vec![128u8; 40 * 40 * 3];
    paint_alert_template(&mut img_pixels, 40, 2, 2);
    let img_payload = rgb_payload(40, 40, 120, 0, &img_pixels);
    let hit = worker_vision::alert_point(&img_payload, Some(&mismatched_base)).unwrap().expect("falls back to no baseline");
    assert_eq!((hit.x, hit.y), (2, 2));
}

#[test]
fn action_request_and_response_wire_codec_and_worker_dispatch() {
    use worker_protocol::{ActionRequest, ActionResponse, OP_CLICK_CAST, OP_CLICK_STRIKE,
        ACTION_STATUS_OK, decode_action_request, encode_action_response};

    // Valid round-trip request
    let mut req_bytes = vec![OP_CLICK_CAST];
    req_bytes.extend_from_slice(&123.456f64.to_le_bytes());
    req_bytes.extend_from_slice(&789.012f64.to_le_bytes());
    assert_eq!(req_bytes.len(), 17);

    let parsed_req = decode_action_request(&req_bytes).unwrap();
    assert_eq!(parsed_req, ActionRequest { opcode: OP_CLICK_CAST, x: 123.456, y: 789.012 });

    // Valid round-trip response
    let resp = ActionResponse {
        opcode: OP_CLICK_STRIKE,
        status_code: ACTION_STATUS_OK,
        press_timestamp_ns: 1000000,
        release_timestamp_ns: 1050000,
        released: true,
    };
    let resp_bytes = encode_action_response(&resp);
    assert_eq!(resp_bytes.len(), 19);
    assert_eq!(resp_bytes[0], OP_CLICK_STRIKE);
    assert_eq!(resp_bytes[1], ACTION_STATUS_OK);
    assert_eq!(resp_bytes[18], 1);

    // Truncation and non-finite rejection
    for len in 0..17 {
        assert!(decode_action_request(&req_bytes[..len]).is_err());
    }
    let mut nan_bytes = vec![OP_CLICK_CAST];
    nan_bytes.extend_from_slice(&f64::NAN.to_le_bytes());
    nan_bytes.extend_from_slice(&100.0f64.to_le_bytes());
    assert!(decode_action_request(&nan_bytes).is_err());
}

#[test]
fn navigation_and_energy_wire_codec_and_worker_dispatch() {
    use worker_protocol::{OP_EAT_BREAD, OP_TRAVEL_LAKE, EAT_BREAD_OK, TRAVEL_LAKE_OK,
        EatBreadResponse, TravelLakeRequest, TravelLakeResponse,
        decode_eat_bread_request, encode_eat_bread_response,
        decode_travel_lake_request, encode_travel_lake_response};

    // Opcode 5: Eat bread
    assert!(decode_eat_bread_request(&[OP_EAT_BREAD]).is_ok());
    assert!(decode_eat_bread_request(&[]).is_err());
    assert!(decode_eat_bread_request(&[OP_EAT_BREAD, 0]).is_err());
    assert!(decode_eat_bread_request(&[99]).is_err());

    let bread_resp = EatBreadResponse {
        opcode: OP_EAT_BREAD,
        status_code: EAT_BREAD_OK,
        recovered_energy: 25,
        duration_ms: 800,
    };
    let bread_bytes = encode_eat_bread_response(&bread_resp);
    assert_eq!(bread_bytes.len(), 10);
    assert_eq!(bread_bytes[0], OP_EAT_BREAD);
    assert_eq!(bread_bytes[1], EAT_BREAD_OK);

    // Opcode 6: Travel lake
    let req6 = decode_travel_lake_request(&[OP_TRAVEL_LAKE, 12]).unwrap();
    assert_eq!(req6, TravelLakeRequest { opcode: OP_TRAVEL_LAKE, lake_num: 12 });

    // Bounds checking
    assert!(decode_travel_lake_request(&[OP_TRAVEL_LAKE, 0]).is_err());
    assert!(decode_travel_lake_request(&[OP_TRAVEL_LAKE, 41]).is_err());
    assert!(decode_travel_lake_request(&[OP_TRAVEL_LAKE]).is_err());
    assert!(decode_travel_lake_request(&[OP_TRAVEL_LAKE, 12, 0]).is_err());

    let travel_resp = TravelLakeResponse {
        opcode: OP_TRAVEL_LAKE,
        status_code: TRAVEL_LAKE_OK,
        lake_num: 12,
        duration_ms: 1200,
    };
    let travel_bytes = encode_travel_lake_response(&travel_resp);
    assert_eq!(travel_bytes.len(), 7);
    assert_eq!(travel_bytes[0], OP_TRAVEL_LAKE);
    assert_eq!(travel_bytes[1], TRAVEL_LAKE_OK);
    assert_eq!(travel_bytes[2], 12);
}
