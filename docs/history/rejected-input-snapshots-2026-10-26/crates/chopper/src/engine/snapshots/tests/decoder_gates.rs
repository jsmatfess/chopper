use super::*;

// Small forward FlatBuffer fixture encoder. All offsets are fixed before the
// immutable bytes are authenticated and passed to the public prepare API.
struct Fb(Vec<u8>);
impl Fb {
    fn new() -> Self {
        Self(vec![0; 8])
    }
    fn align(&mut self, n: usize) {
        while !self.0.len().is_multiple_of(n) {
            self.0.push(0);
        }
    }
    fn table(&mut self, present: &[bool]) -> usize {
        self.align(2);
        let v = self.0.len();
        self.0
            .extend_from_slice(&((4 + present.len() * 2) as u16).to_le_bytes());
        self.0
            .extend_from_slice(&((8 + present.len() * 8) as u16).to_le_bytes());
        for (i, p) in present.iter().enumerate() {
            self.0
                .extend_from_slice(&(if *p { 8 + i * 8 } else { 0 } as u16).to_le_bytes());
        }
        self.align(8);
        let t = self.0.len();
        self.0.resize(t + 8 + present.len() * 8, 0);
        self.0[t..t + 4].copy_from_slice(&((t - v) as i32).to_le_bytes());
        t
    }
    fn slot(t: usize, i: usize) -> usize {
        t + 8 + i * 8
    }
    fn ptr(&mut self, p: usize, target: usize) {
        put32(&mut self.0, p, (target - p) as u32);
    }
    fn string(&mut self, s: &str) -> usize {
        self.align(4);
        let p = self.0.len();
        self.0.extend_from_slice(&(s.len() as u32).to_le_bytes());
        self.0.extend_from_slice(s.as_bytes());
        self.0.push(0);
        p
    }
    fn vector(&mut self, data: &[u8], n: usize, alignment: usize) -> usize {
        self.align(4);
        while !(self.0.len() + 4).is_multiple_of(alignment) {
            self.0.extend_from_slice(&[0; 4]);
        }
        let p = self.0.len();
        self.0.extend_from_slice(&(n as u32).to_le_bytes());
        self.0.extend_from_slice(data);
        p
    }
    fn field(&mut self, index: usize, case: &str) -> usize {
        let child = case == "field-children" && index == 0;
        let t = self.table(&[true, true, true, true, false, child, false]);
        let name = self.string(if case == "positional-name" && index == 0 {
            "x0"
        } else if index == 0 {
            "c0"
        } else {
            "c1"
        });
        self.ptr(Self::slot(t, 0), name);
        self.0[Self::slot(t, 1)] = u8::from(case == "nullable" && index == 0);
        self.0[Self::slot(t, 2)] = if case == "wrong-type" && index == 0 {
            2
        } else {
            5
        };
        let ty = self.table(&[]);
        self.ptr(Self::slot(t, 3), ty);
        if child {
            let v = self.vector(&[0; 4], 1, 4);
            self.ptr(Self::slot(t, 5), v);
            let field = self.field(1, "");
            self.ptr(v + 4, field);
        }
        t
    }
    fn finish(mut self, root: usize) -> Vec<u8> {
        put32(&mut self.0, 0, root as u32);
        self.0
    }
}
fn u32at(b: &[u8], p: usize) -> usize {
    u32::from_le_bytes(b[p..p + 4].try_into().unwrap()) as usize
}
fn put32(b: &mut [u8], p: usize, n: u32) {
    b[p..p + 4].copy_from_slice(&n.to_le_bytes());
}
fn put64(b: &mut [u8], p: usize, n: i64) {
    b[p..p + 8].copy_from_slice(&n.to_le_bytes());
}
fn slot(b: &[u8], t: usize, i: usize) -> usize {
    let v = (t as i64 - i32::from_le_bytes(b[t..t + 4].try_into().unwrap()) as i64) as usize;
    let o = u16::from_le_bytes(b[v + 4 + i * 2..v + 6 + i * 2].try_into().unwrap()) as usize;
    assert_ne!(o, 0, "fixture slot {i} absent");
    t + o
}
fn target(b: &[u8], p: usize) -> usize {
    p + u32at(b, p)
}
fn footer_start(b: &[u8]) -> usize {
    b.len() - 10 - u32at(b, b.len() - 10)
}
fn footer(b: &[u8]) -> usize {
    let p = footer_start(b);
    p + u32at(b, p)
}
fn block(b: &[u8]) -> usize {
    target(b, slot(b, footer(b), 3)) + 4
}
fn message(b: &[u8]) -> (usize, usize, usize, usize) {
    let block = block(b);
    let start = i64::from_le_bytes(b[block..block + 8].try_into().unwrap()) as usize;
    let metadata = u32at(b, block + 8);
    let msg = start + 8 + u32at(b, start + 8);
    let record = target(b, slot(b, msg, 2));
    (start, metadata, msg, record)
}
fn replace_footer(original: &[u8], case: &str) -> Vec<u8> {
    let mut f = Fb::new();
    let root = f.table(&[true, true, false, true, false]);
    f.0[Fb::slot(root, 0)..Fb::slot(root, 0) + 2]
        .copy_from_slice(&(if case == "footer-version" { 3u16 } else { 4 }).to_le_bytes());
    let schema = f.table(&[true, true, case == "schema-metadata", false]);
    f.ptr(Fb::slot(root, 1), schema);
    f.0[Fb::slot(schema, 0)..Fb::slot(schema, 0) + 2]
        .copy_from_slice(&(u16::from(case == "schema-endianness")).to_le_bytes());
    let fields = f.vector(&[0; 8], 2, 4);
    f.ptr(Fb::slot(schema, 1), fields);
    for i in 0..2 {
        let field = f.field(i, case);
        f.ptr(fields + 4 + i * 4, field);
    }
    if case == "schema-metadata" {
        let v = f.vector(&[0; 4], 1, 4);
        f.ptr(Fb::slot(schema, 2), v);
        let kv = f.table(&[true, true]);
        f.ptr(v + 4, kv);
        let key = f.string("key");
        f.ptr(Fb::slot(kv, 0), key);
        let value = f.string("value");
        f.ptr(Fb::slot(kv, 1), value);
    }
    let old = block(original);
    let blocks = f.vector(&original[old..old + 24], 1, 8);
    f.ptr(Fb::slot(root, 3), blocks);
    let f = f.finish(root);
    let mut b = original[..footer_start(original)].to_vec();
    b.extend_from_slice(&f);
    b.extend_from_slice(&(f.len() as u32).to_le_bytes());
    b.extend_from_slice(b"ARROW1");
    b
}
fn variadic(original: &[u8]) -> Vec<u8> {
    let (start, metadata, _, record) = message(original);
    let nodes = target(original, slot(original, record, 1));
    let buffers = target(original, slot(original, record, 2));
    let bl = block(original);
    let body = i64::from_le_bytes(original[bl + 16..bl + 24].try_into().unwrap());
    let mut f = Fb::new();
    let root = f.table(&[true, true, true, true, false]);
    f.0[Fb::slot(root, 0)..Fb::slot(root, 0) + 2].copy_from_slice(&4u16.to_le_bytes());
    f.0[Fb::slot(root, 1)] = 3;
    put64(&mut f.0, Fb::slot(root, 3), body);
    let r = f.table(&[true, true, true, false, true]);
    f.ptr(Fb::slot(root, 2), r);
    put64(&mut f.0, Fb::slot(r, 0), 3);
    let n = f.vector(
        &original[nodes + 4..nodes + 4 + u32at(original, nodes) * 16],
        u32at(original, nodes),
        8,
    );
    f.ptr(Fb::slot(r, 1), n);
    let v = f.vector(
        &original[buffers + 4..buffers + 4 + u32at(original, buffers) * 16],
        u32at(original, buffers),
        8,
    );
    f.ptr(Fb::slot(r, 2), v);
    let v = f.vector(&0i64.to_le_bytes(), 1, 8);
    f.ptr(Fb::slot(r, 4), v);
    let msg = f.finish(root);
    let new_metadata = (msg.len() + 8).next_multiple_of(8);
    let mut b = original[..start].to_vec();
    b.extend_from_slice(&[255; 4]);
    b.extend_from_slice(&(msg.len() as u32).to_le_bytes());
    b.extend_from_slice(&msg);
    b.resize(start + new_metadata, 0);
    b.extend_from_slice(&original[start + metadata..]);
    let bl = block(&b);
    put32(&mut b, bl + 8, new_metadata as u32);
    b
}
fn mutate(original: &[u8], case: &str) -> Vec<u8> {
    if [
        "footer-version",
        "schema-endianness",
        "positional-name",
        "wrong-type",
        "nullable",
        "field-children",
        "schema-metadata",
    ]
    .contains(&case)
    {
        return replace_footer(original, case);
    }
    if case == "variadic" {
        return variadic(original);
    }
    let mut b = original.to_vec();
    let bl = block(&b);
    let (start, metadata, msg, record) = message(&b);
    let nodes = target(&b, slot(&b, record, 1));
    let buffers = target(&b, slot(&b, record, 2));
    match case {
        "magic" => b[0] = 0,
        "footer-cap" => {
            let p = b.len() - 10;
            put32(&mut b, p, 262145);
        }
        "negative-block" => put64(&mut b, bl, -1),
        "block-out-of-file" => put64(&mut b, bl, i64::MAX / 2),
        "metadata-cap" => put32(&mut b, bl + 8, 262145),
        "body-cap" => put64(&mut b, bl + 16, 2 * 1048576),
        "message-continuation" => b[start] = 0,
        "message-length" => put32(&mut b, start + 4, metadata as u32),
        "message-version" => {
            let p = slot(&b, msg, 0);
            b[p..p + 2].copy_from_slice(&3u16.to_le_bytes());
        }
        "node-count" => put32(&mut b, nodes, 1),
        "buffer-out-of-body" => put64(&mut b, buffers + 4, 2 * 1048576),
        "null-validity" => {
            let off = i64::from_le_bytes(b[buffers + 4..buffers + 12].try_into().unwrap()) as usize;
            assert_eq!(
                i64::from_le_bytes(b[buffers + 12..buffers + 20].try_into().unwrap()),
                1
            );
            let validity = start + metadata + off;
            assert_eq!(b[validity] & 1, 1);
            b[validity] &= !1;
            assert_eq!(b[validity] & 1, 0);
        }
        "offsets-order" => {
            let off =
                i64::from_le_bytes(b[buffers + 20..buffers + 28].try_into().unwrap()) as usize;
            put32(&mut b, start + metadata + off + 4, 2);
            put32(&mut b, start + metadata + off + 8, 1);
        }
        "invalid-UTF8" => {
            let off =
                i64::from_le_bytes(b[buffers + 36..buffers + 44].try_into().unwrap()) as usize;
            b[start + metadata + off] = 255;
        }
        "offsets-alignment" => {
            let off = i64::from_le_bytes(b[buffers + 20..buffers + 28].try_into().unwrap());
            put64(&mut b, buffers + 20, off + 1);
        }
        _ => panic!("unselected case {case}"),
    }
    b
}
fn reject_case(
    source: &[u8],
    format: Format,
    name: &str,
    mutate: impl FnOnce(&[u8]) -> Vec<u8>,
    expected: &str,
) -> Result<()> {
    let (root, job) = fixture(source)?;
    let pool = pool();
    let cache = root.path().join("cache");
    create_at(&job, &cache, format, pool.clone())?;
    let original = std::fs::read(cache.join("records.bin"))?;
    let before = std::fs::read(cache.join("manifest.json"))?;
    let changed = mutate(&original);
    let mut manifest: Manifest = serde_json::from_slice(&before)?;
    manifest.artifact_bytes = changed.len() as u64;
    manifest.artifact_blake3 = blake3::hash(&changed).to_hex().to_string();
    let after = serde_json::to_vec(&manifest)?;
    let parent = std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    std::fs::create_dir_all(&parent)?;
    let evidence = tempfile::Builder::new()
        .prefix(&format!("g4-{name}-"))
        .tempdir_in(parent)?
        .keep();
    for (n, b) in [
        ("source.csv", source),
        ("original.bin", original.as_slice()),
        ("mutated.bin", changed.as_slice()),
        ("original-manifest.json", before.as_slice()),
        ("mutated-manifest.json", after.as_slice()),
        ("job.json", serde_json::to_vec(&job)?.as_slice()),
    ] {
        preserve_fixture(&evidence, n, b)?;
    }
    assert_ne!(original, changed, "{name}: mutation must change bytes");
    assert_malformed(&original, &changed, format, name);
    let differences = original
        .iter()
        .zip(&changed)
        .enumerate()
        .filter_map(|(i, (a, b))| (a != b).then_some(i))
        .collect::<Vec<_>>();
    preserve_fixture(
        &evidence,
        "mutation-proof.json",
        &serde_json::to_vec(
            &serde_json::json!({"case": name, "changed_offsets": differences, "original_length": original.len(), "mutated_length": changed.len(), "property_asserted": true}),
        )?,
    )?;
    std::fs::write(cache.join("records.bin"), &changed)?;
    std::fs::write(cache.join("manifest.json"), &after)?;
    std::fs::write(cache.join("keep"), b"caller sentinel")?;
    let result = prepared(job.clone(), Some(&cache), pool.clone());
    let error = match result {
        Err(error) => error,
        Ok(unexpected) => {
            let exported = identity(&unexpected);
            if let Ok((bytes, metadata)) = &exported {
                preserve_fixture(&evidence, "unexpected-prepared.bin", bytes)?;
                preserve_fixture(
                    &evidence,
                    "unexpected-metadata.json",
                    &serde_json::to_vec(metadata)?,
                )?;
            } else if let Err(error) = &exported {
                preserve_fixture(
                    &evidence,
                    "unexpected-export-error.txt",
                    format!("{error:#}").as_bytes(),
                )?;
            }
            drop(unexpected);
            clean(&job, &pool);
            assert_eq!(std::fs::read(cache.join("records.bin"))?, changed);
            assert_eq!(std::fs::read(cache.join("manifest.json"))?, after);
            assert_eq!(std::fs::read(cache.join("keep"))?, b"caller sentinel");
            panic!("{name}: corrupt artifact accepted; export and cleanup preserved");
        }
    };
    preserve_fixture(&evidence, "error.txt", format!("{error:#}").as_bytes())?;
    assert!(
        format!("{error:#}").contains(expected),
        "{name}: wrong first rejection: {error:#}"
    );
    clean(&job, &pool);
    assert_eq!(std::fs::read(cache.join("records.bin"))?, changed);
    assert_eq!(std::fs::read(cache.join("manifest.json"))?, after);
    assert_eq!(std::fs::read(cache.join("keep"))?, b"caller sentinel");
    drop(error);
    clean(&job, &pool);
    println!("G4 {name}: rejected {expected}; exact pool/temp/cache/publication checks passed");
    Ok(())
}
#[test]
fn selected_ipc_rejection_classes() -> Result<()> {
    // Footer-root-offset is the separately executed first regression (IPC1).
    for (name, expected) in [
        ("magic", "invalid IPC file magic"),
        ("footer-cap", "footer exceeds bound"),
        ("footer-version", "metadata V5"),
        ("schema-endianness", "endianness"),
        ("positional-name", "positional non-null"),
        ("wrong-type", "positional non-null"),
        ("nullable", "positional non-null"),
        ("field-children", "positional non-null"),
        ("schema-metadata", "metadata/features"),
        ("negative-block", "negative IPC block offset"),
        ("block-out-of-file", "escape data region"),
        ("metadata-cap", "message/body exceeds bound"),
        ("body-cap", "message/body exceeds bound"),
        ("message-continuation", "continuation framing"),
        ("message-length", "invalid IPC message length"),
        ("message-version", "length or version mismatch"),
        ("variadic", "compressed/variadic"),
        ("node-count", "node/buffer count mismatch"),
        ("buffer-out-of-body", "buffer escapes"),
        ("null-validity", "null validity bits"),
        ("offsets-order", "record batch decoding"),
        ("invalid-UTF8", "record batch decoding"),
        ("offsets-alignment", "record batch decoding"),
    ] {
        reject_case(
            b"id,value\n0,0007\n1,null\n",
            Format::ArrowIpcV1,
            name,
            |b| mutate(b, name),
            expected,
        )?;
    }
    Ok(())
}
#[test]
fn selected_compact_rejection_classes() -> Result<()> {
    for (name, expected) in [
        ("truncated-magic", "fill whole buffer"),
        (
            "truncated-header",
            "truncated compact snapshot block header",
        ),
        ("truncated-row", "truncated compact snapshot block"),
        ("truncated-footer", "fill whole buffer"),
        ("trailing-footer", "trailing bytes after compact"),
        ("record-count", "footer record count mismatch"),
        ("field-count", "field count mismatch"),
        ("field-length", "field length"),
    ] {
        reject_case(
            b"id,value\n0,0007\n1,null\n",
            Format::CompactRowsV1,
            name,
            |original| {
                let mut b = original.to_vec();
                match name {
                    "truncated-magic" => b.truncate(8),
                    "truncated-header" => b.truncate(20),
                    "truncated-row" => b.truncate(28),
                    "truncated-footer" => {
                        b.truncate(b.len() - 1);
                    }
                    "trailing-footer" => b.push(1),
                    "record-count" => {
                        let p = b.len() - 8;
                        put64(&mut b, p, 4);
                    }
                    "field-count" => put32(&mut b, 28, 1),
                    "field-length" => put32(&mut b, 32, u32::MAX),
                    _ => unreachable!(),
                }
                b
            },
            expected,
        )?;
    }
    Ok(())
}

