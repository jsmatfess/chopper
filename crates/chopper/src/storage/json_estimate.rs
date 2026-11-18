//! Nonallocating preflight for admitted JSON schemas using borrowed Serialize.
//! Unsupported custom display/data-enum forms fail before tree construction.
use serde::{
    ser::{self, Error as _, SerializeMap, SerializeSeq},
    Serialize,
};
type Result<T> = std::result::Result<T, serde_json::Error>;

pub(crate) struct Estimate {
    pub(crate) bytes: usize,
    text: bool,
}
impl Estimate {
    fn scalar() -> Self {
        Self {
            bytes: 0,
            text: false,
        }
    }
    fn text(bytes: usize) -> Self {
        Self { bytes, text: true }
    }
}
fn add(a: usize, b: usize) -> Result<usize> {
    a.checked_add(b)
        .ok_or_else(|| serde_json::Error::custom("manifest capacity overflow"))
}
fn slots(count: usize) -> Result<usize> {
    count
        .checked_mul(std::mem::size_of::<serde_json::Value>())
        .ok_or_else(|| serde_json::Error::custom("manifest capacity overflow"))
}
pub(crate) struct Estimator;
macro_rules! scalar {
    ($($name:ident($ty:ty)),* $(,)?) => {$(
        fn $name(self, _: $ty) -> Result<Estimate> { Ok(Estimate::scalar()) }
    )*};
}
impl ser::Serializer for Estimator {
    type Ok = Estimate;
    type Error = serde_json::Error;
    type SerializeSeq = Sequence;
    type SerializeTuple = Sequence;
    type SerializeTupleStruct = Sequence;
    type SerializeTupleVariant = ser::Impossible<Estimate, Self::Error>;
    type SerializeMap = Object;
    type SerializeStruct = Object;
    type SerializeStructVariant = ser::Impossible<Estimate, Self::Error>;
    scalar!(
        serialize_bool(bool),
        serialize_i8(i8),
        serialize_i16(i16),
        serialize_i32(i32),
        serialize_i64(i64),
        serialize_u8(u8),
        serialize_u16(u16),
        serialize_u32(u32),
        serialize_u64(u64),
        serialize_f32(f32),
        serialize_f64(f64)
    );
    fn serialize_i128(self, n: i128) -> Result<Estimate> {
        if i64::try_from(n).is_ok() || u64::try_from(n).is_ok() {
            Ok(Estimate::scalar())
        } else {
            Err(serde_json::Error::custom(
                "manifest integer outside JSON range",
            ))
        }
    }
    fn serialize_u128(self, n: u128) -> Result<Estimate> {
        if u64::try_from(n).is_ok() {
            Ok(Estimate::scalar())
        } else {
            Err(serde_json::Error::custom(
                "manifest integer outside JSON range",
            ))
        }
    }
    fn serialize_char(self, _: char) -> Result<Estimate> {
        // Value's char serializer pushes into a new String: u8 Vec's current
        // nonzero minimum capacity on supported native/WASI targets is eight.
        Ok(Estimate::text(8))
    }
    fn serialize_str(self, text: &str) -> Result<Estimate> {
        Ok(Estimate::text(text.len()))
    }
    fn serialize_bytes(self, bytes: &[u8]) -> Result<Estimate> {
        Ok(Estimate {
            bytes: slots(bytes.len())?,
            text: false,
        })
    }
    fn serialize_none(self) -> Result<Estimate> {
        self.serialize_unit()
    }
    fn serialize_some<T: ?Sized + Serialize>(self, v: &T) -> Result<Estimate> {
        v.serialize(self)
    }
    fn serialize_unit(self) -> Result<Estimate> {
        Ok(Estimate::scalar())
    }
    fn serialize_unit_struct(self, _: &'static str) -> Result<Estimate> {
        self.serialize_unit()
    }
    fn serialize_unit_variant(self, _: &'static str, _: u32, v: &'static str) -> Result<Estimate> {
        self.serialize_str(v)
    }
    fn serialize_newtype_struct<T: ?Sized + Serialize>(
        self,
        _: &'static str,
        v: &T,
    ) -> Result<Estimate> {
        v.serialize(self)
    }
    fn serialize_newtype_variant<T: ?Sized + Serialize>(
        self,
        _: &'static str,
        _: u32,
        _: &'static str,
        _: &T,
    ) -> Result<Estimate> {
        Err(unsupported())
    }
    fn serialize_seq(self, len: Option<usize>) -> Result<Sequence> {
        Ok(Sequence {
            hint: len.unwrap_or(0),
            count: 0,
            children: 0,
        })
    }
    fn serialize_tuple(self, len: usize) -> Result<Sequence> {
        self.serialize_seq(Some(len))
    }
    fn serialize_tuple_struct(self, _: &'static str, len: usize) -> Result<Sequence> {
        self.serialize_seq(Some(len))
    }
    fn serialize_tuple_variant(
        self,
        _: &'static str,
        _: u32,
        _: &'static str,
        _: usize,
    ) -> Result<Self::SerializeTupleVariant> {
        Err(unsupported())
    }
    fn serialize_map(self, _: Option<usize>) -> Result<Object> {
        Ok(Object {
            bytes: 0,
            key: None,
        })
    }
    fn serialize_struct(self, _: &'static str, len: usize) -> Result<Object> {
        self.serialize_map(Some(len))
    }
    fn serialize_struct_variant(
        self,
        _: &'static str,
        _: u32,
        _: &'static str,
        _: usize,
    ) -> Result<Self::SerializeStructVariant> {
        Err(unsupported())
    }
    fn collect_str<T: ?Sized + std::fmt::Display>(self, _: &T) -> Result<Estimate> {
        Err(unsupported())
    }
}
fn unsupported() -> serde_json::Error {
    serde_json::Error::custom(
        "unsupported allocating serialization form in manifest capacity preflight",
    )
}

