//! Admission for the pinned flate2/miniz gzip reader, including header parsing.
use super::*;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

type Decoder<R> = flate2::read::MultiGzDecoder<InputBuffer<R>>;

struct Reader<R> {
    decoder: Decoder<R>,
    // Field order keeps the grant alive through decoder and input destruction.
    _codec: Reservation,
}

// flate2 1.1.10's miniz backend owns one boxed InflateState (all nested
// storage is inline), plus its read adapter's fixed 32 KiB boxed buffer.
// Header extra is u16-sized; filename/comment each stop at 65,535 bytes.
// 512 KiB covers all three buffers, Vec growth overlap and boxed header CRC,
// even allowing two complete headers during member transitions. Reset reuses
// the inflater. This is a conservative working-allocation envelope, not RSS.
// Re-audit dependency/backend changes; see docs/resource-policy-research.md.
const HEADER_ALLOWANCE: usize = 512 * 1024;
pub(super) const fn capacity<R>() -> usize {
    std::mem::size_of::<Reader<R>>()
        + std::mem::size_of::<miniz_oxide::inflate::stream::InflateState>()
        + 32 * 1024
        + HEADER_ALLOWANCE
}

pub(super) fn reader(source: InputBuffer<File>, codec: Reservation) -> Result<Box<dyn Read>> {
    Ok(Box::new(admitted(source, codec)?))
}

fn admitted<R: Read>(source: InputBuffer<R>, mut codec: Reservation) -> Result<Reader<R>> {
    // new() parses the first header, so admission must precede construction.
    codec.resize(capacity::<R>())?;
    Ok(Reader {
        decoder: Decoder::new(source),
        _codec: codec,
    })
}

impl<R: Read> Read for Reader<R> {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        self.decoder.read(bytes)
    }
}
