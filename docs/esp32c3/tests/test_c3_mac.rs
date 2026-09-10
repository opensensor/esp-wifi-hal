#[path = "../../../esp-wifi-hal/src/c3_mac.rs"]
mod c3_mac;

use std::{cell::RefCell, collections::BTreeMap};
type Access = (char, usize, u32);
#[derive(Default)]
struct State { seed: u32, registers: BTreeMap<usize, u32>, trace: Vec<Access> }
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
fn reset(seed: u32) {
    STATE.with(|s| *s.borrow_mut() = State {
        seed, registers: BTreeMap::from([(0x60033d14, seed | 1)]), trace: Vec::new()
    });
}
#[unsafe(no_mangle)]
extern "C" fn c3_test_read(address: usize) -> u32 {
    assert_eq!(address & 3, 0);
    STATE.with(|s| { let mut s=s.borrow_mut(); let value=*s.registers.get(&address).unwrap_or(&s.seed);
        s.trace.push(('r',address,value)); value })
}
#[unsafe(no_mangle)]
extern "C" fn c3_test_write(address: usize, value: u32) {
    assert_eq!(address & 3, 0);
    STATE.with(|s| { let mut s=s.borrow_mut(); s.registers.insert(address,value); s.trace.push(('w',address,value)); });
}
#[unsafe(no_mangle)]
extern "C" fn phy_disable_low_rate() { STATE.with(|s| s.borrow_mut().trace.push(('p',0,0))); }
mod ffi {
    pub unsafe fn slowclk_cal_get() -> u32 {
        super::STATE.with(|s| s.borrow_mut().trace.push(('c',0,0x12345678)));
        0x12345678
    }
}

#[test]
fn rust_matches_all_original_rv32_instruction_traces() {
    let input=include_str!("original-traces.txt");
    let mut count=0;
    for block in input.split("case ").filter(|s| !s.is_empty()) {
        let mut lines=block.lines();
        let fields=lines.next().unwrap().split_whitespace().collect::<Vec<_>>();
        let seed=fields[0].parse::<u32>().unwrap();
        let name=fields[1];
        let args=fields[2..].iter().map(|s| s.parse::<u32>().unwrap()).collect::<Vec<_>>();
        let expected=lines.filter(|s| !s.is_empty()).map(|line| {
            let parts=line.split_whitespace().collect::<Vec<_>>();
            (parts[0].chars().next().unwrap(),parts[1].parse::<usize>().unwrap(),parts[2].parse::<u32>().unwrap())
        }).collect::<Vec<_>>();
        reset(seed);
        unsafe {
            use c3_mac::helpers::*;
            match name {
                "hal_init" => c3_mac::init(),
                "hal_crypto_init" => hal_crypto_init(),
                "hal_attenna_init" => hal_attenna_init(),
                "hal_mac_rate_autoack_init" => hal_mac_rate_autoack_init(),
                "hal_coex_pti_init" => hal_coex_pti_init(),
                "hal_set_rx_active_pti" => hal_set_rx_active_pti(args[0]),
                "hal_set_rx_ack_pti" => hal_set_rx_ack_pti(args[0]),
                "hal_set_wifi_default_pti" => hal_set_wifi_default_pti(args[0]),
                "hal_timer_update_by_rtc" => hal_timer_update_by_rtc(args[0],args[1]),
                _ => panic!("unexpected case {name}"),
            }
        }
        STATE.with(|s| assert_eq!(s.borrow().trace,expected,"{name} seed {seed:#x} arguments {args:?}"));
        count+=1;
    }
    assert_eq!(count,260);
}
