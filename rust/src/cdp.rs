use serde_json::{json, Value};
use std::{collections::VecDeque, fs, net::TcpStream, time::{Duration, Instant}};
use tungstenite::{stream::MaybeTlsStream, Message, WebSocket};

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub trait Browser {
    fn call(&mut self, method: &str, params: Value) -> Result<Value>;
    fn fixture(&self) -> bool { false }
    fn fast_forward_pauses(&self) -> bool { self.fixture() }
    fn finish(&self) -> Result<()> { Ok(()) }
    fn eval(&mut self, expression: &str) -> Result<Value> {
        let result = self.call("Runtime.evaluate", json!({
            "expression": expression, "returnByValue": true, "awaitPromise": true
        }))?;
        if result.get("exceptionDetails").is_some() {
            return Err(format!("JavaScript failed: {}", result).into());
        }
        Ok(result["result"]["value"].clone())
    }
}

pub fn trusted_game_url(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("https://") else { return false };
    let authority = rest.split(['/', '?', '#']).next().unwrap_or("");
    authority == "nomstead.com" || authority == "www.nomstead.com"
}

pub struct Cdp {
    socket: WebSocket<MaybeTlsStream<TcpStream>>,
    id: u64,
}
impl Cdp {
    pub fn connect() -> Result<Self> {
        let pages: Vec<Value> = ureq::get("http://127.0.0.1:9222/json/list")
            .timeout(Duration::from_secs(5)).call()?.into_json()?;
        let matches: Vec<_> = pages.iter().filter(|p| {
            p["type"] == "page" && trusted_game_url(p["url"].as_str().unwrap_or(""))
        }).collect();
        if matches.len() != 1 {
            return Err("Open exactly one NomStead tab in debug Chrome, then log in.".into());
        }
        let address = matches[0]["webSocketDebuggerUrl"].as_str().ok_or("Missing page CDP URL")?;
        // Never connect to a remote debugger returned by an unexpected endpoint.
        if !(address.starts_with("ws://127.0.0.1:9222/") || address.starts_with("ws://localhost:9222/")) {
            return Err("Debugger must remain on loopback port 9222".into());
        }
        let (mut socket, _) = tungstenite::connect(address)?;
        if let MaybeTlsStream::Plain(stream) = socket.get_mut() {
            stream.set_read_timeout(Some(Duration::from_secs(1)))?;
            stream.set_write_timeout(Some(Duration::from_secs(2)))?;
        }
        Ok(Self { socket, id: 0 })
    }
}
impl Browser for Cdp {
    fn call(&mut self, method: &str, params: Value) -> Result<Value> {
        self.id += 1;
        let id = self.id;
        self.socket.send(Message::Text(json!({"id":id,"method":method,"params":params}).to_string()))?;
        let started = Instant::now();
        while started.elapsed() < Duration::from_secs(10) {
            let message = match self.socket.read() {
                Ok(message) => message,
                Err(tungstenite::Error::Io(e)) if matches!(e.kind(), std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock) => continue,
                Err(e) => return Err(e.into()),
            };
            if let Message::Text(text) = message {
                let value: Value = serde_json::from_str(&text)?;
                if value["id"] == id {
                    if value.get("error").is_some() { return Err(format!("CDP {}: {}", method, value["error"]).into()); }
                    return Ok(value["result"].clone());
                }
            }
        }
        Err(format!("CDP timeout: {}", method).into())
    }
}
impl Drop for Cdp {
    fn drop(&mut self) { let _ = self.socket.close(None); }
}

pub struct Fixture { steps: VecDeque<Value> }
impl Fixture {
    pub fn load(path: &str) -> Result<Self> {
        Ok(Self { steps: serde_json::from_str::<Vec<Value>>(&fs::read_to_string(path)?)?.into() })
    }
}
impl Browser for Fixture {
    fn call(&mut self, method: &str, params: Value) -> Result<Value> {
        let step = self.steps.pop_front().ok_or("Unexpected extra CDP call")?;
        if step["method"] != method { return Err(format!("Expected {}, received {}", step["method"], method).into()); }
        if let Some(expected) = step.get("params") {
            if expected != &params { return Err(format!("CDP parameters differ for {}", method).into()); }
        }
        if let Some(fragment) = step["expression_contains"].as_str() {
            if !params["expression"].as_str().unwrap_or("").contains(fragment) {
                return Err(format!("Unexpected expression for {}", method).into());
            }
        }
        if let Some(error) = step["error"].as_str() { return Err(error.into()); }
        Ok(step["result"].clone())
    }
    fn fixture(&self) -> bool { true }
    fn finish(&self) -> Result<()> {
        if self.steps.is_empty() { Ok(()) } else { Err(format!("{} fixture steps unused", self.steps.len()).into()) }
    }
}
