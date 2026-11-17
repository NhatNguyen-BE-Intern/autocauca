use image::{imageops, RgbImage};
use crate::cdp::Result;

pub fn decode(bytes: &[u8]) -> Result<RgbImage> { Ok(image::load_from_memory(bytes)?.to_rgb8()) }
pub fn template(name: &str) -> Result<RgbImage> {
    decode(match name {
        "alert" => include_bytes!("../assets/cham_than.png"),
        "water" => include_bytes!("../assets/ho_nuoc.png"),
        "bread" => include_bytes!("../assets/banh_mi.png"),
        "codex" => include_bytes!("../assets/btn_codex.png"),
        "bookmarks" => include_bytes!("../assets/tab_bookmarks.png"),
        "pocket" => include_bytes!("../assets/btn_pocket.png"),
        _ => return Err("Unknown template".into()),
    })
}

#[derive(Debug, Clone, Copy)]
pub struct Hit { pub x: u32, pub y: u32, pub score: f64, pub width: u32, pub height: u32 }

// Scalar reference for correctness tests. RGB channel means are subtracted as in TM_CCOEFF_NORMED.
#[cfg(test)]
fn correlation(image: &RgbImage, pattern: &RgbImage, x: u32, y: u32, stride: usize) -> f64 {
    let mut a = [0.0;3]; let mut b = [0.0;3];
    let mut aa = 0.0; let mut bb = 0.0; let mut ab = 0.0; let mut n = 0.0;
    for ty in (0..pattern.height()).step_by(stride) {
        for tx in (0..pattern.width()).step_by(stride) {
            let p = image.get_pixel(x + tx, y + ty);
            let t = pattern.get_pixel(tx,ty);
            n += 1.0;
            for c in 0..3 {
                let v = p[c] as f64; let u = t[c] as f64;
                a[c] += v; b[c] += u; aa += v*v; bb += u*u; ab += v*u;
            }
        }
    }
    let numerator = ab - (0..3).map(|c| a[c]*b[c]/n).sum::<f64>();
    let denominator = ((aa-a.iter().map(|s|s*s/n).sum::<f64>()).max(0.0)
        * (bb-b.iter().map(|s|s*s/n).sum::<f64>()).max(0.0)).sqrt();
    if denominator < 0.0001 { 0.0 } else { numerator / denominator }
}

pub struct PreparedTemplate {
    width:u32,
    height:u32,
    centered:Vec<f64>,
    variance:f64,
    suffix_energy:Vec<f64>,
    suffix_channel_sum:Vec<[f64;3]>,
}
impl PreparedTemplate {
    pub fn new(pattern:&RgbImage)->Self {
        let n=(pattern.width()*pattern.height()) as f64;
        let mut sums=[0.0;3];
        let mut squares=0.0;
        for pixel in pattern.pixels() {
            for c in 0..3 {
                let value=pixel[c] as f64;
                sums[c]+=value;
                squares+=value*value;
            }
        }
        let mean=sums.map(|sum|sum/n);
        let variance=(squares-(0..3).map(|c|sums[c]*sums[c]/n).sum::<f64>()).max(0.0);
        let centered=pattern.as_raw().chunks_exact(3).flat_map(|pixel| {
            (0..3).map(move |c|pixel[c] as f64-mean[c])
        }).collect();
        let mut suffix_energy=vec![0.0;pattern.height() as usize+1];
        let mut suffix_channel_sum=vec![[0.0;3];pattern.height() as usize+1];
        for y in (0..pattern.height() as usize).rev() {
            let mut energy=0.0;
            let mut channel_sum=[0.0;3];
            for x in 0..pattern.width() as usize {
                let offset=(y*pattern.width() as usize+x)*3;
                for c in 0..3 {
                    let value=centered[offset+c];
                    energy+=value*value;
                    channel_sum[c]+=value;
                }
            }
            suffix_energy[y]=suffix_energy[y+1]+energy;
            for c in 0..3 {suffix_channel_sum[y][c]=suffix_channel_sum[y+1][c]+channel_sum[c];}
        }
        Self{width:pattern.width(),height:pattern.height(),centered,variance,suffix_energy,suffix_channel_sum}
    }
}

