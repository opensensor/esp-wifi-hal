use super::*;
use core::{
    future::Future,
    pin::pin,
    task::{Context, Poll, Waker},
};

fn frame(sequence: u16, packet_number: u8) -> [u8; 64] {
    let mut frame = [0x6bu8; 64];
    frame[0] = 0x08; // Non-QoS data.
    frame[1] = 0x41; // To-DS and Protected, initially no Retry.
    frame[22..24].copy_from_slice(&(sequence << 4).to_le_bytes());
    frame[24..32].copy_from_slice(&[packet_number, 2, 0, 0x20, 3, 4, 5, 6]);
    frame
}

fn run(
    driver: &TestDriver,
    frame: &mut [u8],
    behaviour: TxErrorBehaviour<'_>,
) -> Result<u8, TxError> {
    let plcp = TxPlcpParameters {
        rate: TxPhyRate(7),
        ..Default::default()
    };
    let mac = TxMacParameters {
        wait_for_ack: true,
        ..Default::default()
    };
    let mut descriptor = pin!(DmaDescriptor::default());
    let mut future = pin!(driver.transmit_with_retry(
        0,
        &plcp,
        &mac,
        behaviour,
        HardwareTxQueue::Edcaf(EdcaAccessCategory::default()),
        descriptor.as_mut(),
        frame,
    ));
    for _ in 0..1024 {
        match future
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
        {
            Poll::Ready(result) => return result,
            Poll::Pending => {}
        }
    }
    panic!("production retry loop did not finish");
}

fn flags(driver: &TestDriver) -> Vec<bool> {
    driver
        .observed
        .borrow()
        .iter()
        .map(|frame| frame[1] & 8 != 0)
        .collect()
}

fn assert_only_retry_changed(driver: &TestDriver, original: &[u8]) {
    for frame in driver.observed.borrow().iter() {
        assert_eq!(frame.len(), original.len());
        for (i, (&got, &expected)) in frame.iter().zip(original).enumerate() {
            assert_eq!(
                if i == 1 { got & !8 } else { got },
                expected,
                "byte {i} changed"
            );
        }
    }
}

#[test]
fn lost_ack_retransmits_same_mpdu_without_duplicate_peer_delivery() {
    let driver = TestDriver::new([Attempt::ack_lost(), Attempt::success()]);
    let mut frame = frame(13, 1);
    let original = frame;
    assert_eq!(
        run(&driver, &mut frame, TxErrorBehaviour::RetryUntil(7)),
        Ok(1)
    );
    assert_eq!(driver.peer.borrow().delivered.len(), 1);
    assert_eq!(driver.peer.borrow().duplicates, 1);
    assert_eq!(flags(&driver), [false, true]);
    assert_eq!(
        driver.preparations.get(),
        1,
        "do not reassign sequence or PN on retry"
    );
    assert_only_retry_changed(&driver, &original);
    assert_eq!(
        frame, original,
        "final cleanup must restore the caller's frame"
    );
}

#[test]
fn channel_access_failures_before_any_mac_error_do_not_mark_retry() {
    let driver = TestDriver::new([
        Attempt::channel(ChannelAccessError::Timeout),
        Attempt::channel(ChannelAccessError::Collision),
        Attempt::success(),
    ]);
    let mut frame = frame(1, 1);
    assert_eq!(
        run(&driver, &mut frame, TxErrorBehaviour::RetryUntil(2)),
        Ok(2)
    );
    assert_eq!(flags(&driver), [false, false, false]);
    assert_eq!(driver.peer.borrow().delivered.len(), 1);
    assert_eq!(driver.peer.borrow().duplicates, 0);
}

#[test]
fn mac_retry_survives_later_channel_access_failures() {
    let driver = TestDriver::new([
        Attempt::ack_lost(),
        Attempt::channel(ChannelAccessError::Timeout),
        Attempt::channel(ChannelAccessError::Collision),
        Attempt::success(),
    ]);
    let mut frame = frame(2, 1);
    let original = frame;
    assert_eq!(
        run(&driver, &mut frame, TxErrorBehaviour::RetryUntil(3)),
        Ok(3)
    );
    assert_eq!(flags(&driver), [false, true, true, true]);
    assert_eq!(driver.peer.borrow().delivered.len(), 1);
    assert_eq!(driver.peer.borrow().duplicates, 1);
    assert_only_retry_changed(&driver, &original);
    assert_eq!(frame, original);
}

#[test]
fn channel_then_mac_failure_marks_only_subsequent_attempts() {
    let driver = TestDriver::new([
        Attempt::channel(ChannelAccessError::Timeout),
        Attempt::ack_lost(),
        Attempt::success(),
    ]);
    let mut frame = frame(3, 1);
    assert_eq!(
        run(&driver, &mut frame, TxErrorBehaviour::RetryUntil(2)),
        Ok(2)
    );
    assert_eq!(flags(&driver), [false, false, true]);
    assert_eq!(driver.peer.borrow().delivered.len(), 1);
}

