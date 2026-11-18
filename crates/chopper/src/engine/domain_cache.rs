//! Optional domain memoization. Capacity pressure always falls back to hashing.
use super::*;

use std::hash::{Hash, Hasher};

type Entry = Option<(Vec<u8>, [u8; 32])>;

pub(super) struct DomainCache {
    entries: Vec<Entry>,
    len: usize,
    reservation: Reservation,
    limit: usize,
}

impl DomainCache {
    #[cfg(test)]
    pub(super) fn for_test(ctx: &Context, limit: usize) -> Self {
        let mut cache = Self::new(ctx);
        cache.reservation = Reservation::for_workspace(Arc::new(Workspace::new(limit)));
        cache
    }

    pub(super) fn new(ctx: &Context) -> Self {
        Self {
            entries: Vec::new(),
            len: 0,
            reservation: Reservation::new(ctx),
            limit: ctx.memory / 64,
        }
    }

    fn slot(entries: &[Entry], key: &[u8]) -> usize {
        // Hashing controls memoization placement only; v1 random domains still
        // come from the existing lineage framing and BLAKE3 implementation.
        let mut hash = std::collections::hash_map::DefaultHasher::new();
        key.hash(&mut hash);
        let mut index = hash.finish() as usize % entries.len();
        loop {
            match &entries[index] {
                Some((stored, _)) if stored.as_slice() != key => {
                    index = (index + 1) % entries.len();
                }
                _ => return index,
            }
        }
    }

    pub(super) fn get(&self, key: &[u8]) -> Option<[u8; 32]> {
        if self.entries.is_empty() {
            return None;
        }
        self.entries[Self::slot(&self.entries, key)]
            .as_ref()
            .map(|(_, domain)| *domain)
    }

    fn reserve(&mut self, bytes: usize) -> Result<()> {
        ensure!(bytes <= self.limit, "domain cache capacity limit");
        self.reservation.resize(bytes)
    }

    pub(super) fn insert(&mut self, key: &[u8], domain: [u8; 32]) {
        if self.get(key).is_some() {
            return;
        }
        let old = self.reservation.bytes() as usize;
        let mut copy = Vec::new();
        let mut replacement = Vec::new();
        let result = (|| -> Result<usize> {
            self.reserve(
                old.checked_add(key.len())
                    .context("domain cache overflow")?,
            )?;
            copy.try_reserve_exact(key.len())?;
            let retained = old
                .checked_add(copy.capacity())
                .context("domain cache overflow")?;
            self.reserve(retained)?;
            copy.extend_from_slice(key);
            // Keep an empty slot for terminating misses, including collisions.
            if self.len >= self.entries.len() / 2 {
                let capacity = self
                    .entries
                    .capacity()
                    .checked_mul(2)
                    .context("domain cache overflow")?
                    .max(2);
                let bytes = capacity
                    .checked_mul(std::mem::size_of::<Entry>())
                    .context("domain cache overflow")?;
                self.reserve(
                    retained
                        .checked_add(bytes)
                        .context("domain cache overflow")?,
                )?;
                // Keep both descriptor arrays charged until the old one is freed.
                replacement.try_reserve_exact(capacity)?;
                let actual = replacement
                    .capacity()
                    .checked_mul(std::mem::size_of::<Entry>())
                    .context("domain cache overflow")?;
                self.reserve(
                    retained
                        .checked_add(actual)
                        .context("domain cache overflow")?,
                )?;
                let final_bytes =
                    retained + actual - self.entries.capacity() * std::mem::size_of::<Entry>();
                replacement.resize_with(capacity, || None);
                for entry in &mut self.entries {
                    if let Some(entry) = entry.take() {
                        let slot = Self::slot(&replacement, &entry.0);
                        replacement[slot] = Some(entry);
                    }
                }
                self.entries = std::mem::take(&mut replacement);
                Ok(final_bytes)
            } else {
                Ok(retained)
            }
        })();
        match result {
            Ok(bytes) => {
                let slot = Self::slot(&self.entries, key);
                self.entries[slot] = Some((copy, domain));
                self.len += 1;
                self.reservation
                    .resize(bytes)
                    .expect("shrinking domain cache charge");
            }
            Err(_) => {
                drop(copy);
                drop(replacement);
                self.reservation
                    .resize(old)
                    .expect("restoring domain cache charge");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cache(limit: usize) -> Result<DomainCache> {
        let ctx = Context::new(
            &Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let mut cache = DomainCache::new(&ctx);
        cache.reservation = Reservation::for_workspace(Arc::new(Workspace::new(limit)));
        cache.limit = limit;
        Ok(cache)
    }

    #[test]
    fn exact_capacity_growth_overlap_and_lookup() -> Result<()> {
        let entry = std::mem::size_of::<Entry>();
        let edge = 6 * entry + 5;
        for limit in [edge - 1, edge, edge + 1] {
            let mut cache = cache(limit)?;
            cache.insert(b"zz", [1; 32]);
            cache.insert(b"aaa", [2; 32]);
            assert_eq!(cache.get(b"zz"), Some([1; 32]));
            assert_eq!(cache.get(b"aaa").is_some(), limit >= edge);
            assert_eq!(
                cache.reservation.bytes() as usize,
                if limit >= edge {
                    4 * entry + 5
                } else {
                    2 * entry + 2
                }
            );
            cache.insert(b"zz", [9; 32]);
            assert_eq!(cache.get(b"zz"), Some([1; 32]));
        }
        Ok(())
    }

    #[test]
    fn shared_pressure_denies_optional_insert_and_releases_on_drop() -> Result<()> {
        let mut cache = cache(1024)?;
        let mut other = cache.reservation.sibling();
        other.resize(1024)?;
        cache.insert(b"key", [1; 32]);
        assert_eq!(cache.get(b"key"), None);
        assert_eq!(cache.reservation.bytes(), 0);
        other.resize(0)?;
        cache.insert(b"key", [1; 32]);
        assert_eq!(cache.get(b"key"), Some([1; 32]));
        drop(cache);
        other.resize(1024)?;
        Ok(())
    }

    #[test]
    fn local_limit_and_failed_growth_preserve_retained_entries() -> Result<()> {
        let mut cache = cache(4096)?;
        cache.limit = 2 * std::mem::size_of::<Entry>() + 3;
        cache.insert(b"key", [1; 32]);
        let retained = cache.reservation.bytes();
        cache.insert(b"another key", [2; 32]);
        assert_eq!(cache.reservation.bytes(), retained);
        assert_eq!(cache.get(b"another key"), None);
        assert_eq!(cache.get(b"key"), Some([1; 32]));
        // A key allocation can fit while the overlapping descriptor growth cannot.
        cache.limit = retained as usize + 1;
        cache.insert(b"x", [3; 32]);
        assert_eq!(cache.reservation.bytes(), retained);
        assert_eq!(cache.get(b"x"), None);
        Ok(())
    }

    #[test]
    fn collisions_and_rehashing_preserve_high_cardinality_entries() -> Result<()> {
        let mut cache = cache(2 * 1024 * 1024)?;
        for id in (0u64..5000).rev() {
            cache.insert(&id.to_le_bytes(), [id as u8; 32]);
        }
        assert_eq!(cache.len, 5000);
        for id in 0u64..5000 {
            assert_eq!(cache.get(&id.to_le_bytes()), Some([id as u8; 32]));
        }
        assert_eq!(cache.get(&5001u64.to_le_bytes()), None);
        assert_eq!(
            cache.reservation.bytes() as usize,
            cache.entries.capacity() * std::mem::size_of::<Entry>() + 5000 * 8
        );
        Ok(())
    }
}
