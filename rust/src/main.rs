mod cdp;
mod game;
mod state;
mod vision;
use cdp::{Browser,Result};
use game::{Game,Outcome,Status};
use state::{ResetMarker,Session,SessionAction};
use serde_json::json;
use std::{sync::{Arc,atomic::{AtomicBool,Ordering}},time::{Duration,Instant},path::Path};

fn sleep_until(game:&Game<'_>,start:Instant,ms:u64)->Result<()> {
    let remaining=Duration::from_millis(ms).saturating_sub(start.elapsed());
    game.pause(remaining.as_millis() as u64)
}
const POST_CATCH_REEL_MS:u64=500;
const STUCK_ROD_TIMEOUT:Duration=Duration::from_secs(30);
#[derive(Debug,Clone,Copy,PartialEq,Eq)]
enum StuckAction { Wait, RetryCast, Reload, LimitReached }
struct RodWatchdog { idle_since:Instant, retry_pending:bool }
impl RodWatchdog {
    fn new(now:Instant)->Self {Self{idle_since:now,retry_pending:false}}
    fn progress(&mut self,now:Instant) {self.idle_since=now;self.retry_pending=false;}
    fn after_miss(&mut self,now:Instant,casts_used:usize,cast_limit:usize)->StuckAction {
        if self.retry_pending {
            return if casts_used>=cast_limit {StuckAction::LimitReached} else {StuckAction::Reload};
        }
        if now.saturating_duration_since(self.idle_since)<STUCK_ROD_TIMEOUT {
            StuckAction::Wait
        } else if casts_used>=cast_limit {
            StuckAction::LimitReached
        } else {
            // The outer bounded loop's next cast is the single retry. Do not restart the timer.
            self.retry_pending=true;
            StuckAction::RetryCast
        }
    }
}
fn handle_stuck_miss<F>(watchdog:&mut RodWatchdog,now:Instant,casts_used:usize,cast_limit:usize,
    fixture:bool,reload_ready:F)->Result<StuckAction>
where F:FnOnce()->Result<()> {
    let action=watchdog.after_miss(now,casts_used,cast_limit);
    if action==StuckAction::Reload {
        if fixture {return Err("Fixture cannot validate stuck-rod reload recovery".into());}
        reload_ready()?;
        watchdog.progress(Instant::now());
    }
    Ok(action)
}
fn reel_wait(strike_at:Instant,now:Instant)->Duration {
    Duration::from_millis(POST_CATCH_REEL_MS).saturating_sub(now.saturating_duration_since(strike_at))
}
fn outcome_reel_wait(outcome:&Outcome,strike_at:Instant,now:Instant)->Duration {
    if *outcome==Outcome::Catch {reel_wait(strike_at,now)} else {Duration::ZERO}
}

#[derive(Debug,Clone,Copy)]
struct PressSample {
    capture_ms:f64,
    decode_ms:f64,
    detect_ms:f64,
    image_received_to_press_send_ms:f64,
    press_release_round_trip_ms:f64,
}
fn percentile(values:&[f64],p:f64)->Option<f64> {
    if values.is_empty() {return None;}
    let mut sorted=values.to_vec();
    sorted.sort_by(f64::total_cmp);
    let index=((p.clamp(0.0,1.0)*sorted.len() as f64).ceil() as usize).saturating_sub(1).min(sorted.len()-1);
    Some(sorted[index])
}
fn print_press_summary(samples:&[PressSample]) {
    let values=samples.iter().map(|s|s.image_received_to_press_send_ms).collect::<Vec<_>>();
    if let (Some(p50),Some(p95))=(percentile(&values,0.50),percentile(&values,0.95)) {
        println!("{}",json!({"press_samples":values.len(),
            "image_received_to_press_send_ms_p50":p50,
            "image_received_to_press_send_ms_p95":p95}));
    }
}
fn metrics_equal(a:&Status,b:&Status)->bool {
    a.width==b.width && a.height==b.height && a.dpr==b.dpr && a.url==b.url
}
#[derive(Debug,Default,Clone,Copy,PartialEq,Eq)]
struct RunCounts { caught:u32, inferred:u32, misses:u32 }
#[derive(Debug,Clone,Copy,PartialEq,Eq)]
enum FishDisposition { Continue(Outcome), StopAfterCommit(Outcome), StopUnresolved, Unverified }
fn finish_fish_result<F>(result:Result<Outcome>,session:&mut Session,counts:&mut RunCounts,
    stop_observed:bool,saved_at:u64,mut persist:F)->Result<FishDisposition>
where F:FnMut(&Session)->Result<()> {
    let outcome=match result {
        Ok(outcome)=>outcome,
        Err(error) if game::is_cancelled(error.as_ref())=>return Ok(FishDisposition::StopUnresolved),
        Err(error)=>return Err(error),
    };
    session.saved_at_unix_secs=saved_at;
    if outcome==Outcome::Unverified {
        persist(session)?;
        return Ok(if stop_observed {FishDisposition::StopUnresolved} else {FishDisposition::Unverified});
    }
    if !session.action_uncertain {return Err("Cannot commit a cast outcome without a pending action".into());}
    session.finish_action();
    session.casts=session.casts.saturating_add(1);
    if matches!(outcome,Outcome::Empty|Outcome::Trash) {session.mark_depleted();}
    persist(session)?;
    match outcome {
        Outcome::Catch=>counts.caught=counts.caught.saturating_add(1),
        Outcome::Inferred=>counts.inferred=counts.inferred.saturating_add(1),
        Outcome::Miss=>counts.misses=counts.misses.saturating_add(1),
        _=>{},
    }
    Ok(if stop_observed {FishDisposition::StopAfterCommit(outcome)} else {FishDisposition::Continue(outcome)})
}

fn fish<F>(game:&mut Game<'_>,samples:&mut Vec<PressSample>,matcher_scratch:&mut vision::MatcherScratch,
    before_cast:F)->Result<Outcome>
