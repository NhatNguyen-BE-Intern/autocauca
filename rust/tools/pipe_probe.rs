use std::io::{self, Read};

fn main() -> io::Result<()> {
    let mut input = Vec::new();
    io::stdin().read_to_end(&mut input)?;
    let checksum = input
        .iter()
        .fold(0u64, |sum, byte| sum.wrapping_add(*byte as u64));
    println!("rust-pipe-probe-ok bytes={} checksum={}", input.len(), checksum);
    Ok(())
}
