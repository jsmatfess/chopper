#[unsafe(no_mangle)]
pub fn quoted_field(value: &str, delimiter: char, quote: char) -> bool {
    value.is_empty() || value.contains([delimiter, quote, '\r', '\n'])
}

#[unsafe(no_mangle)]
pub fn quoted_field_default(value: &str) -> bool {
    value.is_empty() || value.contains([',', '"', '\r', '\n'])
}
