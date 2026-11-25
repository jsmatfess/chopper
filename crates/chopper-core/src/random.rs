use std::cmp::Ordering;

pub fn domain(seed: &str, operation: u64, scope: &str) -> [u8; 32] {
    let mut h = domain_prefix(seed, operation);
    h.update(scope.as_bytes());
    *h.finalize().as_bytes()
}

fn domain_prefix(seed: &str, operation: u64) -> blake3::Hasher {
    let mut h = blake3::Hasher::new_derive_key("chopper-v1-blake3-1");
    h.update(&(seed.len() as u64).to_le_bytes());
    h.update(seed.as_bytes());
    h.update(&operation.to_le_bytes());
    h
}

/// Hash the exact compact JSON scope without materializing its encoded text.
/// Identical to `domain(seed, operation, &serde_json::to_string(scope)?)`.
pub fn json_domain(
    seed: &str,
    operation: u64,
    scope: &impl serde::Serialize,
) -> Result<[u8; 32], serde_json::Error> {
    struct Writer(blake3::Hasher);
    impl std::io::Write for Writer {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            self.0.update(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut writer = Writer(domain_prefix(seed, operation));
    serde_json::to_writer(&mut writer, scope)?;
    Ok(*writer.0.finalize().as_bytes())
}
pub fn block(domain: &[u8; 32], row: u64, index: u64) -> [u8; 32] {
    let mut h = blake3::Hasher::new_keyed(domain);
    h.update(&row.to_le_bytes());
    h.update(&index.to_le_bytes());
    *h.finalize().as_bytes()
}
pub fn compare_ties(domain: &[u8; 32], a: u64, b: u64) -> Ordering {
    if a == b {
        return Ordering::Equal;
    }
    for index in 1.. {
        let order = block(domain, a, index).cmp(&block(domain, b, index));
        if order != Ordering::Equal {
            return order;
        }
    }
    unreachable!()
}
pub struct Random {
    domain: [u8; 32],
    counter: u64,
    // Each keyed block supplies four disjoint words; rejection still consumes a full word.
    buffer: [u8; 32],
    offset: usize,
}
impl Random {
    pub fn new(domain: [u8; 32]) -> Self {
        Self {
            domain,
            counter: 0,
            buffer: [0; 32],
            offset: 32,
        }
    }
    pub fn below(&mut self, bound: u64) -> u64 {
        below_with(bound, || {
            if self.offset == self.buffer.len() {
                self.buffer = block(&self.domain, self.counter, 0);
                self.counter = self
                    .counter
                    .checked_add(1)
                    .expect("random stream exhausted");
                self.offset = 0;
            }
            let value = u64::from_le_bytes(
                self.buffer[self.offset..self.offset + 8]
                    .try_into()
                    .unwrap(),
            );
            self.offset += 8;
            value
        })
    }
}

// Keep the rejection rule shared with deterministic boundary tests. The draw
// source stays private; production always uses the versioned stream above.
pub(crate) fn below_with(bound: u64, mut draw: impl FnMut() -> u64) -> u64 {
    assert!(bound > 0);
    let threshold = bound.wrapping_neg() % bound;
    loop {
        let value = draw();
        if value >= threshold {
            return value % bound;
        }
    }
}

pub fn tuple_key(fields: &[String], columns: &[usize]) -> Vec<u8> {
    tuple_key_views(fields.iter().map(String::as_str), columns)
}

/// Encode selected borrowed fields in caller-specified column order.
pub fn tuple_key_views<'a>(
    fields: impl Iterator<Item = &'a str> + Clone,
    columns: &[usize],
) -> Vec<u8> {
    let mut key = Vec::new();
    for &i in columns {
        for &byte in fields.clone().nth(i).expect("validated column").as_bytes() {
            key.push(byte);
            if byte == 0 {
                key.push(255);
            }
        }
        key.extend_from_slice(&[0, 0]);
    }
    key
}

/// Versioned domain separation for opt-in algorithms, leaving v1 draws intact.
pub fn algorithm_domain(domain: &[u8; 32], algorithm: &str) -> [u8; 32] {
    *blake3::keyed_hash(domain, algorithm.as_bytes()).as_bytes()
}

/// A separate stream per source row and stratum needs no per-stratum counters.
pub fn categorical(
    domain: &[u8; 32],
    row: u64,
    fields: &[String],
    columns: &[usize],
    weights: &[u64],
) -> usize {
    categorical_views(
        domain,
        row,
        fields.iter().map(String::as_str),
        columns,
        weights,
    )
}

/// Preserve categorical v1 framing while reading checked compact field views.
pub fn categorical_views<'a>(
    domain: &[u8; 32],
    row: u64,
    fields: impl Iterator<Item = &'a str> + Clone,
    columns: &[usize],
    weights: &[u64],
) -> usize {
    let mut hash = blake3::Hasher::new_keyed(domain);
    hash.update(&row.to_le_bytes());
    for &column in columns {
        let field = fields.clone().nth(column).expect("validated column");
        hash.update(&(field.len() as u64).to_le_bytes());
        hash.update(field.as_bytes());
    }
    // This per-row cursor supplies one draw; buffering its unused words adds work.
    let domain = *hash.finalize().as_bytes();
    let mut counter = 0u64;
    let mut draw = below_with(100_000_000, || {
        let bytes = block(&domain, counter, 0);
        counter = counter.checked_add(1).expect("random stream exhausted");
        u64::from_le_bytes(bytes[..8].try_into().unwrap())
    });
    for (index, weight) in weights.iter().enumerate() {
        if draw < *weight {
            return index;
        }
        draw -= weight;
    }
    unreachable!("validated weights total 100 percent")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn primary_key_ties_use_the_next_row_key_and_compare_equal_ids_once() {
        let domain = domain("row-key-tie", 2, "[]");
        let expected = block(&domain, 12, 1).cmp(&block(&domain, 37, 1));
        assert_ne!(expected, Ordering::Equal);
        assert_eq!(compare_ties(&domain, 12, 37), expected);
        assert_eq!(compare_ties(&domain, 37, 12), expected.reverse());
        assert_eq!(compare_ties(&domain, 12, 12), Ordering::Equal);
    }

    #[test]
    fn streamed_json_domains_match_v1_for_escaped_and_large_scopes() {
        for scope in [
            serde_json::json!([]),
            serde_json::json!([{"operation":1,"values":["界", "quote\"\\\n\0", "", "NULL"]}]),
            serde_json::json!([{"operation":u64::MAX,"allocation":"界".repeat(100000)}]),
        ] {
            for seed in ["", "seed\0界"] {
                for step in [0, 1, u64::MAX] {
                    assert_eq!(
                        json_domain(seed, step, &scope).unwrap(),
                        domain(seed, step, &serde_json::to_string(&scope).unwrap()),
                    );
                }
            }
        }
        struct Failure;
        impl serde::Serialize for Failure {
            fn serialize<S: serde::Serializer>(&self, _: S) -> Result<S::Ok, S::Error> {
                Err(serde::ser::Error::custom("deliberate scope failure"))
            }
        }
        assert!(json_domain("seed", 1, &Failure).is_err());
    }

    #[test]
    fn categorical_views_preserve_v1_stratum_framing() {
        let domain = domain("categorical-views", 7, "[]");
        let fields = ["界\0\n".to_string(), String::new(), "x".repeat(10000)];
        let weights = [0, 25_000_000, 75_000_000];
        for columns in [vec![], vec![0], vec![2, 0, 1], vec![0, 0]] {
            for id in 0..100 {
                // Independent pre-view v1 framing, including ordered/repeated
                // columns, empty values, Unicode, NUL and a wide field.
                let mut hash = blake3::Hasher::new_keyed(&domain);
                hash.update(&u64::to_le_bytes(id));
                for &column in &columns {
                    hash.update(&(fields[column].len() as u64).to_le_bytes());
                    hash.update(fields[column].as_bytes());
                }
                let draw = Random::new(*hash.finalize().as_bytes()).below(100_000_000);
                let expected = if draw < weights[1] { 1 } else { 2 };
                assert_eq!(
                    categorical_views(
                        &domain,
                        id,
                        fields.iter().map(String::as_str),
                        &columns,
                        &weights
                    ),
                    expected
                );
            }
        }
    }

    #[test]
    fn bounded_draw_rejects_until_threshold_and_accepts_boundaries() {
        for bound in [1, 2, 3, 7, 256, (1 << 63) + 1, u64::MAX] {
            // Calculate 2^64 modulo bound independently of wrapping negation.
            let threshold = ((1u128 << 64) % bound as u128) as u64;
            for accepted in [threshold, u64::MAX] {
                let mut values = Vec::new();
                if threshold > 0 {
                    values.extend([0, threshold - 1, 0]);
                }
                values.push(accepted);
                let mut draws = values.iter().copied();
                let actual = below_with(bound, || draws.next().expect("excess draw"));
                assert_eq!(actual, accepted % bound);
                assert!(actual < bound);
                assert!(draws.next().is_none(), "accepted a rejected value");
            }
        }
    }

    #[test]
    fn bounded_draw_uses_every_word_and_preserves_rejection() {
        let domain = domain("bounded-draw-contract", 3, "[]");
        let mut rng = Random::new(domain);
        let mut consumed = 0u64;
        let mut rejected = 0;
        for bound in [1, 2, 3, (1 << 63) + 1, u64::MAX].repeat(32) {
            let threshold = ((1u128 << 64) % bound as u128) as u64;
            let expected = loop {
                let bytes = block(&domain, consumed / 4, 0);
                let offset = (consumed % 4) as usize * 8;
                consumed += 1;
                let value = u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
                if value >= threshold {
                    break value % bound;
                }
                rejected += 1;
            };
            assert_eq!(rng.below(bound), expected);
            assert_eq!(rng.counter, consumed.div_ceil(4));
        }
        assert!(rejected > 0);
    }

    #[test]
    #[should_panic(expected = "assertion failed: bound > 0")]
    fn bounded_draw_rejects_zero_bound_before_drawing() {
        below_with(0, || panic!("must validate bound before drawing"));
    }
}