#[derive(Debug,Default,Clone,Copy)]
struct ScanStats {
    positions:usize,
    exact_positions:usize,
    pruned_positions:usize,
    dot_macs:usize,
    theoretical_full_macs:usize,
}
#[derive(Default)]
pub struct MatcherScratch {
    sums:Vec<[u64;3]>,
    squares:Vec<u64>,
    scores:Vec<f64>,
    buffer_growths:usize,
    last_scan:ScanStats,
}
impl MatcherScratch {
    fn ensure_integral(&mut self,size:usize) {
        if size>self.sums.capacity() {self.buffer_growths+=1;}
        if size>self.squares.capacity() {self.buffer_growths+=1;}
        self.sums.resize(size,[0;3]);
        self.squares.resize(size,0);
        self.sums.fill([0;3]);
        self.squares.fill(0);
    }
}

struct IntegralImage;
impl IntegralImage {
    fn build(image:&RgbImage,scratch:&mut MatcherScratch) {
        let width=image.width() as usize;
        let height=image.height() as usize;
        let stride=width+1;
        let size=stride*(height+1);
        scratch.ensure_integral(size);
        for y in 0..height {
            let mut row_sum=[0u64;3];
            let mut row_square=0u64;
            for x in 0..width {
                let pixel=image.get_pixel(x as u32,y as u32);
                let index=(y+1)*stride+x+1;
                let above=y*stride+x+1;
                for c in 0..3 {
                    let value=u64::from(pixel[c]);
                    row_sum[c]+=value;
                    row_square+=value*value;
                    scratch.sums[index][c]=scratch.sums[above][c]+row_sum[c];
                }
                scratch.squares[index]=scratch.squares[above]+row_square;
            }
        }
    }
    fn rect_sum(table:&[[u64;3]],stride:usize,x:usize,y:usize,w:usize,h:usize)->[f64;3] {
        let left=x;
        let right=x+w;
        let top=y;
        let bottom=y+h;
        std::array::from_fn(|c|(table[bottom*stride+right][c]+table[top*stride+left][c]
            -table[top*stride+right][c]-table[bottom*stride+left][c]) as f64)
    }
    fn rect_scalar(table:&[u64],stride:usize,x:usize,y:usize,w:usize,h:usize)->f64 {
        let left=x;
        let right=x+w;
        let top=y;
        let bottom=y+h;
        (table[bottom*stride+right]+table[top*stride+left]
            -table[top*stride+right]-table[bottom*stride+left]) as f64
    }
}

const DOT_BAND_ROWS:usize=4;
// Deliberately loose relative margins cover prefix-sum and bound roundoff. Anything close
// to the current best/threshold is evaluated through the full dot product.
const BOUND_RELATIVE_SAFETY:f64=1e-9;
fn residual_energy_bound(sums:[f64;3],square:f64,area:f64,mean:[f64;3])->Option<(f64,f64)> {
    let mut correction=0.0;
    let mut scale=square.abs()+1.0;
    for c in 0..3 {
        let cross=2.0*mean[c]*sums[c];
        let mean_square=area*mean[c]*mean[c];
        correction+=cross;
        scale+=cross.abs()+mean_square.abs();
    }
    let raw=square-correction+area*mean.iter().map(|v|v*v).sum::<f64>();
    if !raw.is_finite() {return None;}
    let rounding=scale*BOUND_RELATIVE_SAFETY;
    if raw < -rounding {return None;}
    Some((raw.max(0.0)+rounding,rounding))
}
fn can_prune(upper:f64,target:f64,denominator:f64,rounding:f64)->bool {
    if !upper.is_finite() || !target.is_finite() {return false;}
    let margin=BOUND_RELATIVE_SAFETY*(upper.abs()+target.abs()+denominator.abs()+1.0)+rounding;
    upper < target-margin
}

