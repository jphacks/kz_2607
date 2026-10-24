# Core2 BLE voice capture

The Core2 advertises as `M5StackCore2` with service
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

## Android reply audio to Core2

Cloud Functions can return `replyFormat: "ima_adpcm"`. Android must request that
format, Base64-decode `replyAudioBase64`, and check that `replyAudio` reports
`format: "ima_adpcm"`, `sampleRate: 16000`, `channels: 1`, and a `sampleCount`
of 1 to 480000. The encoded length must be `(sampleCount + 1) / 2` rounded
down. The current Android code requests WAV and does not yet send reply audio;
it needs its own sender before this path can run end to end.

- Android writes reply packets to
  `7f5a0001-7b7d-4f3b-9d01-000000000007` and subscribes to ACK notifications
  on `7f5a0001-7b7d-4f3b-9d01-000000000008`.
- `START [1, session, sampleCount LE32, codec=1, chunkSize]` declares the
  recording. `chunkSize` is 1 to 240 bytes and must fit the negotiated ATT MTU
  minus seven bytes. Core2 replies `[2, session, sequence=0 LE16]`.
- `DATA [2, session, sequence LE16, ADPCM bytes]` starts at sequence one. Core2
  cumulatively acknowledges every four packets and the final data packet.
- `END [3, session, lastDataSequence+1 LE16]` completes transfer. Core2
  acknowledges it, decodes the ADPCM from the zero predictor/index state, and
  plays 16 kHz mono PCM16 on its speaker. Android should retry unacknowledged
  packet windows. An error notification is `[4, session, code, 0]`, where code
  1 means invalid format, 2 means busy, and 3 means insufficient audio memory.

The END ACK confirms receipt of all encoded bytes; playback may still fail
afterward. Core2 displays receiving and playing status. It rejects new reply
audio while recording, transmitting, receiving, or playing. A partial transfer
times out after eight seconds.
