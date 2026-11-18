use chopper_core::{csv::CompactRecord, csv::Parser, CsvSettings};
use std::io::{BufReader, Cursor};

#[test]
fn compact_views_retain_valid_text_across_construction_cloning_and_recycling() -> anyhow::Result<()>
{
    let text = "\0\u{7f}\u{80}\u{7ff}\u{800}\u{d7ff}\u{e000}\u{ffff}\u{10000}\u{10ffff}";
    let fields = ["", text, "quoted,\"\r\nfield"];
    let mut record = CompactRecord::with_storage(vec![0xff; 256]);
    assert_eq!(record.fields().next(), None);
    record.set_text_fields_reserved(fields.into_iter(), 4096, &mut |_| Ok(()))?;
    let encoded = record.encoded_fields().to_vec();
    let check = |record: &CompactRecord| {
        let mut view = record.fields();
        assert_eq!(view.next(), Some(""));
        assert_eq!(view.len(), 2);
        let clone = view.clone();
        assert_eq!(view.collect::<Vec<_>>(), fields[1..]);
        assert_eq!(clone.collect::<Vec<_>>(), fields[1..]);
        assert_eq!(record.fields().collect::<Vec<_>>(), fields);
    };
    check(&record);
    let csv = chopper_core::csv::serialize(&fields.map(str::to_owned), &CsvSettings::default())?;
    for capacity in [1, 2, 3, 7, 65536] {
        record = CompactRecord::with_storage(record.into_encoded_fields());
        assert_eq!(record.fields().next(), None);
        let mut parser = Parser::new(
            BufReader::with_capacity(capacity, Cursor::new(&csv)),
            CsvSettings::default(),
            4096,
        );
        assert!(parser.next_compact_record_into(&mut record)?);
        check(&record);
        assert_eq!(record.encoded_fields(), encoded);
    }
    // A valid first field must not expose a partially constructed record when
    // a later field contains invalid UTF-8.
    let mut parser = Parser::new(Cursor::new(b"valid,\xff\n"), CsvSettings::default(), 4096);
    assert!(parser.next_compact_record_into(&mut record).is_err());
    assert_eq!(record.fields().next(), None);
    Ok(())
}