pub(crate) struct Sequence {
    hint: usize,
    count: usize,
    children: usize,
}
impl SerializeSeq for Sequence {
    type Ok = Estimate;
    type Error = serde_json::Error;
    fn serialize_element<T: ?Sized + Serialize>(&mut self, v: &T) -> Result<()> {
        self.children = add(self.children, v.serialize(Estimator)?.bytes)?;
        self.count = add(self.count, 1)?;
        Ok(())
    }
    fn end(self) -> Result<Estimate> {
        // Include the initial hinted allocation and old/new growth overlap if
        // an unhinted sequence grows. Sum child capacities independently.
        let growth = if self.count == 0 {
            0
        } else {
            self.count
                .checked_mul(3)
                .ok_or_else(|| serde_json::Error::custom("manifest capacity overflow"))?
                .max(4)
        };
        Ok(Estimate {
            bytes: add(self.children, slots(self.hint.max(growth))?)?,
            text: false,
        })
    }
}
impl ser::SerializeTuple for Sequence {
    type Ok = Estimate;
    type Error = serde_json::Error;
    fn serialize_element<T: ?Sized + Serialize>(&mut self, v: &T) -> Result<()> {
        SerializeSeq::serialize_element(self, v)
    }
    fn end(self) -> Result<Estimate> {
        SerializeSeq::end(self)
    }
}
impl ser::SerializeTupleStruct for Sequence {
    type Ok = Estimate;
    type Error = serde_json::Error;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, v: &T) -> Result<()> {
        SerializeSeq::serialize_element(self, v)
    }
    fn end(self) -> Result<Estimate> {
        SerializeSeq::end(self)
    }
}
pub(crate) struct Object {
    bytes: usize,
    key: Option<usize>,
}
impl SerializeMap for Object {
    type Ok = Estimate;
    type Error = serde_json::Error;
    fn serialize_key<T: ?Sized + Serialize>(&mut self, key: &T) -> Result<()> {
        let key = key.serialize(Estimator)?;
        if !key.text || self.key.is_some() {
            return Err(unsupported());
        }
        self.key = Some(key.bytes);
        Ok(())
    }
    fn serialize_value<T: ?Sized + Serialize>(&mut self, value: &T) -> Result<()> {
        let key = self.key.take().ok_or_else(unsupported)?;
        self.bytes = add(
            self.bytes,
            add(
                crate::storage::json_map_entry_allowance(),
                add(key, value.serialize(Estimator)?.bytes)?,
            )?,
        )?;
        Ok(())
    }
    fn end(self) -> Result<Estimate> {
        if self.key.is_some() {
            return Err(unsupported());
        }
        Ok(Estimate {
            bytes: self.bytes,
            text: false,
        })
    }
}
impl ser::SerializeStruct for Object {
    type Ok = Estimate;
    type Error = serde_json::Error;
    fn serialize_field<T: ?Sized + Serialize>(
        &mut self,
        key: &'static str,
        value: &T,
    ) -> Result<()> {
        self.serialize_key(key)?;
        self.serialize_value(value)
    }
    fn end(self) -> Result<Estimate> {
        SerializeMap::end(self)
    }
}
