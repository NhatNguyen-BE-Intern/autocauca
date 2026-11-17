use serde::{Deserialize,Serialize};
use std::{error::Error,fs,io,io::Write,path::Path,time::{SystemTime,UNIX_EPOCH}};

pub const SESSION_VERSION:u32=1;
pub const SESSION_MAX_AGE_SECS:u64=7200;
const RESET_HOURS:[u8;8]=[1,4,7,10,13,16,19,22];

#[derive(Debug,Clone,Copy,Serialize,Deserialize,PartialEq,Eq,PartialOrd,Ord)]
pub struct ResetMarker { pub year:i32, pub month:u8, pub day:u8, pub hour:u8 }
impl ResetMarker {
    fn valid(self)->bool {
        let days=match self.month {
            1|3|5|7|8|10|12=>31,
            4|6|9|11=>30,
            2 if self.year%400==0 || self.year%4==0 && self.year%100!=0=>29,
            2=>28,
            _=>return false,
        };
        self.day>=1 && self.day<=days && RESET_HOURS.contains(&self.hour)
    }
}

#[derive(Debug,Clone,Copy,PartialEq,Eq)]
pub struct LocalDateTime { pub year:i32, pub month:u8, pub day:u8, pub hour:u8, pub minute:u8, pub second:u8 }
impl LocalDateTime {
    pub fn add_days(self,days:i64)->Self {
        let (year,month,day)=civil_from_days(days_from_civil(self.year,self.month,self.day)+days);
        Self{year,month,day,..self}
    }
    pub fn latest_reset(self)->ResetMarker {
        let seconds=self.minute as u16*60+self.second as u16;
        if let Some(hour)=RESET_HOURS.iter().rev().find(|&&hour|hour<self.hour || (hour==self.hour && seconds>=15)) {
            ResetMarker{year:self.year,month:self.month,day:self.day,hour:*hour}
        } else {
            let previous=self.add_days(-1);
            ResetMarker{year:previous.year,month:previous.month,day:previous.day,hour:22}
        }
    }
    pub fn next_reset(self)->ResetMarker {
        let seconds=self.minute as u16*60+self.second as u16;
        if let Some(hour)=RESET_HOURS.iter().find(|&&hour|hour>self.hour || (hour==self.hour && seconds<15)) {
            ResetMarker{year:self.year,month:self.month,day:self.day,hour:*hour}
        } else {
            let next=self.add_days(1);
            ResetMarker{year:next.year,month:next.month,day:next.day,hour:1}
        }
    }
}

#[derive(Debug,Clone,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct Session {
    pub version:u32,
    pub saved_at_unix_secs:u64,
    pub reset_marker:ResetMarker,
    pub lake:Option<u32>,
    pub depleted:bool,
    pub pending_lake:Option<u32>,
    pub waiting_reset:bool,
    pub action_uncertain:bool,
    #[serde(default)]
    pub cast_attempts:u64,
    #[serde(default)]
    pub casts:u64,
}
#[derive(Debug,Clone,Copy,PartialEq,Eq)]
pub enum SessionAction { Cast(Option<u32>), Travel(u32), WaitReset, StopUnknown, StopUncertain }
impl Session {
    pub fn new(lake:Option<u32>,saved_at_unix_secs:u64,reset_marker:ResetMarker)->Self {
        Self{version:SESSION_VERSION,saved_at_unix_secs,reset_marker,lake,depleted:false,
            pending_lake:None,waiting_reset:false,action_uncertain:false,cast_attempts:0,casts:0}
    }
    pub fn validate(&self,now_unix_secs:u64,current_reset:ResetMarker)->io::Result<bool> {
        let invalid=||io::Error::new(io::ErrorKind::InvalidData,"invalid Rust session state");
        if self.version!=SESSION_VERSION || !self.reset_marker.valid() || self.lake.map(|n|!(1..=40).contains(&n)).unwrap_or(false)
            || self.pending_lake.map(|n|!(1..=40).contains(&n)).unwrap_or(false)
            || self.waiting_reset && (self.lake!=Some(40) || !self.depleted || self.pending_lake.is_some())
            || self.pending_lake.is_some() && (!self.depleted || self.waiting_reset)
            || self.depleted && self.pending_lake.is_none() && !self.waiting_reset && self.lake.is_some_and(|n|n<40) {
            return Err(invalid());
        }
        if self.depleted && self.lake==Some(40) && self.pending_lake.is_none() && !self.waiting_reset {return Err(invalid());}
        if self.saved_at_unix_secs>now_unix_secs {
            return Err(io::Error::new(io::ErrorKind::InvalidData,"session timestamp is in the future"));
        }
        if now_unix_secs-self.saved_at_unix_secs>SESSION_MAX_AGE_SECS {
            return Err(io::Error::new(io::ErrorKind::InvalidData,"session is older than two hours"));
        }
        if current_reset<self.reset_marker {
            return Err(io::Error::new(io::ErrorKind::InvalidData,"local reset clock moved behind saved session"));
        }
        Ok(current_reset>self.reset_marker)
    }
    pub fn mark_depleted(&mut self) {
        self.depleted=true;
        self.pending_lake=self.lake.and_then(|lake|(lake<40).then_some(lake+1));
        self.waiting_reset=self.lake==Some(40);
        self.action_uncertain=false;
    }
    pub fn begin_action(&mut self) { self.action_uncertain=true; }
    pub fn finish_action(&mut self) { self.action_uncertain=false; }
    pub fn begin_travel(&mut self,lake:u32,saved_at_unix_secs:u64,reset_marker:ResetMarker)->io::Result<()> {
        if !(1..=40).contains(&lake) {return Err(io::Error::new(io::ErrorKind::InvalidInput,"travel target outside HO 1..40"));}
        self.depleted=true;
        self.pending_lake=Some(lake);
        self.waiting_reset=false;
        self.saved_at_unix_secs=saved_at_unix_secs;
        self.reset_marker=reset_marker;
        Ok(())
    }
    pub fn begin_new_cycle(&mut self,saved_at_unix_secs:u64,reset_marker:ResetMarker)->io::Result<()> {
        self.begin_travel(1,saved_at_unix_secs,reset_marker)
    }
    pub fn next_action(&self)->SessionAction {
        if self.action_uncertain {return SessionAction::StopUncertain;}
        if self.waiting_reset {return SessionAction::WaitReset;}
        if let Some(target)=self.pending_lake {return SessionAction::Travel(target);}
        if self.depleted {return SessionAction::StopUnknown;}
        SessionAction::Cast(self.lake)
    }
    pub fn complete_travel(&mut self,lake:u32,saved_at_unix_secs:u64,reset_marker:ResetMarker)->io::Result<()> {
        if !(1..=40).contains(&lake) || self.pending_lake.is_some_and(|target|target!=lake) {
            return Err(io::Error::new(io::ErrorKind::InvalidInput,"travel target does not match saved pending lake"));
        }
        self.lake=Some(lake);
        self.depleted=false;
        self.pending_lake=None;
        self.waiting_reset=false;
        self.action_uncertain=false;
        self.saved_at_unix_secs=saved_at_unix_secs;
        self.reset_marker=reset_marker;
        Ok(())
    }
}

