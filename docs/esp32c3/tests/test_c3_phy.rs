#[path = "../../../esp-wifi-hal/src/c3_phy.rs"]
mod c3_phy;

use std::{cell::RefCell, collections::BTreeMap};
type Access = (char, usize, u32);
#[derive(Default)]
struct State {
    seed: u32,
    registers: BTreeMap<usize, u32>,
    trace: Vec<Access>,
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }

#[unsafe(no_mangle)]
extern "C" fn c3_phy_test_read(address: usize) -> u32 {
    assert_eq!(address & 3, 0);
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        let value = *s.registers.get(&address).unwrap_or(&s.seed);
        s.trace.push(('r', address, value));
        value
    })
}

#[unsafe(no_mangle)]
extern "C" fn c3_phy_test_write(address: usize, value: u32) {
    assert_eq!(address & 3, 0);
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        s.registers.insert(address, value);
        s.trace.push(('w', address, value));
    });
}

#[test]
fn rust_matches_original_phy_and_sdk_clock_transactions() {
    let mut count = 0;
    for block in include_str!("phy-traces.txt")
        .split("case ")
        .filter(|s| !s.is_empty())
    {
        let mut lines = block.lines();
        let fields = lines.next().unwrap().split_whitespace().collect::<Vec<_>>();
        let seed = fields[0].parse::<u32>().unwrap();
        let name = fields[1];
        let args = fields[2..]
            .iter()
            .map(|s| s.parse::<u32>().unwrap())
            .collect::<Vec<_>>();
        let expected = lines
            .filter(|s| !s.is_empty())
            .map(|line| {
                let fields = line.split_whitespace().collect::<Vec<_>>();
                (
                    fields[0].chars().next().unwrap(),
                    fields[1].parse::<usize>().unwrap(),
                    fields[2].parse::<u32>().unwrap(),
                )
            })
            .collect::<Vec<_>>();
        STATE.with(|s| {
            let registers = if name == "slowclk" {
                BTreeMap::from([(0x600c0024, args[0]), (0x60008054, args[1])])
            } else {
                BTreeMap::new()
            };
            *s.borrow_mut() = State {
                seed,
                registers,
                trace: Vec::new(),
            };
        });
        unsafe {
            match name {
                "phy_disable_low_rate" => c3_phy::disable_low_rate(),
                "rom_disable_wifi_agc" => c3_phy::disable_wifi_agc(),
                "rom_enable_wifi_agc" => c3_phy::enable_wifi_agc(),
                "agc_cycle" => {
                    c3_phy::disable_wifi_agc();
                    c3_phy::enable_wifi_agc();
                }
                "slowclk" => {
                    let value = c3_phy::slowclk_cal_get();
                    STATE.with(|s| s.borrow_mut().trace.push(('v', 0, value)));
                }
                _ => panic!("unexpected case {name}"),
            }
        }
        STATE.with(|s| {
            assert_eq!(
                s.borrow().trace,
                expected,
                "{name}, seed {seed:#x}, args {args:?}"
            )
        });
        count += 1;
    }
    assert_eq!(count, 48);
}
