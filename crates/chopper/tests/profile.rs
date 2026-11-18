use chopper::{
    core::*,
    profile::{InputProfile, ProfileCache},
};
use std::{
    fs,
    io::Write,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
fn fixture(text: &str) -> (tempfile::TempDir, Job) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("input.csv");
    fs::write(&path, text).unwrap();
    let job = Job {
        input: path.to_string_lossy().into(),
        ..Job::default()
    };
    (dir, job)
}
fn profile(cache: &mut ProfileCache, job: &Job) -> anyhow::Result<InputProfile> {
    cache.profile(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}
#[test]
fn preview_membership_does_not_change_when_parser_storage_is_reused() {
    let (_dir, job) = fixture(&format!("value\nfirst\n{}\nlast\n", "x".repeat(20000)));
    let result = profile(&mut ProfileCache::default(), &job).unwrap();
    assert_eq!(result.preview, vec![vec!["first"], vec!["last"]]);
}
#[test]
fn reuses_input_across_pipeline_output_and_seed_edits() {
    let (dir, mut job) = fixture("id,key\n1,\"a\nb\"\n2,c\n3,c\n");
    let mut cache = ProfileCache::default();
    let first = profile(&mut cache, &job).unwrap();
    assert!(!first.cache_hit);
    assert_eq!(first.rows, 3);
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Name("key".into())],
    }];
    job.output = dir.path().join("must-not-exist").to_string_lossy().into();
    job.random_seed = Some("different".into());
    job.limits.rows = Some(1);
    job.resources.temp_dir = Some(dir.path().join("does-not-exist").to_string_lossy().into());
    let second = profile(&mut cache, &job).unwrap();
    assert_eq!(second.cache_hit, !cfg!(windows));
    assert_eq!(second.stages[0].input_distinct_keys, Some(2));
    assert!(second.stages[0].distinct_exact);
    assert_eq!(second.column_values[1].values, ["a\nb", "c"]);
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}
#[test]
fn source_settings_and_new_combination_invalidate_cache() {
    let (_dir, mut job) = fixture("id,key\n1,a\n");
    let mut cache = ProfileCache::default();
    profile(&mut cache, &job).unwrap();
    fs::write(&job.input, "id,key\n1,a\n2,b\n").unwrap();
    let changed = profile(&mut cache, &job).unwrap();
    assert!(!changed.cache_hit);
    assert_eq!(changed.rows, 2);
    job.input_csv.headers = false;
    job.output_csv.headers = false;
    assert_eq!(profile(&mut cache, &job).unwrap().rows, 3);
    job.zip_member = Some("different.csv".into());
    assert!(!profile(&mut cache, &job).unwrap().cache_hit);
    job.resources.max_record_bytes /= 2;
    assert!(!profile(&mut cache, &job).unwrap().cache_hit);
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Index(0), Column::Index(1)],
    }];
    assert!(!profile(&mut cache, &job).unwrap().cache_hit);
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Index(1), Column::Index(0)],
    }];
    assert_eq!(profile(&mut cache, &job).unwrap().cache_hit, !cfg!(windows));
}
#[test]
fn sorted_input_includes_late_groups_and_rejects_late_malformed_rows() {
    let (_dir, job) =
        fixture(&("key\n".to_owned() + &"a\n".repeat(20_000) + &"z\n".repeat(20_000)));
    let mut cache = ProfileCache::default();
    let p = profile(&mut cache, &job).unwrap();
    assert_eq!(p.rows, 40_000);
    assert_eq!(p.column_values[0].distinct, 2);
    assert!(p.column_values[0].distinct_exact);
    fs::OpenOptions::new()
        .append(true)
        .open(&job.input)
        .unwrap()
        .write_all(b"\"unterminated")
        .unwrap();
    assert!(profile(&mut cache, &job).is_err());
}
#[test]
fn full_file_estimates_are_order_independent_and_bounded() {
    let (_dir, job) = fixture("");
    let mut observed = Vec::new();
    for reverse in [false, true] {
        let mut file = fs::File::create(&job.input).unwrap();
        writeln!(file, "id,key").unwrap();
        for i in 0..50_000 {
            let n = if reverse { 49_999 - i } else { i };
            writeln!(file, "{n},{}", n % 1000).unwrap();
        }
        let p = profile(&mut ProfileCache::default(), &job).unwrap();
        assert_eq!(p.rows, 50_000);
        for (column, expected) in p.column_values.iter().zip([50_000u64, 1000]) {
            assert!(!column.distinct_exact);
            assert!(column.truncated);
            assert_eq!(column.values.len(), 100);
            assert!(column.distinct.abs_diff(expected) < expected / 10);
        }
        observed.push(
            p.column_values
                .iter()
                .map(|c| c.distinct)
                .collect::<Vec<_>>(),
        );
    }
    assert_eq!(observed[0], observed[1]);
}
#[test]
#[cfg(windows)]
fn same_size_source_rewrite_with_unchanged_timestamps_invalidates_profile() {
    use std::io::{Read, Seek, SeekFrom};

    let (_dir, job) = fixture("id\n1\n");
    // Keep the writer open across both profiles: Windows may defer metadata
    // changes until a writer closes. This checks the product's rescan fallback,
    // rather than relying on a particular filesystem change-token API.
    let mut writer = fs::File::options()
        .read(true)
        .write(true)
        .open(&job.input)
        .unwrap();
    let metadata = writer.metadata().unwrap();
    let mut cache = ProfileCache::default();
    let first = profile(&mut cache, &job).unwrap();
    assert!(!first.cache_hit);
    assert_eq!(first.preview, vec![vec!["1"]]);
    writer.seek(SeekFrom::Start(0)).unwrap();
    writer.write_all(b"id\n2\n").unwrap();
    writer.flush().unwrap();
    writer
        .set_times(fs::FileTimes::new().set_modified(metadata.modified().unwrap()))
        .unwrap();
    let rewritten = fs::metadata(&job.input).unwrap();
    assert_eq!(rewritten.len(), metadata.len());
    assert_eq!(rewritten.modified().unwrap(), metadata.modified().unwrap());
    assert_eq!(rewritten.created().unwrap(), metadata.created().unwrap());
    let updated = profile(&mut cache, &job).unwrap();
    assert!(!updated.cache_hit);
    assert_eq!(updated.preview, vec![vec!["2"]]);
    // Read through the same still-open handle after reprofiling.
    writer.seek(SeekFrom::Start(0)).unwrap();
    let mut contents = String::new();
    writer.read_to_string(&mut contents).unwrap();
    assert_eq!(contents, "id\n2\n");
}