fn scan_best(image:&RgbImage,pattern:&PreparedTemplate,scratch:&mut MatcherScratch,
    minimum_score:Option<f64>)->Option<Hit> {
    let (width,height)=(image.width() as usize,image.height() as usize);
    let (pattern_width,pattern_height)=(pattern.width as usize,pattern.height as usize);
    if pattern_width==0 || pattern_height==0 || pattern_width>width || pattern_height>height {return None;}
    let stride=width+1;
    let score_len=(width-pattern_width+1)*(height-pattern_height+1);
    if minimum_score.is_some() {
        if score_len>scratch.scores.capacity() {scratch.buffer_growths+=1;}
        scratch.scores.resize(score_len,f64::NEG_INFINITY);
        scratch.scores.fill(f64::NEG_INFINITY);
    }
    IntegralImage::build(image,scratch);
    let n=(pattern_width*pattern_height) as f64;
    let pixels=image.as_raw();
    let mut best:Option<Hit>=None;
    let mut stats=ScanStats::default();
    stats.positions=score_len;
    stats.theoretical_full_macs=score_len.saturating_mul(pattern_width).saturating_mul(pattern_height).saturating_mul(3);
    let threshold=minimum_score.unwrap_or(f64::NEG_INFINITY);
    for y in 0..=height-pattern_height {
        for x in 0..=width-pattern_width {
            let image_sum=IntegralImage::rect_sum(&scratch.sums,stride,x,y,pattern_width,pattern_height);
            let image_square=IntegralImage::rect_scalar(&scratch.squares,stride,x,y,pattern_width,pattern_height);
            let image_variance=(image_square-(0..3).map(|c|image_sum[c]*image_sum[c]/n).sum::<f64>()).max(0.0);
            let denominator=(image_variance*pattern.variance).sqrt();
            let means=image_sum.map(|sum|sum/n);
            let candidate_index=y*(width-pattern_width+1)+x;
            let mut dot=0.0;
            let mut processed=0;
            let mut was_pruned=false;
            if denominator>=0.0001 {
                while processed<pattern_height {
                    let end=(processed+DOT_BAND_ROWS).min(pattern_height);
                    for py in processed..end {
                        let image_offset=((y+py)*width+x)*3;
                        let template_offset=py*pattern_width*3;
                        for pixel_channel in 0..pattern_width*3 {
                            dot+=pixels[image_offset+pixel_channel] as f64*pattern.centered[template_offset+pixel_channel];
                        }
                    }
                    stats.dot_macs=stats.dot_macs.saturating_add((end-processed)*pattern_width*3);
                    processed=end;
                    if processed==pattern_height {break;}

                    let remaining_height=pattern_height-processed;
                    let rem_sums=IntegralImage::rect_sum(&scratch.sums,stride,x,y+processed,pattern_width,remaining_height);
                    let rem_square=IntegralImage::rect_scalar(&scratch.squares,stride,x,y+processed,pattern_width,remaining_height);
                    let Some((patch_energy,energy_rounding))=residual_energy_bound(
                        rem_sums,rem_square,(pattern_width*remaining_height) as f64,means) else {continue;};
                    let template_energy=pattern.suffix_energy[processed];
                    let template_sum=pattern.suffix_channel_sum[processed];
                    let mean_correction=(0..3).map(|c|means[c]*template_sum[c]).sum::<f64>().abs();
                    let upper=dot+(template_energy*patch_energy).sqrt()+mean_correction;
                    let target=minimum_score.map(|value|value*denominator)
                        .or_else(||best.map(|hit|hit.score*denominator)).unwrap_or(f64::NEG_INFINITY);
                    if (best.is_some() || minimum_score.is_some()) && can_prune(upper,target,denominator,energy_rounding) {
                        was_pruned=true;
                        break;
                    }
                }
            }
            if was_pruned {
                stats.pruned_positions+=1;
                continue;
            }
            let score=if denominator<0.0001 {0.0} else {dot/denominator};
            stats.exact_positions+=1;
            if minimum_score.is_none() || score>=threshold {
                if minimum_score.is_some() {scratch.scores[candidate_index]=score;}
                if best.map(|current|score>current.score).unwrap_or(true) {
                    best=Some(Hit{x:x as u32,y:y as u32,score,width:pattern.width,height:pattern.height});
                }
            }
        }
    }
    scratch.last_scan=stats;
    best
}
pub fn best_match_prepared(image:&RgbImage,pattern:&PreparedTemplate)->Option<Hit> {
    best_match_prepared_with_scratch(image,pattern,&mut MatcherScratch::default())
}
pub fn best_match_prepared_with_scratch(image:&RgbImage,pattern:&PreparedTemplate,scratch:&mut MatcherScratch)->Option<Hit> {
    scan_best(image,pattern,scratch,None)
}
pub fn unique_match(image:&RgbImage,pattern:&RgbImage,threshold:f64)->std::result::Result<Option<Hit>,()> {
    let prepared=PreparedTemplate::new(pattern);
    unique_match_prepared_with_scratch(image,&prepared,threshold,&mut MatcherScratch::default())
}
pub fn unique_match_prepared_with_scratch(image:&RgbImage,pattern:&PreparedTemplate,threshold:f64,
    scratch:&mut MatcherScratch)->std::result::Result<Option<Hit>,()> {
    let Some(best)=scan_best(image,pattern,scratch,Some(threshold)) else {return Ok(None);};
    let (width,height)=(image.width() as usize,image.height() as usize);
    let (pattern_width,pattern_height)=(pattern.width as usize,pattern.height as usize);
    let columns=width-pattern_width+1;
    for y in 0..=height-pattern_height {
        for x in 0..columns {
            let score=scratch.scores[y*columns+x];
            if score==f64::NEG_INFINITY || (x==best.x as usize && y==best.y as usize) {continue;}
            let overlap_x=x<(best.x as usize+pattern_width) && x+pattern_width>best.x as usize;
            let overlap_y=y<(best.y as usize+pattern_height) && y+pattern_height>best.y as usize;
            if !(overlap_x && overlap_y) && score>=threshold {return Err(());}
        }
    }
    Ok(Some(best))
}

