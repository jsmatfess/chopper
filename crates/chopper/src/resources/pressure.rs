//! Boundary-triggered admission changes. Charged capacity is not resident RAM.
use super::host::Observation;
use std::time::{Duration, Instant};

const INTERVAL: Duration = Duration::from_secs(1);

pub(super) struct Pressure {
    pub limit: u64,
    pub baseline: u64,
    pub observation: Observation,
    pub rechecks: u64,
    checked: Instant,
    observe: Box<dyn Fn() -> Observation + Send + Sync>,
}

impl std::fmt::Debug for Pressure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Pressure")
            .field("limit", &self.limit)
            .field("baseline", &self.baseline)
            .field("observation", &self.observation)
            .field("rechecks", &self.rechecks)
            .finish_non_exhaustive()
    }
}
impl Pressure {
    #[cfg(any(target_os = "linux", test))]
    pub fn new(
        limit: u64,
        observation: Observation,
        observe: impl Fn() -> Observation + Send + Sync + 'static,
    ) -> Self {
        Self {
            limit,
            baseline: 0,
            observation,
            rechecks: 0,
            checked: Instant::now(),
            observe: Box::new(observe),
        }
    }
    pub fn refresh(&mut self, maximum: u64, used: impl Fn() -> u64, now: Instant) {
        if now.saturating_duration_since(self.checked) < INTERVAL {
            return;
        }
        // The caller serializes grants across observation. Releases may still
        // reduce used; using the later value cannot add those released promises
        // to an observation made before release. No live ownership is revoked.
        let observation = (self.observe)();
        let baseline = used();
        let additional = observation
            .headroom_bytes
            .map(|n| n / 2)
            .unwrap_or(128 * 1024 * 1024);
        let proposed = maximum.min(baseline.saturating_add(additional));
        // Losing discovery must not justify restoring a previously reduced
        // allowance. Retain any smaller known boundary until a complete sample.
        self.limit = if observation.complete {
            proposed
        } else {
            self.limit.min(proposed)
        };
        self.baseline = baseline;
        self.observation = observation;
        self.rechecks = self.rechecks.saturating_add(1);
        self.checked = now;
    }
    #[cfg(test)]
    pub fn make_due(&mut self) {
        self.checked = Instant::now() - INTERVAL;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    };

    fn observation(headroom: Option<u64>, complete: bool) -> Observation {
        Observation {
            observed_unix_ms: None,
            host_available_bytes: headroom,
            cgroup_headroom_bytes: None,
            headroom_bytes: headroom,
            complete,
            discovery: "injected pressure, not OS pressure".into(),
        }
    }
    #[test]
    fn throttling_unknown_discovery_recovery_and_overflow() {
        let calls = Arc::new(AtomicU64::new(0));
        let c = calls.clone();
        let mut pressure = Pressure::new(128, observation(Some(256), true), move || {
            c.fetch_add(1, Ordering::Relaxed);
            observation(Some(64), true)
        });
        let start = Instant::now();
        pressure.refresh(128, || 64, start);
        assert_eq!(calls.load(Ordering::Relaxed), 0);
        pressure.refresh(128, || 64, start + INTERVAL);
        assert_eq!(pressure.limit, 96);
        assert_eq!(calls.load(Ordering::Relaxed), 1);
        pressure.observe = Box::new(|| observation(None, false));
        pressure.refresh(128, || 64, start + 2 * INTERVAL);
        assert_eq!(
            pressure.limit, 96,
            "unknown observations cannot restore grants"
        );
        pressure.observe = Box::new(|| observation(Some(2), false));
        pressure.refresh(128, || 64, start + 3 * INTERVAL);
        assert_eq!(pressure.limit, 65);
        pressure.observe = Box::new(|| observation(Some(u64::MAX), true));
        pressure.refresh(128, || 64, start + 4 * INTERVAL);
        assert_eq!(pressure.limit, 128);
        pressure.refresh(u64::MAX, || u64::MAX, start + 5 * INTERVAL);
        assert_eq!(pressure.limit, u64::MAX);
        assert_eq!(pressure.rechecks, 5);
    }

    #[test]
    fn releases_during_observation_are_not_added_to_the_baseline() {
        let used = Arc::new(AtomicU64::new(64));
        let released = used.clone();
        let mut pressure = Pressure::new(128, observation(Some(256), true), move || {
            released.store(32, Ordering::Relaxed);
            observation(Some(64), true)
        });
        pressure.make_due();
        pressure.refresh(128, || used.load(Ordering::Relaxed), Instant::now());
        assert_eq!(pressure.baseline, 32);
        assert_eq!(pressure.limit, 64);
    }
}
