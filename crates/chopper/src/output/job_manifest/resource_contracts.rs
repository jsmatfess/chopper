//! Current manifest schema, construction admission and serialization lifetime.
use super::*;
use crate::engine::{
    Analysis, ColumnValues, ExecutionRng, ExecutionSummary, ReplayGuarantee, StageStats,
};
use crate::resources::{MemoryAdmission, MemoryPool};
use chopper_core::{Allocation, FullShuffleAlgorithm, FullShuffleRng, Shuffle, ALGORITHM_VERSION};
use serde::ser::{Error as _, SerializeStruct};
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc,
};

fn fixture() -> (Job, Analysis) {
    let allocations = vec![
        Allocation {
            name: "\u{754c} treatment".into(),
            percent: "33.333333".into(),
        },
        Allocation {
            name: "control".into(),
            percent: "66.666667".into(),
        },
    ];
    let mut job = Job {
        input: "input/\u{754c}\"\\data.csv".into(),
        output: "output/\u{e9}".into(),
        zip_member: Some("nested/\u{754c}.csv".into()),
        random_seed: Some("seed\n\u{754c}".into()),
        operations: vec![
            Operation::Balanced { files: 3 },
            Operation::Interleaved { files: 4 },
            Operation::Partition {
                columns: vec![Column::Index(0), Column::Name("\u{754c}".into())],
            },
            Operation::Assign {
                groups: allocations.clone(),
                strata: vec![Column::Name("stratum".into())],
            },
            Operation::AssignProbabilistic {
                groups: allocations,
                strata: Vec::new(),
            },
        ],
        ..Job::default()
    };
    for strategy in [Shuffle::Uniform, Shuffle::Auto, Shuffle::FisherYates] {
        job.operations.push(Operation::Shuffle { strategy });
    }
    job.input_csv.delimiter = ';';
    job.input_csv.quote = '\u{754c}';
    job.input_csv.escape = Some('\\');
    job.output_csv.encoding = "utf-16le".into();
    job.output_csv.bom = true;
    job.limits.bytes = Some(u64::MAX);
    job.limits.rows = Some(1024);
    job.limits.compressed_bytes = Some(2048);
    job.resources.temp_dir = Some("scratch/\u{e9}".into());
    job.resources.temp_bytes = Some(1024 * 1024);
    job.resources.grouping = chopper_core::Grouping::Sort;
    let analysis = Analysis { algorithm_version: Analysis::algorithm_version_for(&job),
        column_values: vec![ColumnValues {
            column: 0,
            values: ["\u{754c}".into(), "quoted\ntext".into()]
                .into_iter()
                .collect(),
            frequencies: Default::default(),
            truncated: true,
        }]
        .into(),
        seed: "seed\n\u{754c}".into(),
        rows: u64::MAX,
        columns: 2,
        header: Some(vec!["\u{754c}\"\\".into(), "".into()].into()),
        preview: vec![
            vec!["\u{754c}\n\"\\".repeat(128), "second".into()],
            Vec::new(),
        ]
        .into(),
        logical_digest: "digest".into(),
        groups: 3,
        output_files: 5,
        output_csv_bytes: 1024,
        largest_record_bytes: 1024,
        temp_bytes: 4096,
        peak_temp_bytes: 8192,
        memory_budget_bytes: 32 * 1024 * 1024,
        workers: 2,
        analysis_seconds: 1.25,
        timings: [("\u{754c} stage".into(), 0.5)]
            .into_iter()
            .collect::<std::collections::BTreeMap<_, _>>()
            .into(),
        diagnostics: json!({"nullable":null,"array":[true,false,17,-4,0.125,{"nested":"\u{754c}\n\""}],"empty_array":[],"empty_object":{}}).into(),
        stages: vec![StageStats {
            operation: 0,
            input_groups: 1,
            output_groups: 3,
            smallest_group: 0,
            largest_group: 2,
            empty_groups: 1,
        }]
        .into(),
        warnings: vec!["warning\n\u{754c}".into()].into(),
        accuracy: "exact".into(),
        auto_plan: None,
        execution: Some(ExecutionSummary {

            plan_version: 1,
            rng_version: ExecutionRng::Blake3CounterV1,
            replay_guarantee: ReplayGuarantee::PreparedSnapshotOnly,
            records: 7,
            plan_digest_blake3: [255; 32],
        }),
    };
    (job, analysis)
}

