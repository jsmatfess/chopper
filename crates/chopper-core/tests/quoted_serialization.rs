use chopper_core::{csv::Serializer, CsvSettings};

#[test]
fn quoted_spans_preserve_literal_escape_bytes_and_admitted_retry() -> anyhow::Result<()> {
    let cases = [
        ('"', None, "a,b", "\"a,b\"\n"),
        ('"', None, "a\"b", "\"a\"\"b\"\n"),
        ('"', None, "a\\b,c", "\"a\\b,c\"\n"),
        ('"', Some('\\'), "a\\b,\"c", "\"a\\\\b,\\\"c\"\n"),
        ('"', Some('"'), "a\"b", "\"a\"\"b\"\n"),
        ('界', Some('§'), "a界b§c,d", "界a§界b§§c,d界\n"),
        ('界', None, "a界b", "界a界界b界\n"),
        ('"', None, "", "\"\"\n"),
        (
            '"',
            None,
            "\0界,\r\n\u{10ffff}",
            "\"\0界,\r\n\u{10ffff}\"\n",
        ),
    ];
    for (quote, escape, field, expected) in cases {
        // Serializer's public API also supports non-ASCII quote/escape chars;
        // preserve that behavior independently of Job's narrower dialect checks.
        let settings = CsvSettings {
            quote,
            escape,
            ..Default::default()
        };
        let mut serializer = Serializer::new(&settings)?;
        let mut held = 0;
        let mut peak = 0;
        let mut first_growth = None;
        let actual = serializer.serialize_fields_reserved([field], &mut |bytes| {
            if bytes != 0 {
                first_growth.get_or_insert(bytes);
            }
            held = bytes;
            peak = peak.max(bytes);
            Ok(())
        })?;
        assert_eq!(actual, expected.as_bytes());
        // The initial reservation includes multibyte escapes before any growth.
        if expected.len() > 8 {
            assert_eq!(first_growth, Some(expected.len()));
        }
        assert_eq!(held, serializer.capacity());
        let mut denied = Serializer::new(&settings)?;
        let mut admitted = 0;
        assert!(denied
            .serialize_fields_reserved([field], &mut |bytes| {
                anyhow::ensure!(bytes < peak, "denied");
                admitted = bytes;
                Ok(())
            })
            .is_err());
        assert_eq!(admitted, denied.capacity());
        assert_eq!(
            denied.serialize_fields_reserved([field], &mut |_| Ok(()))?,
            expected.as_bytes()
        );
    }
    Ok(())
}
