use super::*;
use serde::de::value;
use serde::Serialize;

#[derive(Deserialize, Serialize)]
#[serde(
    untagged,
    expecting = "data did not match any variant of untagged enum Column"
)]
enum LegacyColumn {
    Index(usize),
    Name(String),
}

#[test]
fn scalar_and_buffered_json_match_original_untagged_values_and_errors() {
    let mut cases: Vec<Vec<u8>> = [
        "0",
        "1",
        "4294967295",
        "4294967296",
        "18446744073709551615",
        "18446744073709551616",
        "-1",
        "-0",
        "0.0",
        "1e0",
        "null",
        "true",
        "false",
        "\"\"",
        "\"0\"",
        "\"01\"",
        "\"界é\\n\\u0000\"",
        "[]",
        "{}",
        "[1,2]",
        "{\"a\":1}",
        "[\"\\ud800\"]",
        "{\"a\":\"\\udc00\"}",
        "[tru]",
        "[1,]",
        "{\"a\":1,}",
        "[",
        "{",
        "\"\\ud800\"",
        "\"unterminated",
        "",
        "1 2",
    ]
    .into_iter()
    .map(|s| s.as_bytes().to_vec())
    .collect();
    cases.extend([
        vec![0xff],
        b"[\"\xff\"]".to_vec(),
        [vec![b'['; 127], b"0".to_vec(), vec![b']'; 127]].concat(),
        [vec![b'['; 128], b"0".to_vec(), vec![b']'; 128]].concat(),
    ]);
    for source in cases {
        match (
            serde_json::from_slice::<LegacyColumn>(&source),
            serde_json::from_slice::<Column>(&source),
        ) {
            (Ok(expected), Ok(actual)) => assert_eq!(
                serde_json::to_value(expected).unwrap(),
                serde_json::to_value(actual).unwrap()
            ),
            (Err(expected), Err(actual)) => assert_eq!(
                actual.to_string(),
                expected.to_string(),
                "{}",
                String::from_utf8_lossy(&source)
            ),
            _ => panic!(
                "Column result changed for {}",
                String::from_utf8_lossy(&source)
            ),
        }
    }
}
#[test]
fn owned_names_move_without_trial_error_or_copy() {
    let mut name = String::with_capacity(32768);
    name.push_str(&"\u{1}".repeat(16384));
    let pointer = name.as_ptr();
    let column = Column::deserialize(value::StringDeserializer::<value::Error>::new(name)).unwrap();
    let Column::Name(name) = column else {
        panic!("name changed to index")
    };
    assert_eq!(name.as_ptr(), pointer);
    assert_eq!(name.capacity(), 32768);
    assert_eq!(name.len(), 16384);
    assert!(matches!(
        serde_json::from_str::<Column>("\"0\"").unwrap(),
        Column::Name(_)
    ));
    assert!(matches!(
        serde_json::from_str::<Column>("0").unwrap(),
        Column::Index(0)
    ));
}
#[test]
fn non_json_scalar_and_wrapper_forms_match_original() {
    macro_rules! compare {
        ($de:expr) => {{
            let expected = LegacyColumn::deserialize($de)
                .map(|c| serde_json::to_value(c).unwrap())
                .map_err(|e| e.to_string());
            let actual = Column::deserialize($de)
                .map(|c| serde_json::to_value(c).unwrap())
                .map_err(|e| e.to_string());
            assert_eq!(actual, expected);
        }};
    }
    compare!(value::U64Deserializer::<value::Error>::new(u64::MAX));
    compare!(value::I64Deserializer::<value::Error>::new(7));
    compare!(value::I64Deserializer::<value::Error>::new(-1));
    compare!(value::I128Deserializer::<value::Error>::new(1));
    compare!(value::U128Deserializer::<value::Error>::new(1));
    compare!(value::CharDeserializer::<value::Error>::new('a'));
    compare!(value::BorrowedBytesDeserializer::<value::Error>::new(
        b"name"
    ));
    compare!(value::BorrowedBytesDeserializer::<value::Error>::new(&[
        0xff
    ]));
    compare!(Wrapped {
        de: value::BorrowedStrDeserializer::<value::Error>::new("name"),
        some: true
    });
    compare!(Wrapped {
        de: value::BorrowedStrDeserializer::<value::Error>::new("name"),
        some: false
    });
    for some in [true, false] {
        compare!(Wrapped {
            de: &mut serde_json::Deserializer::from_str(r#"["\ud800"]"#),
            some
        });
    }
}

struct Wrapped<D> {
    de: D,
    some: bool,
}
impl<'de, D: Deserializer<'de>> Deserializer<'de> for Wrapped<D> {
    type Error = D::Error;
    fn deserialize_any<V: Visitor<'de>>(self, visitor: V) -> Result<V::Value, D::Error> {
        if self.some {
            visitor.visit_some(self.de)
        } else {
            visitor.visit_newtype_struct(self.de)
        }
    }
    fn is_human_readable(&self) -> bool {
        self.de.is_human_readable()
    }
    serde::forward_to_deserialize_any! {bool i8 i16 i32 i64 i128 u8 u16 u32 u64 u128 f32 f64 char str string bytes byte_buf option unit unit_struct newtype_struct seq tuple tuple_struct map struct enum identifier ignored_any}
}