pub fn best_match(image: &RgbImage, pattern: &RgbImage) -> Option<Hit> {
    best_match_prepared(image,&PreparedTemplate::new(pattern))
}

pub fn alert(image: &RgbImage, pattern: &RgbImage, baseline: Option<&RgbImage>) -> Option<Hit> {
    alert_hit(image,best_match(image,pattern)?,baseline)
}
pub fn alert_prepared(image:&RgbImage,pattern:&PreparedTemplate,baseline:Option<&RgbImage>)->Option<Hit> {
    alert_prepared_with_scratch(image,pattern,baseline,&mut MatcherScratch::default())
}
pub fn alert_prepared_with_scratch(image:&RgbImage,pattern:&PreparedTemplate,baseline:Option<&RgbImage>,
    scratch:&mut MatcherScratch)->Option<Hit> {
    alert_hit(image,best_match_prepared_with_scratch(image,pattern,scratch)?,baseline)
}
fn alert_hit(image:&RgbImage,hit:Hit,baseline:Option<&RgbImage>)->Option<Hit> {
    if hit.score >= 0.80 { return Some(hit); }
    if hit.score < 0.60 { return None; }
    let Some(base) = baseline.filter(|b| b.dimensions()==image.dimensions()) else {
        return (hit.score >= 0.74).then_some(hit);
    };
    let mut difference = 0.0; let mut dark = 0;
    for y in hit.y..hit.y+hit.height {
        for x in hit.x..hit.x+hit.width {
            let p = image.get_pixel(x,y); let q=base.get_pixel(x,y);
            for c in 0..3 { difference += (p[c] as f64-q[c] as f64).abs(); }
            if p.0.iter().all(|&v|v<45) { dark += 1; }
        }
    }
    let n=(hit.width*hit.height) as f64;
    (difference/(n*3.0)>=18.0 && dark as f64/n>=0.05).then_some(hit)
}

