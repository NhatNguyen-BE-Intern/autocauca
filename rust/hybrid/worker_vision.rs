use std::io;

const WATER_WIDTH: usize = 70;
const WATER_HEIGHT: usize = 63;
const WATER_RGB: &[u8; 13230] = include_bytes!("assets/water.rgb");

const ALERT_WIDTH: usize = 33;
const ALERT_HEIGHT: usize = 35;
const ALERT_RGB: &[u8; 3465] = include_bytes!("assets/alert.rgb");

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AlertHit {
    pub x: u32,
    pub y: u32,
    pub score: f32,
}

pub fn water_point(payload: &[u8]) -> io::Result<Option<(u32, u32)>> {
    let image = crate::worker_protocol::validate_rgb_payload(payload)?;
    let (width, height) = (image.width as usize, image.height as usize);
    if width < 60 || height < 60 { return Ok(None); }

    let mut mean = [0.0; 3];
    for pixel in WATER_RGB.chunks_exact(3) {
        for channel in 0..3 { mean[channel] += f64::from(pixel[channel]); }
    }
    for value in &mut mean { *value /= (WATER_WIDTH * WATER_HEIGHT) as f64; }

    // Count every water pixel, including the interior of each 51 x 51 safe square.
    let table_stride = width + 1;
    let mut sums = vec![0u32; table_stride * (height + 1)];
    for y in 0..height {
        let mut row = 0;
        for x in 0..width {
            let offset = y * image.stride as usize + x * 3;
            let pixel = &image.rgb[offset..offset + 3];
            row += u32::from((0..3).all(|channel| (f64::from(pixel[channel]) - mean[channel]).abs() <= 14.0));
            sums[(y + 1) * table_stride + x + 1] = sums[y * table_stride + x + 1] + row;
        }
    }
    for y in ((height / 5).max(25)..(height * 82 / 100).min(height - 25)).step_by(4) {
        for x in ((width / 4).max(25)..(width * 3 / 4).min(width - 25)).step_by(4) {
            let (left, right, top, bottom) = (x - 25, x + 26, y - 25, y + 26);
            let count = sums[bottom * table_stride + right] + sums[top * table_stride + left]
                - sums[top * table_stride + right] - sums[bottom * table_stride + left];
            if count == 2601 { return Ok(Some((x as u32, y as u32))); }
        }
    }
    Ok(None)
}

pub fn alert_point(
    payload: &[u8],
    baseline_payload: Option<&[u8]>,
) -> io::Result<Option<AlertHit>> {
    let image = crate::worker_protocol::validate_rgb_payload(payload)?;
    let baseline = match baseline_payload {
        Some(base) => {
            let b = crate::worker_protocol::validate_rgb_payload(base)?;
            if b.width == image.width && b.height == image.height {
                Some(b)
            } else {
                None
            }
        }
        None => None,
    };

    let (width, height) = (image.width as usize, image.height as usize);
    if width < ALERT_WIDTH || height < ALERT_HEIGHT {
        return Ok(None);
    }

    let n = (ALERT_WIDTH * ALERT_HEIGHT) as f64;
    let mut t_mean = [0.0f64; 3];
    for pixel in ALERT_RGB.chunks_exact(3) {
        for c in 0..3 {
            t_mean[c] += f64::from(pixel[c]);
        }
    }
    for v in &mut t_mean {
        *v /= n;
    }

    let mut t_var = 0.0f64;
    for pixel in ALERT_RGB.chunks_exact(3) {
        for c in 0..3 {
            let diff = f64::from(pixel[c]) - t_mean[c];
            t_var += diff * diff;
        }
    }

    let mut best_score = -2.0f64;
    let mut best_coord = None;

    for y in 0..=(height - ALERT_HEIGHT) {
        for x in 0..=(width - ALERT_WIDTH) {
            let mut p_mean = [0.0f64; 3];
            for py in 0..ALERT_HEIGHT {
                let row_offset = (y + py) * image.stride as usize + x * 3;
                for px in 0..ALERT_WIDTH {
                    let offset = row_offset + px * 3;
                    for c in 0..3 {
                        p_mean[c] += f64::from(image.rgb[offset + c]);
                    }
                }
            }
            for v in &mut p_mean {
                *v /= n;
            }

            let mut p_var = 0.0f64;
            let mut cov = 0.0f64;
            let mut t_idx = 0;
            for py in 0..ALERT_HEIGHT {
                let row_offset = (y + py) * image.stride as usize + x * 3;
                for px in 0..ALERT_WIDTH {
                    let offset = row_offset + px * 3;
                    for c in 0..3 {
                        let p_diff = f64::from(image.rgb[offset + c]) - p_mean[c];
                        let t_diff = f64::from(ALERT_RGB[t_idx + c]) - t_mean[c];
                        p_var += p_diff * p_diff;
                        cov += p_diff * t_diff;
                    }
                    t_idx += 3;
                }
            }

            let denom = (t_var * p_var).sqrt();
            let score = if denom < 0.0001 { 0.0 } else { cov / denom };

            if score > best_score {
                best_score = score;
                best_coord = Some((x as u32, y as u32));
            }
        }
    }

    let (bx, by) = match best_coord {
        Some(coord) => coord,
        None => return Ok(None),
    };

    let hit = AlertHit {
        x: bx,
        y: by,
        score: best_score as f32,
    };

    if best_score >= 0.80 {
        return Ok(Some(hit));
    }
    if best_score < 0.60 {
        return Ok(None);
    }

    let Some(base) = baseline else {
        return Ok(if best_score >= 0.74 { Some(hit) } else { None });
    };

    let mut difference = 0.0f64;
    let mut dark = 0usize;

    for py in 0..ALERT_HEIGHT {
        let img_row = (by as usize + py) * image.stride as usize + bx as usize * 3;
        let base_row = (by as usize + py) * base.stride as usize + bx as usize * 3;
        for px in 0..ALERT_WIDTH {
            let i_off = img_row + px * 3;
            let b_off = base_row + px * 3;
            let mut is_dark = true;
            for c in 0..3 {
                let p_val = image.rgb[i_off + c];
                let q_val = base.rgb[b_off + c];
                difference += (f64::from(p_val) - f64::from(q_val)).abs();
                if p_val >= 45 {
                    is_dark = false;
                }
            }
            if is_dark {
                dark += 1;
            }
        }
    }

    let diff_avg = difference / (n * 3.0);
    let dark_ratio = dark as f64 / n;

    if diff_avg >= 18.0 && dark_ratio >= 0.05 {
        Ok(Some(hit))
    } else {
        Ok(None)
    }
}
