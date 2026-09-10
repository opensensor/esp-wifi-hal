//! Small S3 PHY register operations reviewed against the linked PHY library.
//!
//! AGC preserves the ROM contract used by the driver's direct calls, including
//! register 0x6001c038. Internal vendor RAM patches use 0x6001c034; substituting
//! that address here regressed RX buffer recovery in the hardware comparison.
//! Calibration and channel tuning still belong to the vendor PHY library.
//! See `docs/esp32s3/PHY-ROM.md` for the instruction and dispatch evidence.

#[inline(always)]
fn read(address: usize) -> u32 {
    #[cfg(test)]
    return tests::read(address);
    #[cfg(not(test))]
    unsafe {
        (address as *const u32).read_volatile()
    }
}

#[inline(always)]
fn write(address: usize, value: u32) {
    #[cfg(test)]
    tests::write(address, value);
    #[cfg(not(test))]
    unsafe {
        (address as *mut u32).write_volatile(value);
    }
}

#[inline(always)]
fn update(address: usize, keep: u32, set: u32) {
    write(address, (read(address) & keep) | set);
}

/// Requires exclusive PHY ownership during MAC initialization.
pub(crate) unsafe fn disable_low_rate() {
    // Preserve the two distinct read/modify/write transactions on 0x6001c860.
    update(0x6001c860, !(1 << 10), 0);
    update(0x6001c860, !(1 << 11), 0);
    update(0x6001c87c, !(1 << 11), 0);
}

/// Requires exclusive PHY ownership during channel switching.
pub(crate) unsafe fn disable_wifi_agc() {
    update(0x6001c01c, !0x00ff0000, 0x007f0000);
    update(0x6001c038, u32::MAX, 0x80);
    update(0x6001c080, u32::MAX, 1);
}

/// Requires exclusive PHY ownership during channel switching.
pub(crate) unsafe fn enable_wifi_agc() {
    update(0x6001c080, !1, 0);
    update(0x6001c01c, !0x00ff0000, 0x00200000);
    update(0x6001c038, u32::MAX, 0x80);
}

#[cfg(test)]
mod tests {
    extern crate std;
    use super::*;
    use std::{cell::RefCell, collections::BTreeMap, vec, vec::Vec};

    // Expected accesses are transcribed from the original Xtensa instruction
    // streams, independently of the update helper. Each read is recorded too:
    // comparing final register values alone misses ordering/merged-write bugs.
    type Access = (char, usize, u32);
    #[derive(Default)]
    struct State {
        seed: u32,
        registers: BTreeMap<usize, u32>,
        trace: Vec<Access>,
        change_after_first_low_rate_write: bool,
    }
    std::thread_local! {
        static STATE: RefCell<State> = RefCell::new(State::default());
    }
    fn reset(seed: u32) {
        STATE.with(|state| {
            *state.borrow_mut() = State {
                seed,
                ..State::default()
            };
        });
    }
    pub(super) fn read(address: usize) -> u32 {
        assert_eq!(address & 3, 0, "PHY accesses must stay 32-bit aligned");
        STATE.with(|state| {
            let mut state = state.borrow_mut();
            let value = *state.registers.get(&address).unwrap_or(&state.seed);
            state.trace.push(('r', address, value));
            value
        })
    }
    pub(super) fn write(address: usize, value: u32) {
        assert_eq!(address & 3, 0, "PHY accesses must stay 32-bit aligned");
        STATE.with(|state| {
            let mut state = state.borrow_mut();
            state.registers.insert(address, value);
            state.trace.push(('w', address, value));
            if address == 0x6001c860 && state.change_after_first_low_rate_write {
                // Model hardware changing unrelated bits between transactions.
                state.registers.insert(address, 0xa55a0801);
                state.change_after_first_low_rate_write = false;
            }
        });
    }
    fn check(expected: Vec<Access>) {
        STATE.with(|state| assert_eq!(state.borrow().trace, expected));
    }
    fn seeds() -> impl Iterator<Item = u32> {
        [0, u32::MAX, 0xaaaaaaaa, 0x55555555]
            .into_iter()
            .chain((0..=255u32).map(|byte| byte * 0x01010101))
    }

    #[test]
    fn low_rate_matches_original_three_ordered_transactions() {
        for seed in seeds() {
            reset(seed);
            unsafe { disable_low_rate() };
            check(vec![
                ('r', 0x6001c860, seed),
                ('w', 0x6001c860, seed & 0xfffffbff),
                ('r', 0x6001c860, seed & 0xfffffbff),
                ('w', 0x6001c860, seed & 0xfffff3ff),
                ('r', 0x6001c87c, seed),
                ('w', 0x6001c87c, seed & 0xfffff7ff),
            ]);
        }
    }

    #[test]
    fn low_rate_reads_hardware_again_before_the_second_write() {
        reset(u32::MAX);
        STATE.with(|state| state.borrow_mut().change_after_first_low_rate_write = true);
        unsafe { disable_low_rate() };
        check(vec![
            ('r', 0x6001c860, u32::MAX),
            ('w', 0x6001c860, 0xfffffbff),
            ('r', 0x6001c860, 0xa55a0801),
            ('w', 0x6001c860, 0xa55a0001),
            ('r', 0x6001c87c, u32::MAX),
            ('w', 0x6001c87c, 0xfffff7ff),
        ]);
    }

    #[test]
    fn disable_agc_matches_direct_rom_contract_and_preserves_other_bits() {
        for seed in seeds() {
            reset(seed);
            unsafe { disable_wifi_agc() };
            check(vec![
                ('r', 0x6001c01c, seed),
                ('w', 0x6001c01c, (seed & 0xff00ffff) | 0x007f0000),
                ('r', 0x6001c038, seed),
                ('w', 0x6001c038, seed | 0x80),
                ('r', 0x6001c080, seed),
                ('w', 0x6001c080, seed | 1),
            ]);
        }
    }

    #[test]
    fn enable_agc_matches_direct_rom_contract_in_its_distinct_order() {
        for seed in seeds() {
            reset(seed);
            unsafe { enable_wifi_agc() };
            check(vec![
                ('r', 0x6001c080, seed),
                ('w', 0x6001c080, seed & 0xfffffffe),
                ('r', 0x6001c01c, seed),
                ('w', 0x6001c01c, (seed & 0xff00ffff) | 0x00200000),
                ('r', 0x6001c038, seed),
                ('w', 0x6001c038, seed | 0x80),
            ]);
        }
    }

    #[test]
    fn agc_pair_leaves_the_internal_ram_patch_register_untouched() {
        reset(0x13579bdf);
        unsafe {
            disable_wifi_agc();
            enable_wifi_agc();
        }
        STATE.with(|state| {
            let state = state.borrow();
            assert_eq!(state.trace.len(), 12);
            assert!(
                state
                    .trace
                    .iter()
                    .all(|(_, address, _)| *address != 0x6001c034)
            );
            assert_eq!(state.registers[&0x6001c01c], 0x13209bdf);
            assert_eq!(state.registers[&0x6001c038], 0x13579bdf);
            assert_eq!(state.registers[&0x6001c080], 0x13579bde);
        });
    }
}
