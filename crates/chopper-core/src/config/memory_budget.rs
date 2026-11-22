use serde::{de, Deserialize, Deserializer, Serialize, Serializer};
use std::{fmt, str::FromStr};

/// Requested working memory; automatic selection is resolved by the runtime.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MemoryBudget {
    Auto,
    MiB(u64),
}
// Inline payload only on the supported native and wasm32 layouts. No heap owner.
const _: () = assert!(std::mem::size_of::<MemoryBudget>() == 16);

impl MemoryBudget {
    pub fn as_mib(self) -> Option<u64> {
        match self {
            Self::Auto => None,
            Self::MiB(value) => Some(value),
        }
    }
}
impl Default for MemoryBudget {
    fn default() -> Self {
        Self::MiB(256)
    }
}
impl From<u64> for MemoryBudget {
    fn from(value: u64) -> Self {
        Self::MiB(value)
    }
}
impl fmt::Display for MemoryBudget {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Auto => f.write_str("auto"),
            Self::MiB(value) => value.fmt(f),
        }
    }
}
impl FromStr for MemoryBudget {
    type Err = &'static str;
    fn from_str(text: &str) -> Result<Self, Self::Err> {
        if text == "auto" {
            return Ok(Self::Auto);
        }
        if !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit()) {
            if let Ok(value) = text.parse() {
                return Ok(Self::MiB(value));
            }
        }
        Err("memory budget must be auto or an unsigned integer in MiB")
    }
}
impl Serialize for MemoryBudget {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Auto => serializer.serialize_str("auto"),
            Self::MiB(value) => serializer.serialize_u64(*value),
        }
    }
}
impl<'de> Deserialize<'de> for MemoryBudget {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Scalar;
        impl de::Visitor<'_> for Scalar {
            type Value = MemoryBudget;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("\"auto\" or an unsigned integer in MiB")
            }
            fn visit_u64<E: de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(MemoryBudget::MiB(value))
            }
            fn visit_i64<E: de::Error>(self, value: i64) -> Result<Self::Value, E> {
                u64::try_from(value)
                    .map(MemoryBudget::MiB)
                    .map_err(|_| E::invalid_value(de::Unexpected::Signed(value), &self))
            }
            fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
                if value == "auto" {
                    Ok(MemoryBudget::Auto)
                } else {
                    Err(E::invalid_value(de::Unexpected::Str(value), &self))
                }
            }
        }
        // No untagged Content buffering or failed numeric trial for Auto.
        deserializer.deserialize_any(Scalar)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Job, Resources};
    #[test]
    fn strict_scalar_roundtrip_and_cli() {
        for (wire, expected) in [
            ("\"auto\"", MemoryBudget::Auto),
            ("0", MemoryBudget::MiB(0)),
            ("256", MemoryBudget::MiB(256)),
            ("18446744073709551615", MemoryBudget::MiB(u64::MAX)),
        ] {
            assert_eq!(
                serde_json::from_str::<MemoryBudget>(wire).unwrap(),
                expected
            );
            assert_eq!(
                serde_json::from_value::<MemoryBudget>(serde_json::from_str(wire).unwrap())
                    .unwrap(),
                expected
            );
            assert_eq!(serde_json::to_string(&expected).unwrap(), wire);
            assert_eq!(
                expected.to_string().parse::<MemoryBudget>().unwrap(),
                expected
            );
        }
        for wire in [
            "\"256\"",
            "\"AUTO\"",
            "\"\"",
            "1.0",
            "-0",
            "-1",
            "1e2",
            "null",
            "true",
            "{}",
            "[]",
            "18446744073709551616",
        ] {
            assert!(
                serde_json::from_str::<MemoryBudget>(wire).is_err(),
                "{wire}"
            );
            let value = serde_json::from_str(wire).unwrap();
            assert!(
                serde_json::from_value::<MemoryBudget>(value).is_err(),
                "{wire}"
            );
        }
        for text in [
            "",
            "+1",
            "-1",
            " 256",
            "256 ",
            "1.0",
            "AUTO",
            "18446744073709551616",
        ] {
            assert!(text.parse::<MemoryBudget>().is_err());
        }
        assert_eq!(MemoryBudget::from(256).as_mib(), Some(256));
        assert_eq!(MemoryBudget::Auto.as_mib(), None);
    }
    #[test]
    fn defaults_and_deferred_validation() {
        for wire in ["{}", r#"{"resources":{}}"#] {
            let job: Job = serde_json::from_str(wire).unwrap();
            assert_eq!(job.resources.memory_mb, MemoryBudget::Auto);
            assert_eq!(
                serde_json::to_value(&job).unwrap()["resources"]["memory_mb"],
                "auto"
            );
        }
        let mut job = Job {
            input: "input.csv".into(),
            ..Job::default()
        };
        job.resources.memory_mb = MemoryBudget::Auto;
        job.resources.max_record_bytes = 64 * 1024 * 1024;
        assert!(job.validate().is_ok());
        assert!(job.resources.validate_effective_memory(256).is_err());
        assert!(job.resources.validate_effective_memory(1024).is_ok());
        assert_eq!(job.resources.memory_mb, MemoryBudget::Auto);
        assert_eq!(job.resources.max_record_bytes, 64 * 1024 * 1024);
        for memory in [0, 31, 1_048_577, u64::MAX] {
            assert!(job.resources.validate_effective_memory(memory).is_err());
        }
        job.resources.max_record_bytes = 0;
        assert!(job.validate().is_err());
        job.resources.max_record_bytes = 1;
        job.resources.workers = 65;
        assert!(job.validate().is_err());
        job.resources.workers = 64;
        assert!(job.validate().is_ok());
        assert!(job.resources.validate_effective_memory(32).is_err());
        job.resources.memory_mb = MemoryBudget::MiB(32);
        assert!(job.validate().is_err());
        let resources = Resources {
            max_record_bytes: 1,
            workers: 0,
            ..Resources::default()
        };
        assert!(resources.validate_effective_memory(32).is_ok());
        assert!(resources.validate_effective_memory(1_048_576).is_ok());
    }
}
