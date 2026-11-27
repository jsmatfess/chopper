# Formula functions

Calculated columns evaluate expressions against the current row. The same
formulas work in the hosted app, the CLI, and both libraries. The function
tables use Chopper formula text.

## Build formulas with the client libraries

<!-- chopper-docs:formula-syntax -->

<div id="formula-text-syntax" data-formula-syntax="formula">

**Formula text**

Paste this expression into the hosted formula editor. For the CLI, pass
`--calculated-column 'review_status=...'` with the expression after `=`.
In Job JSON, set the calculated column's `expression` field.

```text
IF(STARTSWITH([country], "u", TRUE) AND NOT IS_BLANK([segment]), "review", "skip")
```

See [calculated columns in Job JSON](job-json.md#formulas) and
[CLI flags](run-cli.md#calculated-columns).

</div>

<div id="rust-syntax" data-formula-syntax="rust">

**Rust syntax**

Import the helpers from `chopper::formula::functions`. Names are lowercase,
with `if_else` for `IF`. Use `col("country")` for a header, `col(0)` for the
first field, and `lit(value)` for an explicit literal expression.

```rust
use chopper::formula::{col, functions as f, lit};

fn main() {
    let country = f::startswith(col("country"), "u", Some(lit(true)));
    let needs_review = country.and(f::is_blank(col("segment")).not());
    println!("{}", f::if_else(needs_review, "review", "skip"));
}
```

- Pass `None` to omit an optional argument and `Some(expr)` to supply one.
  Use `null()` for formula `NULL`, or `Some(null())` in an optional slot.
- Pass an iterator of expressions to `concat` and `coalesce`. `concat_ws`
  takes the separator followed by the iterator, including any literal Boolean
  flags at its end. `ifs` takes `(condition, value)` pairs and a fallback.
- Compose Boolean expressions with `.and()`, `.or()`, and `.not()`, or use
  `&`, `|`, and `!`. For text concatenation, use `f::concat`.
- Use `f::safe(expr)` to catch row errors. Use `chopper::formula::parse`
  for formula text such as comparisons, `IN`, or `SAFE.NUMBER([amount])`.

See [Rust examples](user/libraries.md?lang=rust#add-calculated-columns) for
adding expressions to a Job.

</div>

<div id="python-syntax" data-formula-syntax="python">

**Python syntax**

Import the helpers from `chopper_csv.functions`. Names are lowercase,
with `if_else` for `IF`. Use `col("country")` for a header, `col(0)` for the
first field, and `lit(value)` for an explicit literal expression.

```python
from chopper_csv import col, functions as f

country = f.startswith(col("country"), "u", True)
needs_review = country.and_(f.is_blank(col("segment")).not_())
print(f.if_else(needs_review, "review", "skip"))
```

- Omit an optional argument to use the function default. Pass `None` for
  formula `NULL`.
- Pass arguments individually to `concat` and `coalesce`. Append any
  literal Boolean flags to `concat_ws`. `ifs` takes `(condition, value)`
  pairs and a `fallback=` keyword argument.
- Compose Boolean expressions with `.and_()`, `.or_()`, and `.not_()`, or use
  `&`, `|`, and `~`. The trailing underscores avoid Python's reserved
  keywords. For text concatenation, use `f.concat`.
- Use `f.safe(expr)` to catch row errors. Use `chopper_csv.parse`
  for formula text such as comparisons, `IN`, or `SAFE.NUMBER([amount])`.

See [Python examples](user/libraries.md?lang=python#add-calculated-columns)
for adding expressions to a Job.

</div>

## Write a formula

Write a bare column name, a bracketed name such as `[Sales Region]`, or an
index such as `$0` for the first field. Double a closing bracket inside a
bracketed name. Use zero-based indices for headerless input or duplicate
headers. Double quotes delimit text literals,
and doubling an embedded quote inserts it literally. In the hosted editor, Tab accepts the highlighted suggestion and Ctrl+Space
opens suggestions. Exact and prefix matches appear first, followed by names
that contain the typed text. Each group is alphabetical, and matching is
case-insensitive. Functions and column references use distinct colors in the
formula field and suggestions.
While the caret is inside a function call, the editor shows the function's
arguments, behavior, and examples below the formula. Examples show text in
quotes and identify typed date and timestamp results.

On wide screens, the Column explorer can insert directly into the focused
formula. Click the text of a column name to insert its reference or the text
of an analyzed value to insert it as quoted text. Use the
plus control to open a column's values while keeping focus in the formula.

Below the formula, the preview shows the result or error for a source row
and the input columns the formula uses, including inputs used through another
calculated column. Type over any preview value to recalculate that example.
These edits apply only to the preview. Choosing another row restores its
original values.

**Next distinct row** finds another source row with a different combination
of the referenced inputs. Chopper keeps up to 512 rows or 1 MiB per sample
batch in the background after the initial input preview loads. Use **Scan more rows**
to read the next batch when the sample has no new combination. Row numbers
count data records from 1, excluding the header. Very large records can be
skipped by the sample.

Function names are case-insensitive. CSV fields start as text. Use `NUMBER`,
`DATE_PARSE`, or `TIMESTAMP_PARSE` to convert input explicitly.

## Handle row errors with SAFE

| Function | Behavior | Examples |
| --- | --- | --- |
| `SAFE(expression)` | Evaluate `expression` and return `NULL` on a row error. Successful results pass through. | `SAFE(1 / 0)` → `NULL`<br>`SAFE(NUMBER("42"))` → `42` |
| `IS_ERROR(expression)` | Return `TRUE` if `expression` raises a row error, otherwise `FALSE`, including when the result is `NULL`. | `IS_ERROR(NUMBER("unknown"))` → `TRUE`<br>`IS_ERROR(NULL)` → `FALSE` |

The `SAFE.function(...)` form applies to any function call.
Chopper still reports invalid formulas and resource errors.

- `SAFE.NUMBER("unknown")` returns `NULL`, and `SAFE.NUMBER("42")` returns `42`.
- `SAFE(1 / 0)` returns `NULL`.
- `IS_ERROR(NUMBER("unknown"))` returns `TRUE`. Wrapping the conversion in
  `SAFE.NUMBER("unknown")` first makes the result `FALSE`.

## Operators

| Operator | Behavior |
| --- | --- |
| `+`, `-`, `*`, `/`, `%` | Add, subtract, multiply, divide, and take the remainder of numbers. Unary `+` and `-` also work on numbers. |
| `&` | Join text. Either operand being `NULL` yields `NULL`, as with `CONCAT`. |
| `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=` | Compare values of matching types. A null operand yields `NULL`. |
| `AND`, `OR`, `NOT` | Evaluate Boolean conditions. `FALSE AND NULL` is false, `TRUE OR NULL` is true, and `NOT NULL` yields `NULL`. |

Arithmetic binds before `&`, which binds before comparisons and `IN`.
For example, `first_name & " " & last_name = "Ada Lovelace"` joins the name
before comparing it.

`region IN ("North", "West")` tests membership in a nonempty list. Items can
be expressions or column references. `IN` uses the same type and case rules
as equality and stops at the first match. A `NULL` input yields `NULL`.
When no item matches, the result is `NULL` if the list contains a `NULL`
value and `FALSE` otherwise.

## Text functions

Substring positions start at zero. Substrings, lengths, and padding use
Unicode scalar values. `BYTE_LENGTH` counts bytes instead.

| Function | Behavior | Examples |
| --- | --- | --- |
| `TRIM(text)` | Remove whitespace at both ends of `text`. | `TRIM("  north  ")` → `"north"` |
| `UPPER(text)` | Convert `text` to Unicode uppercase. | `UPPER("Straße")` → `"STRASSE"` |
| `LOWER(text)` | Convert `text` to Unicode lowercase. | `LOWER("ÉTÉ")` → `"été"` |
| `CONCAT(text, ...)` | Join `text` and any additional text arguments directly. A `NULL` argument returns `NULL`. | `CONCAT("North", "-", "West")` → `"North-West"`<br>`CONCAT("x", NULL)` → `NULL` |
| `REPLACE(text, search, replacement)` | Replace all literal occurrences of `search` in `text` with `replacement`. | `REPLACE("red red", "red", "blue")` → `"blue blue"` |
| `STARTSWITH(text, prefix, ignore_case?)` | Test whether `text` starts with the literal `prefix`. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `STARTSWITH("North", "No")` → `TRUE`<br>`STARTSWITH("North", "no", TRUE)` → `TRUE` |
| `ENDSWITH(text, suffix, ignore_case?)` | Test whether `text` ends with the literal `suffix`. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `ENDSWITH("data.csv", ".CSV")` → `FALSE`<br>`ENDSWITH("data.csv", ".CSV", TRUE)` → `TRUE` |
| `SUBSTRING(text, start, length?)` | Take text at a zero-based position `start` in `text`. Omit `length` to take the rest. | `SUBSTRING("North", 1, 2)` → `"or"`<br>`SUBSTRING("North", 1)` → `"orth"` |
| `LEFT(text, count)` | Take up to the first `count` Unicode scalar values of `text`. | `LEFT("é🙂z", 2)` → `"é🙂"` |
| `RIGHT(text, count)` | Take up to the last `count` Unicode scalar values of `text`. | `RIGHT("é🙂z", 2)` → `"🙂z"` |
| `LENGTH(text)` | Count the Unicode scalar values in `text`. | `LENGTH("é🙂")` → `2` |
| `BYTE_LENGTH(text)` | Count the UTF-8 bytes in `text`. | `BYTE_LENGTH("é🙂")` → `6` |
| `CONTAINS(text, search, ignore_case?)` | Test whether `text` contains the literal `search`. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `CONTAINS("North", "north")` → `FALSE`<br>`CONTAINS("North", "north", TRUE)` → `TRUE` |
| `IS_ASCII(text)` | Test whether every character in `text` is ASCII. | `IS_ASCII("é")` → `FALSE`<br>`IS_ASCII("")` → `TRUE` |
| `IS_DIGITS(text)` | Test whether `text` is a nonempty sequence of ASCII digits. | `IS_DIGITS("007")` → `TRUE`<br>`IS_DIGITS("１")` → `FALSE` |
| `LTRIM(text)` | Remove whitespace from the start of `text` using the same rules as `TRIM`. | `LTRIM("  x  ")` → `"x  "` |
| `RTRIM(text)` | Remove whitespace from the end of `text` using the same rules as `TRIM`. | `RTRIM("  x  ")` → `"  x"` |
| `IS_BLANK(text)` | Test whether `text` is null, empty, or whitespace-only using the same rules as `TRIM`. | `IS_BLANK(" ")` → `TRUE`<br>`IS_BLANK(NULL)` → `TRUE` |
| `STRIP_PREFIX(text, prefix, ignore_case?)` | Remove one matching literal `prefix` from `text`. If it does not match, return `text`. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `STRIP_PREFIX("prepreflight", "pre")` → `"preflight"`<br>`STRIP_PREFIX("PREFlight", "pre", TRUE)` → `"Flight"` |
| `STRIP_SUFFIX(text, suffix, ignore_case?)` | Remove one matching literal `suffix` from `text`. If it does not match, return `text`. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `STRIP_SUFFIX("data.csv", ".CSV")` → `"data.csv"`<br>`STRIP_SUFFIX("Data.CSV", ".csv", TRUE)` → `"Data"` |
| `TEXT_BEFORE(text, delimiter, ignore_case?)` | Take the part of `text` before the first literal `delimiter`. Return `NULL` if it is absent. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `TEXT_BEFORE("a:b:c", ":")` → `"a"`<br>`TEXT_BEFORE("North VIA Central", " via ", TRUE)` → `"North"`<br>`TEXT_BEFORE("abc", ":")` → `NULL` |
| `TEXT_AFTER(text, delimiter, ignore_case?)` | Take the part of `text` after the first literal `delimiter`. Return `NULL` if it is absent. Set `ignore_case` to `TRUE` to ignore case. The default is `FALSE`. | `TEXT_AFTER("a:b:c", ":")` → `"b:c"`<br>`TEXT_AFTER("North VIA Central", " via ", TRUE)` → `"Central"`<br>`TEXT_AFTER("abc", ":")` → `NULL` |
| `SPLIT_PART(text, delimiter, index)` | Split `text` on the literal `delimiter` and select the zero-based `index`. Preserve empty parts and return `NULL` if `index` is out of range. | `SPLIT_PART("apple,banana,cherry", ",", 1)` → `"banana"`<br>`SPLIT_PART("a::c", ":", 1)` → `""`<br>`SPLIT_PART("a::c", ":", 3)` → `NULL` |
| `TRANSLATE(text, from, to)` | In `text`, replace each character found in `from` with the character at the same position in `to`. Use its first position in `from` and remove it if `to` has no character at that position. | `TRANSLATE("a!b", "ab!", "xy")` → `"xy"` |
| `LPAD(text, width, pad?)` | Extend `text` on the left to `width` Unicode scalar values by repeating `pad`, a space by default. A shorter `width` keeps the start of `text`. | `LPAD("x", 3, "0")` → `"00x"`<br>`LPAD("abc", 2)` → `"ab"` |
| `RPAD(text, width, pad?)` | Extend `text` on the right to `width` Unicode scalar values by repeating `pad`, a space by default. A shorter `width` keeps the start of `text`. | `RPAD("x", 4, "ab")` → `"xaba"`<br>`RPAD("abc", 2)` → `"ab"` |
| `REPEAT(text, count)` | Repeat `text` a nonnegative whole number of times given by `count`. | `REPEAT("ab", 3)` → `"ababab"`<br>`REPEAT("ab", 0)` → `""` |
| `CONCAT_WS(separator, text, ..., ignore_null?, ignore_empty?)` | Join `text` and any additional text arguments with `separator`. A null `separator` returns `NULL`. The trailing Boolean literals `ignore_null` and `ignore_empty` control whether to skip null and empty arguments. They default to `TRUE` and `FALSE`, respectively. | `CONCAT_WS(":", "a", NULL, "", "b")` → `"a::b"`<br>`CONCAT_WS(":", "a", NULL, "", "b", TRUE, TRUE)` → `"a:b"`<br>`CONCAT_WS(":", "a", NULL, "", "b", FALSE, TRUE)` → `"a::b"` |

With `ignore_case` enabled, literal matching uses the same character-by-character
Unicode rules as [`ILIKE`](#pattern-matching). For example, `É` matches `é`, and
`ß` remains distinct from `ss`. Functions that return part of `text` preserve
its original capitalization. A null `ignore_case` argument returns `NULL`.

The optional `CONCAT_WS` flags are trailing Boolean literals, in the order
`ignore_null` then `ignore_empty`. Set `ignore_null` to `FALSE` to keep a null
argument's position as an empty slot, even when empty text is skipped. For
example, `CONCAT_WS("|", "a", NULL, "", "b", FALSE, TRUE)` produces `a||b`.

Empty delimiters and padding strings are row errors. Generated strings are
subject to the job's memory and record limits.

## Pattern matching

In `LIKE` and `ILIKE` patterns, `.` matches one character, `.*` matches zero
or more characters, and a backslash escapes a pattern character. Wildcards
count the original Unicode scalar values. Regular
expressions support groups, classes, alternation, anchors, and greedy repetition.

| Function | Behavior | Examples |
| --- | --- | --- |
| `LIKE(text, pattern)` | Match the entire `text` against the case-sensitive wildcard `pattern`. | `LIKE("North", "N.*")` → `TRUE`<br>`LIKE("North", "or")` → `FALSE` |
| `ILIKE(text, pattern)` | Match the entire `text` against the case-insensitive wildcard `pattern`. Literal letters compare one Unicode scalar at a time. | `ILIKE("North", "n.*")` → `TRUE` |
| `REGEX_MATCH(text, pattern)` | Test whether the regular expression `pattern` matches anywhere in `text`. | `REGEX_MATCH("Order 42", "[0-9]+")` → `TRUE`<br>`REGEX_MATCH("Order 42", "^[0-9]+$")` → `FALSE` |
| `REGEX_REPLACE(text, pattern, replacement)` | Replace each match of `pattern` in `text` with `replacement`. In `replacement`, `$0` inserts the full match and `$1`, `$2`, and so on insert numbered captures. | `REGEX_REPLACE("Order 42", "([0-9]+)", "number $1")` → `"Order number 42"` |
| `REGEX_EXTRACT(text, pattern, group?)` | Return the first match of `pattern` in `text` when `group` is 0 or omitted. A positive `group` selects a numbered capture. Return `NULL` if there is no match or the capture did not participate. | `REGEX_EXTRACT("Order 42", "Order ([0-9]+)")` → `"Order 42"`<br>`REGEX_EXTRACT("Order 42", "Order ([0-9]+)", 1)` → `"42"`<br>`REGEX_EXTRACT("b", "(a)?b", 1)` → `NULL` |

Patterns must be literal text. Alternatives are tried in pattern order at
the earliest matching position. A repeated group can retain its last
consuming capture. For example, `REGEX_EXTRACT("aaa", "(a*)*", 1)` returns
`"aaa"`. A capture number that exceeds the number of groups is a row error.

## Conditions and conversions

| Function | Behavior | Examples |
| --- | --- | --- |
| `IF(condition, when_true, when_false)` | Evaluate `when_true` if `condition` is true, otherwise evaluate `when_false`. | `IF(2 < 3, "yes", "no")` → `"yes"`<br>`IF(NULL, "yes", "no")` → `"no"` |
| `IFS(condition, value, ..., fallback)` | Evaluate the `value` for the first true `condition` in the sequence of pairs. Evaluate `fallback` if none is true. | `IFS(FALSE, "a", TRUE, "b", "other")` → `"b"`<br>`IFS(FALSE, "a", "other")` → `"other"` |
| `IS_NULL(value)` | Test whether `value` is `NULL`. | `IS_NULL(NULL)` → `TRUE`<br>`IS_NULL("")` → `FALSE` |
| `COALESCE(value, ...)` | Return `value` if it is non-null, otherwise the first non-null additional argument. Return `NULL` if every argument is null. | `COALESCE(NULL, "", "fallback")` → `""`<br>`COALESCE(NULL, NULL)` → `NULL` |
| `NUMBER(text)` | Parse `text` as a finite binary floating-point number. Empty `text` returns `NULL`. Trim surrounding whitespace explicitly. | `NUMBER("0042")` → `42`<br>`NUMBER("")` → `NULL`<br>`SAFE.NUMBER(" 42")` → `NULL` |
| `TEXT(value)` | Convert `value` to its output text. A null `value` returns `NULL`. | `TEXT(42)` → `"42"`<br>`TEXT(NULL)` → `NULL` |

## Comparisons and numeric functions

| Function | Behavior | Examples |
| --- | --- | --- |
| `ABS(number)` | Return the absolute value of `number`. | `ABS(-7)` → `7` |
| `ROUND(number, places?)` | Round `number` to `places` decimal places, defaulting to zero. Negative `places` round to tens, hundreds, and so on. | `ROUND(12.375, 2)` → `12.38`<br>`ROUND(125, -1)` → `130` |
| `NULLIF(value, match)` | Return `NULL` when `value` and `match` compare equal. Otherwise return `value`. | `NULLIF("x", "x")` → `NULL`<br>`NULLIF("x", "y")` → `"x"` |
| `BETWEEN(value, lower, upper)` | Test whether `value` is at least `lower` and at most `upper`. The arguments must have matching types. A null argument returns `NULL`. | `BETWEEN(3, 1, 3)` → `TRUE`<br>`BETWEEN(4, 1, 3)` → `FALSE` |
| `IS_TEXT(value)` | Test whether `value` is already text. | `IS_TEXT("42")` → `TRUE`<br>`IS_TEXT(42)` → `FALSE` |
| `IS_NUMBER(value)` | Test whether `value` is already a number. Use `NUMBER` to convert CSV text first. | `IS_NUMBER("42")` → `FALSE`<br>`IS_NUMBER(NUMBER("42"))` → `TRUE` |
| `IS_BOOLEAN(value)` | Test whether `value` is already Boolean. | `IS_BOOLEAN(TRUE)` → `TRUE`<br>`IS_BOOLEAN("TRUE")` → `FALSE` |
| `FLOOR(number)` | Round `number` down toward negative infinity. | `FLOOR(-2.7)` → `-3` |
| `CEIL(number)` | Round `number` up toward positive infinity. | `CEIL(-2.7)` → `-2` |
| `TRUNC(number)` | Drop the fractional part of `number` toward zero. | `TRUNC(-2.7)` → `-2` |
| `SQRT(number)` | Return the square root of `number`. A negative `number` is a row error. | `SQRT(81)` → `9`<br>`SAFE.SQRT(-1)` → `NULL` |
| `POWER(base, exponent)` | Raise `base` to `exponent`. | `POWER(2, 3)` → `8`<br>`POWER(2, -1)` → `0.5` |
| `LN(number)` | Return the natural logarithm of positive `number`. | `LN(1)` → `0` |
| `LOG10(number)` | Return the base-10 logarithm of positive `number`. | `LOG10(1000)` → `3` |
| `EXP(number)` | Raise Euler's number to the power `number`. | `EXP(0)` → `1` |
| `BUCKET(number, width, origin?)` | Return the lower boundary of the bucket containing `number`. Buckets have positive `width` and are anchored at `origin`, which defaults to zero. | `BUCKET(-1, 5)` → `-5`<br>`BUCKET(8, 5, 2)` → `7` |

Numeric functions use binary floating point. Non-finite results are row errors.
For example, `BUCKET(-1, 5)` returns `-5`.

## Dates and timestamps

### Parsing, formatting, and parts

| Function | Behavior | Examples |
| --- | --- | --- |
| `DATE_PARSE(text, format?)` | Parse `text` as a date using the literal `format` or the default YYYY-MM-DD layout. | `DATE_PARSE("2024-02-29")` → `DATE 2024-02-29`<br>`DATE_PARSE("29/02/2024", "%d/%m/%Y")` → `DATE 2024-02-29` |
| `TIMESTAMP_PARSE(text, format?)` | Parse `text` as a timestamp using the literal `format`. The default requires a date, time, and a `Z` or numeric offset. | `TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00")` → `TIMESTAMP 2024-01-02T01:04:05Z` |
| `DATE_FORMAT(date, format)` | Render `date` as text using the literal `format`. | `DATE_FORMAT(DATE_PARSE("2024-02-29"), "%d/%m/%Y")` → `"29/02/2024"` |
| `TIMESTAMP_FORMAT(timestamp, format, basis?)` | Render `timestamp` as text using the literal `format`. The `basis` defaults to UTC. Use `"local"` to use the value's offset. | `TIMESTAMP_FORMAT(TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00"), "%H:%M")` → `"01:04"`<br>`TIMESTAMP_FORMAT(TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00"), "%H:%M", "local")` → `"03:04"` |
| `DATE_EXTRACT(date, part)` | Return the numeric `part` of `date`, such as `"year"`, `"quarter"`, `"month"`, or `"day"`. | `DATE_EXTRACT(DATE_PARSE("2024-05-29"), "quarter")` → `2` |
| `TIMESTAMP_EXTRACT(timestamp, part, basis?)` | Return the numeric calendar or clock `part` of `timestamp`. The `basis` defaults to UTC. Use `"local"` to use the value's offset. | `TIMESTAMP_EXTRACT(TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00"), "hour")` → `1`<br>`TIMESTAMP_EXTRACT(TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00"), "hour", "local")` → `3` |
| `DATE_TRUNC(date, unit)` | Return the first date of the calendar `unit` containing `date`. | `DATE_TRUNC(DATE_PARSE("2024-05-29"), "quarter")` → `DATE 2024-04-01` |
| `TIMESTAMP_TRUNC(timestamp, unit, basis?)` | Return the start of the calendar or clock `unit` containing `timestamp`. The `basis` defaults to UTC. Use `"local"` to truncate at the value's offset. | `TIMESTAMP_TRUNC(TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00"), "day")` → `TIMESTAMP 2024-01-02T00:00:00Z`<br>`TIMESTAMP_TRUNC(TIMESTAMP_PARSE("2024-01-02T03:04:05+02:00"), "day", "local")` → `TIMESTAMP 2024-01-01T22:00:00Z` |

### Format literals

Pass formats as quoted strings. Separators and other text are used literally.
An explicit parse format must include `%Y`, `%m`, and `%d`. Timestamp parse
formats also require `%H` and `%M`. Omitted seconds and fractional seconds
default to zero, and an omitted offset means UTC. Formatting can use any subset
of the tokens supported by the function.

| Token | Available in | Meaning | Example |
| --- | --- | --- | --- |
| `%Y` | Date and timestamp | Four-digit year | `2024` |
| `%m` | Date and timestamp | Two-digit month, `01`–`12` | `02` |
| `%d` | Date and timestamp | Two-digit day of the month, `01`–`31` | `29` |
| `%H` | Timestamp | Two-digit hour on a 24-hour clock, `00`–`23` | `15` |
| `%M` | Timestamp | Two-digit minute, `00`–`59` | `04` |
| `%S` | Timestamp | Two-digit whole second, `00`–`59` | `05` |
| `%f` | Timestamp | Fractional seconds without the decimal point. Parsing accepts one to nine digits. Formatting emits nine. | `123` parses as `123000000` nanoseconds |
| `%z` | Timestamp | UTC offset. Parsing accepts `Z`, `z`, or a signed `HH:MM` offset. Formatting emits a signed offset. | `+02:00` or `+00:00` |
| `%%` | Date and timestamp | Literal percent sign | `%` |

With no explicit format, `DATE_PARSE` expects `2024-02-29`-style dates.
`TIMESTAMP_PARSE` expects a date and time separated by `T` or `t`, followed by
`Z` or a signed offset. The seconds are required, and the fractional part is
optional, as in `2024-02-29T13:04:05.123Z`.

### Common formats

The timestamp examples use the `"local"` basis to show the clock time and
offset from `2024-02-29T15:04:05.123+02:00`.

| Use | Format literal | Example output | Can also parse this layout? |
| --- | --- | --- | --- |
| Year-month-day | `"%Y-%m-%d"` | `2024-02-29` | Yes, with `DATE_PARSE` |
| US month/day/year | `"%m/%d/%Y"` | `02/29/2024` | Yes, with `DATE_PARSE` |
| Day/month/year | `"%d/%m/%Y"` | `29/02/2024` | Yes, with `DATE_PARSE` |
| Compact date | `"%Y%m%d"` | `20240229` | Yes, with `DATE_PARSE` |
| Year and month | `"%Y-%m"` | `2024-02` | Formatting only |
| Timestamp with offset | `"%Y-%m-%dT%H:%M:%S%z"` | `2024-02-29T15:04:05+02:00` | Yes, with `TIMESTAMP_PARSE` |
| Timestamp with fractional seconds and offset | `"%Y-%m-%dT%H:%M:%S.%f%z"` | `2024-02-29T15:04:05.123000000+02:00` | Yes, with `TIMESTAMP_PARSE` |
| Date and time to the minute | `"%Y-%m-%d %H:%M"` | `2024-02-29 15:04` | Yes, with `TIMESTAMP_PARSE`, which assumes UTC |
| Time of day | `"%H:%M:%S"` | `15:04:05` | Formatting only |

### Extraction and truncation literals

Use these quoted strings for the `part` argument to extraction or the `unit`
argument to truncation.

| Literal | Available in | Extracts | Truncates to |
| --- | --- | --- | --- |
| `"year"` | Date and timestamp | Calendar year | January 1 |
| `"quarter"` | Date and timestamp | Calendar quarter, `1`–`4` | First day of January, April, July, or October |
| `"month"` | Date and timestamp | Month of the year, `1`–`12` | First day of the month |
| `"day"` | Date and timestamp | Day of the month, `1`–`31` | Start of the day |
| `"hour"` | Timestamp | Hour of the day, `0`–`23` | Start of the hour |
| `"minute"` | Timestamp | Minute of the hour, `0`–`59` | Start of the minute |
| `"second"` | Timestamp | Whole second of the minute, `0`–`59` | Start of the second, dropping fractional seconds |

Timestamp truncation to a calendar unit sets the time to midnight in the chosen
basis. Date truncation to `"day"` returns the date itself.

| Timestamp basis literal | Used by `TIMESTAMP_FORMAT`, `TIMESTAMP_EXTRACT`, and `TIMESTAMP_TRUNC` |
| --- | --- |
| `"utc"` | Use UTC. This is the default. |
| `"local"` | Use the numeric offset stored in the timestamp. |

### Calendar and timestamp arithmetic

| Function | Behavior | Examples |
| --- | --- | --- |
| `DATE_FROM_PARTS(year, month, day)` | Build a Gregorian date from integer `year`, `month`, and `day`. The `year` ranges from 0001 to 9999. | `DATE_FROM_PARTS(2024, 2, 29)` → `DATE 2024-02-29` |
| `DATE_ADD_DAYS(date, count)` | Add a signed whole `count` of calendar days to `date`. | `DATE_ADD_DAYS(DATE_FROM_PARTS(2024, 3, 1), -1)` → `DATE 2024-02-29` |
| `DATE_DIFF_DAYS(start, end)` | Return `end` minus `start` in calendar days. | `DATE_DIFF_DAYS(DATE_FROM_PARTS(2024, 2, 28), DATE_FROM_PARTS(2024, 3, 1))` → `2` |
| `DATE_WEEKDAY(date)` | Return the weekday of `date` from Monday = 1 to Sunday = 7. | `DATE_WEEKDAY(DATE_FROM_PARTS(2024, 2, 29))` → `4` |
| `DATE_IS_WEEKEND(date)` | Test whether `date` is a Saturday or Sunday. | `DATE_IS_WEEKEND(DATE_FROM_PARTS(2024, 3, 3))` → `TRUE` |
| `DATE_END_OF_MONTH(date)` | Return the last day of the month containing `date`. | `DATE_END_OF_MONTH(DATE_FROM_PARTS(2024, 2, 1))` → `DATE 2024-02-29` |
| `DATE_ADD_MONTHS(date, count)` | Add a signed whole `count` of months to `date`. Clamp to the destination month's last day when needed. | `DATE_ADD_MONTHS(DATE_FROM_PARTS(2024, 1, 31), 1)` → `DATE 2024-02-29` |
| `DATE_ISO_WEEK(date)` | Return the ISO week number for `date`. Weeks start Monday, and the first week includes January 4. | `DATE_ISO_WEEK(DATE_FROM_PARTS(2021, 1, 1))` → `53` |
| `DATE_ISO_WEEK_YEAR(date)` | Return the year of the ISO week that contains `date`. | `DATE_ISO_WEEK_YEAR(DATE_FROM_PARTS(2021, 1, 1))` → `2020` |
| `TIMESTAMP_ADD_SECONDS(timestamp, count)` | Add `count` elapsed seconds to `timestamp`, preserving its numeric offset. | `TIMESTAMP_ADD_SECONDS(TIMESTAMP_FROM_UNIX(0), 0.5)` → `TIMESTAMP 1970-01-01T00:00:00.5Z` |
| `TIMESTAMP_DIFF_SECONDS(start, end)` | Return `end` minus `start` in elapsed seconds. | `TIMESTAMP_DIFF_SECONDS(TIMESTAMP_FROM_UNIX(1), TIMESTAMP_FROM_UNIX(3))` → `2` |
| `TIMESTAMP_FROM_UNIX(seconds)` | Convert epoch `seconds` into a UTC timestamp, rounding fractional input to the nearest nanosecond. | `TIMESTAMP_FROM_UNIX(0.5)` → `TIMESTAMP 1970-01-01T00:00:00.5Z` |
| `TIMESTAMP_TO_UNIX(timestamp)` | Return the epoch seconds of `timestamp` as a number. Large values can lose subsecond precision. | `TIMESTAMP_TO_UNIX(TIMESTAMP_PARSE("1970-01-01T01:00:00+01:00"))` → `0` |
