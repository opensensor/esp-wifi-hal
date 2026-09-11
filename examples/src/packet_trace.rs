//! Packet metadata at the FoA/embassy boundary, enabled only for network tracing.
//! No payload bytes or network credentials are logged.
//! Opt in with `ESP_LOG=info,examples::packet_trace=trace`. Synchronous packet
//! output can substantially delay radio servicing; keep it off for timing tests.
use core::task::Context;
use embassy_net_driver::{Capabilities, Driver, HardwareAddress, LinkState, RxToken, TxToken};

pub struct TraceDriver<D>(pub D);
pub struct TraceRx<T>(T);
pub struct TraceTx<T>(T);
impl<D: Driver> Driver for TraceDriver<D> {
    type RxToken<'a>
        = TraceRx<D::RxToken<'a>>
    where
        Self: 'a;
    type TxToken<'a>
        = TraceTx<D::TxToken<'a>>
    where
        Self: 'a;
    fn receive(&mut self, cx: &mut Context) -> Option<(Self::RxToken<'_>, Self::TxToken<'_>)> {
        self.0
            .receive(cx)
            .map(|(rx, tx)| (TraceRx(rx), TraceTx(tx)))
    }
    fn transmit(&mut self, cx: &mut Context) -> Option<Self::TxToken<'_>> {
        self.0.transmit(cx).map(TraceTx)
    }
    fn link_state(&mut self, cx: &mut Context) -> LinkState {
        self.0.link_state(cx)
    }
    fn capabilities(&self) -> Capabilities {
        self.0.capabilities()
    }
    fn hardware_address(&self) -> HardwareAddress {
        self.0.hardware_address()
    }
}
impl<T: RxToken> RxToken for TraceRx<T> {
    fn consume<R, F: FnOnce(&mut [u8]) -> R>(self, f: F) -> R {
        self.0.consume(|buf| {
            record("rx", buf);
            f(buf)
        })
    }
}
impl<T: TxToken> TxToken for TraceTx<T> {
    fn consume<R, F: FnOnce(&mut [u8]) -> R>(self, len: usize, f: F) -> R {
        self.0.consume(len, |buf| {
            let result = f(buf);
            record("tx", buf);
            result
        })
    }
}
fn word(b: &[u8], p: usize) -> u16 {
    u16::from_be_bytes([b[p], b[p + 1]])
}
fn record(direction: &str, b: &[u8]) {
    if !log::log_enabled!(log::Level::Trace) || b.len() < 14 {
        return;
    }
    let now = embassy_time::Instant::now().as_micros();
    match word(b, 12) {
        0x0806
            if b.len() >= 42
                && word(b, 14) == 1
                && word(b, 16) == 0x0800
                && b[18] == 6
                && b[19] == 4 =>
        {
            log::trace!(
                "stage=packet us={} dir={} arp={} from={:?} to={:?}",
                now,
                direction,
                word(b, 20),
                &b[28..32],
                &b[38..42]
            )
        }
        0x0800 if b.len() >= 34 && b[14] >> 4 == 4 => {
            let header = (b[14] & 15) as usize * 4;
            let offset = 14 + header;
            if header >= 20
                && b.len() >= offset + 8
                && b[23] == 1
                && word(b, 20) & 0x1fff == 0
                && matches!(b[offset], 0 | 8)
            {
                log::trace!(
                    "stage=packet us={} dir={} icmp={} id={} seq={} len={} from={:?} to={:?}",
                    now,
                    direction,
                    b[offset],
                    word(b, offset + 4),
                    word(b, offset + 6),
                    word(b, 16),
                    &b[26..30],
                    &b[30..34]
                );
            }
        }
        _ => {}
    }
}