where F:FnMut(game::ClickPhase)->Result<()> {
    game.check_stop()?;
    let initial=game.status()?;
    if initial.modal {return Err("Close game dialogs before fishing".into());}
    if initial.energy.is_none() {return Err("Log in and enter the game first; energy status unavailable".into());}
    if initial.energy.unwrap_or(0)<2 {return Err("Energy below 2; recover before casting".into());}
    let full=game.screenshot(None)?;
    let (px,py)=vision::water_point(&full).ok_or("No safe water square found")?;
    let x=px as f64*initial.width/full.width() as f64;
    let y=py as f64*initial.height/full.height() as f64;
    let current=game.status()?;
    if !metrics_equal(&initial,&current) {return Err("Viewport/page changed before cast".into());}
    let before=game.status()?;
    game.check_stop()?;
    let dispatch=game.click_timed_with(x,y,before_cast)?;
    let cast_at=dispatch.press_sent_at;
    let clip=json!({"x":initial.width*0.35,"y":initial.height*0.20,
        "width":initial.width*0.30,"height":initial.height*0.40,"scale":1});
    sleep_until(game,cast_at,800)?;
    let baseline=game.screenshot(Some(clip.clone()))?;
    sleep_until(game,cast_at,950)?;
    let original_pattern=vision::template("alert")?;
    // Capture pixels can differ from CSS pixels. Preserve the original sample's CSS scale.
    let scale=baseline.width() as f64/(initial.width*0.30);
    let resized_pattern=image::imageops::resize(&original_pattern,
        (original_pattern.width() as f64*scale).round().max(1.0) as u32,
        (original_pattern.height() as f64*scale).round().max(1.0) as u32,
        image::imageops::FilterType::Triangle);
    let pattern=vision::PreparedTemplate::new(&resized_pattern);
    let deadline=cast_at+Duration::from_millis(11450);
    let mut banner_at=Instant::now();
    while Instant::now()<deadline {
        game.check_stop()?;
        if banner_at.elapsed()>=Duration::from_millis(250) {
            let now=game.status()?;
            if !metrics_equal(&initial,&now) {return Err("Viewport/page changed during cast".into());}
            let result=game::classify(&before,&now);
            if matches!(result,Outcome::Empty|Outcome::Trash|Outcome::Energy) {return Ok(result);}
            banner_at=Instant::now();
        }
        let frame=game.screenshot(Some(clip.clone()))?;
        let capture_ms=frame.capture_ms;
        let decode_ms=frame.decode_ms;
        let detect_at=Instant::now();
        let hit=vision::alert_prepared_with_scratch(&frame,&pattern,Some(&baseline),matcher_scratch);
        let detect_ms=detect_at.elapsed().as_secs_f64()*1000.0;
        if hit.is_some() {
            let pre_strike=game.status()?;
            if !metrics_equal(&initial,&pre_strike) {return Err("Viewport changed before strike".into());}
            let dispatch=game.click_timed(x,y)?;
            let sample=PressSample{capture_ms,decode_ms,detect_ms,
                image_received_to_press_send_ms:dispatch.press_sent_at.saturating_duration_since(frame.received_at).as_secs_f64()*1000.0,
                press_release_round_trip_ms:dispatch.press_release_round_trip_ms};
            samples.push(sample);
            let verify_until=Instant::now()+Duration::from_millis(6500);
            let mut inferred=false;
            while Instant::now()<verify_until {
                if game.stop.load(Ordering::Relaxed) {
                    if inferred {return Ok(Outcome::Inferred);}
                    game.check_stop()?;
                }
                let now=match game.status() {
                    Ok(now)=>now,
                    Err(error) if inferred && game::is_cancelled(error.as_ref())=>return Ok(Outcome::Inferred),
                    Err(error)=>return Err(error),
                };
                if !metrics_equal(&initial,&now) {return Err("Viewport/page changed during verification".into());}
                match game::classify(&pre_strike,&now) {
                    Outcome::Inferred=>inferred=true,
                    Outcome::Unverified=>{},
                    outcome=>{
                        println!("{}",json!({"capture_ms":sample.capture_ms,"decode_ms":sample.decode_ms,
                            "detect_ms":sample.detect_ms,
                            "image_received_to_press_send_ms":sample.image_received_to_press_send_ms,
                            "press_release_round_trip_ms":sample.press_release_round_trip_ms,"outcome":outcome}));
                        let wait=outcome_reel_wait(&outcome,dispatch.press_sent_at,Instant::now());
                        if let Err(error)=game.pause(wait.as_millis() as u64) {
                            if game::is_cancelled(error.as_ref()) {return Ok(outcome);}
                            return Err(error);
                        }
                        return Ok(outcome);
                    }
                }
                if let Err(error)=game.pause(100) {
                    if inferred && game::is_cancelled(error.as_ref()) {return Ok(Outcome::Inferred);}
                    return Err(error);
                }
            }
            if game.stop.load(Ordering::Relaxed) && inferred {return Ok(Outcome::Inferred);}
            game.check_stop()?;
            let outcome=if inferred {Outcome::Inferred} else {Outcome::Unverified};
            println!("{}",json!({"capture_ms":sample.capture_ms,"decode_ms":sample.decode_ms,
                "detect_ms":sample.detect_ms,
                "image_received_to_press_send_ms":sample.image_received_to_press_send_ms,
                "press_release_round_trip_ms":sample.press_release_round_trip_ms,"outcome":outcome}));
            return Ok(outcome);
        }
        let elapsed=cast_at.elapsed().as_secs_f64();
        game.pause(if elapsed<2.5 {70} else if elapsed<3.2 {35} else {22})?;
    }
    game.check_stop()?;
    Ok(Outcome::Miss)
}

#[derive(Clone,Copy)]
struct SessionStore<'a> { path:&'a Path, fixture:bool }
fn save_session(session:&Session,store:SessionStore<'_>)->Result<()> {
    if !store.fixture {state::write_atomic(store.path,session)?;}
    Ok(())
}
fn travel_verified(game:&mut Game<'_>,session:&mut Session,target:u32,store:SessionStore<'_>)->Result<()> {
    game.check_stop()?;
    let marker=state::local_now().latest_reset();
    session.begin_travel(target,state::unix_now(),marker)?;
    save_session(session,store)?;
    for attempt in 1..=3 {
        game.check_stop()?;
        match game.travel(target) {
            Ok(())=>{
                session.complete_travel(target,state::unix_now(),state::local_now().latest_reset())?;
                save_session(session,store)?;
                return Ok(());
            }
            Err(error) if error.to_string().contains("Travel unverified")=>{
                eprintln!("HO {} travel verification attempt {}/3 failed: {}",target,attempt,error);
                if attempt<3 {game.pause(1000)?;}
            }
            Err(error)=>return Err(error),
        }
    }
    game.check_stop()?;
    if store.fixture {return Err(format!("Fixture could not verify travel to HO {} after three attempts",target).into());}
    game.reload_ready()?;
    game.check_stop()?;
    game.travel(target)?;
    session.complete_travel(target,state::unix_now(),state::local_now().latest_reset())?;
    save_session(session,store)
}
fn wait_for_reset(game:&Game<'_>,session:&mut Session,target:ResetMarker,store:SessionStore<'_>)->Result<bool> {
    eprintln!("Waiting for local reset {:04}-{:02}-{:02} {:02}:00:15",target.year,target.month,target.day,target.hour);
    let mut last_save=Instant::now();
    loop {
        if game.stop.load(Ordering::Relaxed) {return Ok(false);}
        if state::local_now().latest_reset()>=target {return Ok(true);}
        if last_save.elapsed()>=Duration::from_secs(60) {
            session.saved_at_unix_secs=state::unix_now();
            save_session(session,store)?;
            last_save=Instant::now();
        }
        game.pause(1000)?;
    }
}
fn transient_transport(error:&dyn std::error::Error)->bool {
    let message=error.to_string().to_ascii_lowercase();
    ["cdp timeout","connection reset","connection refused","broken pipe","connection closed",
        "websocket","unexpected eof","timed out","not connected","protocol error"]
        .iter().any(|part|message.contains(part))
}
fn reconnect_allowed(error:&dyn std::error::Error,fixture:bool,stop_observed:bool)->bool {
    !fixture && !stop_observed && !game::is_cancelled(error) && transient_transport(error)
}
fn initial_session(requested:Option<u32>,store:SessionStore<'_>,now:u64,marker:ResetMarker)->Result<(Session,bool)> {
    if store.fixture {return Ok((Session::new(requested,now,marker),false));}
    match state::read(store.path) {
        Ok(Some(mut session))=>match session.validate(now,marker) {
            Ok(reset_elapsed)=>Ok((session,reset_elapsed)),
            Err(error) if requested.is_some()=>{
                eprintln!("Ignoring unusable saved session: {}; explicit --lake will be verified",error);
                Ok((Session::new(requested,now,marker),false))
            }
            Err(error)=>Err(format!("Saved session is unusable ({}); provide --lake N to choose a verified start",error).into()),
        },
        Ok(None)=>Ok((Session::new(requested,now,marker),false)),
        Err(error) if requested.is_some() && error.kind()==std::io::ErrorKind::InvalidData=>{
            eprintln!("Ignoring malformed saved session; explicit --lake will be verified");
            Ok((Session::new(requested,now,marker),false))
        }
        Err(error)=>Err(error.into()),
    }
}
fn prepare_session(game:&mut Game<'_>,session:&mut Session,requested:Option<u32>,reset_elapsed:bool,store:SessionStore<'_>)->Result<bool> {
    game.check_stop()?;
    if reset_elapsed {
        session.begin_new_cycle(state::unix_now(),state::local_now().latest_reset())?;
        save_session(session,store)?;
        travel_verified(game,session,1,store)?;
        return Ok(true);
    }
    if session.waiting_reset {
        if store.fixture {return Err("A static fixture cannot wait for the local reset clock".into());}
        let target=state::local_now().next_reset();
        if !wait_for_reset(game,session,target,store)? {return Ok(false);}
        game.check_stop()?;
        session.begin_new_cycle(state::unix_now(),state::local_now().latest_reset())?;
        save_session(session,store)?;
        travel_verified(game,session,1,store)?;
        return Ok(true);
    }
    if let Some(lake)=requested {
        travel_verified(game,session,lake,store)?;
        return Ok(true);
    }
    match session.next_action() {
        SessionAction::StopUncertain=>return Err("Saved session has an interrupted action; inspect the game before restarting, or choose an explicit --lake to verify a new destination".into()),
        SessionAction::StopUnknown=>return Err("Saved depleted state has no verified next lake; provide --lake N after checking the route".into()),
        SessionAction::Travel(target)=>travel_verified(game,session,target,store)?,
        SessionAction::WaitReset=>{
            if store.fixture {return Err("A static fixture cannot wait for the local reset clock".into());}
            let target=state::local_now().next_reset();
            if !wait_for_reset(game,session,target,store)? {return Ok(false);}
            game.check_stop()?;
            session.begin_new_cycle(state::unix_now(),state::local_now().latest_reset())?;
            save_session(session,store)?;
            travel_verified(game,session,1,store)?;
        }
        SessionAction::Cast(Some(lake))=>travel_verified(game,session,lake,store)?,
        SessionAction::Cast(None)=>{},
    }
    Ok(true)
}
fn restore_energy(game:&mut Game<'_>,session:&mut Session,store:SessionStore<'_>)->Result<()> {
    game.check_stop()?;
    let before=game.status()?.energy.ok_or("Energy unavailable; stopped before cast")?;
    game.check_stop()?;
    if before>=2 {return Ok(());}
    let mut mark_bread_action=|| {
        session.begin_action();
        session.saved_at_unix_secs=state::unix_now();
        session.reset_marker=state::local_now().latest_reset();
        save_session(session,store)
    };
    let after=game.bread_with(&mut mark_bread_action)?;
    drop(mark_bread_action);
    session.finish_action();
    session.saved_at_unix_secs=state::unix_now();
    save_session(session,store)?;
    if after<2 {return Err(format!("Bread raised energy only to {}; stopped before cast",after).into());}
    Ok(())
}
fn value(args:&[String],flag:&str)->Result<Option<String>> {
    if let Some(i)=args.iter().position(|a|a==flag) {
        return Ok(Some(args.get(i+1).filter(|s|!s.starts_with("--")).ok_or("Missing argument value")?.clone()));
    }
    Ok(None)
}
#[derive(Debug,Clone,Copy)]
enum RunCommand { Check, Travel(u32), Run { casts:u32, lake:Option<u32> } }

