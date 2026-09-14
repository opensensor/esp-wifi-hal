//! Replay every externally visible access against original instruction traces.
#[path = "../../../esp-wifi-hal/src/phy_spur.rs"]
mod phy_spur;
use std::cell::RefCell;
use std::collections::VecDeque;
use std::io::{BufRead, BufReader};

#[derive(Debug, PartialEq, Eq)]
struct Event(char, Vec<u32>);

#[derive(Default)]
struct State {
    events: VecDeque<Event>,
    generation: u32,
    table_mutation: bool,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State::default());
}

#[derive(Debug)]
struct DivideTrap;
struct Host;

impl phy_spur::Access for Host {
    unsafe fn parameter() -> usize {
        0x230000
    }
    unsafe fn table_global() -> usize {
        0x220000
    }
    unsafe fn read(address: usize, width: usize) -> u32 {
        STATE.with_borrow_mut(|state| {
            assert!(matches!(width, 1 | 2 | 4));
            assert_eq!(address % width, 0);
            if address == 0x220000 {
                assert_eq!(width, 4);
                return 0x70000000 + state.generation * 0x1000;
            }
            if (0x70000000..0x71000000).contains(&address) {
                assert_eq!(width, 4);
                return address as u32 + 0x1000000;
            }
            let event = state.events.pop_front().expect("Read past trace end");
            assert_eq!(
                event.0, 'R',
                "Expected read at {address:x}/{width}: {event:?}"
            );
            assert_eq!(event.1.len(), 3);
            assert_eq!(event.1[..2], [address as u32, width as u32]);
            event.1[2]
        })
    }
    unsafe fn write(address: usize, width: usize, value: u32) {
        assert!(matches!(width, 1 | 2 | 4));
        assert_eq!(address % width, 0);
        let mask = match width {
            1 => 255,
            2 => 65535,
            _ => u32::MAX,
        };
        STATE.with_borrow_mut(|state| {
            assert_eq!(
                state.events.pop_front(),
                Some(Event('W', vec![address as u32, width as u32, value & mask]))
            );
        });
    }
    unsafe fn call(target: usize, kind: u32, args: &[u32]) -> u32 {
        STATE.with_borrow_mut(|state| {
            let mut call = vec![kind, target as u32];
            call.extend(args);
            assert_eq!(state.events.pop_front(), Some(Event('K', call)));
            // These writes belong to the opaque callback fixture. Subsequent
            // production reads must still consume the corresponding live values.
            while state.events.front().is_some_and(|event| event.0 == 'W') {
                state.events.pop_front();
            }
            let event = state.events.pop_front().expect("Missing callback return");
            assert_eq!(event.0, 'V');
            assert_eq!(event.1.len(), 1);
            if state.table_mutation {
                state.generation += 1;
            }
            event.1[0]
        })
    }
    unsafe fn quotient(numerator: i32, denominator: i32) -> i32 {
        if denominator == 0 {
            std::panic::panic_any(DivideTrap);
        }
        ((numerator as i64) / (denominator as i64)) as i32
    }
}

fn main() {
    let original_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if !info.payload().is::<DivideTrap>() {
            original_hook(info);
        }
    }));
    let path = std::env::args()
        .nth(1)
        .expect("host-cases.txt path required");
    let mut lines = BufReader::new(std::fs::File::open(path).unwrap()).lines();
    let mut cases = 0;
    let mut traps = 0;
    while let Some(line) = lines.next() {
        let line = line.unwrap();
        let mut fields = line.split_whitespace();
        assert_eq!(fields.next(), Some("C"));
        let header: Vec<u32> = fields.map(|word| word.parse().unwrap()).collect();
        assert_eq!(header.len(), 10);
        let arguments: [u32; 7] = header[3..].try_into().unwrap();
        let mut events = VecDeque::new();
        loop {
            let line = lines.next().expect("Missing case terminator").unwrap();
            if line == "E" {
                break;
            }
            let mut fields = line.split_whitespace();
            let kind = fields.next().unwrap().chars().next().unwrap();
            events.push_back(Event(
                kind,
                fields.map(|word| word.parse().unwrap()).collect(),
            ));
        }
        STATE.set(State {
            events,
            generation: 0,
            table_mutation: header[1] != 0,
        });
        let result = std::panic::catch_unwind(|| unsafe {
            match header[0] {
                0 => phy_spur::configure::<Host>(arguments),
                1 => phy_spur::power::<Host>(header[2]),
                _ => panic!("Unknown operation"),
            }
        });
        if let Err(error) = result {
            if error.is::<DivideTrap>() {
                STATE.with_borrow_mut(|state| {
                    assert_eq!(state.events.pop_front(), Some(Event('X', vec![6])))
                });
                traps += 1;
            } else {
                eprintln!("Host replay failed in case {}", cases + 1);
                std::panic::resume_unwind(error);
            }
        }
        STATE.with_borrow(|state| {
            assert!(
                state.events.is_empty(),
                "Unconsumed trace in case {}: {:?}",
                cases + 1,
                state.events.front()
            )
        });
        cases += 1;
    }
    assert_eq!(cases, 4308);
    assert_eq!(traps, 32);
    println!(
        "S3 spur production Rust: {cases} original trace cases, {traps} divide-by-zero boundaries passed"
    );
}
