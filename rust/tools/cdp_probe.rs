use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut stream = TcpStream::connect_timeout(
        &"127.0.0.1:9222".parse()?,
        Duration::from_secs(3),
    )?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    stream.set_write_timeout(Some(Duration::from_secs(3)))?;
    stream.write_all(
        b"GET /json/list HTTP/1.1\r\nHost: 127.0.0.1:9222\r\nConnection: close\r\n\r\n",
    )?;

    let mut response = String::new();
    stream.read_to_string(&mut response)?;
    let (_, body) = response
        .split_once("\r\n\r\n")
        .ok_or("invalid HTTP response from Chrome")?;
    let trusted = body.contains("\"type\": \"page\"")
        && (body.contains("https://nomstead.com/")
            || body.contains("https://www.nomstead.com/"))
        && body.contains("ws://127.0.0.1:9222/devtools/page/");
    if !trusted {
        return Err("no trusted NomStead CDP target found".into());
    }

    println!("rust-cdp-probe-ok: trusted NomStead target found on 127.0.0.1:9222");
    Ok(())
}
