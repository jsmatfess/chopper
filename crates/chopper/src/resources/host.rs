//! Read-only, bounded Linux observations. Values describe additional headroom,
//! not total process allowance; WASI uses a separate fixed address-space policy.
use serde::Serialize;
#[cfg(target_os = "linux")]
use std::{fs::File, io::Read, path::Path};

#[derive(Clone, Debug, Serialize)]
pub struct Observation {
    pub observed_unix_ms: Option<u128>,
    pub host_available_bytes: Option<u64>,
    pub cgroup_headroom_bytes: Option<u64>,
    pub headroom_bytes: Option<u64>,
    pub complete: bool,
    pub discovery: String,
}
fn observed_unix_ms() -> Option<u128> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|n| n.as_millis())
}
pub(super) fn observe() -> Observation {
    #[cfg(target_os = "linux")]
    {
        let host = read(Path::new("/proc/meminfo"))
            .ok()
            .and_then(|s| mem_available(&s));
        let (group, cgroup_result) = linux_cgroup();
        let (cgroup_complete, discovery) = match cgroup_result {
            Ok(()) => (true, "linux proc/cgroup-v2 snapshot".into()),
            Err(error) => (false, format!("Linux cgroup discovery incomplete: {error}")),
        };
        // Incomplete cgroup discovery must not justify a larger grant than the
        // unknown-platform fallback, even if host MemAvailable is much larger.
        let headroom = selected_headroom(host, group, cgroup_complete);
        Observation {
            observed_unix_ms: observed_unix_ms(),
            host_available_bytes: host,
            cgroup_headroom_bytes: group,
            headroom_bytes: headroom,
            complete: cgroup_complete && host.is_some(),
            discovery,
        }
    }
    #[cfg(not(target_os = "linux"))]
    Observation {
        observed_unix_ms: observed_unix_ms(),
        host_available_bytes: None,
        cgroup_headroom_bytes: None,
        headroom_bytes: None,
        complete: false,
        discovery: if cfg!(target_os = "wasi") {
            "host RAM unavailable; fixed 1 GiB tracked capacity within 2 GiB WASM memory"
        } else {
            "host RAM unavailable; conservative 128 MiB tracked-capacity fallback"
        }
        .into(),
    }
}
#[cfg(any(test, target_os = "linux"))]
fn selected_headroom(host: Option<u64>, group: Option<u64>, complete: bool) -> Option<u64> {
    let headroom = match (host, group) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (Some(a), None) => Some(a),
        (None, Some(b)) => Some(b),
        _ => None,
    };
    if !complete || host.is_none() {
        Some(headroom.unwrap_or(256 * 1024 * 1024).min(256 * 1024 * 1024))
    } else {
        headroom
    }
}
#[cfg(target_os = "linux")]
fn read(path: &Path) -> Result<String, String> {
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|e| e.to_string())?
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 1024 * 1024 {
        return Err("discovery file exceeds 1 MiB".into());
    }
    String::from_utf8(bytes).map_err(|e| e.to_string())
}
#[cfg(any(test, target_os = "linux"))]
fn mem_available(text: &str) -> Option<u64> {
    let mut fields = text
        .lines()
        .find(|line| line.starts_with("MemAvailable:"))?
        .split_whitespace();
    fields.next()?;
    let value = fields.next()?.parse::<u64>().ok()?;
    if fields.next() != Some("kB") || fields.next().is_some() {
        return None;
    }
    value.checked_mul(1024)
}
#[cfg(target_os = "linux")]
fn linux_cgroup() -> (Option<u64>, Result<(), String>) {
    let mut headroom = None;
    let result = (|| {
        let membership = read(Path::new("/proc/self/cgroup"))?;
        let member = membership
            .lines()
            .find_map(|line| line.strip_prefix("0::"))
            .ok_or("cgroup v2 membership absent")?;
        let mounts = read(Path::new("/proc/self/mountinfo"))?;
        let (leaf, mount, root) =
            resolve_mount(member, &mounts).ok_or("cgroup v2 mount/root unresolved")?;
        // The actual hierarchy root has no memory-controller files. A mounted
        // subtree must retain its own limits, and hidden ancestors stay unknown.
        // https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files
        let exempt_root = root == Path::new("/")
            && !mount
                .join("memory.current")
                .try_exists()
                .map_err(|e| e.to_string())?;
        ancestor_headroom(&leaf, &mount, &mut headroom, |path| {
            if exempt_root && path.parent() == Some(mount.as_path()) {
                Ok(
                    if path.file_name() == Some(std::ffi::OsStr::new("memory.current")) {
                        "0"
                    } else {
                        "max"
                    }
                    .into(),
                )
            } else {
                read(path)
            }
        })?;
        if root != Path::new("/") {
            return Err("ancestors outside cgroup mount are inaccessible".into());
        }
        if read(Path::new("/proc/self/cgroup"))? != membership {
            return Err("cgroup membership changed during observation".into());
        }
        Ok(())
    })();
    (headroom, result)
}
#[cfg(any(test, target_os = "linux"))]
fn ancestor_headroom(
    leaf: &std::path::Path,
    mount: &std::path::Path,
    headroom: &mut Option<u64>,
    mut read_value: impl FnMut(&std::path::Path) -> Result<String, String>,
) -> Result<(), String> {
    if !leaf.starts_with(mount) {
        return Err("cgroup leaf outside mount".into());
    }
    let mut directory = leaf;
    loop {
        let current = read_value(&directory.join("memory.current"))?
            .trim()
            .parse::<u64>()
            .map_err(|e| e.to_string())?;
        for file in ["memory.max", "memory.high"] {
            let value = read_value(&directory.join(file))?;
            if let Some(limit) = finite_limit(&value)? {
                let remaining = limit.saturating_sub(current);
                *headroom = Some(headroom.map_or(remaining, |old: u64| old.min(remaining)));
            }
        }
        if directory == mount {
            break;
        }
        directory = directory.parent().ok_or("cgroup ancestor escaped mount")?;
    }
    Ok(())
}
#[cfg(any(test, target_os = "linux"))]
fn finite_limit(text: &str) -> Result<Option<u64>, String> {
    match text.trim() {
        "max" => Ok(None),
        value => value
            .parse()
            .map(Some)
            .map_err(|_| "invalid cgroup memory limit".into()),
    }
}
#[cfg(any(test, target_os = "linux"))]
fn unescape_mount(text: &str) -> Option<String> {
    let mut bytes = Vec::new();
    let mut input = text.bytes();
    while let Some(b) = input.next() {
        if b == b'\\' {
            let digits = [input.next()?, input.next()?, input.next()?];
            if !digits.iter().all(|b| (b'0'..=b'7').contains(b)) {
                return None;
            }
            let value = (digits[0] - b'0') as u16 * 64
                + (digits[1] - b'0') as u16 * 8
                + (digits[2] - b'0') as u16;
            bytes.push(u8::try_from(value).ok()?);
        } else {
            bytes.push(b)
        }
    }
    String::from_utf8(bytes).ok()
}
#[cfg(target_os = "linux")]
fn resolve_mount(
    member: &str,
    mounts: &str,
) -> Option<(std::path::PathBuf, std::path::PathBuf, std::path::PathBuf)> {
    use std::path::{Component, Path, PathBuf};
    let member = Path::new(member);
    if !member.is_absolute()
        || member
            .components()
            .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
    {
        return None;
    }
    let mut best: Option<(usize, PathBuf, PathBuf, PathBuf)> = None;
    for line in mounts.lines() {
        let (left, right) = line.split_once(" - ")?;
        if right.split_whitespace().next() != Some("cgroup2") {
            continue;
        }
        let fields: Vec<_> = left.split_whitespace().collect();
        if fields.len() < 6 {
            continue;
        }
        let root = PathBuf::from(unescape_mount(fields[3])?);
        let mount = PathBuf::from(unescape_mount(fields[4])?);
        if !root.is_absolute()
            || !mount.is_absolute()
            || root
                .components()
                .chain(mount.components())
                .any(|c| matches!(c, Component::ParentDir))
        {
            continue;
        }
        if let Ok(relative) = member.strip_prefix(&root) {
            let depth = root.components().count();
            if best.as_ref().is_none_or(|b| depth > b.0) {
                best = Some((depth, mount.join(relative), mount, root));
            }
        }
    }
    best.map(|(_, leaf, mount, root)| (leaf, mount, root))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn incomplete_discovery_never_increases_the_conservative_fallback() {
        let fallback = 256 * 1024 * 1024;
        assert_eq!(selected_headroom(Some(1000), Some(500), true), Some(500));
        assert_eq!(
            selected_headroom(Some(u64::MAX), None, false),
            Some(fallback)
        );
        assert_eq!(
            selected_headroom(None, Some(u64::MAX), true),
            Some(fallback)
        );
        assert_eq!(selected_headroom(None, None, false), Some(fallback));
        assert_eq!(selected_headroom(Some(1000), None, false), Some(1000));
        assert_eq!(selected_headroom(Some(1000), Some(0), true), Some(0));
    }
    #[test]
    fn linux_memory_units_overflow_and_mount_escapes() {
        assert_eq!(
            mem_available("MemTotal: 999 kB\nMemAvailable: 123 kB\n"),
            Some(123 * 1024)
        );
        for text in [
            "MemAvailable: 1 MB",
            "MemAvailable: 18446744073709551615 kB",
            "MemAvailable: -1 kB",
            "MemAvailable: 1 kB extra",
        ] {
            assert_eq!(mem_available(text), None)
        }
        assert_eq!(finite_limit("max\n"), Ok(None));
        assert_eq!(finite_limit("123\n"), Ok(Some(123)));
        assert!(finite_limit("-1").is_err());
        assert_eq!(unescape_mount("bad\\999"), None);
        assert_eq!(
            unescape_mount("nested\\040mount"),
            Some("nested mount".into())
        );
    }
    // Mountinfo contains Linux paths, so resolving it uses Linux Path semantics.
    #[cfg(target_os = "linux")]
    #[test]
    fn linux_mount_roots() {
        let mounts="1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n2 1 0:1 /jobs /nested\\040mount rw - cgroup2 cgroup rw";
        assert_eq!(
            resolve_mount("/jobs/a", mounts),
            Some((
                "/nested mount/a".into(),
                "/nested mount".into(),
                "/jobs".into()
            ))
        );
        assert_eq!(
            resolve_mount("/other", mounts),
            Some((
                "/sys/fs/cgroup/other".into(),
                "/sys/fs/cgroup".into(),
                "/".into()
            ))
        );
        assert!(resolve_mount("/../other", mounts).is_none());
        assert!(resolve_mount("relative", mounts).is_none());
    }
    #[cfg(not(target_os = "linux"))]
    #[test]
    fn unsupported_hosts_use_the_conservative_fallback() {
        let observation = observe();
        assert!(!observation.complete);
        assert_eq!(observation.host_available_bytes, None);
        assert_eq!(observation.cgroup_headroom_bytes, None);
        assert_eq!(observation.headroom_bytes, None);
        assert!(observation.discovery.contains(if cfg!(target_os = "wasi") {
            "fixed 1 GiB"
        } else {
            "conservative 128 MiB"
        }));
    }
}

