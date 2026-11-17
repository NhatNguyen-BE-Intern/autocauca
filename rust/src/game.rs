use crate::cdp::{Browser, Result, trusted_game_url};
use serde::{Serialize,Deserialize};
use serde_json::{Value,json};
use std::{sync::{Arc,atomic::{AtomicBool,Ordering}}, thread, time::{Duration,Instant}};
use image::RgbImage;
use base64::{engine::general_purpose::STANDARD,Engine};
use crate::vision;
use std::ops::Deref;
use std::fmt;

#[derive(Debug)]
pub struct StoppedByCtrlC;
impl fmt::Display for StoppedByCtrlC {
    fn fmt(&self,formatter:&mut fmt::Formatter<'_>)->fmt::Result {write!(formatter,"Stopped by Ctrl+C")}
}
impl std::error::Error for StoppedByCtrlC {}
pub fn is_cancelled(error:&(dyn std::error::Error+'static))->bool {
    error.downcast_ref::<StoppedByCtrlC>().is_some()
}

#[derive(Debug,Deserialize,Serialize,Clone)]
pub struct Status {
    pub url:String, pub width:f64, pub height:f64, pub dpr:f64,
    pub energy:Option<u32>, pub toast:String, pub sequence:u64, pub xp:Option<u64>, pub modal:bool,
}

pub struct Screenshot { pub image:RgbImage, pub received_at:Instant, pub capture_ms:f64, pub decode_ms:f64 }
impl Deref for Screenshot {
    type Target=RgbImage;
    fn deref(&self)->&Self::Target {&self.image}
}

pub struct MouseTiming { pub press_sent_at:Instant, pub press_release_round_trip_ms:f64 }
#[derive(Debug,Clone,Copy,PartialEq,Eq)]
pub enum ClickPhase { BeforePress, PressAttempted }
pub const STATUS:&str = r#"(() => {
 const visible=e=>e && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
 if(!window.__nomsteadRustWatch) {
   const state={sequence:0};
   const observer=new MutationObserver(records=>{
     if(records.some(r=>{
       const e=r.target.nodeType===1?r.target:r.target.parentElement;
       return e?.closest('.message-bar') ||
         [...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches?.('.message-bar')||n.querySelector?.('.message-bar')));
     })) state.sequence++;
   });
   observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true});
   window.__nomsteadRustWatch={state,observer};
 }
 const energy=(document.querySelector('div.info > div.number')?.innerText||'').match(/(\d+)\s*\/\s*80/);
 const xp=(document.querySelector('.remaining-xp')?.innerText||'').replace(/,/g,'').match(/(\d+)/);
 return {url:location.href,width:innerWidth,height:innerHeight,dpr:devicePixelRatio||1,
 energy:energy?Number(energy[1]):null,toast:(document.querySelector('.message-bar')?.innerText||'').trim().toLowerCase(),
 sequence:window.__nomsteadRustWatch.state.sequence,xp:xp?Number(xp[1]):null,
 modal:[...document.querySelectorAll('.modal-body')].some(visible)};
})()"#;

