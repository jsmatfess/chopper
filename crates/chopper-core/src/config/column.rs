//! Valid scalars avoid allocating errors for an untagged trial alternative.
use super::Column;
use serde::{
    de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor},
    Deserialize, Deserializer,
};
use std::fmt;
const INVALID: &str = "data did not match any variant of untagged enum Column";

impl<'de> Deserialize<'de> for Column {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        // Reject outside deserialize_any, just as the original untagged enum did.
        // Returning a custom visitor error here would add a JSON position suffix.
        ColumnVisitor { scalar: true }
            .deserialize(deserializer)?
            .ok_or_else(|| de::Error::custom(INVALID))
    }
}
struct ColumnVisitor {
    scalar: bool,
}
impl<'de> DeserializeSeed<'de> for ColumnVisitor {
    type Value = Option<Column>;
    fn deserialize<D: Deserializer<'de>>(self, de: D) -> Result<Self::Value, D::Error> {
        de.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for ColumnVisitor {
    type Value = Option<Column>;
    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("any value")
    }
    fn visit_u64<E: de::Error>(self, n: u64) -> Result<Self::Value, E> {
        Ok(if self.scalar {
            usize::try_from(n).ok().map(Column::Index)
        } else {
            None
        })
    }
    fn visit_i64<E: de::Error>(self, n: i64) -> Result<Self::Value, E> {
        Ok(if self.scalar {
            usize::try_from(n).ok().map(Column::Index)
        } else {
            None
        })
    }
    fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
        Ok(self.scalar.then(|| Column::Name(s.to_owned())))
    }
    fn visit_string<E: de::Error>(self, s: String) -> Result<Self::Value, E> {
        Ok(if self.scalar {
            Some(Column::Name(s))
        } else {
            None
        })
    }
    fn visit_bytes<E: de::Error>(self, s: &[u8]) -> Result<Self::Value, E> {
        Ok(if self.scalar {
            std::str::from_utf8(s)
                .ok()
                .map(|s| Column::Name(s.to_owned()))
        } else {
            None
        })
    }
    fn visit_byte_buf<E: de::Error>(self, s: Vec<u8>) -> Result<Self::Value, E> {
        Ok(if self.scalar {
            String::from_utf8(s).ok().map(Column::Name)
        } else {
            None
        })
    }
    fn visit_bool<E: de::Error>(self, _: bool) -> Result<Self::Value, E> {
        Ok(None)
    }
    fn visit_f64<E: de::Error>(self, _: f64) -> Result<Self::Value, E> {
        Ok(None)
    }
    fn visit_char<E: de::Error>(self, _: char) -> Result<Self::Value, E> {
        Ok(None)
    }
    fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
        Ok(None)
    }
    fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
        Ok(None)
    }
    fn visit_some<D: Deserializer<'de>>(self, de: D) -> Result<Self::Value, D::Error> {
        ColumnVisitor { scalar: false }.deserialize(de)?;
        Ok(None)
    }
    fn visit_newtype_struct<D: Deserializer<'de>>(self, de: D) -> Result<Self::Value, D::Error> {
        ColumnVisitor { scalar: false }.deserialize(de)?;
        Ok(None)
    }
    // Strictly visit invalid containers instead of IgnoredAny, which can skip
    // UTF-8/escape validation. No intermediate tree is needed for rejection.
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Self::Value, A::Error> {
        while seq
            .next_element_seed(ColumnVisitor { scalar: false })?
            .is_some()
        {}
        Ok(None)
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
        while map
            .next_key_seed(ColumnVisitor { scalar: false })?
            .is_some()
        {
            map.next_value_seed(ColumnVisitor { scalar: false })?;
        }
        Ok(None)
    }
    fn visit_enum<A: de::EnumAccess<'de>>(self, _: A) -> Result<Self::Value, A::Error> {
        Err(de::Error::custom(
            "untagged and internally tagged enums do not support enum input",
        ))
    }
}
#[cfg(test)]
mod tests;