#[cfg(test)]
mod hierarchy_tests {
    use super::*;
    use std::{
        collections::BTreeMap,
        path::{Path, PathBuf},
    };
    #[test]
    fn ancestor_current_includes_siblings_high_pressure_and_unknown_limits() {
        let mut files = BTreeMap::new();
        for (dir, current, maximum, high) in [
            ("/c", 800, 1000, "max"),
            ("/c/a", 20, 500, "400"),
            ("/c/a/b", 10, 300, "max"),
        ] {
            files.insert(Path::new(dir).join("memory.current"), current.to_string());
            files.insert(Path::new(dir).join("memory.max"), maximum.to_string());
            files.insert(Path::new(dir).join("memory.high"), high.into());
        }
        let evaluate = |files: &BTreeMap<PathBuf, String>| {
            let mut known = None;
            let result =
                ancestor_headroom(Path::new("/c/a/b"), Path::new("/c"), &mut known, |path| {
                    files.get(path).cloned().ok_or("missing controller".into())
                });
            result.map(|()| known)
        };
        assert_eq!(evaluate(&files), Ok(Some(200))); // parent's own current, not leaf current
        files.insert("/c/a/memory.high".into(), "25".into());
        assert_eq!(evaluate(&files), Ok(Some(5)));
        files.insert("/c/a/memory.high".into(), "15".into());
        assert_eq!(evaluate(&files), Ok(Some(0)));
        files.remove(Path::new("/c/memory.max"));
        assert!(evaluate(&files).is_err());
        let mut partial = None;
        assert!(
            ancestor_headroom(Path::new("/c/a/b"), Path::new("/c"), &mut partial, |path| {
                files.get(path).cloned().ok_or("missing".into())
            })
            .is_err()
        );
        assert_eq!(partial, Some(0));
        assert_eq!(selected_headroom(Some(u64::MAX), partial, false), Some(0));
        files.insert("/c/memory.max".into(), "invalid".into());
        assert!(evaluate(&files).is_err());
        for value in files.values_mut() {
            *value = "max".into()
        }
        for dir in ["/c", "/c/a", "/c/a/b"] {
            files.insert(Path::new(dir).join("memory.current"), "0".into());
        }
        assert_eq!(evaluate(&files), Ok(None));
    }
}
