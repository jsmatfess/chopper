//! ZIP input preflight, parser admission and borrowed-member ownership.
use super::*;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod codec_contracts;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

pub(super) fn consume<T>(
    mut file: File,
    job: &Job,
    buffer: Reservation,
    consume: impl FnOnce(Box<dyn Read + '_>) -> Result<T>,
) -> Result<T> {
    let memory = job
        .resources
        .memory_mb
        .as_mib()
        .map_or_else(|| buffer.effective_memory_bytes(), |mb| mb * 1024 * 1024);
    check_zip_directory(&mut file, memory / 8, buffer.sibling())?;
    // This grant is declared before the archive, so archive metadata drops
    // before its allowance even though ZipArchive drops its reader first.
    let mut readers = buffer.sibling();
    let mut metadata = buffer.sibling();
    let mut denial = None;
    let archive =
        zip::ZipArchive::new_with_metadata_budget(InputBuffer::new(file, 8192, buffer)?, |bytes| {
            metadata.resize(bytes).map_err(|error| {
                denial = Some(error);
                std::io::Error::new(
                    std::io::ErrorKind::OutOfMemory,
                    "ZIP metadata admission denied",
                )
            })
        });
    if let Some(error) = denial {
        return Err(error);
    }
    let mut archive = archive?;
    // by_index constructs a reader even while looking up names. At most one
    // member is live at a time; this grant outlives archive/member destruction.
    // Keep legacy selection/error behavior, including unrelated bad members.
    readers.resize(reader_capacity())?;
    let index = if let Some(member) = &job.zip_member {
        let mut found = None;
        for i in 0..archive.len() {
            if archive.by_index(i)?.name() == member {
                ensure!(found.is_none(), "duplicate ZIP member name");
                found = Some(i);
            }
        }
        found.context("selected ZIP member was not found")?
    } else {
        let mut found = None;
        for i in 0..archive.len() {
            let member = archive.by_index(i)?;
            if !member.is_dir()
                && member.name().as_bytes()[member.name().len().saturating_sub(4)..]
                    .eq_ignore_ascii_case(b".csv")
            {
                ensure!(
                    found.is_none(),
                    "ZIP has multiple CSV members; set zip_member"
                );
                found = Some(i);
            }
        }
        found.context("ZIP has no CSV member; set zip_member explicitly")?
    };
    let member = archive.by_index(index)?;
    ensure!(!member.is_dir(), "selected ZIP member is a directory");
    ensure!(
        matches!(
            member.compression(),
            zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated
        ),
        "ZIP input supports Stored and Deflate members"
    );
    consume(Box::new(member))
}

fn reader_capacity() -> usize {
    zip::read::chopper_reader_container_bytes()
        + std::mem::size_of::<miniz_oxide::inflate::stream::InflateState>()
}

fn check_zip_directory(file: &mut File, budget: u64, mut buffer: Reservation) -> Result<()> {
    let size = file.metadata()?.len();
    let tail_len = size.min(65557) as usize;
    file.seek(SeekFrom::End(-(tail_len as i64)))?;
    let mut tail = Vec::new();
    buffer.reserve_vec(&mut tail, tail_len)?;
    tail.resize(tail_len, 0);
    file.read_exact(&mut tail)?;
    let pos = (0..tail.len().saturating_sub(21))
        .rev()
        .find(|&p| {
            tail[p..].starts_with(b"PK\x05\x06")
                && p + 22 + u16::from_le_bytes(tail[p + 20..p + 22].try_into().unwrap()) as usize
                    == tail.len()
        })
        .context("ZIP end directory is missing")?;
    ensure!(
        tail[pos + 4..pos + 8] == [0, 0, 0, 0],
        "multi-volume ZIP is unsupported"
    );
    let mut count = u16::from_le_bytes(tail[pos + 10..pos + 12].try_into().unwrap()) as u64;
    let mut length = u32::from_le_bytes(tail[pos + 12..pos + 16].try_into().unwrap()) as u64;
    if count == 65535 || length == u32::MAX as u64 {
        let end_offset = size - tail_len as u64 + pos as u64;
        ensure!(end_offset >= 20, "missing ZIP64 locator");
        file.seek(SeekFrom::Start(end_offset - 20))?;
        let mut locator = [0; 20];
        file.read_exact(&mut locator)?;
        ensure!(&locator[..4] == b"PK\x06\x07", "missing ZIP64 locator");
        file.seek(SeekFrom::Start(u64::from_le_bytes(
            locator[8..16].try_into().unwrap(),
        )))?;
        let mut end = [0; 56];
        file.read_exact(&mut end)?;
        ensure!(&end[..4] == b"PK\x06\x06", "invalid ZIP64 end record");
        count = u64::from_le_bytes(end[32..40].try_into().unwrap());
        length = u64::from_le_bytes(end[40..48].try_into().unwrap());
    }
    ensure!(
        length.saturating_add(count.saturating_mul(512)) <= budget,
        "ZIP input directory exceeds metadata budget; increase memory_mb"
    );
    file.seek(SeekFrom::Start(0))?;
    Ok(())
}