fn original(job: &Job, analysis: &Analysis) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(
        &json!({"type":"job","schema_version":1,"algorithm_version":ALGORITHM_VERSION,"config":job,"analysis":analysis,"application_version":env!("CARGO_PKG_VERSION")}),
    )?)
}

fn tree_controls() -> Result<serde_json::Value> {
    let (mut job, mut analysis) = fixture();
    let mut cases = Vec::new();
    for flexible in [false, true] {
        job.full_shuffle_rng = FullShuffleRng::Blake3CounterV1;
        job.full_shuffle_algorithm = FullShuffleAlgorithm::AdaptiveV1;
        analysis.algorithm_version = Analysis::algorithm_version_for(&job);
        let serialized = serde_json::to_value(&analysis)?;
        let decoded: Analysis = serde_json::from_value(serialized)?;
        ensure!(
            decoded.algorithm_version == analysis.algorithm_version,
            "analysis algorithm round trip changed"
        );
        ensure!(
            analysis.clone().text_reserved_bytes() == analysis.text_reserved_bytes(),
            "static algorithm version changed text admission"
        );
        if !flexible {
            analysis.execution = None;
        }
        for compression in [
            Compression::None,
            Compression::Gzip,
            Compression::Zstd,
            Compression::Zip,
        ] {
            job.compression = compression;
            let expected = original(&job, &analysis)?;
            let source = JobRecord::new(&job, &analysis);
            let allowance = source.serialize(estimate::Estimator)?.bytes;
            let workspace = Arc::new(Workspace::new(8 * 1024 * 1024));
            let tree = ManifestTree::build(
                &job,
                &analysis,
                Reservation::for_workspace(workspace.clone()),
            )?;
            let retained = tree.value.json_capacity()?;
            ensure!(
                tree.value["algorithm_version"] == tree.value["analysis"]["algorithm_version"],
                "analysis/manifest algorithm mismatch"
            );
            ensure!(
                serde_json::to_vec(&tree)? == expected
                    && retained > 0
                    && workspace.used() == retained as u64
                    && retained <= allowance,
                "manifest bytes/capacity changed"
            );
            drop(tree);
            ensure!(workspace.used() == 0, "manifest probe leaked");
            cases.push(json!({"flexible":flexible,"compression":compression,"allowance_bytes":allowance,"retained_bytes":retained,"serialized_bytes":expected.len(),"manifest_blake3":blake3::hash(&expected).to_hex().as_str()}));
        }
    }
    // Restore the richest schema, including execution's fixed array and enums.
    let (job, analysis) = fixture();
    let expected = original(&job, &analysis)?;
    let source = JobRecord::new(&job, &analysis);
    let allowance = source.serialize(estimate::Estimator)?.bytes;
    let probe = Arc::new(Workspace::new(8 * 1024 * 1024));
    let tree = ManifestTree::build(&job, &analysis, Reservation::for_workspace(probe.clone()))?;
    let retained = probe.used();
    drop(tree);
    for shared in [false, true] {
        for limit in [allowance - 1, allowance, allowance + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * allowance, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let attempt = ManifestTree::build(
                &job,
                &analysis,
                Reservation::for_workspace(workspace.clone()),
            );
            if limit < allowance {
                let error = attempt.err().context("manifest edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "manifest denial lost type"
                );
            } else {
                let tree = attempt?;
                ensure!(
                    serde_json::to_vec(&tree)? == expected,
                    "edge changed manifest"
                );
                drop(tree);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "manifest edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(allowance as u64));
    let workspace = Arc::new(Workspace::shared(2 * allowance, pool.clone()));
    let mut competitor = Reservation::for_workspace(workspace.clone());
    competitor.resize(1)?;
    let error = ManifestTree::build(
        &job,
        &analysis,
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("competing manifest accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == 1,
        "manifest competitor rollback changed"
    );
    drop(competitor);
    drop(ManifestTree::build(
        &job,
        &analysis,
        Reservation::for_workspace(workspace.clone()),
    )?);
    ensure!(pool.usage().reserved_bytes == 0, "manifest retry leaked");

    let pool = Arc::new(MemoryPool::new(2 * allowance as u64));
    let workspace = Arc::new(Workspace::shared(2 * allowance, pool.clone()));
    let first = ManifestTree::build(
        &job,
        &analysis,
        Reservation::for_workspace(workspace.clone()),
    )?;
    let second = ManifestTree::build(
        &job,
        &analysis,
        Reservation::for_workspace(workspace.clone()),
    )?;
    drop(job);
    drop(analysis);
    ensure!(
        workspace.used() == 2 * retained,
        "source drop released independent manifest trees"
    );
    struct Writer {
        workspace: Arc<Workspace>,
        held: u64,
        fail: bool,
    }
    impl Write for Writer {
        fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
            assert_eq!(self.workspace.used(), self.held);
            if self.fail {
                Err(std::io::Error::other("injected manifest write failure"))
            } else {
                Ok(b.len())
            }
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    for fail in [false, true] {
        let mut writer = Writer {
            workspace: workspace.clone(),
            held: 2 * retained,
            fail,
        };
        ensure!(
            serde_json::to_writer(&mut writer, &first).is_err() == fail,
            "manifest serialization fault changed"
        );
    }
    drop(first);
    ensure!(
        workspace.used() == retained,
        "other manifest released early"
    );
    drop(second);
    ensure!(pool.usage().reserved_bytes == 0, "manifest owners leaked");
    Ok(
        json!({"cases":cases,"rich_schema_allowance_bytes":allowance,"rich_schema_retained_bytes":retained,"rich_schema_manifest_blake3":blake3::hash(&expected).to_hex().as_str(),"local_shared_edge_checks":6,"competitor_retry":true,"independent_trees":2,"serialization_failure_retains_owner":true,"final_reserved_bytes":0}),
    )
}

fn failure_controls() -> Result<serde_json::Value> {
    struct Passes<'a>(&'a AtomicUsize);
    impl Serialize for Passes<'_> {
        fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
            self.0.fetch_add(1, Ordering::Relaxed);
            s.serialize_str("value")
        }
    }
    let calls = AtomicUsize::new(0);
    let workspace = Arc::new(Workspace::new(0));
    let error = ManifestTree::from_serializable(
        &Passes(&calls),
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("manifest construction admitted at zero")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Local)
        ) && calls.load(Ordering::Relaxed) == 1
            && workspace.used() == 0,
        "denial ran JSON construction"
    );
    struct Failure<'a>(&'a AtomicUsize);
    impl Serialize for Failure<'_> {
        fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
            let pass = self.0.fetch_add(1, Ordering::Relaxed);
            let mut object = s.serialize_struct("Failure", 1)?;
            object.serialize_field("payload", "partially constructed Unicode \u{754c}")?;
            if pass == 1 {
                return Err(S::Error::custom(
                    "injected second-pass construction failure",
                ));
            }
            object.end()
        }
    }
    let calls = AtomicUsize::new(0);
    let workspace = Arc::new(Workspace::new(1024 * 1024));
    let error = ManifestTree::from_serializable(
        &Failure(&calls),
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("construction failure ignored")?;
    ensure!(
        error
            .to_string()
            .contains("second-pass construction failure")
            && calls.load(Ordering::Relaxed) == 2
            && workspace.used() == 0,
        "partial manifest tree leaked"
    );
    struct DisplayOnly;
    impl std::fmt::Display for DisplayOnly {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.write_str("unsupported")
        }
    }
    impl Serialize for DisplayOnly {
        fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
            s.collect_str(self)
        }
    }
    ensure!(
        ManifestTree::from_serializable(
            &DisplayOnly,
            Reservation::for_workspace(workspace.clone())
        )
        .is_err()
            && workspace.used() == 0,
        "unsupported allocating serializer accepted"
    );
    struct Overflow;
    impl Serialize for Overflow {
        fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
            serde::ser::SerializeSeq::end(s.serialize_seq(Some(usize::MAX))?)
        }
    }
    let error =
        ManifestTree::from_serializable(&Overflow, Reservation::for_workspace(workspace.clone()))
            .err()
            .context("manifest capacity overflow accepted")?;
    ensure!(
        error.to_string().contains("capacity overflow") && workspace.used() == 0,
        "overflow preflight leaked"
    );
    #[derive(Serialize)]
    enum DataVariant {
        Newtype(u64),
    }
    ensure!(
        ManifestTree::from_serializable(
            &DataVariant::Newtype(1),
            Reservation::for_workspace(workspace.clone())
        )
        .is_err()
            && workspace.used() == 0,
        "unsupported data enum accepted"
    );
    let numeric_keys = [(1u64, "value")]
        .into_iter()
        .collect::<std::collections::BTreeMap<_, _>>();
    ensure!(
        ManifestTree::from_serializable(
            &numeric_keys,
            Reservation::for_workspace(workspace.clone())
        )
        .is_err()
            && workspace.used() == 0,
        "non-string manifest map keys accepted"
    );
    Ok(
        json!({"denial_runs_only_preflight":true,"partial_construction_failure_cleanup":true,"unsupported_display_rejected":true,"preflight_overflow_rejected":true,"unsupported_data_enum_rejected":true,"non_string_keys_rejected":true,"final_reserved_bytes":0}),
    )
}

