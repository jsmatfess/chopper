//! Retained path capacity, typed denial and publication cleanup on native/WASI.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

fn path_controls() -> Result<serde_json::Value> {
    let filename = "\u{754c}-part-00000001.csv.zst";
    let mut cases = Vec::new();
    for parent in [
        "",
        "/",
        "relative/\u{754c}",
        "relative/\u{754c}/",
        "parent\\child",
    ] {
        let parent = Path::new(parent);
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let path = PublicationPath::join(
            parent,
            filename,
            Reservation::for_workspace(workspace.clone()),
        )?;
        ensure!(
            path.as_ref() == parent.join(filename),
            "joined path semantics changed"
        );
        ensure!(
            workspace.used() == path.path.capacity() as u64
                && path.path.capacity() >= path.path.as_os_str().len(),
            "path lost capacity grant"
        );
        cases.push(json!({"parent":parent.to_string_lossy(),"result":path.path.to_string_lossy(),"retained_capacity_bytes":workspace.used()}));
        drop(path);
        ensure!(workspace.used() == 0, "path shape leaked");
    }
    #[cfg(windows)]
    for parent in [
        r"C:\root\directory",
        r"\\?\C:\root\directory",
        r"\\server\share\directory",
    ] {
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let path = PublicationPath::join(
            Path::new(parent),
            filename,
            Reservation::for_workspace(workspace.clone()),
        )?;
        ensure!(
            path.as_ref() == Path::new(parent).join(filename)
                && workspace.used() == path.path.capacity() as u64,
            "Windows prefix join changed"
        );
        drop(path);
        ensure!(workspace.used() == 0, "Windows path owner leaked");
    }
    let parent = Path::new("relative/\u{754c}");
    let required = parent.as_os_str().len() + 1 + filename.len();
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * required, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let attempt = PublicationPath::join(
                parent,
                filename,
                Reservation::for_workspace(workspace.clone()),
            );
            if limit < required {
                let error = attempt.err().context("path edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "path denial lost type"
                );
            } else {
                drop(attempt?);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "path edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(required as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let mut competitor = Reservation::for_workspace(workspace.clone());
    competitor.resize(1)?;
    let error = PublicationPath::join(
        parent,
        filename,
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("competing path accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == 1,
        "competing path denial leaked"
    );
    drop(competitor);
    drop(PublicationPath::join(
        parent,
        filename,
        Reservation::for_workspace(workspace.clone()),
    )?);
    ensure!(pool.usage().reserved_bytes == 0, "path retry leaked");
    for name in [
        "",
        ".",
        "..",
        "../escape",
        "child/file",
        "child\\file",
        "C:relative",
        "nul\0byte",
    ] {
        ensure!(
            PublicationPath::join(parent, name, Reservation::for_workspace(workspace.clone()))
                .is_err()
                && workspace.used() == 0,
            "invalid publication component accepted"
        );
    }
    let pool = Arc::new(MemoryPool::new(2 * required as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = PublicationPath::join(
        parent,
        filename,
        Reservation::for_workspace(workspace.clone()),
    )?;
    let second = PublicationPath::join(
        parent,
        filename,
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        pool.usage().reserved_bytes == (first.path.capacity() + second.path.capacity()) as u64,
        "concurrent paths lost grant"
    );
    let remaining = second.path.capacity() as u64;
    drop(first);
    ensure!(
        pool.usage().reserved_bytes == remaining,
        "independent path released early"
    );
    drop(second);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "concurrent path owners leaked"
    );
    Ok(
        json!({"cases":cases,"windows_prefix_controls":cfg!(windows),"local_shared_edge_checks":6,"competitor_retry":true,"invalid_components_rejected":8,"independent_paths":2,"final_reserved_bytes":0}),
    )
}

fn filesystem_controls() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let root = dir.path().to_owned();
    let pool = Arc::new(MemoryPool::new(1024 * 1024));
    let workspace = Arc::new(Workspace::shared(1024 * 1024, pool.clone()));
    let path = PublicationPath::join(
        &root,
        "\u{754c}.csv",
        Reservation::for_workspace(workspace.clone()),
    )?;
    let charge = workspace.used();
    let mut file = File::create(&path)?;
    file.write_all(b"exact bytes")?;
    file.flush()?;
    ensure!(
        std::fs::metadata(&path)?.len() == 11 && workspace.used() == charge,
        "file operations released live path"
    );
    drop(path);
    ensure!(workspace.used() == 0, "path outlived allocation");
    drop(file);
    let missing = root.join("missing");
    let path = PublicationPath::join(
        &missing,
        "failure.csv",
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        File::create(&path).is_err() && workspace.used() == path.path.capacity() as u64,
        "file creation failure lost live path"
    );
    drop(path);
    ensure!(pool.usage().reserved_bytes == 0, "failed file path leaked");
    dir.close()?;
    ensure!(!root.try_exists()?, "path fixture directory leaked");
    Ok(
        json!({"file_create_metadata_and_drop":true,"creation_failure_retains_owner":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

fn publication_controls() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let root = dir.path().to_owned();
    let input = root.join("input.csv");
    std::fs::write(&input, "id,key\n1,\u{754c}\n2,a\n")?;
    let mut cases = Vec::new();
    for compression in [Compression::None, Compression::Gzip, Compression::Zip] {
        let output = root.join(format!("result-界-{compression:?}"));
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            compression,
            random_seed: Some("publication-path-contract".into()),
            resources: chopper_core::Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                temp_dir: Some(root.to_string_lossy().into_owned()),
                ..Default::default()
            },
            ..Default::default()
        };
        let limit = 64 * 1024 * 1024;
        let pool = Arc::new(MemoryPool::new(limit));
        let cancel = Arc::new(AtomicBool::new(false));
        let prepared = crate::engine::prepare_with_memory_pool(
            job,
            cancel.clone(),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let retained = pool.usage().reserved_bytes;
        let destination_capacity = std::path::absolute(&output)?.capacity() as u64;
        let stage = prepared.ctx.staging_directory(&root)?;
        let stage_grant = pool.usage().reserved_bytes - retained;
        let manifest_capacity = stage.path().as_os_str().len() + 1 + "manifest.jsonl".len();
        drop(stage);
        let mut pressure =
            Reservation::for_workspace(Arc::new(Workspace::shared(limit as usize, pool.clone())));
        pressure.resize(
            (limit - retained - destination_capacity - stage_grant - manifest_capacity as u64 + 1)
                as usize,
        )?;
        let held = pool.usage().reserved_bytes;
        let error = execute(&prepared)
            .err()
            .context("publication path denial succeeded")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && format!("{error:#}").contains("publication path")
                && pool.usage().reserved_bytes == held
                && !output.try_exists()?,
            "publication path denial leaked or changed type"
        );
        ensure!(
            !std::fs::read_dir(&root)?.any(|entry| entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".chopper-staging-")),
            "path denial left staging"
        );
        drop(pressure);
        cancel.store(true, Ordering::Relaxed);
        ensure!(
            execute(&prepared).is_err() && !output.try_exists()?,
            "cancelled path published"
        );
        cancel.store(false, Ordering::Relaxed);
        execute(&prepared)?;
        ensure!(
            pool.usage().reserved_bytes == retained,
            "published paths retained grants"
        );
        let text = std::fs::read_to_string(output.join("manifest.jsonl"))?;
        let records = text
            .lines()
            .map(serde_json::from_str::<serde_json::Value>)
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let record = records
            .iter()
            .find(|r| r["type"] == "output")
            .context("missing published chunk")?;
        let name = record["path"].as_str().context("missing output name")?;
        let decoded = match compression {
            Compression::None => std::fs::read(output.join(name))?,
            Compression::Gzip => {
                let mut bytes = Vec::new();
                flate2::read::GzDecoder::new(File::open(output.join(name))?)
                    .read_to_end(&mut bytes)?;
                bytes
            }
            Compression::Zip => {
                let mut archive = zip::ZipArchive::new(File::open(output.join("outputs.zip"))?)?;
                let mut bytes = Vec::new();
                archive.by_name(name)?.read_to_end(&mut bytes)?;
                bytes
            }
        };
        ensure!(
            decoded == "id,key\n1,\u{754c}\n2,a\n".as_bytes(),
            "publication paths changed output CSV bytes"
        );
        drop(prepared);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "path publication context leaked"
        );
        cases.push(json!({"compression":compression,"typed_path_denial":true,"staging_removed":true,"cancelled_no_publication":true,"retry_csv_equal":true,"final_reserved_bytes":0}));
    }
    dir.close()?;
    ensure!(!root.try_exists()?, "publication path fixture leaked");
    Ok(json!({"cases":cases,"fixture_directory_removed":true,"final_reserved_bytes":0}))
}

pub(crate) fn run() -> Result<serde_json::Value> {
    Ok(
        json!({"contract":"publication-path-capacity-contract-v1","paths":path_controls()?,"filesystem":filesystem_controls()?,"publication":publication_controls()?}),
    )
}
#[cfg(test)]
#[test]
fn publication_path_capacity_and_lifetimes() -> Result<()> {
    println!("CHOPPER_PUBLICATION_PATH_CONTRACT {}", run()?);
    Ok(())
}