#[test]
fn gzip_utf16_and_empty_inputs_use_real_parser() {
    let (dir, mut job) = fixture("id\n");
    let mut cache = ProfileCache::default();
    assert_eq!(profile(&mut cache, &job).unwrap().rows, 0);
    let path = dir.path().join("input.gz");
    let mut gzip = flate2::write::GzEncoder::new(
        fs::File::create(&path).unwrap(),
        flate2::Compression::default(),
    );
    for unit in "\u{feff}id,key\r\n1,界\r\n".encode_utf16() {
        gzip.write_all(&unit.to_le_bytes()).unwrap();
    }
    gzip.finish().unwrap();
    job.input = path.to_string_lossy().into();
    job.input_csv.encoding = "utf-16le".into();
    assert_eq!(
        profile(&mut cache, &job).unwrap().preview,
        vec![vec!["1", "界"]]
    );
    let mut bytes = fs::read(&job.input).unwrap();
    let end = bytes.len();
    bytes[end - 8] ^= 1;
    fs::write(&job.input, bytes).unwrap();
    assert!(profile(&mut cache, &job).is_err());
}
#[test]
fn cancellation_and_source_replacement_do_not_cache_partial_results() {
    let (_dir, job) = fixture(&("id\n".to_owned() + &"x\n".repeat(20_000)));
    let mut cache = ProfileCache::default();
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    assert!(cache
        .profile(
            &job,
            cancel,
            Arc::new(move |_| signal.store(true, Ordering::Relaxed))
        )
        .is_err());
    assert!(!profile(&mut cache, &job).unwrap().cache_hit);
    cache.clear();
    let path = job.input.clone();
    assert!(cache
        .profile(
            &job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |_| {
                fs::write(&path, "id\nx\n").unwrap();
            })
        )
        .is_err());
}
#[test]
fn invalid_columns_fail_even_on_cache_hit() {
    let (_dir, mut job) = fixture("id\n1\n");
    let mut cache = ProfileCache::default();
    profile(&mut cache, &job).unwrap();
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Name("missing".into())],
    }];
    assert!(profile(&mut cache, &job).is_err());
}
