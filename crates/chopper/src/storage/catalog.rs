//! Capacity-charged catalogs. Iteration keeps the allocation and its charge live.
use super::*;
use std::ops::{Deref, DerefMut};

pub(super) struct Catalog<T> {
    values: Vec<T>,
    reservation: Reservation,
}
impl<T> Catalog<T> {
    pub(super) fn new(ctx: &Context) -> Self {
        Self {
            values: Vec::new(),
            reservation: Reservation::new(ctx),
        }
    }
    fn with_capacity(reservation: Reservation, capacity: usize) -> Result<Self> {
        let mut result = Self {
            values: Vec::new(),
            reservation,
        };
        result.grow(capacity)?;
        Ok(result)
    }
    fn grow(&mut self, capacity: usize) -> Result<()> {
        let size = std::mem::size_of::<T>();
        ensure!(size != 0, "zero-sized catalog entry");
        let old = self
            .values
            .capacity()
            .checked_mul(size)
            .context("catalog size overflow")?;
        let bytes = capacity
            .checked_mul(size)
            .context("catalog size overflow")?;
        self.reservation
            .resize(old.checked_add(bytes).context("catalog size overflow")?)?;
        // Allocate separately so old/new overlap is explicit, even when an
        // allocator could have grown the original allocation in place.
        let mut values = Vec::new();
        let result = (|| -> Result<usize> {
            values.try_reserve_exact(capacity)?;
            let actual = values
                .capacity()
                .checked_mul(size)
                .context("catalog size overflow")?;
            self.reservation
                .resize(old.checked_add(actual).context("catalog size overflow")?)?;
            Ok(actual)
        })();
        let actual = match result {
            Ok(actual) => actual,
            Err(error) => {
                drop(values);
                self.reservation.resize(old)?;
                return Err(error);
            }
        };
        values.append(&mut self.values);
        self.values = values;
        self.reservation.resize(actual)
    }
    pub(super) fn push(&mut self, value: T) -> Result<()> {
        if self.values.len() == self.values.capacity() {
            self.grow(
                self.values
                    .capacity()
                    .checked_mul(2)
                    .context("catalog size overflow")?
                    .max(1),
            )?;
        }
        self.values.push(value);
        Ok(())
    }
    pub(super) fn take_prefix(&mut self, count: usize) -> Result<Self> {
        let mut result = Self::with_capacity(self.reservation.sibling(), count)?;
        result.values.extend(self.values.drain(..count));
        Ok(result)
    }
}
impl<T> Deref for Catalog<T> {
    type Target = [T];
    fn deref(&self) -> &[T] {
        &self.values
    }
}
impl<T> DerefMut for Catalog<T> {
    fn deref_mut(&mut self) -> &mut [T] {
        &mut self.values
    }
}
pub(super) struct CatalogIter<T> {
    values: std::vec::IntoIter<T>,
    _reservation: Reservation,
}
impl<T> IntoIterator for Catalog<T> {
    type Item = T;
    type IntoIter = CatalogIter<T>;
    fn into_iter(self) -> Self::IntoIter {
        CatalogIter {
            values: self.values.into_iter(),
            _reservation: self.reservation,
        }
    }
}
impl<T> Iterator for CatalogIter<T> {
    type Item = T;
    fn next(&mut self) -> Option<T> {
        self.values.next()
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        self.values.size_hint()
    }
}
impl<T> ExactSizeIterator for CatalogIter<T> {}

#[cfg(test)]
mod tests {
    use super::*;

    fn context(limit: usize) -> Result<Context> {
        let mut ctx = Context::new(
            &chopper_core::Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        ctx.replace_workspace_for_test(Workspace::new(limit))?;
        Ok(ctx)
    }

    #[test]
    fn growth_reserves_overlap_at_exact_capacity_edges() -> Result<()> {
        let size = std::mem::size_of::<u64>();
        for limit in [3 * size - 1, 3 * size, 3 * size + 1] {
            let ctx = context(limit)?;
            let mut catalog = Catalog::new(&ctx);
            catalog.push(7u64)?;
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + size as u64
            );
            let result = catalog.push(9);
            assert_eq!(result.is_ok(), limit >= 3 * size);
            if result.is_ok() {
                assert_eq!(&*catalog, &[7, 9]);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + (2 * size) as u64
                );
                assert_eq!(
                    ctx.workspace.peak(),
                    ctx.directory_reserved_bytes() + (3 * size) as u64
                );
            } else {
                assert_eq!(&*catalog, &[7]);
                assert_eq!(catalog.values.capacity(), 1);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + size as u64
                );
            }
            drop(catalog);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        }
        Ok(())
    }

    #[test]
    fn draining_and_exhausted_iterators_retain_capacity_charges() -> Result<()> {
        let size = std::mem::size_of::<u64>();
        for limit in [4 * size - 1, 4 * size, 4 * size + 1] {
            let ctx = context(limit)?;
            let mut catalog = Catalog::new(&ctx);
            catalog.push(1u64)?;
            catalog.push(2)?;
            let batch = catalog.take_prefix(2);
            assert_eq!(batch.is_ok(), limit >= 4 * size);
            if let Ok(batch) = batch {
                assert!(catalog.is_empty());
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + (4 * size) as u64
                );
                let mut iter = batch.into_iter();
                assert_eq!(iter.next(), Some(1));
                assert_eq!(iter.next(), Some(2));
                assert_eq!(iter.next(), None);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + (4 * size) as u64
                );
                drop(iter);
            } else {
                assert_eq!(&*catalog, &[1, 2]);
            }
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (2 * size) as u64
            );
            drop(catalog);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        }
        Ok(())
    }
}