pub fn unix_now()->u64 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() }

#[cfg(windows)]
pub fn local_now()->LocalDateTime {
    #[repr(C)] struct WinSystemTime { year:u16,month:u16,weekday:u16,day:u16,hour:u16,minute:u16,second:u16,millis:u16 }
    #[link(name="kernel32")] extern "system" { fn GetLocalTime(value:*mut WinSystemTime); }
    let mut value=WinSystemTime{year:0,month:0,weekday:0,day:0,hour:0,minute:0,second:0,millis:0};
    unsafe {GetLocalTime(&mut value);}
    LocalDateTime{year:value.year as i32,month:value.month as u8,day:value.day as u8,
        hour:value.hour as u8,minute:value.minute as u8,second:value.second as u8}
}

#[cfg(not(windows))]
pub fn local_now()->LocalDateTime {
    let seconds=SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
    let (year,month,day)=civil_from_days((seconds/86400) as i64);
    let daytime=seconds%86400;
    LocalDateTime{year,month,day,hour:(daytime/3600) as u8,minute:((daytime%3600)/60) as u8,second:(daytime%60) as u8}
}

fn days_from_civil(year:i32,month:u8,day:u8)->i64 {
    let mut y=year as i64;
    let m=month as i64;
    y-=if m<=2 {1} else {0};
    let era=(if y>=0 {y} else {y-399})/400;
    let year_of_era=y-era*400;
    let month_prime=m+if m>2 {-3} else {9};
    let day_of_year=(153*month_prime+2)/5+day as i64-1;
    let day_of_era=year_of_era*365+year_of_era/4-year_of_era/100+day_of_year;
    era*146097+day_of_era-719468
}
fn civil_from_days(days:i64)->(i32,u8,u8) {
    let z=days+719468;
    let era=(if z>=0 {z} else {z-146096})/146097;
    let day_of_era=z-era*146097;
    let year_of_era=(day_of_era-day_of_era/1460+day_of_era/36524-day_of_era/146096)/365;
    let mut year=year_of_era+era*400;
    let day_of_year=day_of_era-(365*year_of_era+year_of_era/4-year_of_era/100);
    let month_prime=(5*day_of_year+2)/153;
    let day=day_of_year-(153*month_prime+2)/5+1;
    let month=month_prime+if month_prime<10 {3} else {-9};
    year+=if month<=2 {1} else {0};
    (year as i32,month as u8,day as u8)
}