fn publication_controls() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let directory = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let directory = tempfile::tempdir()?;
    let root = directory.path().to_owned();
    let input = root.join("input.csv");
    std::fs::write(&input, "id,label\n1,\u{754c}\n2,quoted\n")?;
    let output = root.join("result");
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        output: output.to_string_lossy().into_owned(),
        random_seed: Some("manifest-contract".into()),
        resources: chopper_core::Resources {
            workers: 1,
            memory_mb: 32.into(),
            max_record_bytes: 1024 * 1024,
            temp_dir: Some(root.to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    let limit = 16 * 1024 * 1024;
    let pool = Arc::new(MemoryPool::new(limit));
    let cancel = Arc::new(AtomicBool::new(false));
    let prepared = crate::engine::prepare_with_memory_pool(
        job,
        cancel.clone(),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let retained = pool.usage().reserved_bytes;
    let allowance = JobRecord::new(&prepared.job, &prepared.analysis)
        .serialize(estimate::Estimator)?
        .bytes;
    ensure!(
        allowance > 16 * 1024,
        "fixture manifest does not force construction denial"
    );
    let mut pressure =
        Reservation::for_workspace(Arc::new(Workspace::shared(limit as usize, pool.clone())));
    pressure.resize((limit - retained - 16 * 1024) as usize)?;
    let held = pool.usage().reserved_bytes;
    let error = execute(&prepared)
        .err()
        .context("pressured manifest published")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && pool.usage().reserved_bytes == held
            && !output.try_exists()?,
        "manifest denial leaked or lost type"
    );
    ensure!(
        !std::fs::read_dir(&root)?.any(|entry| entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".chopper-staging-")),
        "denied manifest retained staging"
    );
    drop(pressure);
    cancel.store(true, Ordering::Relaxed);
    ensure!(
        execute(&prepared).is_err() && !output.try_exists()?,
        "cancelled manifest published"
    );
    cancel.store(false, Ordering::Relaxed);
    execute(&prepared)?;
    let manifest = std::fs::read(output.join("manifest.jsonl"))?;
    let line = manifest
        .split(|b| *b == b'\n')
        .next()
        .context("empty published manifest")?;
    ensure!(
        line == original(&prepared.job, &prepared.analysis)?,
        "real publication changed canonical job record bytes"
    );
    ensure!(
        pool.usage().reserved_bytes == retained,
        "published manifest tree outlived serialization"
    );
    drop(prepared);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "publication context leaked"
    );
    directory.close()?;
    ensure!(!root.try_exists()?, "manifest fixture leaked");
    Ok(
        json!({"construction_shared_denial":true,"denial_staging_cleanup":true,"cancelled_no_publication":true,"fresh_retry_published":true,"canonical_job_record_bytes_equal":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

pub(crate) fn run() -> Result<serde_json::Value> {
    Ok(
        json!({"contract":"job-manifest-tree-admission-contract-v1","trees":tree_controls()?,"failures":failure_controls()?,"publication":publication_controls()?}),
    )
}
#[cfg(test)]
#[test]
fn job_manifest_tree_admission_and_lifetimes() -> Result<()> {
    println!("CHOPPER_JOB_MANIFEST_CONTRACT {}", run()?);
    Ok(())
}
