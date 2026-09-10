#![allow(dead_code, unexpected_cfgs)]

use core::{
    ops::{DerefMut, RangeInclusive},
    pin::Pin,
};
use log::{trace, warn};
use macro_bits::bit;
use std::{
    cell::{Cell, RefCell},
    collections::VecDeque,
};

// Only the hardware boundary is replaced. Use actual retry/EDCA algorithms,
// parameters, queue categories, error classes and rate iterator from production.
extern crate self as esp_hal;
pub mod rng {
    pub struct Rng;
    impl Rng {
        pub fn new() -> Self {
            Self
        }
        pub fn random(&self) -> u32 {
            7
        }
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TxPhyRate(pub u8);
mod edca {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../esp-wifi-hal/src/edca.rs"
    ));
}
use edca::EdcaContentionState;

#[derive(Default)]
struct DmaDescriptor {
    buffer: *const u8,
    len: usize,
}
#[derive(Clone, Copy)]
struct Attempt {
    result: Result<(), TxError>,
    reaches_peer: bool,
}
impl Attempt {
    fn success() -> Self {
        Self {
            result: Ok(()),
            reaches_peer: true,
        }
    }
    fn ack_lost() -> Self {
        Self {
            result: Err(TxError::MacProtocol(MacProtocolError::AckTimeout)),
            reaches_peer: true,
        }
    }
    fn channel(error: ChannelAccessError) -> Self {
        Self {
            result: Err(TxError::ChannelAccess(error)),
            reaches_peer: false,
        }
    }
}
#[derive(Default)]
struct Peer {
    last_sequence: Option<u16>,
    delivered: Vec<Vec<u8>>,
    duplicates: usize,
}
impl Peer {
    fn receive(&mut self, bytes: &[u8]) {
        if bytes.len() < 24 {
            return;
        }
        // A non-QoS unicast peer duplicate cache, matching the Retry+SC check.
        let sequence = u16::from_le_bytes([bytes[22], bytes[23]]);
        if bytes[1] & 8 != 0 && self.last_sequence == Some(sequence) {
            self.duplicates += 1;
        } else {
            self.last_sequence = Some(sequence);
            self.delivered.push(bytes.to_vec());
        }
    }
}
struct TestDriver {
    steps: RefCell<VecDeque<Attempt>>,
    observed: RefCell<Vec<Vec<u8>>>,
    observed_rates: RefCell<Vec<TxPhyRate>>,
    peer: RefCell<Peer>,
    preparations: Cell<usize>,
}
impl TestDriver {
    fn new(steps: impl IntoIterator<Item = Attempt>) -> Self {
        Self {
            steps: RefCell::new(steps.into_iter().collect()),
            observed: RefCell::new(Vec::new()),
            observed_rates: RefCell::new(Vec::new()),
            peer: RefCell::new(Peer::default()),
            preparations: Cell::new(0),
        }
    }
    fn prepare_frame_for_tx(
        &self,
        _: usize,
        _: &TxMacParameters,
        _: &mut [u8],
    ) -> Result<ExtractedParameters, TxError> {
        self.preparations.set(self.preparations.get() + 1);
        // Intentionally allow tiny buffers here to exercise the retry loop's
        // bounds guards independently of normal hardware frame validation.
        Ok(ExtractedParameters {
            duration: 0,
            is_unicast: true,
        })
    }
    fn prepare_dma_descriptor_for_tx(frame: &mut [u8], descriptor: &mut DmaDescriptor) {
        descriptor.buffer = frame.as_ptr();
        descriptor.len = frame.len();
    }
    async fn transmit_raw(
        &self,
        _: usize,
        rate: TxPhyRate,
        _: &TxMacParameters,
        _: HardwareTxQueue,
        descriptor: Pin<&DmaDescriptor>,
        _: Result<(ExtractedParameters, EdcaTxParameters), TxError>,
    ) -> Result<(), TxError> {
        // SAFETY: the production retry method owns the frame throughout this
        // awaited call. The fake DMA reads it only now and retains a copy; no
        // aliased view survives into the next mutation or attempt.
        let frame =
            unsafe { core::slice::from_raw_parts(descriptor.buffer, descriptor.len) }.to_vec();
        self.observed.borrow_mut().push(frame.clone());
        self.observed_rates.borrow_mut().push(rate);
        let step = self
            .steps
            .borrow_mut()
            .pop_front()
            .expect("unexpected extra retry");
        if step.reaches_peer {
            self.peer.borrow_mut().receive(&frame);
        }
        let mut waited = false;
        core::future::poll_fn(|cx| {
            if waited {
                core::task::Poll::Ready(())
            } else {
                waited = true;
                cx.waker().wake_by_ref();
                core::task::Poll::Pending
            }
        })
        .await;
        step.result
    }
}

include!(concat!(env!("OUT_DIR"), "/production.rs"));

#[cfg(test)]
mod tests;