pub struct Game<'a> {pub browser:&'a mut dyn Browser, pub stop:Arc<AtomicBool>}
impl Game<'_> {
    pub fn check_stop(&self)->Result<()> {
        if self.stop.load(Ordering::Relaxed) {Err(Box::new(StoppedByCtrlC))} else {Ok(())}
    }
    pub fn pause(&self,millis:u64)->Result<()> {
        self.check_stop()?;
        if self.browser.fast_forward_pauses() {return self.check_stop();}
        let until=Instant::now()+Duration::from_millis(millis);
        while Instant::now()<until {
            self.check_stop()?;
            thread::sleep(Duration::from_millis(10).min(until.saturating_duration_since(Instant::now())));
        }
        self.check_stop()
    }
    pub fn status(&mut self)->Result<Status> {
        self.check_stop()?;
        let value=self.browser.eval(STATUS)?;
        self.check_stop()?;
        let s:Status=serde_json::from_value(value)?;
        if !trusted_game_url(&s.url) || !s.width.is_finite() || !s.height.is_finite()
            || s.width<100.0 || s.height<100.0 || s.width>8192.0 || s.height>8192.0 {
            return Err("Wrong game origin or invalid viewport".into());
        }
        Ok(s)
    }
    pub fn click(&mut self,x:f64,y:f64)->Result<()> {
        self.click_timed(x,y).map(|_|())
    }
    pub fn click_timed(&mut self,x:f64,y:f64)->Result<MouseTiming> {
        self.click_timed_with(x,y,|_|Ok(()))
    }
    pub fn click_timed_with<F>(&mut self,x:f64,y:f64,mut on_press:F)->Result<MouseTiming>
    where F:FnMut(ClickPhase)->Result<()> {
        self.check_stop()?;
        let s=self.status()?;
        if !x.is_finite() || !y.is_finite() || x<0.0 || y<0.0 || x>=s.width || y>=s.height || s.modal {
            return Err("Unsafe click coordinates or blocking modal".into());
        }
        self.check_stop()?;
        on_press(ClickPhase::BeforePress)?;
        self.check_stop()?;
        self.mouse_with(x,y,||on_press(ClickPhase::PressAttempted))
    }
    fn mouse(&mut self,x:f64,y:f64)->Result<MouseTiming> {
        self.mouse_with(x,y,||Ok(()))
    }
    fn mouse_with<F>(&mut self,x:f64,y:f64,mut after_press_attempt:F)->Result<MouseTiming>
    where F:FnMut()->Result<()> {
        self.check_stop()?;
        let press_sent_at=Instant::now();
        let press=self.browser.call("Input.dispatchMouseEvent",json!({
            "type":"mousePressed","x":x,"y":y,"button":"left","buttons":1,"clickCount":1
        }));
        // Attempt release even when the press response fails.
        let release=self.browser.call("Input.dispatchMouseEvent",json!({
            "type":"mouseReleased","x":x,"y":y,"button":"left","buttons":0,"clickCount":1
        }));
        let press_release_round_trip_ms=press_sent_at.elapsed().as_secs_f64()*1000.0;
        after_press_attempt()?;
        self.check_stop()?;
        press?; release?; Ok(MouseTiming{press_sent_at,press_release_round_trip_ms})
    }
    pub fn screenshot(&mut self,clip:Option<Value>)->Result<Screenshot> {
        self.check_stop()?;
        let mut p=json!({"format":"jpeg","quality":50,"fromSurface":true,"optimizeForSpeed":true,"captureBeyondViewport":false});
        if let Some(c)=clip {p["clip"]=c;}
        let capture_started=Instant::now();
        let result=self.browser.call("Page.captureScreenshot",p)?;
        self.check_stop()?;
        let received_at=Instant::now();
        let capture_ms=capture_started.elapsed().as_secs_f64()*1000.0;
        let decode_started=Instant::now();
        let bytes=STANDARD.decode(result["data"].as_str().ok_or("Missing screenshot data")?)?;
        if bytes.len()>24*1024*1024 {return Err("Screenshot too large".into());}
        let image=vision::decode(&bytes)?;
        self.check_stop()?;
        let decode_ms=decode_started.elapsed().as_secs_f64()*1000.0;
        Ok(Screenshot{image,received_at,capture_ms,decode_ms})
    }
    pub fn click_dom(&mut self,expression:&str)->Result<Value> {
        self.check_stop()?;
        self.status()?;
        let target=self.browser.eval(expression)?;
        self.check_stop()?;
        let x=target["x"].as_f64().ok_or_else(||format!("UI target unavailable: {}",target))?;
        let y=target["y"].as_f64().ok_or("UI target missing y")?;
        let s=self.status()?;
        if !x.is_finite() || !y.is_finite() || x<0.0 || y<0.0 || x>=s.width || y>=s.height {
            return Err("UI target outside viewport".into());
        }
        self.check_stop()?;
        self.mouse(x,y)?;
        Ok(target)
    }
    pub fn travel(&mut self,lake:u32)->Result<()> {
        self.check_stop()?;
        if !(1..=40).contains(&lake) {return Err("Lake must be in 1..40".into());}
        // Exact visible control first, template fallback for icon-only Codex.
        let open=r#"(() => {const es=[...document.querySelectorAll('button,a,[role=button]')].filter(e=>e.getClientRects().length && /^(codex)$/i.test((e.innerText||e.getAttribute('aria-label')||'').trim()));if(es.length!==1)return null;const r=es[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()"#;
        if self.browser.eval(open)?.is_null() {
            let full=self.screenshot(None)?;
            let t=vision::template("codex")?;
            let hit=vision::best_match(&full,&t).filter(|h|h.score>=0.85).ok_or("Codex icon not recognized")?;
            let s=self.status()?;
            self.click((hit.x+hit.width/2) as f64*s.width/full.width() as f64,
                (hit.y+hit.height/2) as f64*s.height/full.height() as f64)?;
        } else {self.click_dom(open)?;}
        self.pause(350)?;
        self.click_dom(r#"(() => {const es=[...document.querySelectorAll('.modal-body li[data-ui-tab="bookmarks"]')].filter(e=>e.getClientRects().length);if(es.length!==1)return null;const r=es[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()"#)?;
        self.pause(350)?;
        let expression=format!(r#"(() => {{
 const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
 const modals=[...document.querySelectorAll('.modal-body')].filter(e=>visible(e)&&e.querySelector('li.active[data-ui-tab="bookmarks"]'));
 if(modals.length!==1)return {{error:'Bookmarks modal missing or ambiguous'}};
 const rows=[...modals[0].querySelectorAll('.map ul.tiles > li.tile')].filter(r=>visible(r)&&[...r.querySelectorAll('.info-meta > .description')].some(d=>/^HO\s+{}\s*$/i.test(d.innerText.trim())));
 if(rows.length!==1)return {{error:'Exact lake row missing or ambiguous'}};
 const links=[...rows[0].querySelectorAll('a.btn[href^="/"]')].filter(a=>/^Fast travel$/i.test(a.innerText.trim()) && visible(a));
 if(links.length!==1)return {{error:'Exact Fast travel link missing or ambiguous'}};
 const a=links[0]; if(new URL(a.href).origin!==location.origin)return {{error:'External destination'}};
 a.scrollIntoView({{block:'center'}});
 const r=a.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2,url:a.href}};
}})()"#,lake);
        let target=self.click_dom(&expression)?;
        let url=target["url"].as_str().ok_or("Travel destination URL absent")?;
        let deadline=Instant::now()+Duration::from_secs(30);
        while Instant::now()<deadline {
            self.check_stop()?;
            let s=self.status()?;
            if s.url==url && !s.modal {
                let image=self.screenshot(None)?;
                if vision::water_point(&image).is_some() {self.check_stop()?;return Ok(());}
            }
            self.pause(200)?;
        }
        Err("Travel unverified, lake index unchanged".into())
    }
    pub fn bread_with<F>(&mut self,mut before_bread_click:F)->Result<u32>
    where F:FnMut()->Result<()> {
        self.check_stop()?;
        let initial=self.status()?;
        if initial.modal {return Err("Close game dialogs before restoring energy".into());}
        let before=initial.energy.ok_or("Energy unavailable; cannot verify bread")?;
        if before>=2 {return Ok(before);}
        let full=self.screenshot(None)?;
        self.check_stop()?;
        let roi=vision::crop_fraction(&full,0.2,0.7,0.6,0.24);
        let t=vision::template("bread")?;
        let hit=vision::unique_match(&roi,&t,0.90).map_err(|_|"Multiple possible bread items in quick slots; stopped")?;
        if let Some(hit)=hit {
            let s=self.status()?;
            before_bread_click()?;
            self.click((hit.x+hit.width/2) as f64*s.width/full.width() as f64+s.width*0.2,
                (hit.y+hit.height/2) as f64*s.height/full.height() as f64+s.height*0.7)?;
            return self.wait_for_energy_increase(before,false);
        }

        let pocket=r#"(() => {const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';const es=[...document.querySelectorAll('button,a,[role=button]')].filter(e=>visible(e)&&/^(pocket)$/i.test((e.innerText||e.getAttribute('aria-label')||'').trim()));if(es.length!==1)return null;const r=es[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()"#;
        self.check_stop()?;
        if self.browser.eval(pocket)?.is_null() {return Err("Bread not found in quick slots; Pocket control is not uniquely identifiable".into());}
        self.check_stop()?;
        self.click_dom(pocket)?;
        for _ in 0..20 {
            self.pause(100)?;
            if self.status()?.modal {break;}
        }
        if !self.status()?.modal {return Err("Pocket did not open; stopped before selecting an item".into());}
        let bread=r#"(() => {const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';const ms=[...document.querySelectorAll('.modal-body')].filter(visible);if(ms.length!==1)return null;const es=[...ms[0].querySelectorAll('button,a,[role=button]')].filter(e=>visible(e)&&/^(bread)$/i.test((e.innerText||e.getAttribute('aria-label')||'').trim()));if(es.length!==1)return null;const r=es[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()"#;
        if self.browser.eval(bread)?.is_null() {
            self.close_modal_escape()?;
            return Err("Pocket opened but a unique Bread control was not found".into());
        }
        before_bread_click()?;
        if let Err(error)=self.click_dom(bread) {
            let _=self.close_modal_escape();
            return Err(error);
        }
        self.wait_for_energy_increase(before,true)
    }
    fn wait_for_energy_increase(&mut self,before:u32,pocket_open:bool)->Result<u32> {
        let mut increased=None;
        for _ in 0..20 {
            self.pause(150)?;
            if let Some(energy)=self.status()?.energy.filter(|energy|*energy>before) {
                increased=Some(energy);
                break;
            }
        }
        if pocket_open {self.close_modal_escape()?;}
        increased.ok_or_else(||"Bread did not restore energy; stopped".into())
    }
    fn close_modal_escape(&mut self)->Result<()> {
        self.check_stop()?;
        let down=self.browser.call("Input.dispatchKeyEvent",json!({"type":"keyDown","key":"Escape","code":"Escape","windowsVirtualKeyCode":27}));
        let up=self.browser.call("Input.dispatchKeyEvent",json!({"type":"keyUp","key":"Escape","code":"Escape","windowsVirtualKeyCode":27}));
        down?; up?;
        for _ in 0..20 {
            self.pause(100)?;
            if !self.status()?.modal {return Ok(());}
        }
        Err("Pocket modal did not close after Escape".into())
    }
    pub fn reload_ready(&mut self)->Result<()> {
        self.check_stop()?;
        self.status()?;
        self.check_stop()?;
        self.browser.call("Page.reload",json!({"ignoreCache":false}))?;
        let deadline=Instant::now()+Duration::from_secs(10);
        let mut last_error=String::new();
        while Instant::now()<deadline {
            self.check_stop()?;
            match self.status() {
                Ok(status) if !status.modal=>{
                    let frame=self.screenshot(None)?;
                    if vision::water_point(&frame).is_some() {self.check_stop()?;return Ok(());}
                }
                Ok(_)=>last_error="modal still open after reload".into(),
                Err(error) if error.to_string().contains("Wrong game origin")=>return Err(error),
                Err(error)=>last_error=error.to_string(),
            }
            self.pause(200)?;
        }
        Err(format!("Reload did not restore verified page and water: {}",last_error).into())
    }
}

