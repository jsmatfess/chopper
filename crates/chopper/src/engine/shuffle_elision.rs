//! Adjacent shuffle elimination; explicit resident requests always execute.
use super::{Job, Operation, Shuffle};

pub(super) const ENABLED: bool = true;

pub(super) fn can_elide(current: &Operation, next: &Operation) -> bool {
    super::uniform(current)
        && (super::uniform(next)
            || ENABLED
                && matches!(
                    next,
                    Operation::Shuffle {
                        strategy: Shuffle::FisherYates
                    }
                ))
}

pub(super) fn initial_fisher_step(job: &Job, leading_shuffles: usize) -> Option<usize> {
    if matches!(
        job.operations.first(),
        Some(Operation::Shuffle {
            strategy: Shuffle::FisherYates
        })
    ) {
        Some(0)
    } else if ENABLED
        && leading_shuffles > 0
        && matches!(
            job.operations.get(leading_shuffles),
            Some(Operation::Shuffle {
                strategy: Shuffle::FisherYates
            })
        )
    {
        Some(leading_shuffles)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shuffle(strategy: Shuffle) -> Operation {
        Operation::Shuffle { strategy }
    }

    #[test]
    fn every_method_pair_preserves_earlier_explicit_requests() {
        for a in [Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates] {
            for b in [Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates] {
                assert_eq!(
                    can_elide(&shuffle(a), &shuffle(b)),
                    a != Shuffle::FisherYates && (b != Shuffle::FisherYates || ENABLED)
                );
            }
        }
    }

    #[test]
    fn barriers_are_not_shuffles_and_prefix_keeps_original_index() {
        let barriers = [
            Operation::Balanced { files: 1 },
            Operation::Interleaved { files: 2 },
            Operation::Partition {
                columns: vec![super::super::Column::Index(0)],
            },
            Operation::Assign {
                groups: vec![],
                strata: vec![],
            },
            Operation::AssignProbabilistic {
                groups: vec![],
                strata: vec![],
            },
        ];
        for barrier in barriers {
            assert!(!can_elide(&shuffle(Shuffle::Auto), &barrier));
            assert!(!can_elide(&barrier, &shuffle(Shuffle::FisherYates)));
            let job = Job {
                operations: vec![
                    shuffle(Shuffle::Auto),
                    barrier,
                    shuffle(Shuffle::FisherYates),
                ],
                ..Default::default()
            };
            assert_eq!(initial_fisher_step(&job, 1), None);
        }
        for (methods, expected) in [
            (vec![], None),
            (vec![Shuffle::FisherYates], Some(0)),
            (vec![Shuffle::Auto], None),
            (
                vec![Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates],
                ENABLED.then_some(2),
            ),
            (
                vec![Shuffle::FisherYates, Shuffle::Auto, Shuffle::FisherYates],
                Some(0),
            ),
            (
                vec![Shuffle::Auto, Shuffle::FisherYates, Shuffle::Auto],
                ENABLED.then_some(1),
            ),
        ] {
            let job = Job {
                operations: methods.into_iter().map(shuffle).collect(),
                ..Default::default()
            };
            let prefix = job
                .operations
                .iter()
                .take_while(|op| super::super::uniform(op))
                .count();
            assert_eq!(initial_fisher_step(&job, prefix), expected);
        }
    }
}