pub fn read(path:&Path)->io::Result<Option<Session>> {
    match fs::read(path) {
        Ok(bytes)=>serde_json::from_slice(&bytes).map(Some).map_err(|e|io::Error::new(io::ErrorKind::InvalidData,e)),
        Err(error) if error.kind()==io::ErrorKind::NotFound=>Ok(None),
        Err(error)=>Err(error),
    }
}
pub fn write_atomic(path:&Path,session:&Session)->Result<(),Box<dyn Error>> {
    let temp=path.with_extension("tmp");
    let mut file=fs::File::create(&temp)?;
    file.write_all(&serde_json::to_vec(session)?)?;
    file.sync_all()?;
    drop(file);
    atomic_replace(&temp,path)?;
    Ok(())
}
#[cfg(not(windows))]
fn atomic_replace(source:&Path,target:&Path)->io::Result<()> { fs::rename(source,target) }
#[cfg(windows)]
fn atomic_replace(source:&Path,target:&Path)->io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name="kernel32")] extern "system" { fn MoveFileExW(from:*const u16,to:*const u16,flags:u32)->i32; }
    let from:Vec<u16>=source.as_os_str().encode_wide().chain(Some(0)).collect();
    let to:Vec<u16>=target.as_os_str().encode_wide().chain(Some(0)).collect();
    if unsafe {MoveFileExW(from.as_ptr(),to.as_ptr(),1|8)}==0 {return Err(io::Error::last_os_error());}
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dt(year:i32,month:u8,day:u8,hour:u8,minute:u8,second:u8)->LocalDateTime {
        LocalDateTime{year,month,day,hour,minute,second}
    }
    #[test] fn reset_schedule_uses_local_date_and_second_fifteen() {
        assert_eq!(dt(2026,11,16,1,0,14).next_reset(),ResetMarker{year:2026,month:11,day:16,hour:1});
        assert_eq!(dt(2026,11,16,1,0,15).latest_reset(),ResetMarker{year:2026,month:11,day:16,hour:1});
        assert_eq!(dt(2026,11,16,22,0,16).next_reset(),ResetMarker{year:2026,month:11,day:17,hour:1});
        assert_eq!(dt(2026,1,1,0,0,0).latest_reset(),ResetMarker{year:2025,month:12,day:31,hour:22});
        assert_eq!(dt(2024,2,28,23,0,0).add_days(1),dt(2024,2,29,23,0,0));
    }
    #[test] fn session_rejects_bad_age_and_future_and_reports_reset_crossing() {
        let marker=ResetMarker{year:2026,month:11,day:16,hour:19};
        let mut session=Session::new(Some(12),1000,marker);
        assert_eq!(session.validate(8200,marker).unwrap(),false);
        assert_eq!(session.validate(8201,marker).unwrap_err().kind(),io::ErrorKind::InvalidData);
        assert_eq!(session.validate(999,marker).unwrap_err().kind(),io::ErrorKind::InvalidData);
        let next=ResetMarker{hour:22,..marker};
        assert!(session.validate(1001,next).unwrap());
    }
    #[test] fn depletion_state_blocks_cast_until_exact_travel_or_reset() {
        let marker=ResetMarker{year:2026,month:11,day:16,hour:19};
        let mut session=Session::new(Some(39),1000,marker);
        session.mark_depleted();
        assert!(session.depleted);
        assert_eq!(session.pending_lake,Some(40));
        assert!(session.complete_travel(39,1001,marker).is_err());
        session.complete_travel(40,1001,marker).unwrap();
        assert_eq!(session.lake,Some(40));
        session.mark_depleted();
        assert!(session.waiting_reset);
        assert_eq!(session.pending_lake,None);
        assert_eq!(session.next_action(),SessionAction::WaitReset);
    }
    #[test] fn saved_state_never_casts_while_travel_or_action_is_uncertain() {
        let marker=ResetMarker{year:2026,month:11,day:16,hour:19};
        let mut session=Session::new(Some(7),1000,marker);
        assert_eq!(session.next_action(),SessionAction::Cast(Some(7)));
        session.begin_action();
        assert_eq!(session.next_action(),SessionAction::StopUncertain);
        session.finish_action();
        session.begin_travel(8,1001,marker).unwrap();
        assert_eq!(session.next_action(),SessionAction::Travel(8));
    }
    #[test] fn atomic_session_round_trips_and_rejects_legacy_json() {
        let path=std::env::temp_dir().join(format!("nomstead-session-{}.json",unix_now()));
        let marker=ResetMarker{year:2026,month:11,day:16,hour:19};
        let session=Session::new(Some(4),unix_now(),marker);
        write_atomic(&path,&session).unwrap();
        assert_eq!(read(&path).unwrap(),Some(session));
        fs::write(&path,b"{\"lake\":4}").unwrap();
        assert_eq!(read(&path).unwrap_err().kind(),io::ErrorKind::InvalidData);
        let _=fs::remove_file(&path);
    }
    #[test] fn interrupted_cast_attempt_persists_separately_from_completed_outcomes() {
        let path=std::env::temp_dir().join(format!("nomstead-session-attempt-{}.json",unix_now()));
        let marker=ResetMarker{year:2026,month:11,day:16,hour:19};
        let mut session=Session::new(Some(4),unix_now(),marker);
        session.begin_action();
        session.cast_attempts=1;
        write_atomic(&path,&session).unwrap();
        let loaded=read(&path).unwrap().unwrap();
        assert!(loaded.action_uncertain);
        assert_eq!(loaded.cast_attempts,1);
        assert_eq!(loaded.casts,0);
        let _=fs::remove_file(path);
    }
}
