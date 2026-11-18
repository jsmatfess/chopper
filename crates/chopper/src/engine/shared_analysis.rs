//! Shared immutable Analysis payloads retain admission through final deallocation.
use super::*;

struct Payload<T> {
    value: T,
    // Declaration order releases payload allocations before their grant.
    memory: Option<Reservation>,
}
pub(super) struct Shared<T>(Option<Arc<Payload<T>>>);
impl<T> Default for Shared<T> {
    fn default() -> Self {
        Self(None)
    }
}
impl<T> Clone for Shared<T> {
    fn clone(&self) -> Self {
        Self(self.0.clone())
    }
}
impl<T> Shared<T> {
    // Payload, two Arc counters and alignment headroom in the audited std Arc.
    pub(super) const fn controller_bytes() -> usize {
        std::mem::size_of::<Payload<T>>() + 4 * std::mem::size_of::<usize>()
    }
    /// The caller already admits the payload's allocations before construction.
    pub(super) fn admit(value: T, memory: Reservation) -> Result<Self> {
        let mut payload = Payload {
            value,
            memory: Some(memory),
        };
        let memory = payload.memory.as_mut().unwrap();
        memory.resize(
            (memory.bytes() as usize)
                .checked_add(Self::controller_bytes())
                .context("shared Analysis owner capacity overflow")?,
        )?;
        Ok(Self(Some(Arc::new(payload))))
    }
    pub(super) fn caller_owned(value: T) -> Self {
        Self(Some(Arc::new(Payload {
            value,
            memory: None,
        })))
    }
    pub(super) fn get(&self) -> Option<&T> {
        self.0.as_ref().map(|payload| &payload.value)
    }
    // Only private engine builders may mutate a uniquely owned payload. No
    // mutable API or Arc/Weak handle escapes through public Analysis wrappers.
    pub(super) fn get_mut(&mut self) -> Option<&mut T> {
        self.0
            .as_mut()
            .and_then(Arc::get_mut)
            .map(|payload| &mut payload.value)
    }
    pub(super) fn reserved_bytes(&self) -> u64 {
        self.0
            .as_ref()
            .and_then(|payload| payload.memory.as_ref())
            .map_or(0, Reservation::bytes)
    }
}
impl<T> Drop for Shared<T> {
    fn drop(&mut self) {
        if let Some(payload) = self.0.take() {
            // Every clone uses into_inner: exactly one receives the payload,
            // including concurrent drops. No Weak handles escape. The Arc block
            // deallocates before the returned payload and finally its grant.
            drop(Arc::into_inner(payload));
        }
    }
}
