use std::ffi::c_void;
use std::ptr::{null, null_mut};

type HInternet = *mut c_void;
type Bool = i32;

#[link(name = "winhttp")]
extern "system" {
    fn WinHttpOpen(
        user_agent: *const u16,
        access_type: u32,
        proxy_name: *const u16,
        proxy_bypass: *const u16,
        flags: u32,
    ) -> HInternet;
    fn WinHttpConnect(
        session: HInternet,
        server_name: *const u16,
        server_port: u16,
        reserved: u32,
    ) -> HInternet;
    fn WinHttpOpenRequest(
        connect: HInternet,
        verb: *const u16,
        object_name: *const u16,
        version: *const u16,
        referrer: *const u16,
        accept_types: *const *const u16,
        flags: u32,
    ) -> HInternet;
    fn WinHttpSendRequest(
        request: HInternet,
        headers: *const u16,
        headers_length: u32,
        optional: *mut c_void,
        optional_length: u32,
        total_length: u32,
        context: usize,
    ) -> Bool;
    fn WinHttpReceiveResponse(request: HInternet, reserved: *mut c_void) -> Bool;
    fn WinHttpQueryDataAvailable(request: HInternet, available: *mut u32) -> Bool;
    fn WinHttpReadData(
        request: HInternet,
        buffer: *mut c_void,
        bytes_to_read: u32,
        bytes_read: *mut u32,
    ) -> Bool;
    fn WinHttpCloseHandle(handle: HInternet) -> Bool;
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

fn os_error(step: &str) -> Box<dyn std::error::Error> {
    format!("{step}: {}", std::io::Error::last_os_error()).into()
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    unsafe {
        let agent = wide("nomstead-rust-probe/1");
        let host = wide("127.0.0.1");
        let verb = wide("GET");
        let path = wide("/json/list");
        let session = WinHttpOpen(agent.as_ptr(), 1, null(), null(), 0);
        if session.is_null() {
            return Err(os_error("WinHttpOpen"));
        }
        let connect = WinHttpConnect(session, host.as_ptr(), 9222, 0);
        if connect.is_null() {
            WinHttpCloseHandle(session);
            return Err(os_error("WinHttpConnect"));
        }
        let request = WinHttpOpenRequest(
            connect,
            verb.as_ptr(),
            path.as_ptr(),
            null(),
            null(),
            null(),
            0,
        );
        if request.is_null() {
            WinHttpCloseHandle(connect);
            WinHttpCloseHandle(session);
            return Err(os_error("WinHttpOpenRequest"));
        }
        if WinHttpSendRequest(request, null(), 0, null_mut(), 0, 0, 0) == 0 {
            return Err(os_error("WinHttpSendRequest"));
        }
        if WinHttpReceiveResponse(request, null_mut()) == 0 {
            return Err(os_error("WinHttpReceiveResponse"));
        }

        let mut body = Vec::new();
        loop {
            let mut available = 0u32;
            if WinHttpQueryDataAvailable(request, &mut available) == 0 {
                return Err(os_error("WinHttpQueryDataAvailable"));
            }
            if available == 0 {
                break;
            }
            let offset = body.len();
            body.resize(offset + available as usize, 0);
            let mut read = 0u32;
            if WinHttpReadData(
                request,
                body[offset..].as_mut_ptr().cast(),
                available,
                &mut read,
            ) == 0
            {
                return Err(os_error("WinHttpReadData"));
            }
            body.truncate(offset + read as usize);
        }
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connect);
        WinHttpCloseHandle(session);

        let body = String::from_utf8(body)?;
        let trusted = body.contains("\"type\": \"page\"")
            && (body.contains("https://nomstead.com/")
                || body.contains("https://www.nomstead.com/"))
            && body.contains("ws://127.0.0.1:9222/devtools/page/");
        if !trusted {
            return Err("no trusted NomStead CDP target found".into());
        }
        println!("rust-winhttp-cdp-probe-ok: trusted NomStead target found");
    }
    Ok(())
}