#[test]
fn corrected_null_validity_rejection() -> Result<()> {
    reject_case(
        b"id,value\n0,0007\n1,null\n",
        Format::ArrowIpcV1,
        "null-validity",
        |b| mutate(b, "null-validity"),
        "null validity bits",
    )
}

fn i64at(b: &[u8], p: usize) -> i64 {
    i64::from_le_bytes(b[p..p + 8].try_into().unwrap())
}
fn assert_malformed(original: &[u8], b: &[u8], format: Format, name: &str) {
    if format == Format::CompactRowsV1 {
        match name {
            "truncated-magic" => assert!(b.len() < 16),
            "truncated-header" => assert!((16..24).contains(&b.len())),
            "truncated-row" => assert!(b.len() < 24 + u32at(b, 16)),
            "truncated-footer" => assert_eq!(b.len() + 1, original.len()),
            "trailing-footer" => assert_eq!(&b[..b.len() - 1], original),
            "record-count" => {
                assert_ne!(i64at(b, b.len() - 8), i64at(original, original.len() - 8))
            }
            "field-count" => assert_ne!(u32at(b, 28), 2),
            "field-length" => assert!(u32at(b, 32) > b.len()),
            _ => panic!("unselected property {name}"),
        }
        return;
    }
    if name == "magic" {
        assert_ne!(&b[..6], b"ARROW1");
        return;
    }
    if name == "footer-cap" {
        assert!(u32at(b, b.len() - 10) > 262144);
        return;
    }
    let f = arrow_ipc::root_as_footer(&b[footer_start(b)..b.len() - 10]).unwrap();
    let schema = f.schema().unwrap();
    let field = schema.fields().unwrap().get(0);
    match name {
        "footer-version" => assert_ne!(f.version(), arrow_ipc::MetadataVersion::V5),
        "schema-endianness" => assert_ne!(schema.endianness(), arrow_ipc::Endianness::Little),
        "positional-name" => assert_ne!(field.name(), Some("c0")),
        "wrong-type" => assert_ne!(field.type_type(), arrow_ipc::Type::Utf8),
        "nullable" => assert!(field.nullable()),
        "field-children" => assert!(!field.children().unwrap().is_empty()),
        "schema-metadata" => assert!(!schema.custom_metadata().unwrap().is_empty()),
        "negative-block" => assert!(f.recordBatches().unwrap().get(0).offset() < 0),
        "block-out-of-file" => assert!(f.recordBatches().unwrap().get(0).offset() > b.len() as i64),
        "metadata-cap" => assert!(f.recordBatches().unwrap().get(0).metaDataLength() > 262144),
        "body-cap" => assert!(f.recordBatches().unwrap().get(0).bodyLength() > 1048576),
        _ => {
            let (start, metadata, _, record) = message(b);
            if name == "message-continuation" {
                assert_ne!(&b[start..start + 4], &[255; 4]);
                return;
            }
            if name == "message-length" {
                assert!(u32at(b, start + 4) > metadata - 8);
                return;
            }
            let msg =
                arrow_ipc::root_as_message(&b[start + 8..start + 8 + u32at(b, start + 4)]).unwrap();
            let r = msg.header_as_record_batch().unwrap();
            let buffers = target(b, slot(b, record, 2));
            let body = start + metadata;
            match name {
                "message-version" => assert_ne!(msg.version(), arrow_ipc::MetadataVersion::V5),
                "variadic" => assert!(!r.variadicBufferCounts().unwrap().is_empty()),
                "node-count" => assert_ne!(r.nodes().unwrap().len(), 2),
                "buffer-out-of-body" => assert!(
                    r.buffers().unwrap().get(0).offset()
                        > f.recordBatches().unwrap().get(0).bodyLength()
                ),
                "null-validity" => {
                    let v = r.buffers().unwrap().get(0);
                    let p = body + v.offset() as usize;
                    assert_eq!(v.length(), 1);
                    assert_eq!(original[p] & 1, 1);
                    assert_eq!(b[p] & 1, 0);
                    assert_eq!(r.nodes().unwrap().get(0).null_count(), 0);
                    assert_eq!(&original[..p], &b[..p]);
                    assert_eq!(&original[p + 1..], &b[p + 1..]);
                }
                "offsets-order" => {
                    let p = body + i64at(b, buffers + 20) as usize;
                    assert!(u32at(b, p + 4) > u32at(b, p + 8));
                }
                "invalid-UTF8" => {
                    let v = r.buffers().unwrap().get(2);
                    assert!(std::str::from_utf8(
                        &b[body + v.offset() as usize..body + (v.offset() + v.length()) as usize]
                    )
                    .is_err());
                }
                "offsets-alignment" => assert_ne!(r.buffers().unwrap().get(1).offset() % 4, 0),
                _ => panic!("unselected property {name}"),
            }
        }
    }
}