#[test]
fn all_existing_mac_error_classes_keep_historical_retry_policy() {
    for error in [
        MacProtocolError::AckTimeout,
        MacProtocolError::CtsTimeout,
        MacProtocolError::RtsChannelAccessError(ChannelAccessError::Timeout),
        MacProtocolError::InvalidKeyId,
        MacProtocolError::Unknown {
            error: 9,
            sub_error: 7,
        },
    ] {
        let driver = TestDriver::new([
            Attempt {
                result: Err(TxError::MacProtocol(error)),
                reaches_peer: false,
            },
            Attempt::success(),
        ]);
        assert_eq!(
            run(&driver, &mut frame(4, 1), TxErrorBehaviour::RetryUntil(1)),
            Ok(1)
        );
        assert_eq!(flags(&driver), [false, true], "{error:?}");
    }
}

#[test]
fn completed_retry_does_not_mark_a_fresh_frame_using_the_same_buffer() {
    let driver = TestDriver::new([Attempt::ack_lost(), Attempt::success(), Attempt::success()]);
    let mut bytes = frame(13, 1);
    assert_eq!(
        run(&driver, &mut bytes, TxErrorBehaviour::RetryUntil(1)),
        Ok(1)
    );
    bytes[22..24].copy_from_slice(&(14u16 << 4).to_le_bytes());
    bytes[24] = 2;
    assert_eq!(
        run(&driver, &mut bytes, TxErrorBehaviour::RetryUntil(1)),
        Ok(0)
    );
    assert_eq!(flags(&driver), [false, true, false]);
    assert_eq!(driver.peer.borrow().delivered.len(), 2);
    assert_eq!(driver.peer.borrow().duplicates, 1);
}

#[test]
fn exhaustion_keeps_attempt_limit_final_error_and_cleanup() {
    let driver = TestDriver::new([
        Attempt::ack_lost(),
        Attempt::ack_lost(),
        Attempt::ack_lost(),
        Attempt::success(),
    ]);
    let mut bytes = frame(5, 1);
    let original = bytes;
    assert_eq!(
        run(&driver, &mut bytes, TxErrorBehaviour::RetryUntil(2)),
        Err(TxError::MacProtocol(MacProtocolError::AckTimeout))
    );
    assert_eq!(flags(&driver), [false, true, true]);
    assert_eq!(
        driver.steps.borrow().len(),
        1,
        "must not extend caller's retry limit"
    );
    assert_eq!(driver.peer.borrow().delivered.len(), 1);
    assert_eq!(driver.peer.borrow().duplicates, 2);
    assert_eq!(bytes, original);
}

#[test]
fn drop_policy_sends_once_and_cleans_up_after_mac_error() {
    let driver = TestDriver::new([Attempt::ack_lost(), Attempt::success()]);
    let mut bytes = frame(6, 1);
    let original = bytes;
    assert_eq!(
        run(&driver, &mut bytes, TxErrorBehaviour::Drop),
        Err(TxError::MacProtocol(MacProtocolError::AckTimeout))
    );
    assert_eq!(flags(&driver), [false]);
    assert_eq!(driver.steps.borrow().len(), 1);
    assert_eq!(bytes, original);
}

#[test]
fn rate_fallback_retains_sequence_and_retry_marking() {
    let driver = TestDriver::new([Attempt::ack_lost(), Attempt::ack_lost(), Attempt::success()]);
    let rates = [TxPhyRate(99), TxPhyRate(3), TxPhyRate(2)];
    let mut bytes = frame(7, 1);
    let original = bytes;
    assert_eq!(
        run(
            &driver,
            &mut bytes,
            TxErrorBehaviour::MultiRateRetry(&rates)
        ),
        Ok(2)
    );
    assert_eq!(
        *driver.observed_rates.borrow(),
        [TxPhyRate(7), TxPhyRate(3), TxPhyRate(2)]
    );
    assert_eq!(flags(&driver), [false, true, true]);
    assert_only_retry_changed(&driver, &original);
}

#[test]
fn raw_caller_retry_flag_is_preserved_on_first_attempt() {
    let driver = TestDriver::new([
        Attempt::channel(ChannelAccessError::Timeout),
        Attempt::success(),
    ]);
    let mut bytes = frame(8, 1);
    bytes[1] |= 8;
    assert_eq!(
        run(&driver, &mut bytes, TxErrorBehaviour::RetryUntil(1)),
        Ok(1)
    );
    assert_eq!(flags(&driver), [true, true]);
    assert_eq!(bytes[1] & 8, 0, "retain existing final clear semantics");
}

#[test]
fn retry_loop_bounds_guards_handle_tiny_buffers() {
    for length in [0, 1, 2, 4, 23] {
        let driver = TestDriver::new([Attempt::ack_lost(), Attempt::success()]);
        let mut bytes = vec![0; length];
        assert_eq!(
            run(&driver, &mut bytes, TxErrorBehaviour::RetryUntil(1)),
            Ok(1)
        );
        assert_eq!(bytes, vec![0; length]);
        assert_eq!(driver.observed.borrow().len(), 2);
    }
}
