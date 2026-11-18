use chopper_core::{weights, weights_into, Allocation, Job, Operation};
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

struct ObservedAllocator;

thread_local! {
    // Observe only this test thread, excluding fixture construction and other tests.
    static ALLOCATIONS: Cell<Option<usize>> = const { Cell::new(None) };
}

fn record_allocation() {
    let _ = ALLOCATIONS.try_with(|count| {
        if let Some(current) = count.get() {
            count.set(Some(current + 1));
        }
    });
}

unsafe impl GlobalAlloc for ObservedAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        System.alloc(layout)
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        System.alloc_zeroed(layout)
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        record_allocation();
        System.realloc(ptr, layout, size)
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        System.dealloc(ptr, layout)
    }
}

#[global_allocator]
static ALLOCATOR: ObservedAllocator = ObservedAllocator;

fn observe<T>(action: impl FnOnce() -> T) -> (T, usize) {
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            ALLOCATIONS.with(|count| count.set(None));
        }
    }
    ALLOCATIONS.with(|count| assert_eq!(count.replace(Some(0)), None));
    let reset = Reset;
    let result = action();
    let count = ALLOCATIONS.with(|count| count.get().unwrap());
    drop(reset);
    (result, count)
}

fn groups(percentages: &[&str]) -> Vec<Allocation> {
    percentages
        .iter()
        .enumerate()
        .map(|(i, percent)| Allocation {
            name: format!("group-{i}"),
            percent: (*percent).into(),
        })
        .collect()
}

fn job(groups: Vec<Allocation>, probabilistic: bool) -> Job {
    Job {
        input: "input.csv".into(),
        operations: vec![if probabilistic {
            Operation::AssignProbabilistic {
                groups,
                strata: vec![],
            }
        } else {
            Operation::Assign {
                groups,
                strata: vec![],
            }
        }],
        ..Job::default()
    }
}

#[test]
fn preconstructed_assignment_validation_does_not_allocate() {
    for probabilistic in [false, true] {
        for count in [1, 2, 1024] {
            // 1,024 positive weights: 1,023 * 0.000001 + 99.998977 = 100.
            let mut groups = groups(&vec!["0.000001"; count]);
            groups[0].percent = match count {
                1 => "100.",
                2 => "99.999999",
                1024 => "99.998977",
                _ => unreachable!(),
            }
            .into();
            let mut storage = vec![0; count];
            // Positive control: the former validation path still allocates its
            // execution vector, so a broken observer cannot silently pass.
            let (parsed, allocations) = observe(|| weights(&groups));
            let parsed = parsed.unwrap();
            assert!(allocations > 0, "weight-vector control was not observed");
            let (result, allocations) = observe(|| weights_into(&groups, &mut storage));
            result.unwrap();
            assert_eq!(allocations, 0);
            assert_eq!(storage, parsed);

            let job = job(groups, probabilistic);
            let (result, allocations) = observe(|| job.validate());
            result.unwrap();
            assert_eq!(
                allocations, 0,
                "probabilistic={probabilistic}, groups={count}"
            );
        }
        let job = job(groups(&["0", "100"]), probabilistic);
        let (result, allocations) = observe(|| job.validate());
        result.unwrap();
        assert_eq!(allocations, 0);
    }
}

#[test]
fn accepted_percentages_keep_exact_execution_weights() {
    for (percentages, expected) in [
        (vec!["100"], vec![100_000_000]),
        (vec!["100.", "0", "00.000000"], vec![100_000_000, 0, 0]),
        (vec!["00001.20", "98.8"], vec![1_200_000, 98_800_000]),
        (
            vec!["33.333333", "33.333333", "33.333334"],
            vec![33_333_333, 33_333_333, 33_333_334],
        ),
        (vec!["0.000001", "99.999999"], vec![1, 99_999_999]),
    ] {
        let groups = groups(&percentages);
        assert_eq!(weights(&groups).unwrap(), expected);
        let mut actual = vec![u64::MAX; groups.len()];
        weights_into(&groups, &mut actual).unwrap();
        assert_eq!(actual, expected);
        for probabilistic in [false, true] {
            job(groups.clone(), probabilistic).validate().unwrap();
        }
    }
}

