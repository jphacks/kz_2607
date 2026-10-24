# Core2 BLE voice capture

The Core2 advertises as `M5StackCore2` with service
`7f5a0001-7b7d-4f3b-9d01-000000000001`. Its screen shows the BLE connection
state. An Android receiver must subscribe to the voice data notification and
configure the transfer before recording is enabled.

## Nearby Core2 distance

Each Core2 keeps advertising its service UUID while connected to Android and
passively scans for other Core2 devices with the same UUID. The screen displays
the strongest recent peer's BLE address, RSSI, and approximate distance. RSSI
is smoothed and converted with a reference of -59 dBm at one meter and a path
loss factor of 2. These values are starting estimates; walls, body position,
antenna orientation, and the local environment can change the displayed
distance substantially. The scan processes repeated advertisements as they
arrive; a peer disappears after two seconds without one. Scanning pauses
during recording, audio transfer, and
reply playback to leave BLE airtime for audio.

Hold button A to record. Releasing it, or reaching five seconds, ends the
recording. Recordings shorter than 0.2 seconds are rejected. The microphone
captures 16 kHz mono PCM16, and the Core2 compresses it to IMA ADPCM (four
bits per sample, low nibble first, predictor and index initially zero).

## BLE voice protocol

- Data notifications: `7f5a0001-7b7d-4f3b-9d01-000000000005`
- Control writes: `7f5a0001-7b7d-4f3b-9d01-000000000006`
- Android first enables data notifications, then writes `[1, chunkSize]` to
  control. `chunkSize` is the audio payload size from 1 to 240 bytes and must
  fit the negotiated ATT MTU minus seven bytes. The Core2 sets its preferred
  MTU to 247.
- Core2 sends `START [1, session, sampleCount LE32, codec=1]`, waits for ACK
  sequence zero, then sends `DATA [2, session, sequence LE16, ADPCM bytes]`.
  Sequence starts at one. After every four data packets, or at the last one,
  Android writes cumulative ACK `[2, session, sequence LE16]`.
- Core2 sends `END [3, session, lastDataSequence+1 LE16]` and waits for its ACK.
  It sends data notifications at least 6 ms apart and retries a packet window
  after 500 ms, up to six retries. The four-packet window matches Android's
  current ACK behavior.

The screen's `Sent to Android` means the Core2 received the END ACK. Firmware
build: `pio run` in this directory. Actual recording and BLE transfer require
a Core2 and Android receiver for verification. Serial output at 115200 baud
reports transfer duration, encoded bytes, and retries.

## Android reply audio to Core2

Cloud Functions can return `replyFormat: "ima_adpcm"`. Android must request that
format, Base64-decode `replyAudioBase64`, and check that `replyAudio` reports
`format: "ima_adpcm"`, `sampleRate: 16000`, `channels: 1`, and a `sampleCount`
of 1 to 480000. The encoded length must be `(sampleCount + 1) / 2` rounded
down. Android currently requests ADPCM and sends the reply through this BLE
protocol.

- Android writes reply packets to
  `7f5a0001-7b7d-4f3b-9d01-000000000007` and subscribes to ACK notifications
  on `7f5a0001-7b7d-4f3b-9d01-000000000008`.
- `START [1, session, sampleCount LE32, codec=1, chunkSize]` declares the
  recording. `chunkSize` is 1 to 240 bytes and must fit the negotiated ATT MTU
  minus seven bytes. Core2 replies `[2, session, sequence=0 LE16]`.
- `DATA [2, session, sequence LE16, ADPCM bytes]` starts at sequence one. Core2
  cumulatively acknowledges every four packets and the final data packet.
- `END [3, session, lastDataSequence+1 LE16]` completes transfer. Core2
  acknowledges it. Core2 decodes ADPCM as packets arrive, retaining the
  predictor/index state across packets. It estimates the BLE transfer rate and
  buffers at least one second of audio, plus a margin when transfer is slower
  than playback. It then queues 500 ms PCM16 segments while the remaining data
  continues to arrive. When the estimated required buffer approaches the whole
  reply, it waits for END and plays the contiguous PCM buffer in one request.
  Android should retry unacknowledged packet windows. An error notification
  is `[4, session, code, 0]`, where code
  1 means invalid format, 2 means busy, and 3 means insufficient audio memory.

The END ACK confirms receipt of all encoded bytes; playback may still fail
afterward. Core2 displays receiving and playing status. Serial output reports
receipt duration, time until the first audio segment is queued, and playback
buffer underruns. Queue timing is not an acoustic measurement. It rejects new
reply audio while recording,
transmitting, receiving, or playing. A partial transfer times out after eight
seconds.
