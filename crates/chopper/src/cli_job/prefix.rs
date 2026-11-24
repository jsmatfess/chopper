//! Nonvalidating lexical accounting; serde remains the only JSON validator.
//! Equations and pinned implementation assumptions: docs/cli-job-decoding.md.
use chopper_core::{Allocation, CalculatedColumn, Column, Operation};
use std::mem::size_of;

pub(super) const DEFAULTS: usize = 28;
pub(super) const C: usize = size_of::<serde::__private229::de::Content<'static>>();
pub(super) const L: usize = size_of::<Column>();
pub(super) const U: usize = {
    let o = size_of::<Operation>();
    let a = size_of::<Allocation>();
    let calculated = size_of::<CalculatedColumn>();
    let m = if o > a { o } else { a };
    let m = if m > calculated { m } else { calculated };
    if m > L {
        m
    } else {
        L
    }
};
const _: () = assert!(C >= 2 && 2 * C <= 1024 && L >= 2 && L <= 1024 && U >= 2 && U <= 1024);

#[derive(Clone, Copy, Default)]
struct Frame {
    array: bool,
    slots: usize,
    containers: usize,
}
fn growth(n: usize, slot: usize) -> Option<usize> {
    if n == 0 {
        Some(0)
    } else {
        n.checked_mul(3)?.max(4).checked_mul(slot)
    }
}
impl Frame {
    fn allowance(self) -> Option<usize> {
        if self.array {
            let typed = self
                .slots
                .checked_mul(U)?
                .min(1_048_576)
                .max(growth(self.slots, L)?)
                .max(growth(self.containers, U)?);
            growth(self.slots, C)?.checked_add(typed)
        } else {
            growth(self.slots, 2 * C)
        }
    }
}
pub(super) fn scratch(n: usize) -> Option<usize> {
    if n == 0 {
        return Some(0);
    }
    let p = n.checked_next_power_of_two()?.max(8);
    p.checked_add(p / 2)
}

pub(super) struct Prefix {
    frames: [Frame; 128],
    depth: usize,
    quoted: bool,
    escaped: bool,
    string: usize,
    pub(super) text: usize,
    pub(super) longest: usize,
    pub(super) descriptors: usize,
    pub(super) bytes: usize,
    arrays: usize,
    objects: usize,
    commas: usize,
    pub(super) fallback: bool,
    pub(super) required: usize,
}
impl Default for Prefix {
    fn default() -> Self {
        Self {
            frames: [Frame::default(); 128],
            depth: 0,
            quoted: false,
            escaped: false,
            string: 0,
            text: 0,
            longest: 0,
            descriptors: 0,
            bytes: 0,
            arrays: 0,
            objects: 0,
            commas: 0,
            fallback: false,
            required: DEFAULTS,
        }
    }
}
impl Prefix {
    // All state is inline. An overflow is terminal accounting inability; callers
    // withhold the inspected byte and never use the partially updated state.
    pub(super) fn advance(&mut self, byte: u8) -> Option<usize> {
        self.bytes = self.bytes.checked_add(1)?;
        match byte {
            b'[' => self.arrays = self.arrays.checked_add(1)?,
            b'{' => self.objects = self.objects.checked_add(1)?,
            b',' => self.commas = self.commas.checked_add(1)?,
            _ => {}
        }
        if !self.fallback {
            if self.quoted {
                if byte == b'"' && !self.escaped {
                    self.quoted = false;
                } else {
                    self.text = self.text.checked_add(1)?;
                    self.string = self.string.checked_add(1)?;
                    self.longest = self.longest.max(self.string);
                    self.escaped = byte == b'\\' && !self.escaped;
                }
            } else {
                match byte {
                    b'"' => {
                        self.quoted = true;
                        self.escaped = false;
                        self.string = 0;
                    }
                    b'[' | b'{' => {
                        if self.depth > 0 && self.frames[self.depth - 1].array {
                            self.update_top(true)?;
                        }
                        if self.depth == self.frames.len() {
                            self.fallback = true;
                        } else {
                            let frame = Frame {
                                array: byte == b'[',
                                slots: 1,
                                containers: 0,
                            };
                            self.descriptors = self.descriptors.checked_add(frame.allowance()?)?;
                            self.frames[self.depth] = frame;
                            self.depth += 1;
                        }
                    }
                    b',' if self.depth > 0 => self.update_top(false)?,
                    b']' | b'}' => {
                        if self.depth == 0 || self.frames[self.depth - 1].array != (byte == b']') {
                            self.fallback = true;
                        } else {
                            self.depth -= 1;
                        }
                    }
                    _ => {}
                }
            }
        }
        let next = if self.fallback {
            let commas = self.commas.checked_mul(3)?;
            let arrays = self
                .arrays
                .checked_mul(4)?
                .checked_add(commas)?
                .checked_mul(C.checked_add(U)?)?;
            let objects = self
                .objects
                .checked_mul(4)?
                .checked_add(commas)?
                .checked_mul(2 * C)?;
            DEFAULTS
                .checked_add(self.bytes)?
                .checked_add(scratch(self.bytes)?)?
                .checked_add(arrays)?
                .checked_add(objects)?
        } else {
            DEFAULTS
                .checked_add(self.text)?
                .checked_add(scratch(self.longest)?)?
                .checked_add(self.descriptors)?
        };
        self.required = self.required.max(next);
        Some(self.required)
    }
    fn update_top(&mut self, container: bool) -> Option<()> {
        let frame = &mut self.frames[self.depth - 1];
        let before = frame.allowance()?;
        if container {
            frame.containers = frame.containers.checked_add(1)?;
        } else {
            frame.slots = frame.slots.checked_add(1)?;
        }
        self.descriptors = self
            .descriptors
            .checked_add(frame.allowance()?.checked_sub(before)?)?;
        Some(())
    }
}