pub fn water_point(image: &RgbImage) -> Option<(u32,u32)> {
    let water=template("water").ok()?;
    let mut mean=[0.0;3];
    for p in water.pixels() { for c in 0..3 { mean[c]+=p[c] as f64; } }
    for v in &mut mean { *v/= (water.width()*water.height()) as f64; }
    let w=image.width() as usize; let h=image.height() as usize;
    if w<60 || h<60 {return None;}
    // Integral mask verifies every pixel in a 51 x 51 safe square, including its interior.
    let mut sums=vec![0u32;(w+1)*(h+1)];
    for y in 0..h {
        let mut row=0;
        for x in 0..w {
            let p=image.get_pixel(x as u32,y as u32);
            row+=u32::from((0..3).all(|c|(p[c] as f64-mean[c]).abs()<=14.0));
            sums[(y+1)*(w+1)+x+1]=sums[y*(w+1)+x+1]+row;
        }
    }
    for y in ((h/5).max(25)..(h*82/100).min(h-25)).step_by(4) {
        for x in ((w/4).max(25)..(w*3/4).min(w-25)).step_by(4) {
            let (left,right,top,bottom)=(x-25,x+26,y-25,y+26);
            let count=sums[bottom*(w+1)+right]+sums[top*(w+1)+left]
                -sums[top*(w+1)+right]-sums[bottom*(w+1)+left];
            if count==51*51 {return Some((x as u32,y as u32));}
        }
    }
    None
}
pub fn crop_fraction(image:&RgbImage, x:f64,y:f64,w:f64,h:f64)->RgbImage {
    imageops::crop_imm(image,(image.width() as f64*x) as u32,(image.height() as f64*y) as u32,
        (image.width() as f64*w) as u32,(image.height() as f64*h) as u32).to_image()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn seeded_image(width:u32,height:u32)->RgbImage {
        seeded_image_with_seed(width,height,0)
    }
    fn seeded_image_with_seed(width:u32,height:u32,mut state:u32)->RgbImage {
        RgbImage::from_fn(width,height,|_,_| {
            let mut channels=[0u8;3];
            for channel in &mut channels {
                state=state.wrapping_mul(1664525).wrapping_add(1013904223);
                *channel=(state>>24) as u8;
            }
            image::Rgb(channels)
        })
    }
    fn reference_full_scan(image:&RgbImage,pattern:&RgbImage)->Option<Hit> {
        if pattern.width()>image.width() || pattern.height()>image.height() {return None;}
        let mut best:Option<Hit>=None;
        for y in 0..=image.height()-pattern.height() {
            for x in 0..=image.width()-pattern.width() {
                let hit=Hit{x,y,score:correlation(image,pattern,x,y,1),width:pattern.width(),height:pattern.height()};
                if best.map(|current|hit.score>current.score).unwrap_or(true) {best=Some(hit);}
            }
        }
        best
    }
    fn reference_alert(image:&RgbImage,pattern:&RgbImage,baseline:Option<&RgbImage>)->Option<Hit> {
        let hit=reference_full_scan(image,pattern)?;
        if hit.score>=0.80 {return Some(hit);}
        if hit.score<0.60 {return None;}
        let Some(base)=baseline.filter(|b|b.dimensions()==image.dimensions()) else {
            return (hit.score>=0.74).then_some(hit);
        };
        let mut difference=0.0;
        let mut dark=0;
        for y in hit.y..hit.y+hit.height {
            for x in hit.x..hit.x+hit.width {
                let p=image.get_pixel(x,y); let q=base.get_pixel(x,y);
                for c in 0..3 {difference+=(p[c] as f64-q[c] as f64).abs();}
                if p.0.iter().all(|&v|v<45) {dark+=1;}
            }
        }
        let n=(hit.width*hit.height) as f64;
        (difference/(n*3.0)>=18.0 && dark as f64/n>=0.05).then_some(hit)
    }
    fn reference_unique(image:&RgbImage,pattern:&RgbImage,threshold:f64)->std::result::Result<Option<Hit>,()> {
        let Some(best)=reference_full_scan(image,pattern).filter(|hit|hit.score>=threshold) else {return Ok(None);};
        for y in 0..=image.height()-pattern.height() {
            for x in 0..=image.width()-pattern.width() {
                let overlap_x=x<best.x+pattern.width() && x+pattern.width()>best.x;
                let overlap_y=y<best.y+pattern.height() && y+pattern.height()>best.y;
                if !(overlap_x&&overlap_y) && correlation(image,pattern,x,y,1)>=threshold {return Err(());}
            }
        }
        Ok(Some(best))
    }
    fn patch_near_score(pattern:&RgbImage,target:f64)->(RgbImage,f64) {
        let noise=seeded_image(pattern.width(),pattern.height());
        let mut best=pattern.clone();
        let mut best_score=1.0;
        let mut best_distance=(best_score-target).abs();
        for step in 0..=2000 {
            let alpha=step as f64/2000.0;
            let mut bytes=Vec::with_capacity(pattern.as_raw().len());
            for (t,n) in pattern.as_raw().iter().zip(noise.as_raw()) {
                bytes.push((*t as f64*alpha+*n as f64*(1.0-alpha)).round().clamp(0.0,255.0) as u8);
            }
            let candidate=RgbImage::from_raw(pattern.width(),pattern.height(),bytes).unwrap();
            let score=correlation(&candidate,pattern,0,0,1);
            let distance=(score-target).abs();
            if distance<best_distance {
                best=candidate;
                best_score=score;
                best_distance=distance;
            }
        }
        (best,best_score)
    }
    #[test] fn template_and_static_negative() {
        let t=template("alert").unwrap();
        assert!(alert(&t,&t,None).is_some());
        let blank=RgbImage::from_pixel(70,70,image::Rgb([100,100,100]));
        assert!(alert(&blank,&t,None).is_none());
        assert!(best_match(&RgbImage::new(t.width()-1,t.height()),&t).is_none());
    }
    #[test] fn full_scan_finds_alert_after_twelve_sparse_distractors() {
        let pattern=template("alert").unwrap();
        let mut frame=seeded_image(560,35);
        for origin_x in (0..=440).step_by(40) {
            for ty in (0..pattern.height()).step_by(5) {
                for tx in (0..pattern.width()).step_by(5) {
                    frame.put_pixel(origin_x+tx,ty,*pattern.get_pixel(tx,ty));
                }
            }
        }
        imageops::replace(&mut frame,&pattern,520,0);
        let hit=best_match(&frame,&pattern).unwrap();
        assert_eq!((hit.x,hit.y),(520,0));
        assert!(hit.score>0.999);
        let alert_hit=alert(&frame,&pattern,None).unwrap();
        assert_eq!((alert_hit.x,alert_hit.y),(520,0));
    }
    #[test] fn full_scan_finds_the_bottom_right_boundary_and_matches_reference() {
        let pattern=RgbImage::from_fn(5,4,|x,y|image::Rgb([(x*37) as u8,(y*53) as u8,((x+y)*29) as u8]));
        let mut frame=seeded_image(12,11);
        imageops::replace(&mut frame,&pattern,7,7);
        let hit=best_match(&frame,&pattern).unwrap();
        assert_eq!((hit.x,hit.y),(7,7));
        let cases=[seeded_image(9,8),seeded_image(10,9),frame];
        for image in &cases {
            let actual=best_match(image,&pattern).unwrap();
            let expected=reference_full_scan(image,&pattern).unwrap();
            assert_eq!((actual.x,actual.y),(expected.x,expected.y));
            assert!((actual.score-expected.score).abs()<1e-12);
        }
    }
    #[test] fn optimized_scan_matches_scalar_reference_and_stable_tie_order() {
        let pattern=template("alert").unwrap();
        let prepared=PreparedTemplate::new(&pattern);
        for image in [seeded_image(37,39),seeded_image(42,41),RgbImage::from_pixel(39,37,image::Rgb([120,120,120]))] {
            let actual=best_match_prepared(&image,&prepared).unwrap();
            let expected=reference_full_scan(&image,&pattern).unwrap();
            assert_eq!((actual.x,actual.y),(expected.x,expected.y));
            assert!((actual.score-expected.score).abs()<1e-9,"{} != {}",actual.score,expected.score);
        }
        let flat=RgbImage::from_pixel(38,40,image::Rgb([75,75,75]));
        let tied=best_match_prepared(&flat,&prepared).unwrap();
        assert_eq!((tied.x,tied.y),(0,0));
    }
    #[test] fn banded_scan_matches_scalar_reference_on_thousands_of_seeded_frames() {
        let mut scratch=MatcherScratch::default();
        for seed in 0..1000u32 {
            let pw=2+seed%4;
            let ph=2+(seed/4)%4;
            let iw=pw+seed.wrapping_mul(7)%9;
            let ih=ph+seed.wrapping_mul(11)%8;
            let pattern=seeded_image_with_seed(pw,ph,seed.wrapping_add(0x9e3779b9));
            let mut frame=seeded_image_with_seed(iw,ih,seed.wrapping_mul(747796405).wrapping_add(2891336453));
            if seed%5==0 {
                let x=seed%(iw-pw+1);
                let y=seed.rotate_left(9)%(ih-ph+1);
                imageops::replace(&mut frame,&pattern,x as i64,y as i64);
            } else if seed%7==0 {
                frame=RgbImage::from_pixel(iw,ih,image::Rgb([seed as u8,seed.rotate_left(8) as u8,70]));
            }
            let prepared=PreparedTemplate::new(&pattern);
            let actual=best_match_prepared_with_scratch(&frame,&prepared,&mut scratch).unwrap();
            let expected=reference_full_scan(&frame,&pattern).unwrap();
            assert_eq!((actual.x,actual.y),(expected.x,expected.y),"seed {seed}");
            assert!((actual.score-expected.score).abs()<1e-8,"seed {seed}: {} != {}",actual.score,expected.score);

            for threshold in [0.60,0.74,0.80,0.90] {
                let actual=unique_match_prepared_with_scratch(&frame,&prepared,threshold,&mut scratch);
                let expected=reference_unique(&frame,&pattern,threshold);
                match (actual,expected) {
                    (Ok(Some(a)),Ok(Some(e)))=>{
                        assert_eq!((a.x,a.y),(e.x,e.y),"seed {seed}, threshold {threshold}");
                        assert!((a.score-e.score).abs()<1e-8,"seed {seed}, threshold {threshold}");
                    }
                    (Ok(None),Ok(None))|(Err(()),Err(()))=>{},
                    (a,e)=>panic!("seed {seed}, threshold {threshold}: {a:?} != {e:?}"),
                }
                let columns=(iw-pw+1) as usize;
                for y in 0..=ih-ph {
                    for x in 0..=iw-pw {
                        let scalar=correlation(&frame,&pattern,x,y,1);
                        let stored=scratch.scores[y as usize*columns+x as usize];
                        if scalar>=threshold {
                            assert_ne!(stored,f64::NEG_INFINITY,"qualifying position pruned at seed {seed}");
                            assert!((stored-scalar).abs()<1e-8,"score map mismatch at seed {seed}");
                        } else {
                            assert_eq!(stored,f64::NEG_INFINITY,"below-threshold score retained at seed {seed}");
                        }
                    }
                }
            }
        }
    }
    #[test] fn optimized_alert_decisions_match_reference_near_python_thresholds() {
        let pattern=template("alert").unwrap();
        let prepared=PreparedTemplate::new(&pattern);
        for threshold in [0.5995,0.6005,0.7395,0.7405,0.7995,0.8005] {
            let (frame,score)=patch_near_score(&pattern,threshold);
            assert!((score-threshold).abs()<0.02,"synthetic score {score} missed threshold {threshold}");
            let actual=alert_prepared(&frame,&prepared,None);
            let expected=reference_alert(&frame,&pattern,None);
            assert_eq!(actual.is_some(),expected.is_some(),"decision differed around {threshold}");
            if let (Some(actual),Some(expected))=(actual,expected) {
                assert_eq!((actual.x,actual.y),(expected.x,expected.y));
                assert!((actual.score-expected.score).abs()<1e-9);
            }
            let baseline=seeded_image_with_seed(frame.width(),frame.height(),threshold.to_bits() as u32);
            let actual=alert_prepared(&frame,&prepared,Some(&baseline));
            let expected=reference_alert(&frame,&pattern,Some(&baseline));
            assert_eq!(actual.is_some(),expected.is_some(),"baseline decision differed around {threshold}");
            if let (Some(actual),Some(expected))=(actual,expected) {
                assert_eq!((actual.x,actual.y),(expected.x,expected.y));
                assert!((actual.score-expected.score).abs()<1e-9);
            }
        }
    }
    #[test] fn unique_match_rejects_multiple_disjoint_bread_candidates() {
        let bread=template("bread").unwrap();
        let one=RgbImage::from_fn(bread.width(),bread.height(),|x,y|*bread.get_pixel(x,y));
        assert!(unique_match(&one,&bread,0.999).unwrap().is_some());
        let mut two=RgbImage::from_pixel(bread.width()*2+10,bread.height(),image::Rgb([0,0,0]));
        imageops::replace(&mut two,&bread,0,0);
        imageops::replace(&mut two,&bread,(bread.width()+10) as i64,0);
        assert!(unique_match(&two,&bread,0.999).is_err());
    }
    #[test] fn scan_bound_reduces_dot_macs_and_scratch_buffers_reuse_capacity() {
        let pattern=template("alert").unwrap();
        let prepared=PreparedTemplate::new(&pattern);
        let mut frame=seeded_image_with_seed(pattern.width()+220,pattern.height(),73);
        imageops::replace(&mut frame,&pattern,0,0);
        let mut scratch=MatcherScratch::default();
        let hit=best_match_prepared_with_scratch(&frame,&prepared,&mut scratch).unwrap();
        assert_eq!((hit.x,hit.y),(0,0));
        let stats=scratch.last_scan;
        assert_eq!(stats.positions,stats.exact_positions+stats.pruned_positions);
        assert!(stats.pruned_positions>0,"bound did not prune any position: {stats:?}");
        assert!(stats.dot_macs<stats.theoretical_full_macs,"dot MACs did not fall: {stats:?}");
        let capacities=(scratch.sums.capacity(),scratch.squares.capacity(),scratch.scores.capacity());
        let growths=scratch.buffer_growths;
        let second=best_match_prepared_with_scratch(&frame,&prepared,&mut scratch).unwrap();
        assert_eq!((hit.x,hit.y),(second.x,second.y));
        assert_eq!(scratch.buffer_growths,growths,"same-sized frame grew scratch buffers again");
        assert_eq!((scratch.sums.capacity(),scratch.squares.capacity(),scratch.scores.capacity()),capacities);

        let _=unique_match_prepared_with_scratch(&frame,&prepared,0.90,&mut scratch);
        let unique_growths=scratch.buffer_growths;
        let _=unique_match_prepared_with_scratch(&frame,&prepared,0.90,&mut scratch);
        assert_eq!(scratch.buffer_growths,unique_growths,"same-sized score map grew again");
    }
    #[test] fn dry_image_has_no_cast() {
        assert!(water_point(&RgbImage::from_pixel(100,100,image::Rgb([255,0,0]))).is_none());
    }
}