fn coordinate<F>(browser:Box<dyn Browser>,stop:Arc<AtomicBool>,command:RunCommand,
    session_path:&Path,mut reconnect:F)->Result<()>
where F:FnMut(&Arc<AtomicBool>)->Result<String> {
    coordinate_with_watchdog_clock(browser,stop,command,session_path,|stop|reconnect(stop),Instant::now)
}

fn coordinate_with_watchdog_clock<F,C>(mut browser:Box<dyn Browser>,stop:Arc<AtomicBool>,command:RunCommand,
    session_path:&Path,mut reconnect:F,mut watchdog_now:C)->Result<()>
where F:FnMut(&Arc<AtomicBool>)->Result<String>, C:FnMut()->Instant {
    let recovery_stop=stop.clone();
    let is_fixture=browser.fixture();
    let store=SessionStore{path:session_path,fixture:is_fixture};
    let result=(||->Result<()> {
        let mut game=Game {browser:browser.as_mut(),stop};
        game.check_stop()?;
        let status=game.status()?;
        println!("{}",serde_json::to_string(&status)?);
        if matches!(command,RunCommand::Check) {return Ok(());}
        let now=state::unix_now();
        let marker=state::local_now().latest_reset();
        if let RunCommand::Travel(n)=command {
            game.check_stop()?;
            let (mut session,_)=initial_session(Some(n),store,now,marker)?;
            travel_verified(&mut game,&mut session,n,store)?;
            println!("Verified HO {}",n);
            return Ok(());
        }
        let RunCommand::Run{casts,lake}=command else {unreachable!()};
        let (mut session,reset_elapsed)=initial_session(lake,store,now,marker)?;
        if !prepare_session(&mut game,&mut session,lake,reset_elapsed,store)? {return Ok(());}
        let mut counts=RunCounts::default();
        let mut casts_this_run=0u32;
        let mut press_samples=Vec::new();
        let mut matcher_scratch=vision::MatcherScratch::default();
        let started=Instant::now();
        let mut watchdog=RodWatchdog::new(watchdog_now());
        while casts_this_run<casts {
            game.check_stop()?;
            let current_marker=state::local_now().latest_reset();
            if current_marker<session.reset_marker {return Err("Local clock moved behind the saved reset marker; stopped safely".into());}
            if current_marker>session.reset_marker {
                session.begin_new_cycle(state::unix_now(),current_marker)?;
                save_session(&session,store)?;
                travel_verified(&mut game,&mut session,1,store)?;
                watchdog.progress(watchdog_now());
            }
            match session.next_action() {
                SessionAction::StopUncertain=>return Err("A previous action has no verified result; refusing to cast again".into()),
                SessionAction::StopUnknown=>return Err("The depleted current lake has no verified next target; refusing to cast".into()),
                SessionAction::Travel(target)=>{travel_verified(&mut game,&mut session,target,store)?;watchdog.progress(watchdog_now());continue;}
                SessionAction::WaitReset=>{
                    if store.fixture {return Err("A static fixture cannot wait for reset".into());}
                    let target=state::local_now().next_reset();
                    if !wait_for_reset(&game,&mut session,target,store)? {break;}
                    session.begin_new_cycle(state::unix_now(),state::local_now().latest_reset())?;
                    save_session(&session,store)?;
                    travel_verified(&mut game,&mut session,1,store)?;
                    watchdog.progress(watchdog_now());
                    continue;
                }
                SessionAction::Cast(_)=>{}
            }
            game.check_stop()?;
            restore_energy(&mut game,&mut session,store)?;
            let cast_stop=game.stop.clone();
            let mut cast_hook=|phase|match phase {
                game::ClickPhase::BeforePress=>{
                    if cast_stop.load(Ordering::Relaxed) {return Err(game::StoppedByCtrlC.into());}
                    let marker=state::local_now().latest_reset();
                    if marker>session.reset_marker {return Err("Server reset crossed before cast; restart to verify HO 1".into());}
                    if marker<session.reset_marker {return Err("Local clock moved behind saved reset marker".into());}
                    session.begin_action();
                    session.saved_at_unix_secs=state::unix_now();
                    save_session(&session,store)
                }
                game::ClickPhase::PressAttempted=>{
                    session.cast_attempts=session.cast_attempts.saturating_add(1);
                    casts_this_run=casts_this_run.saturating_add(1);
                    session.saved_at_unix_secs=state::unix_now();
                    save_session(&session,store)
                }
            };
            let result=fish(&mut game,&mut press_samples,&mut matcher_scratch,&mut cast_hook);
            drop(cast_hook);
            let disposition=finish_fish_result(result,&mut session,&mut counts,game.stop.load(Ordering::Relaxed),
                state::unix_now(),|saved|save_session(saved,store))?;
            let outcome=match disposition {
                FishDisposition::Continue(outcome)=>outcome,
                FishDisposition::StopAfterCommit(outcome)=>{
                    println!("Cast {}: {:?} (verified outcome committed)",casts_this_run,outcome);
                    print_press_summary(&press_samples);
                    eprintln!("Stopped by Ctrl+C after committing the verified outcome; no further action started.");
                    return Ok(());
                }
                FishDisposition::StopUnresolved=>{
                    print_press_summary(&press_samples);
                    eprintln!("Stopped by Ctrl+C before a verified outcome; action_uncertain={} and no action was replayed.",session.action_uncertain);
                    return Ok(());
                }
                FishDisposition::Unverified=>{
                    print_press_summary(&press_samples);
                    return Err("Harvest unverified; stopped to prevent repeated blind actions".into());
                }
            };
            println!("Cast {}: {:?}",casts_this_run,outcome);
            if game.stop.load(Ordering::Relaxed) {
                print_press_summary(&press_samples);
                eprintln!("Stopped by Ctrl+C after committing the verified outcome; no further action started.");
                return Ok(());
            }
            match outcome {
                Outcome::Catch|Outcome::Inferred=>{watchdog.progress(watchdog_now());},
                Outcome::Miss=>{
                    game.check_stop()?;
                    let action=handle_stuck_miss(&mut watchdog,watchdog_now(),casts_this_run,casts,
                        store.fixture,||game.reload_ready())?;
                    match action {
                        StuckAction::Wait=>{},
                        StuckAction::RetryCast=>{
                            eprintln!("No verified progress for 30 seconds; allowing one bounded additional cast");
                        }
                        StuckAction::Reload=>{
                            eprintln!("No verified progress after the retry cast; reloading and verifying the current page/water");
                        }
                        StuckAction::LimitReached=>eprintln!("Cast limit reached; stopping without reload or another cast"),
                    }
                }
                Outcome::Empty|Outcome::Trash=>{watchdog.progress(watchdog_now());},
                Outcome::Energy=>{game.check_stop()?;restore_energy(&mut game,&mut session,store)?;watchdog.progress(watchdog_now());},
                Outcome::Unverified=>unreachable!("unverified outcomes are handled before watchdog dispatch"),
            }
        }
        print_press_summary(&press_samples);
        println!("{}",json!({"verified_catches":counts.caught,"inferred":counts.inferred,"misses":counts.misses,
            "cast_attempts":casts_this_run,
            "elapsed_seconds":started.elapsed().as_secs_f64()}));
        Ok(())
    })();
    let replay=browser.finish();
    match result {
        Ok(())=>replay,
        Err(error) if game::is_cancelled(error.as_ref())=>{
            eprintln!("Stopped by Ctrl+C; no subsequent action or replay was started. Any saved action_uncertain state remains for inspection.");
            replay
        }
        Err(_) if recovery_stop.load(Ordering::Relaxed)=>{
            eprintln!("Stopped by Ctrl+C while handling an error; reconnect and replay were skipped.");
            replay
        }
        Err(error)=>{
            let message=error.to_string();
            if reconnect_allowed(error.as_ref(),is_fixture,recovery_stop.load(Ordering::Relaxed)) {
                drop(browser);
                let reconnect=reconnect(&recovery_stop);
                if let Err(reconnect_error)=reconnect.as_ref() {
                    if game::is_cancelled(reconnect_error.as_ref()) {
                        eprintln!("Stopped by Ctrl+C before reconnect completed; no action was replayed.");
                        return replay;
                    }
                }
                return Err(match reconnect {
                    Ok(url)=>format!("{}; CDP reconnected and verified {}, but the interrupted action was not replayed. Inspect the game/session before restarting.",message,url).into(),
                    Err(reconnect_error)=>format!("{}; one bounded reconnect attempt failed: {}",message,reconnect_error).into(),
                });
            }
            Err(error)
        }
    }
}

