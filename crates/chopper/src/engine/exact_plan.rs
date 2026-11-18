//! Retained-parent preparation and the only legal point for exact-plan retry.
use super::*;

/// The plan owns its original operation indices; the borrowed parent retains its
/// original replay identity. A proposal grants no capacity and has no sink.
pub(super) struct Proposal<'a, P> {
    plan: P,
    parent: &'a Group,
}

pub(super) enum Attempt<T> {
    Prepared(T),
    Retry(anyhow::Error),
}

impl<'a, P> Proposal<'a, P> {
    pub fn new(plan: P, parent: &'a Group) -> Self {
        Self { plan, parent }
    }

    /// Preparation owns all tentative allocations. On failure they must drop
    /// before this returns. Cleanup failure and cancellation override denial.
    /// Emission happens outside this interface: every emission error is terminal.
    pub fn prepare<T>(
        self,
        ctx: &Context,
        prepare: impl FnOnce(P, &'a Group) -> Result<T>,
        retry: impl FnOnce(&anyhow::Error) -> bool,
    ) -> Result<Attempt<T>> {
        ctx.check()?;
        ctx.pressure_boundary();
        match prepare(self.plan, self.parent) {
            Ok(prepared) => Ok(Attempt::Prepared(prepared)),
            Err(error) => {
                ctx.check()?;
                if retry(&error) {
                    Ok(Attempt::Retry(error))
                } else {
                    Err(error)
                }
            }
        }
    }
}