#[derive(Debug,Serialize,PartialEq,Clone,Copy)]
pub enum Outcome { Catch, Inferred, Miss, Trash, Empty, Energy, Unverified }
pub fn classify(before:&Status,now:&Status)->Outcome {
    let fresh=now.sequence!=before.sequence || now.toast!=before.toast;
    if fresh {
        if now.toast.contains("nothing left") || now.toast.contains("come back later") {return Outcome::Empty;}
        if now.toast.contains("trash") {return Outcome::Trash;}
        if now.toast.contains("insufficient") || now.toast.contains("energy level") {return Outcome::Energy;}
        if now.toast.contains("and i got") || now.toast.contains("caught") || now.toast.contains("collected") {return Outcome::Catch;}
        if now.toast.contains("missed") || now.toast.contains("got away") {return Outcome::Miss;}
    }
    if let (Some(before_xp),Some(now_xp))=(before.xp,now.xp) {
        if before_xp!=now_xp {return Outcome::Inferred;}
    }
    Outcome::Unverified
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cdp::Browser;
    use serde_json::json;
    use std::{sync::{Arc,atomic::AtomicBool},time::Duration};

    struct DelayedBrowser { screenshot:String }
    impl Browser for DelayedBrowser {
        fn call(&mut self,method:&str,params:Value)->Result<Value> {
            match method {
                "Page.captureScreenshot"=>{
                    thread::sleep(Duration::from_millis(350));
                    Ok(json!({"data":self.screenshot}))
                }
                "Runtime.evaluate"=>{
                    thread::sleep(Duration::from_millis(70));
                    Ok(json!({"result":{"value":{
                        "url":"https://nomstead.com/qn","width":1280,"height":720,"dpr":1,
                        "energy":70,"toast":"","sequence":0,"xp":null,"modal":false
                    }}}))
                }
                "Input.dispatchMouseEvent"=>{
                    thread::sleep(Duration::from_millis(350));
                    Ok(json!({}))
                }
                _=>Err(format!("unexpected method {method}").into()),
            }
        }
    }

    struct BreadBrowser { screenshot:String, energy:u32, increase_on_release:bool, mouse_events:Vec<String> }
    impl Browser for BreadBrowser {
        fn call(&mut self,method:&str,params:Value)->Result<Value> {
            match method {
                "Page.captureScreenshot"=>Ok(json!({"data":self.screenshot})),
                "Runtime.evaluate"=>{
                    let expression=params["expression"].as_str().unwrap_or("");
                    if expression.contains("^(pocket)$") {return Ok(json!({"result":{"value":null}}));}
                    Ok(json!({"result":{"value":{
                        "url":"https://nomstead.com/qn","width":800,"height":600,"dpr":1,
                        "energy":self.energy,"toast":"","sequence":0,"xp":null,"modal":false
                    }}}))
                }
                "Input.dispatchMouseEvent"=>{
                    let event=params["type"].as_str().unwrap_or("").to_string();
                    if event=="mouseReleased" && self.increase_on_release {self.energy=5;}
                    self.mouse_events.push(event);
                    Ok(json!({}))
                }
                _=>Err(format!("unexpected method {method}").into()),
            }
        }
        fn fixture(&self)->bool {true}
    }
    struct StopOnPressBrowser { stop:Arc<AtomicBool>, mouse_events:Vec<String> }
    impl Browser for StopOnPressBrowser {
        fn call(&mut self,method:&str,params:Value)->Result<Value> {
            match method {
                "Runtime.evaluate"=>Ok(json!({"result":{"value":{
                    "url":"https://nomstead.com/qn","width":800,"height":600,"dpr":1,
                    "energy":70,"toast":"","sequence":0,"xp":null,"modal":false
                }}})),
                "Input.dispatchMouseEvent"=>{
                    let event=params["type"].as_str().unwrap_or("").to_string();
                    if event=="mousePressed" {self.stop.store(true,Ordering::Relaxed);}
                    self.mouse_events.push(event);
                    Ok(json!({}))
                }
                _=>Err(format!("unexpected method {method}").into()),
            }
        }
        fn fixture(&self)->bool {true}
    }
    fn screenshot_with_bread(two:bool)->String {
        let bread=vision::template("bread").unwrap();
        let mut image=RgbImage::from_pixel(800,600,image::Rgb([0,0,0]));
        image::imageops::replace(&mut image,&bread,300,420);
        if two {image::imageops::replace(&mut image,&bread,500,420);}
        let mut encoded=std::io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgb8(image).write_to(&mut encoded,image::ImageOutputFormat::Png).unwrap();
        STANDARD.encode(encoded.into_inner())
    }

    #[test] fn image_to_press_latency_includes_post_receive_work_and_excludes_dispatch_round_trip() {
        let png=STANDARD.encode(include_bytes!("../assets/cham_than.png"));
        let mut browser=DelayedBrowser{screenshot:png};
        let mut game=Game{browser:&mut browser,stop:Arc::new(AtomicBool::new(false))};
        let frame=game.screenshot(None).unwrap();
        assert!(frame.capture_ms>=300.0);
        thread::sleep(Duration::from_millis(80)); // Simulated decode/detection work after image receipt.
        let timing=game.click_timed(10.0,10.0).unwrap();
        let image_to_press_ms=timing.press_sent_at.saturating_duration_since(frame.received_at).as_secs_f64()*1000.0;
        assert!(image_to_press_ms>=130.0,"status plus post-receive work was omitted: {image_to_press_ms}ms");
        assert!(image_to_press_ms<300.0,"press/release round trip leaked into image-to-press metric: {image_to_press_ms}ms");
        assert!(timing.press_release_round_trip_ms>=680.0);
    }
    #[test] fn bread_click_requires_unique_quickslot_and_energy_increase() {
        let mut browser=BreadBrowser{screenshot:screenshot_with_bread(false),energy:1,increase_on_release:true,mouse_events:vec![]};
        let mut game=Game{browser:&mut browser,stop:Arc::new(AtomicBool::new(false))};
        let mut marked=0;
        let after=game.bread_with(||{marked+=1;Ok(())}).unwrap();
        assert_eq!(after,5);
        assert_eq!(marked,1);
        drop(game);
        assert_eq!(browser.mouse_events,vec!["mousePressed","mouseReleased"]);
    }
    #[test] fn bread_stops_when_energy_does_not_increase_or_candidates_are_ambiguous() {
        let mut no_gain=BreadBrowser{screenshot:screenshot_with_bread(false),energy:1,increase_on_release:false,mouse_events:vec![]};
        let mut game=Game{browser:&mut no_gain,stop:Arc::new(AtomicBool::new(false))};
        assert!(game.bread_with(||Ok(())).unwrap_err().to_string().contains("did not restore energy"));
        drop(game);
        assert_eq!(no_gain.mouse_events,vec!["mousePressed","mouseReleased"]);

        let mut duplicate=BreadBrowser{screenshot:screenshot_with_bread(true),energy:1,increase_on_release:true,mouse_events:vec![]};
        let mut game=Game{browser:&mut duplicate,stop:Arc::new(AtomicBool::new(false))};
        assert!(game.bread_with(||Ok(())).unwrap_err().to_string().contains("Multiple possible bread"));
        drop(game);
        assert!(duplicate.mouse_events.is_empty());
    }
    #[test] fn pause_zero_and_pre_action_click_observe_cancellation() {
        let stop=Arc::new(AtomicBool::new(true));
        let mut browser=StopOnPressBrowser{stop:stop.clone(),mouse_events:vec![]};
        let mut game=Game{browser:&mut browser,stop};
        let error=game.pause(0).unwrap_err();
        assert!(is_cancelled(error.as_ref()));
        let error=game.click(10.0,10.0).unwrap_err();
        assert!(is_cancelled(error.as_ref()));
        drop(game);
        assert!(browser.mouse_events.is_empty());
    }
    #[test] fn stop_during_press_still_sends_release_and_returns_typed_cancel() {
        let stop=Arc::new(AtomicBool::new(false));
        let mut browser=StopOnPressBrowser{stop:stop.clone(),mouse_events:vec![]};
        let mut game=Game{browser:&mut browser,stop};
        let error=game.click_timed(10.0,10.0).unwrap_err();
        assert!(is_cancelled(error.as_ref()));
        drop(game);
        assert_eq!(browser.mouse_events,vec!["mousePressed","mouseReleased"]);
    }
}
