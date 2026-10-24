# Core2 BLE voice capture

The Core2 advertises as `M5StackCore2-Pet` with service
`7f5a0001-7b7d-4f3b-9d01-000000000001`. Its screen shows the BLE connection
state. An Android receiver must subscribe to the voice data notification and
configure the transfer before recording is enabled.

Hold button A to record. Releasing it, or reaching five seconds, ends the
recording. Recordings shorter than 0.2 seconds are rejected. The microphone
captures 16 kHz mono PCM16, and the Core2 compresses it to IMA ADPCM (four
bits per sample, low nibble first, predictor and index initially zero).

## BLE voice protocol

- Data notifications: `7f5a0001-7b7d-4f3b-9d01-000000000005`
- Control writes: `7f5a0001-7b7d-4f3b-9d01-000000000006`
- Android first enables data notifications, then writes `[1, chunkSize]` to
  control. `chunkSize` is the audio payload size from 1 to 240 bytes and must
  fit the negotiated ATT MTU minus seven bytes. The Core2 requests MTU 247.
- Core2 sends `START [1, session, sampleCount LE32, codec=1]`, waits for ACK
  sequence zero, then sends `DATA [2, session, sequence LE16, ADPCM bytes]`.
  Sequence starts at one. After every four data packets, or at the last one,
  Android writes cumulative ACK `[2, session, sequence LE16]`.
- Core2 sends `END [3, session, lastDataSequence+1 LE16]` and waits for its ACK.
  It retries a packet window after 500 ms, up to six retries.

The screen's `Sent to Android` means the Core2 received the END ACK. Firmware
build: `pio run` in this directory. Actual recording and BLE transfer require
a Core2 and Android receiver for verification.