#[test]
fn remaining_ipc_rejection_classes() -> Result<()> {
    for name in ["offsets-order", "invalid-UTF8", "offsets-alignment"] {
        reject_case(
            b"id,value\n0,0007\n1,null\n",
            Format::ArrowIpcV1,
            name,
            |b| mutate(b, name),
            "record batch decoding",
        )?;
    }
    Ok(())
}

#[test]
fn ipc_constructor_admission_and_eof_owners() -> Result<()> {
    let source = b"id,value\n0,0007\n1,null\n";
    let (root, job) = fixture(source)?;
    let creation_pool = pool();
    let cache = root.path().join("cache");
    create_at(&job, &cache, Format::ArrowIpcV1, creation_pool.clone())?;
    clean(&job, &creation_pool);
    let original = std::fs::read(cache.join("records.bin"))?;
    let before = std::fs::read(cache.join("manifest.json"))?;
    let manifest: Manifest = serde_json::from_slice(&before)?;
    let mut malformed = original.clone();
    let fs = footer_start(&original);
    put32(&mut malformed, fs, u32::MAX);
    assert_ne!(original, malformed);
    assert!(u32at(&malformed, fs) > malformed.len());
    let mut changed_manifest: Manifest = serde_json::from_slice(&before)?;
    changed_manifest.artifact_blake3 = blake3::hash(&malformed).to_hex().to_string();
    let parent = std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    std::fs::create_dir_all(&parent)?;
    let evidence = tempfile::Builder::new()
        .prefix("ipc-admission-")
        .tempdir_in(parent)?
        .keep();
    for (n, b) in [
        ("source.csv", source.as_slice()),
        ("job.json", serde_json::to_vec(&job)?.as_slice()),
        ("original.bin", original.as_slice()),
        ("mutated.bin", malformed.as_slice()),
        ("original-manifest.json", before.as_slice()),
        (
            "mutated-manifest.json",
            serde_json::to_vec(&changed_manifest)?.as_slice(),
        ),
    ] {
        preserve_fixture(&evidence, n, b)?;
    }
    let foot = arrow_ipc::root_as_footer(&original[fs..original.len() - 10]).unwrap();
    let f = original.len() - 10 - fs;
    let blocks = foot.recordBatches().unwrap();
    let l = blocks
        .iter()
        .map(|b| b.metaDataLength() as usize + b.bodyLength() as usize)
        .max()
        .unwrap();
    let required = [
        f + 65536,
        l + 63 + 4 * f + 128 * blocks.len() + 16384 * manifest.columns + 65536,
    ];
    preserve_fixture(
        &evidence,
        "requirements.json",
        &serde_json::to_vec(&required)?,
    )?;
    let bad_path = evidence.join("mutated.bin");
    for (seam, &requirement) in required.iter().enumerate() {
        for shared in [false, true] {
            for delta in [-1i64, 0, 1] {
                let pool = pool();
                let ctx = Context::with_memory_pool(
                    &job.resources,
                    Arc::new(AtomicBool::new(false)),
                    Arc::new(|_| {}),
                    pool.clone(),
                )?;
                let base = pool.usage().reserved_bytes;
                let local = ctx.diagnostics()["workspace_reserved_bytes"]
                    .as_u64()
                    .unwrap();
                let available = (requirement as i64 + delta) as u64;
                let hold = if shared {
                    pool.usage().limit_bytes - base - available
                } else {
                    ctx.memory as u64 / 2 - local - available
                };
                let mut held = Reservation::new(&ctx);
                if shared {
                    pool.acquire(hold)?;
                } else {
                    held.resize(hold as usize)?;
                }
                let baseline = pool.usage().reserved_bytes;
                let path = if seam == 0 {
                    bad_path.clone()
                } else {
                    cache.join("records.bin")
                };
                let result =
                    ipc::Reader::new(ctx.artifact_reader(File::open(&path)?), &manifest, &ctx);
                let admitted = if seam == 0 {
                    result
                        .as_ref()
                        .err()
                        .is_some_and(|e| e.to_string() == "invalid IPC footer verification")
                } else {
                    result.is_ok()
                };
                let message = result.as_ref().err().map(|e| format!("{e:#}"));
                let admission_kind = result
                    .as_ref()
                    .err()
                    .and_then(|e| e.downcast_ref::<crate::resources::MemoryAdmission>())
                    .map(|e| match e {
                        crate::resources::MemoryAdmission::Local => "local",
                        crate::resources::MemoryAdmission::Shared { .. } => "shared",
                    });
                if delta < 0 {
                    assert_eq!(
                        admission_kind,
                        Some(if shared { "shared" } else { "local" })
                    );
                }
                drop(result);
                preserve_fixture(
                    &evidence,
                    &format!("seam-{seam}-{shared}-{delta}.json"),
                    &serde_json::to_vec(
                        &serde_json::json!({"admitted":admitted,"error":message,"required":requirement,"available":available}),
                    )?,
                )?;
                assert_eq!(pool.usage().reserved_bytes, baseline);
                assert_eq!(
                    admitted,
                    delta >= 0,
                    "seam={seam}/shared={shared}/delta={delta}: {message:?}"
                );
                if delta < 0 {
                    assert!(message.is_some());
                }
                if shared {
                    pool.release(hold);
                } else {
                    drop(held);
                }
                let retry =
                    ipc::Reader::new(ctx.artifact_reader(File::open(&path)?), &manifest, &ctx);
                if seam == 0 {
                    assert_eq!(
                        retry.err().unwrap().to_string(),
                        "invalid IPC footer verification"
                    );
                } else {
                    let mut reader = retry?;
                    assert_eq!(pool.usage().reserved_bytes, base + requirement as u64);
                    let mut count = 0;
                    while reader.next_fields()?.is_some() {
                        count += 1;
                    }
                    assert_eq!(count, manifest.records);
                    assert!(reader.next_fields()?.is_none());
                    assert_eq!(pool.usage().reserved_bytes, base + requirement as u64);
                    drop(reader);
                }
                assert_eq!(pool.usage().reserved_bytes, base);
                drop(ctx);
                clean(&job, &pool);
                assert_eq!(std::fs::read(cache.join("records.bin"))?, original);
                assert_eq!(std::fs::read(cache.join("manifest.json"))?, before);
                println!("admission seam={seam} shared={shared} delta={delta} required={} retry/EOF/release passed",requirement);
            }
        }
    }
    Ok(())
}