#[test]
fn percentage_errors_and_first_error_order_match_execution_parsing() {
    for (percentages, expected) in [
        (vec![""], "invalid percentage: "),
        (vec![".5"], "invalid percentage: .5"),
        (vec!["-1"], "invalid percentage: -1"),
        (vec!["+1"], "invalid percentage: +1"),
        (vec![" 100"], "invalid percentage:  100"),
        (vec!["1e2"], "invalid percentage: 1e2"),
        (vec!["１"], "invalid percentage: １"),
        (vec!["1.2.3"], "invalid percentage: 1.2.3"),
        (
            vec!["0.0000000"],
            "percentages support at most 6 decimal places",
        ),
        (vec!["1.x"], "percentages support at most 6 decimal places"),
        (
            vec!["100. "],
            "percentages support at most 6 decimal places",
        ),
        (
            vec!["18446744073709551616"],
            "number too large to fit in target type",
        ),
        (vec!["18446744073709551615"], "percentage exceeds 100"),
        (vec!["101"], "percentage exceeds 100"),
        (vec!["0"], "percentages must sum exactly to 100"),
        (vec!["99.999999"], "percentages must sum exactly to 100"),
        (vec!["100.000001"], "percentages must sum exactly to 100"),
        (vec!["100", "100"], "percentages must sum exactly to 100"),
        // An incorrect running total must not mask a later scalar error.
        (vec!["100", "100", "bad"], "invalid percentage: bad"),
        (vec!["100.000001", "bad"], "invalid percentage: bad"),
        (vec!["101", "bad"], "percentage exceeds 100"),
        (vec!["bad", "101"], "invalid percentage: bad"),
        (
            vec!["1.x", "bad"],
            "percentages support at most 6 decimal places",
        ),
        (
            vec!["18446744073709551616.x"],
            "percentages support at most 6 decimal places",
        ),
        (
            vec!["18446744073709551616.1.2"],
            "invalid percentage: 18446744073709551616.1.2",
        ),
    ] {
        let groups = groups(&percentages);
        let mut storage = vec![u64::MAX; groups.len()];
        assert_eq!(
            weights_into(&groups, &mut storage).unwrap_err().to_string(),
            expected
        );
        assert_eq!(weights(&groups).unwrap_err().to_string(), expected);
        for probabilistic in [false, true] {
            assert_eq!(
                job(groups.clone(), probabilistic)
                    .validate()
                    .unwrap_err()
                    .to_string(),
                expected
            );
        }
    }

    let mut storage = [u64::MAX; 3];
    assert!(weights_into(&groups(&["25", "bad", "75"]), &mut storage).is_err());
    assert_eq!(storage, [25_000_000, u64::MAX, u64::MAX]);
    assert!(weights_into(&groups(&["100.000001", "bad", "0"]), &mut storage).is_err());
    assert_eq!(storage, [100_000_001, u64::MAX, u64::MAX]);
    let mut storage = [u64::MAX; 2];
    assert_eq!(
        weights_into(&groups(&["bad"]), &mut storage)
            .unwrap_err()
            .to_string(),
        "weight storage length mismatch"
    );
    assert_eq!(storage, [u64::MAX; 2]);
}

#[test]
fn group_count_and_all_names_are_checked_before_percentages() {
    for probabilistic in [false, true] {
        for count in [0, 1025] {
            let mut groups = groups(&vec!["bad"; count]);
            for group in &mut groups {
                group.name.clear();
            }
            assert_eq!(
                job(groups, probabilistic)
                    .validate()
                    .unwrap_err()
                    .to_string(),
                "allocation needs 1 to 1024 groups"
            );
        }
        for name in ["", "group-0"] {
            let mut groups = groups(&["bad", "101"]);
            groups[1].name = name.into();
            assert_eq!(
                job(groups, probabilistic)
                    .validate()
                    .unwrap_err()
                    .to_string(),
                "allocation names must be nonempty and unique"
            );
        }
    }
}
