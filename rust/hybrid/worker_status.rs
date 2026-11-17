//! Strict decoder for the Python status v1 payload. No browser or network access.
use std::io;

fn invalid() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid status payload")
}

struct Reader<'a> { bytes: &'a [u8], offset: usize }
impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> io::Result<&'a [u8]> {
        let end = self.offset.checked_add(count).ok_or_else(invalid)?;
        let result = self.bytes.get(self.offset..end).ok_or_else(invalid)?;
        self.offset = end;
        Ok(result)
    }
    fn tag(&mut self) -> io::Result<bool> {
        match self.take(1)?[0] { 0 => Ok(false), 1 => Ok(true), _ => Err(invalid()) }
    }
    fn u32(&mut self) -> io::Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().map_err(|_| invalid())?))
    }
    fn u64(&mut self) -> io::Result<u64> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().map_err(|_| invalid())?))
    }
    fn float(&mut self) -> io::Result<f64> {
        Ok(f64::from_le_bytes(self.take(8)?.try_into().map_err(|_| invalid())?))
    }
    fn string(&mut self) -> io::Result<&'a str> {
        let size = self.u32()? as usize;
        if size > 4096 { return Err(invalid()); }
        std::str::from_utf8(self.take(size)?).map_err(|_| invalid())
    }
}

fn trusted_url(url: &str) -> bool {
    if url.chars().any(|c| c.is_whitespace() || c.is_control() || c == '\\') { return false; }
    let Some(rest) = url.strip_prefix("https://") else { return false; };
    let authority = rest.split(['/', '?', '#']).next().unwrap_or("");
    matches!(authority.to_ascii_lowercase().as_str(),
        "nomstead.com" | "nomstead.com:443" | "www.nomstead.com" | "www.nomstead.com:443")
}

pub fn validate(payload: &[u8]) -> io::Result<()> {
    let mut reader = Reader { bytes: payload, offset: 0 };
    if !trusted_url(reader.string()?) { return Err(invalid()); }
    for _ in 0..2 {
        let value = reader.float()?;
        if !value.is_finite() || !(100.0..=8192.0).contains(&value) { return Err(invalid()); }
    }
    let dpr = reader.float()?;
    if !dpr.is_finite() || dpr <= 0.0 { return Err(invalid()); }
    if reader.tag()? { reader.u32()?; }
    if reader.tag()? { reader.u64()?; }
    reader.string()?;
    let sequence_available = reader.tag()?;
    let sequence = reader.u64()?;
    if !sequence_available && sequence != 0 { return Err(invalid()); }
    reader.tag()?;
    if reader.offset != payload.len() { return Err(invalid()); }
    Ok(())
}
