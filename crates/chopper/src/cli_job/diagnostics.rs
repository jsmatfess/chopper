use chopper_core::Job;
use serde::Deserialize;
use serde_path_to_error::{Path, Segment, Track};
use std::{fmt, io::Read};

/// JSON Pointer to the field or enclosing object that failed typed decoding.
#[derive(Debug)]
pub struct JobJsonPath(String);

impl JobJsonPath {
    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub(super) fn from_serde(path: Path) -> Self {
        use fmt::Write;
        let mut pointer = String::new();
        for segment in &path {
            match segment {
                Segment::Map { key } => {
                    pointer.push('/');
                    for ch in key.chars() {
                        match ch {
                            '~' => pointer.push_str("~0"),
                            '/' => pointer.push_str("~1"),
                            ch => pointer.push(ch),
                        }
                    }
                }
                Segment::Seq { index } => write!(pointer, "/{index}").unwrap(),
                Segment::Enum { .. } | Segment::Unknown => break,
            }
        }
        Self(pointer)
    }
}

impl fmt::Display for JobJsonPath {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("read job JSON")
    }
}

pub(super) fn decode(reader: impl Read) -> (serde_json::Result<Job>, Option<Path>) {
    let mut json = serde_json::Deserializer::from_reader(reader);
    let mut track = Track::new();
    match Job::deserialize(serde_path_to_error::Deserializer::new(
        &mut json, &mut track,
    )) {
        Ok(job) => (json.end().map(|()| job), None),
        Err(error) => {
            let path = error.is_data().then(|| track.path());
            (Err(error), path)
        }
    }
}