fn execute()->Result<()> {
    let args:Vec<String>=std::env::args().skip(1).collect();
    if args.is_empty() || args.iter().any(|a|a=="--help") {
        println!("nomstead-rust --check | --run [--casts 10] [--lake 1] | --travel 2");
        println!("Offline replay: add --fixture fixtures/check.json");
        println!("--run without --lake fishes only the current lake; --lake verifies travel first.");
        return Ok(());
    }
    let allowed=["--check","--run","--casts","--lake","--travel","--fixture"];
    for a in args.iter().filter(|a|a.starts_with("--")) {
        if !allowed.contains(&a.as_str()) {return Err(format!("Unknown argument {}",a).into());}
    }
    let modes=args.iter().filter(|a|["--check","--run","--travel"].contains(&a.as_str())).count();
    if modes!=1 {return Err("Choose exactly one of --check, --run, --travel".into());}
    let casts:u32=value(&args,"--casts")?.unwrap_or_else(||"10".into()).parse()?;
    if casts==0 || casts>1000 {return Err("--casts must be 1..1000".into());}
    let lake:Option<u32>=value(&args,"--lake")?.map(|n|n.parse()).transpose()?;
    if lake.map(|n|!(1..=40).contains(&n)).unwrap_or(false) {return Err("--lake must be 1..40".into());}
    let travel=value(&args,"--travel")?.map(|n|n.parse()).transpose()?;
    if travel.map(|n|!(1..=40).contains(&n)).unwrap_or(false) {return Err("--travel must be 1..40".into());}
    let command=if args.iter().any(|a|a=="--check") {RunCommand::Check}
        else if let Some(n)=travel {RunCommand::Travel(n)}
        else {RunCommand::Run{casts,lake}};
    let stop=Arc::new(AtomicBool::new(false));
    let handler=stop.clone();
    ctrlc::set_handler(move||handler.store(true,Ordering::Relaxed))?;
    let fixture=value(&args,"--fixture")?;
    let browser:Box<dyn Browser>=if let Some(path)=fixture {
        Box::new(cdp::Fixture::load(&path)?)
    }else{Box::new(cdp::Cdp::connect()?)};
    coordinate(browser,stop,command,Path::new("session.json"),|recovery_stop|{
        if recovery_stop.load(Ordering::Relaxed) {return Err(game::StoppedByCtrlC.into());}
        let mut recovered=cdp::Cdp::connect()?;
        let mut game=Game{browser:&mut recovered,stop:recovery_stop.clone()};
        game.check_stop()?;
        let status=game.status()?;
        if status.energy.is_none() {return Err("reconnected page has no readable game energy/login state".into());}
        Ok(status.url)
    })
}
fn main() {
    if let Err(error)=execute() {
        eprintln!("ERROR: {}\nFor live testing, open start_chrome_debug.bat and log in directly.",error);
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine as _;
    use image::{DynamicImage,GenericImage,ImageOutputFormat,Rgb,RgbImage};
    use std::{fs,io::Cursor,sync::{atomic::{AtomicU64,AtomicUsize},Mutex}};
    fn status(toast:&str,sequence:u64)->Status {
        Status{url:"https://nomstead.com/qn".into(),width:1920.0,height:1080.0,dpr:1.0,
            energy:Some(70),toast:toast.into(),sequence,xp:None,modal:false}
    }
    #[test] fn stale_banner_is_not_a_catch() {
        assert_eq!(game::classify(&status("and i got a fish",2),&status("and i got a fish",2)),Outcome::Unverified);
        assert_eq!(game::classify(&status("and i got a fish",2),&status("and i got a fish",3)),Outcome::Catch);
    }
    #[test] fn xp_inference_requires_two_valid_changed_numbers() {
        let mut before=status("",2);
        before.xp=Some(1234);
        let mut now=before.clone();
        now.xp=None;
        assert_eq!(game::classify(&before,&now),Outcome::Unverified);
        now.xp=Some(1234);
        assert_eq!(game::classify(&before,&now),Outcome::Unverified);
        now.xp=Some(1235);
        assert_eq!(game::classify(&before,&now),Outcome::Inferred);
    }
    #[test] fn catch_wait_only_uses_the_remaining_500ms_from_strike() {
        let strike=Instant::now();
        assert_eq!(reel_wait(strike,strike+Duration::from_millis(250)),Duration::from_millis(250));
        assert_eq!(reel_wait(strike,strike+Duration::from_secs(2)),Duration::ZERO);
    }
    #[test] fn non_catch_outcomes_have_no_reel_wait() {
        let strike=Instant::now();
        for outcome in [Outcome::Inferred,Outcome::Miss,Outcome::Trash,Outcome::Empty,Outcome::Energy,Outcome::Unverified] {
            assert_eq!(outcome_reel_wait(&outcome,strike,strike),Duration::ZERO);
        }
    }
    #[test] fn press_latency_summary_uses_nearest_rank_percentiles() {
        assert_eq!(percentile(&[1.0,2.0,3.0,4.0],0.50),Some(2.0));
        assert_eq!(percentile(&[1.0,2.0,3.0,4.0],0.95),Some(4.0));
        assert_eq!(percentile(&[],0.95),None);
    }
    fn drive_fake_watchdog(times:&[u64],outcomes:&[std::result::Result<Outcome,&'static str>],limit:usize)->Vec<&'static str> {
        let start=Instant::now();
        let mut watchdog=RodWatchdog::new(start);
        let mut events=Vec::new();
        for (index,(second,result)) in times.iter().zip(outcomes).enumerate() {
            if index>=limit {break;}
            events.push("cast");
            let used=index+1;
            let now=start+Duration::from_secs(*second);
            let outcome=match result {
                Ok(outcome)=>outcome,
                Err(_) => {events.push("stop");break;}
            };
            match outcome {
                Outcome::Miss=>match handle_stuck_miss(&mut watchdog,now,used,limit,false,||{
                    events.push("reload");
                    Ok(())
                }).unwrap() {
                    StuckAction::Wait=>events.push("wait"),
                    StuckAction::RetryCast=>events.push("retry_scheduled"),
                    StuckAction::Reload=>break,
                    StuckAction::LimitReached=>{events.push("limit");break;},
                },
                Outcome::Catch|Outcome::Inferred|Outcome::Empty|Outcome::Trash|Outcome::Energy=>{
                    watchdog.progress(now);
                    events.push("progress");
                }
                Outcome::Unverified=>{events.push("stop");break;}
            }
        }
        events
    }

    #[test] fn watchdog_retries_once_then_reloads_on_that_retry_miss() {
        let outcomes=[Ok(Outcome::Miss),Ok(Outcome::Miss),Ok(Outcome::Miss),Ok(Outcome::Catch)];
        assert_eq!(drive_fake_watchdog(&[0,29,30,31],&outcomes,8),
            ["cast","wait","cast","wait","cast","retry_scheduled","cast","reload"]);
    }
    #[test] fn watchdog_never_reloads_or_casts_past_the_cast_limit() {
        let outcomes=[Ok(Outcome::Miss),Ok(Outcome::Miss),Ok(Outcome::Miss),Ok(Outcome::Miss)];
        assert_eq!(drive_fake_watchdog(&[0,30,31,32],&outcomes,3),
            ["cast","wait","cast","retry_scheduled","cast","limit"]);
        assert_eq!(drive_fake_watchdog(&[0,30],&outcomes,2),["cast","wait","cast","limit"]);
    }
    #[test] fn watchdog_success_energy_empty_and_uncertain_results_do_not_reload() {
        for result in [Outcome::Catch,Outcome::Energy,Outcome::Empty,Outcome::Unverified] {
            let outcomes=[Ok(Outcome::Miss),Ok(Outcome::Miss),Ok(result)];
            let events=drive_fake_watchdog(&[0,30,31],&outcomes,8);
            assert!(!events.contains(&"reload"),"unexpected reload after {result:?}: {events:?}");
            assert_eq!(events.iter().filter(|event|**event=="retry_scheduled").count(),1);
        }
        let interrupted=[Ok(Outcome::Miss),Ok(Outcome::Miss),Err("transport")];
        let events=drive_fake_watchdog(&[0,30,31],&interrupted,8);
        assert_eq!(events,["cast","wait","cast","retry_scheduled","cast","stop"]);
    }
    #[test] fn watchdog_reload_callback_runs_once_and_failure_stops_recovery() {
        let start=Instant::now();
        let mut watchdog=RodWatchdog::new(start);
        let mut reloads=0;
        assert_eq!(handle_stuck_miss(&mut watchdog,start,1,5,false,||{reloads+=1;Ok(())}).unwrap(),StuckAction::Wait);
        assert_eq!(handle_stuck_miss(&mut watchdog,start+STUCK_ROD_TIMEOUT,2,5,false,||{reloads+=1;Ok(())}).unwrap(),StuckAction::RetryCast);
        let error=handle_stuck_miss(&mut watchdog,start+STUCK_ROD_TIMEOUT+Duration::from_secs(1),3,5,false,||{
            reloads+=1;
            Err("fake reload failed".into())
        }).unwrap_err();
        assert!(error.to_string().contains("fake reload failed"));
        assert_eq!(reloads,1);
    }
    fn test_session()->Session {
        Session::new(Some(4),state::unix_now(),ResetMarker{year:2026,month:11,day:16,hour:19})
    }
    #[test] fn cancelled_cast_keeps_persisted_uncertainty_and_does_not_commit_or_recover() {
        let mut session=test_session();
        session.begin_action();
        session.cast_attempts=1;
        let persisted=vec![session.clone()]; // Last atomic snapshot written before the cast outcome.
        let mut counts=RunCounts::default();
        let mut followups=Vec::new();
        let disposition=finish_fish_result(Err(game::StoppedByCtrlC.into()),&mut session,&mut counts,true,
            state::unix_now(),|_|{followups.push("persist_after_result");Ok(())}).unwrap();
        assert_eq!(disposition,FishDisposition::StopUnresolved);
        assert_eq!(persisted.last().unwrap().next_action(),SessionAction::StopUncertain);
        assert!(session.action_uncertain);
        assert_eq!(session.cast_attempts,1);
        assert_eq!(session.casts,0);
        assert_eq!(counts,RunCounts::default());
        assert!(followups.is_empty());
    }
    #[test] fn stop_after_verified_catch_commits_once_before_outer_stop() {
        let mut session=test_session();
        session.begin_action();
        session.cast_attempts=1;
        let mut counts=RunCounts::default();
        let mut persisted=Vec::new();
        let disposition=finish_fish_result(Ok(Outcome::Catch),&mut session,&mut counts,true,state::unix_now(),|s|{
            persisted.push(s.clone());Ok(())
        }).unwrap();
        assert_eq!(disposition,FishDisposition::StopAfterCommit(Outcome::Catch));
        assert_eq!(persisted.len(),1);
        assert!(!persisted[0].action_uncertain);
        assert_eq!(persisted[0].casts,1);
        assert_eq!(persisted[0].cast_attempts,1);
        assert_eq!(counts.caught,1);
        let duplicate=finish_fish_result(Ok(Outcome::Catch),&mut session,&mut counts,true,state::unix_now(),|_|Ok(()));
        assert!(duplicate.is_err(),"same action outcome must not commit twice");
        assert_eq!(session.casts,1);
        assert_eq!(counts.caught,1);
    }
    #[test] fn stopped_empty_trash_and_miss_commit_without_scheduling_followup() {
        for outcome in [Outcome::Empty,Outcome::Trash,Outcome::Miss] {
            let mut session=test_session();
            session.begin_action();
            let mut counts=RunCounts::default();
            let disposition=finish_fish_result(Ok(outcome),&mut session,&mut counts,true,state::unix_now(),|_|Ok(())).unwrap();
            assert_eq!(disposition,FishDisposition::StopAfterCommit(outcome));
            assert!(!session.action_uncertain);
            assert_eq!(session.casts,1);
            if matches!(outcome,Outcome::Empty|Outcome::Trash) {
                assert!(session.depleted);
                assert_eq!(session.lake,Some(4));
                assert_eq!(session.pending_lake,Some(5));
            }
            if outcome==Outcome::Miss {assert_eq!(counts.misses,1);}
        }
    }
    #[test] fn cancelled_before_press_does_not_mark_uncertain_or_spend_a_cast() {
        let mut session=test_session();
        let mut counts=RunCounts::default();
        let disposition=finish_fish_result(Err(game::StoppedByCtrlC.into()),&mut session,&mut counts,true,state::unix_now(),|_|Ok(())).unwrap();
        assert_eq!(disposition,FishDisposition::StopUnresolved);
        assert!(!session.action_uncertain);
        assert_eq!(session.cast_attempts,0);
        assert_eq!(session.casts,0);
    }
    #[test] fn observed_stop_suppresses_transport_reconnect() {
        let transport=std::io::Error::new(std::io::ErrorKind::ConnectionReset,"connection reset");
        let cancelled=game::StoppedByCtrlC;
        assert!(reconnect_allowed(&transport,false,false));
        assert!(!reconnect_allowed(&transport,false,true));
        assert!(!reconnect_allowed(&cancelled,false,false));
        assert!(!reconnect_allowed(&transport,true,false));
    }

    #[derive(Clone,Copy,PartialEq,Eq)]
    enum CoordinatorScenario {
        PollStop, TransportStop, CatchStop, TransportWithoutStop,
        EmptyStop, TrashStop, MissAtLimit, RetryMissStop, RetryMissReload, RetryMissLimit,
    }
    struct PendingTravel {
        url:String,
        x:f64,
        y:f64,
        press_seen:bool,
    }
    struct CoordinatorBrowser {
        stop:Arc<AtomicBool>,
        scenario:CoordinatorScenario,
        cast_index:usize,
        cast_active:bool,
        cast_pressed:bool,
        strike_pressed:bool,
        outcome_reported:bool,
        clip_screenshots:usize,
        last_press:Option<&'static str>,
        last_press_position:Option<(f64,f64)>,
        events:Arc<Mutex<Vec<String>>>,
        flat_full:String,
        flat_clip:String,
        alert_clip:String,
        needs_travel:bool,
        travel_verified:bool,
        destination:Option<String>,
        pending_destination:Option<PendingTravel>,
    }
    impl CoordinatorBrowser {
        fn new(stop:Arc<AtomicBool>,scenario:CoordinatorScenario,events:Arc<Mutex<Vec<String>>>,needs_travel:bool)->Self {
            let water=vision::template("water").unwrap();
            let mut sum=[0u64;3];
            for pixel in water.pixels() {for channel in 0..3 {sum[channel]+=pixel[channel] as u64;}}
            let count=(water.width()*water.height()) as u64;
            let color=Rgb([((sum[0]+count/2)/count) as u8,((sum[1]+count/2)/count) as u8,((sum[2]+count/2)/count) as u8]);
            let full=RgbImage::from_pixel(800,600,color);
            let clip=RgbImage::from_pixel(240,240,color);
            let mut alert=clip.clone();
            let pattern=vision::template("alert").unwrap();
            alert.copy_from(&pattern,20,40).unwrap();
            Self{stop,scenario,cast_index:0,cast_active:false,cast_pressed:false,strike_pressed:false,
                outcome_reported:false,clip_screenshots:0,last_press:None,last_press_position:None,events,
                flat_full:encode_test_png(full),flat_clip:encode_test_png(clip),alert_clip:encode_test_png(alert),
                needs_travel,travel_verified:false,destination:None,pending_destination:None}
        }
        fn expected_outcome(&self)->Outcome {
            match self.scenario {
                CoordinatorScenario::CatchStop=>Outcome::Catch,
                CoordinatorScenario::EmptyStop=>Outcome::Empty,
                CoordinatorScenario::TrashStop=>Outcome::Trash,
                CoordinatorScenario::MissAtLimit|CoordinatorScenario::RetryMissStop
                    |CoordinatorScenario::RetryMissReload|CoordinatorScenario::RetryMissLimit=>Outcome::Miss,
                _=>Outcome::Miss,
            }
        }
        fn status_json(&mut self)->serde_json::Value {
            if self.pending_destination.is_some()&&self.destination.is_none() {
                self.events.lock().unwrap().push("TRAVEL:status_old_url:https://nomstead.com/qn".into());
            }
            let verified=self.cast_active && self.strike_pressed;
            let toast=if verified {
                if !self.outcome_reported {
                    self.events.lock().unwrap().push(format!("OUTCOME[{}]:{:?}",self.cast_index,self.expected_outcome()));
                }
                self.outcome_reported=true;
                match self.expected_outcome() {
                    Outcome::Catch=>"and i got a fish",
                    Outcome::Empty=>"nothing left",
                    Outcome::Trash=>"trash",
                    Outcome::Miss=>"missed",
                    _=>"",
                }
            } else {""};
            let sequence=if self.cast_active {(self.cast_index as u64)*2+if verified {1} else {0}} else {0};
            json!({"url":self.destination.as_deref().unwrap_or("https://nomstead.com/qn"),"width":800,"height":600,"dpr":1,
                "energy":70,"toast":toast,"sequence":sequence,"xp":null,"modal":false})
        }
        fn begin_cast(&mut self)->Result<()> {
            if self.cast_active && !self.outcome_reported {return Err("Fake began another cast before the prior outcome was observed".into());}
            self.cast_index+=1;
            self.cast_active=true;
            self.cast_pressed=false;
            self.strike_pressed=false;
            self.outcome_reported=false;
            self.clip_screenshots=0;
            self.events.lock().unwrap().push(format!("CAST[{}]:begin",self.cast_index));
            Ok(())
        }
    }
    impl Browser for CoordinatorBrowser {
        fn call(&mut self,method:&str,params:serde_json::Value)->Result<serde_json::Value> {
            let detail=params["type"].as_str().or_else(||params["expression"].as_str()
                .filter(|expression|expression.contains("Fast travel")||expression.contains("data-ui-tab=\"bookmarks\"")))
                .unwrap_or("");
            self.events.lock().unwrap().push(format!("{method}:{detail}"));
            match method {
                "Runtime.evaluate"=>{
                    let expression=params["expression"].as_str().unwrap_or("");
                    if expression.contains("^(codex)$")||expression.contains("data-ui-tab=\"bookmarks\"") {
                        return Ok(json!({"result":{"value":{"x":100,"y":100}}}));
                    }
                    if expression.contains("Fast travel") {
                        let url="https://nomstead.com/ho/4";
                        let (x,y)=(120.0,120.0);
                        self.pending_destination=Some(PendingTravel{url:url.into(),x,y,press_seen:false});
                        return Ok(json!({"result":{"value":{"x":x,"y":y,"url":url}}}));
                    }
                    Ok(json!({"result":{"value":self.status_json()}}))
                }
                "Page.captureScreenshot"=>{
                    if params.get("clip").is_none() {
                        if self.needs_travel && !self.travel_verified {
                            if self.destination.as_deref()!=Some("https://nomstead.com/ho/4")||self.pending_destination.is_some() {
                                return Err("Fake water verification refused before the destination changed".into());
                            }
                            self.travel_verified=true;
                            self.events.lock().unwrap().push("TRAVEL:verified_water".into());
                        } else {
                            self.begin_cast()?;
                        }
                        return Ok(json!({"data":self.flat_full}));
                    }
                    if !self.cast_active {return Err("Clip screenshot arrived outside a cast".into());}
                    self.clip_screenshots+=1;
                    if self.clip_screenshots==1 {return Ok(json!({"data":self.flat_clip}));}
                    match self.scenario {
                        CoordinatorScenario::PollStop=>{
                            self.stop.store(true,Ordering::Relaxed);
                            self.events.lock().unwrap().push("STOP:poll_screenshot".into());
                            Ok(json!({"data":self.flat_clip}))
                        }
                        CoordinatorScenario::TransportStop=>{
                            self.stop.store(true,Ordering::Relaxed);
                            self.events.lock().unwrap().push("STOP:transport_error".into());
                            Err(std::io::Error::new(std::io::ErrorKind::ConnectionReset,"connection reset").into())
                        }
                        CoordinatorScenario::TransportWithoutStop=>Err(std::io::Error::new(std::io::ErrorKind::ConnectionReset,"connection reset").into()),
                        _=>Ok(json!({"data":self.alert_clip})),
                    }
                }
                "Input.dispatchMouseEvent"=>{
                    if params["type"]=="mousePressed" {
                        let (kind,index)=if self.cast_active && !self.cast_pressed {
                            self.cast_pressed=true;("CAST",self.cast_index)
                        } else if self.cast_active && !self.strike_pressed {
                            self.strike_pressed=true;("STRIKE",self.cast_index)
                        } else {("UI",self.cast_index)};
                        if kind=="UI" {
                            let x=params["x"].as_f64().unwrap_or(f64::NAN);
                            let y=params["y"].as_f64().unwrap_or(f64::NAN);
                            if let Some(pending)=self.pending_destination.as_mut() {
                                if x==pending.x&&y==pending.y {
                                    pending.press_seen=true;
                                    self.events.lock().unwrap().push("TRAVEL:link_pressed".into());
                                }
                            }
                        }
                        self.last_press=Some(kind);
                        self.last_press_position=Some((params["x"].as_f64().unwrap_or(f64::NAN),params["y"].as_f64().unwrap_or(f64::NAN)));
                        self.events.lock().unwrap().push(format!("{kind}[{index}]:mousePressed"));
                    } else if params["type"]=="mouseReleased" {
                        let kind=self.last_press.take().unwrap_or("UI");
                        let press_position=self.last_press_position.take();
                        self.events.lock().unwrap().push(format!("{kind}[{}]:mouseReleased",self.cast_index));
                        let x=params["x"].as_f64().unwrap_or(f64::NAN);
                        let y=params["y"].as_f64().unwrap_or(f64::NAN);
                        let matches_pending=self.pending_destination.as_ref().is_some_and(|pending|
                            pending.press_seen&&x==pending.x&&y==pending.y&&press_position==Some((x,y)));
                        if matches_pending&&kind=="UI" {
                            let old_url=self.destination.as_deref().unwrap_or("https://nomstead.com/qn");
                            if old_url!="https://nomstead.com/qn" {return Err("Travel fake received a second destination before verification".into());}
                            self.events.lock().unwrap().push(format!("TRAVEL:old_url_before_release:{old_url}"));
                            let pending=self.pending_destination.take().unwrap();
                            self.destination=Some(pending.url);
                            self.events.lock().unwrap().push("TRAVEL:link_released".into());
                        } else if let Some(pending)=self.pending_destination.as_mut() {
                            pending.press_seen=false;
                        }
                    }
                    Ok(json!({}))
                }
                "Page.reload"=>Err("intentional test reload reached".into()),
                _=>Ok(json!({})),
            }
        }
        fn fast_forward_pauses(&self)->bool {
            let stop_after=self.outcome_reported&&match self.scenario {
                CoordinatorScenario::CatchStop|CoordinatorScenario::EmptyStop|CoordinatorScenario::TrashStop=>self.cast_index==1,
                CoordinatorScenario::RetryMissStop=>self.cast_index==2,
                _=>false,
            };
            if stop_after {
                self.stop.store(true,Ordering::Relaxed);
                self.events.lock().unwrap().push(format!("STOP:verified_outcome_cast_{}",self.cast_index));
            }
            true
        }
    }
    fn encode_test_png(image:RgbImage)->String {
        let mut bytes=Cursor::new(Vec::new());
        DynamicImage::ImageRgb8(image).write_to(&mut bytes,ImageOutputFormat::Png).unwrap();
        base64::engine::general_purpose::STANDARD.encode(bytes.into_inner())
    }
    struct TempSession { directory:std::path::PathBuf, path:std::path::PathBuf }
    impl TempSession {
        fn new()->Self { Self::with_lake(None) }
        fn with_lake(lake:Option<u32>)->Self {
            static NEXT:AtomicU64=AtomicU64::new(0);
            let directory=std::env::temp_dir().join(format!("nomstead-coordinator-{}-{}",std::process::id(),NEXT.fetch_add(1,Ordering::Relaxed)));
            fs::create_dir(&directory).unwrap();
            let path=directory.join("session.json");
            let marker=state::local_now().latest_reset();
            state::write_atomic(&path,&Session::new(lake,state::unix_now(),marker)).unwrap();
            Self{directory,path}
        }
        fn read(&self)->Session { state::read(&self.path).unwrap().unwrap() }
    }
    impl Drop for TempSession {
        fn drop(&mut self) {let _=fs::remove_dir_all(&self.directory);}
    }
    fn assert_action_counts(browser_events:&[String],casts:usize,strikes:usize) {
        assert_eq!(browser_events.iter().filter(|event|event.starts_with("CAST[")&&event.ends_with(":mousePressed")).count(),casts);
        assert_eq!(browser_events.iter().filter(|event|event.starts_with("STRIKE[")&&event.ends_with(":mousePressed")).count(),strikes);
        assert_eq!(browser_events.iter().filter(|event|event.starts_with("CAST[")&&event.ends_with(":mouseReleased")).count(),casts);
        assert_eq!(browser_events.iter().filter(|event|event.starts_with("STRIKE[")&&event.ends_with(":mouseReleased")).count(),strikes);
    }
    fn assert_no_follow_up_events(browser_events:&[String],expected_casts:usize,expected_strikes:usize) {
        assert_action_counts(browser_events,expected_casts,expected_strikes);
        assert!(!browser_events.iter().any(|event|event.starts_with("Page.reload:")));
        assert!(!browser_events.iter().any(|event|event.contains("Fast travel")||event.contains("data-ui-tab=\"bookmarks\"")));
    }
    fn assert_verified_outcomes(browser_events:&[String],outcomes:&[Outcome]) {
        for (index,outcome) in outcomes.iter().enumerate() {
            let cast=index+1;
            let position=|expected:&str|browser_events.iter().position(|event|event==expected)
                .unwrap_or_else(||panic!("missing event {expected}: {browser_events:?}"));
            let cast_press=position(&format!("CAST[{cast}]:mousePressed"));
            let cast_release=position(&format!("CAST[{cast}]:mouseReleased"));
            let strike_press=position(&format!("STRIKE[{cast}]:mousePressed"));
            let strike_release=position(&format!("STRIKE[{cast}]:mouseReleased"));
            let verified=position(&format!("OUTCOME[{cast}]:{outcome:?}"));
            assert!(cast_press<cast_release&&cast_release<strike_press&&strike_press<strike_release&&strike_release<verified,
                "cast/strike/outcome events were out of order for cast {cast}: {browser_events:?}");
        }
    }
    fn assert_no_action_after_observed_stop(browser_events:&[String]) {
        let stop_index=browser_events.iter().position(|event|event.starts_with("STOP:")).expect("stop marker");
        assert!(!browser_events[stop_index+1..].iter().any(|event|
            event.starts_with("Input.dispatchMouseEvent:mousePressed")||event.starts_with("Page.reload:")
                ||event.starts_with("UI[")&&event.ends_with(":mousePressed")
                ||event.contains("Fast travel")||event.contains("data-ui-tab=\"bookmarks\"")));
    }
    fn assert_verified_travel_order(browser_events:&[String]) {
        let position=|expected:&str|browser_events.iter().position(|event|event==expected)
            .unwrap_or_else(||panic!("missing travel event {expected}: {browser_events:?}"));
        let selector=browser_events.iter().position(|event|event.starts_with("Runtime.evaluate:")&&event.contains("Fast travel"))
            .expect("Fast travel selector evaluation");
        let old_status=position("TRAVEL:status_old_url:https://nomstead.com/qn");
        let press=position("TRAVEL:link_pressed");
        let old_before_release=position("TRAVEL:old_url_before_release:https://nomstead.com/qn");
        let release=position("TRAVEL:link_released");
        let water=position("TRAVEL:verified_water");
        let cast=position("CAST[1]:begin");
        let stop=browser_events.iter().position(|event|event.starts_with("STOP:")).expect("stop marker");
        assert!(selector<old_status&&old_status<press&&press<old_before_release&&old_before_release<release
            &&release<water&&water<cast&&cast<stop,"travel/cast/stop events out of order: {browser_events:?}");
    }
    fn watchdog_clock(offsets:&[u64],calls:Arc<AtomicUsize>)->impl FnMut()->Instant {
        let started=Instant::now();
        let mut offsets=offsets.to_vec().into_iter();
        move||{
            calls.fetch_add(1,Ordering::Relaxed);
            started+Duration::from_secs(offsets.next().unwrap_or_default())
        }
    }
    #[test] fn coordinator_stop_before_outcome_keeps_real_saved_action_uncertain_and_stops_actions() {
        let file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::PollStop,events.clone(),false));
        let mut reconnects=0;
        let result=coordinate(browser,stop,RunCommand::Run{casts:4,lake:None},&file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        });
        assert!(result.is_ok());
        let saved=file.read();
        assert!(saved.action_uncertain);
        assert_eq!(saved.cast_attempts,1);
        assert_eq!(saved.casts,0);
        assert_eq!(saved.next_action(),SessionAction::StopUncertain);
        assert_eq!(reconnects,0);
        let events=events.lock().unwrap();
        assert_no_follow_up_events(&events,1,0);
        assert_no_action_after_observed_stop(&events);
        assert_eq!(events.iter().filter(|event|event.starts_with("Input.dispatchMouseEvent:mouseReleased")).count(),1);
    }
    #[test] fn coordinator_commits_verified_catch_once_then_stops_without_follow_up() {
        let file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::CatchStop,events.clone(),false));
        let mut reconnects=0;
        let result=coordinate(browser,stop,RunCommand::Run{casts:4,lake:None},&file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        });
        assert!(result.is_ok());
        let saved=file.read();
        assert!(!saved.action_uncertain);
        assert_eq!(saved.cast_attempts,1);
        assert_eq!(saved.casts,1);
        assert_eq!(saved.next_action(),SessionAction::Cast(None));
        assert_eq!(reconnects,0);
        let events=events.lock().unwrap();
        assert_no_follow_up_events(&events,1,1);
        assert_no_action_after_observed_stop(&events);
        assert_eq!(events.iter().filter(|event|event.starts_with("Input.dispatchMouseEvent:mouseReleased")).count(),2);
    }
    #[test] fn coordinator_stop_with_transport_error_skips_reconnect_but_unstopped_error_reconnects_once() {
        let stopped_file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::TransportStop,events.clone(),false));
        let mut reconnects=0;
        let result=coordinate(browser,stop,RunCommand::Run{casts:3,lake:None},&stopped_file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        });
        assert!(result.is_ok());
        let saved=stopped_file.read();
        assert!(saved.action_uncertain);
        assert_eq!(saved.cast_attempts,1);
        assert_eq!(saved.casts,0);
        assert_eq!(reconnects,0);
        let events=events.lock().unwrap();
        assert_no_follow_up_events(&events,1,0);
        assert_no_action_after_observed_stop(&events);
        assert_eq!(events.iter().filter(|event|event.starts_with("Input.dispatchMouseEvent:mouseReleased")).count(),1);

        let retry_file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::TransportWithoutStop,events.clone(),false));
        let mut reconnects=0;
        let result=coordinate(browser,stop,RunCommand::Run{casts:3,lake:None},&retry_file.path,|_|{
            reconnects+=1;Ok("https://nomstead.com/qn".into())
        });
        assert!(result.is_err());
        assert!(retry_file.read().action_uncertain);
        assert_eq!(reconnects,1);
    }
    #[test] fn coordinator_empty_and_trash_stop_commit_real_depletion_without_travel_after_stop() {
        for (scenario,outcome) in [(CoordinatorScenario::EmptyStop,Outcome::Empty),(CoordinatorScenario::TrashStop,Outcome::Trash)] {
            let file=TempSession::with_lake(Some(4));
            let stop=Arc::new(AtomicBool::new(false));
            let events=Arc::new(Mutex::new(Vec::new()));
            let browser=Box::new(CoordinatorBrowser::new(stop.clone(),scenario,events.clone(),true));
            let mut reconnects=0;
            let result=coordinate(browser,stop,RunCommand::Run{casts:4,lake:None},&file.path,|_|{
                reconnects+=1;Ok("unexpected reconnect".into())
            });
            assert!(result.is_ok());
            let saved=file.read();
            assert!(!saved.action_uncertain);
            assert_eq!(saved.cast_attempts,1);
            assert_eq!(saved.casts,1);
            assert!(saved.depleted);
            assert_eq!(saved.lake,Some(4));
            assert_eq!(saved.pending_lake,Some(5));
            assert!(!saved.waiting_reset);
            assert_eq!(saved.next_action(),SessionAction::Travel(5));
            assert_eq!(reconnects,0);
            let events=events.lock().unwrap();
            assert_verified_outcomes(&events,&[outcome]);
            assert_action_counts(&events,1,1);
            let stop_index=events.iter().position(|event|event.starts_with("STOP:")).expect("verified stop marker");
            assert_verified_travel_order(&events);
            assert!(events[..stop_index].iter().any(|event|event.contains("Fast travel")));
            assert_eq!(events[..stop_index].iter().filter(|event|event.starts_with("UI[")&&event.ends_with(":mousePressed")).count(),3);
            assert_no_action_after_observed_stop(&events);
        }
    }
    #[test] fn coordinator_fake_travel_requires_selector_press_and_matching_release_coordinates() {
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let mut browser=CoordinatorBrowser::new(stop,CoordinatorScenario::EmptyStop,events.clone(),true);
        let selector=browser.call("Runtime.evaluate",json!({"expression":"Fast travel selector"})).unwrap();
        assert_eq!(selector["result"]["value"]["url"],"https://nomstead.com/ho/4");
        let status=browser.call("Runtime.evaluate",json!({"expression":game::STATUS})).unwrap();
        assert_eq!(status["result"]["value"]["url"],"https://nomstead.com/qn");
        for kind in ["mousePressed","mouseReleased"] {
            browser.call("Input.dispatchMouseEvent",json!({"type":kind,"x":119.0,"y":120.0,
                "button":"left","buttons":if kind=="mousePressed" {1} else {0},"clickCount":1})).unwrap();
        }
        let status=browser.call("Runtime.evaluate",json!({"expression":game::STATUS})).unwrap();
        assert_eq!(status["result"]["value"]["url"],"https://nomstead.com/qn");
        browser.call("Input.dispatchMouseEvent",json!({"type":"mousePressed","x":120.0,"y":120.0,
            "button":"left","buttons":1,"clickCount":1})).unwrap();
        let status=browser.call("Runtime.evaluate",json!({"expression":game::STATUS})).unwrap();
        assert_eq!(status["result"]["value"]["url"],"https://nomstead.com/qn");
        browser.call("Input.dispatchMouseEvent",json!({"type":"mouseReleased","x":120.0,"y":121.0,
            "button":"left","buttons":0,"clickCount":1})).unwrap();
        let status=browser.call("Runtime.evaluate",json!({"expression":game::STATUS})).unwrap();
        assert_eq!(status["result"]["value"]["url"],"https://nomstead.com/qn");
        assert!(browser.destination.is_none());
        assert!(browser.call("Page.captureScreenshot",json!({"format":"jpeg"})).is_err());
        assert!(!browser.travel_verified);
        let events=events.lock().unwrap();
        assert_eq!(events.iter().filter(|event|event.as_str()=="TRAVEL:link_pressed").count(),1);
        assert!(!events.iter().any(|event|event=="TRAVEL:link_released"||event=="TRAVEL:verified_water"));
    }
    #[test] fn coordinator_verified_miss_at_cast_limit_does_not_reload() {
        let file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::MissAtLimit,events.clone(),false));
        let clock_calls=Arc::new(AtomicUsize::new(0));
        let clock=watchdog_clock(&[0,30],clock_calls.clone());
        let mut reconnects=0;
        let result=coordinate_with_watchdog_clock(browser,stop,RunCommand::Run{casts:1,lake:None},&file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        },clock);
        assert!(result.is_ok());
        let saved=file.read();
        assert!(!saved.action_uncertain);
        assert_eq!(saved.cast_attempts,1);
        assert_eq!(saved.casts,1);
        assert!(!saved.depleted);
        assert_eq!(reconnects,0);
        assert_eq!(clock_calls.load(Ordering::Relaxed),2);
        let events=events.lock().unwrap();
        assert_verified_outcomes(&events,&[Outcome::Miss]);
        assert_no_follow_up_events(&events,1,1);
    }
    #[test] fn coordinator_stops_after_retry_miss_and_reload_counterexample_proves_retry_path() {
        let stopped_file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::RetryMissStop,events.clone(),false));
        let stop_clock_calls=Arc::new(AtomicUsize::new(0));
        let clock=watchdog_clock(&[0,30],stop_clock_calls.clone());
        let mut reconnects=0;
        let result=coordinate_with_watchdog_clock(browser,stop,RunCommand::Run{casts:4,lake:None},&stopped_file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        },clock);
        assert!(result.is_ok());
        let saved=stopped_file.read();
        assert!(!saved.action_uncertain);
        assert_eq!(saved.cast_attempts,2);
        assert_eq!(saved.casts,2);
        assert_eq!(reconnects,0);
        assert_eq!(stop_clock_calls.load(Ordering::Relaxed),2,"watchdog initialization and first overdue Miss must schedule the retry");
        let events=events.lock().unwrap();
        assert_verified_outcomes(&events,&[Outcome::Miss,Outcome::Miss]);
        assert_action_counts(&events,2,2);
        assert_no_action_after_observed_stop(&events);
        assert!(!events.iter().any(|event|event.starts_with("Page.reload:")));

        let reload_file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::RetryMissReload,events.clone(),false));
        let mut reconnects=0;
        let result=coordinate_with_watchdog_clock(browser,stop,RunCommand::Run{casts:4,lake:None},&reload_file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        },watchdog_clock(&[0,30,31],Arc::new(AtomicUsize::new(0))));
        assert!(result.is_err(),"the fake reload should stop the coordinator after recording the call");
        let saved=reload_file.read();
        assert!(!saved.action_uncertain);
        assert_eq!(saved.cast_attempts,2);
        assert_eq!(saved.casts,2);
        assert_eq!(reconnects,0);
        let events=events.lock().unwrap();
        assert_verified_outcomes(&events,&[Outcome::Miss,Outcome::Miss]);
        assert_action_counts(&events,2,2);
        assert_eq!(events.iter().filter(|event|event.starts_with("Page.reload:")).count(),1);

        let limit_file=TempSession::new();
        let stop=Arc::new(AtomicBool::new(false));
        let events=Arc::new(Mutex::new(Vec::new()));
        let browser=Box::new(CoordinatorBrowser::new(stop.clone(),CoordinatorScenario::RetryMissLimit,events.clone(),false));
        let mut reconnects=0;
        let result=coordinate_with_watchdog_clock(browser,stop,RunCommand::Run{casts:2,lake:None},&limit_file.path,|_|{
            reconnects+=1;Ok("unexpected reconnect".into())
        },watchdog_clock(&[0,30,31],Arc::new(AtomicUsize::new(0))));
        assert!(result.is_ok());
        let saved=limit_file.read();
        assert!(!saved.action_uncertain);
        assert_eq!(saved.cast_attempts,2);
        assert_eq!(saved.casts,2);
        assert_eq!(reconnects,0);
        let events=events.lock().unwrap();
        assert_verified_outcomes(&events,&[Outcome::Miss,Outcome::Miss]);
        assert_no_follow_up_events(&events,2,2);
    }
    #[test] fn game_origin_must_be_exact() {
        assert!(cdp::trusted_game_url("https://nomstead.com/qn"));
        for s in ["http://nomstead.com","https://nomstead.com.evil.test","https://nomstead.com@evil.test","https://evil.test/?nomstead.com"] {
            assert!(!cdp::trusted_game_url(s));
        }
    }
    #[test] fn failed_press_still_releases() {
        struct F{calls:Vec<String>}
        impl Browser for F {
            fn call(&mut self,m:&str,p:serde_json::Value)->Result<serde_json::Value> {
                if m=="Runtime.evaluate" {return Ok(json!({"result":{"value":status("",0)}}));}
                self.calls.push(p["type"].as_str().unwrap().into());
                if p["type"]=="mousePressed" {return Err("press failed".into());}
                Ok(json!({}))
            }
        }
        let mut f=F{calls:vec![]};
        {let mut g=Game{browser:&mut f,stop:Arc::new(AtomicBool::new(false))};assert!(g.click(10.0,10.0).is_err());}
        assert_eq!(f.calls,vec!["mousePressed","mouseReleased"]);
    }
}
