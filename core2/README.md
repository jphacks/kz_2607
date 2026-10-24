# Core2 BLE voice capture

The Core2 advertises as `M5StackCore2` with service
`7f5a0001-7b7d-4f3b-9d01-000000000001`. Its screen shows the BLE connection
state. An Android receiver must subscribe to the voice data notification and
configure the transfer before recording is enabled.

## Pet ID configuration and status

The status characteristic (`...0002`, read/notify) contains a JSON object with
`id`, `mac`, `peerId`, `distance`, `petId`, and `exchangeStatus`. For example, before pet
configuration it reports
`{"id":"M5-AABBCCDDEEFF","mac":"AA:BB:CC:DD:EE:FF","peerId":"","distance":0,"petId":"","exchangeStatus":"NO PET"}`.
The peer fields show the closest recent Core2. After configuration, `petId`
contains the saved ID. Core2 updates the readable status and notifies Android
when it changes, and displays the last received ID even while disconnected.
It reloads the ID from ESP32 Preferences after reboot, and the saved value
remains available in the status JSON.

Android writes `{"type":"pet_config","transactionId":"<16 hex digits>","deviceId":"<12 hex digits>","petId":"<ID>"}`
to command characteristic `7f5a0001-7b7d-4f3b-9d01-000000000003`.
As in the demo, this JSON is split into 20-byte frames: `F`, version 1,
type (`1` data or `2` ACK), reserved zero, 8-byte little-endian transaction ID,
sequence, frame count, payload length, and up to 5 payload bytes. Core2 ACKs
each data frame on the status characteristic. After saving the ID, it sends
`pet_config_ack` with `transactionId`, `status: "received"`, and `deviceId`
over the same framing; Android ACKs those frames. Invalid device IDs and
empty or malformed pet IDs are ignored. A successful application ACK means
the new ID was saved.

## Pet exchange

Two Core2 devices use the same RSSI based distance estimate as the screen.
Exchange setup starts only after at least three fresh advertisements keep the
estimated distance at or below **0.1 m** for 700 ms. The Core2 with the lower
device ID connects to the other Core2. It reads the peer's pet ID and exchange
sequence from the read only characteristic `...0004`, then writes an exchange
request to `...0009`. The peer independently checks its own measured distance
and current pet ID, saves the same transaction ID, and exposes that ID on
`...0004`. The initiator saves its candidate after reading that confirmation.
The request on `...0009` is binary: `X`, version 1, the sender's 12 ASCII hex
device ID, an 8-byte little-endian transaction ID, a 4-byte little-endian
exchange sequence, two reserved zero bytes, two pet ID lengths, then the
sender and receiver pet IDs. Pet IDs are limited to 64 bytes for this peer
protocol. The receiver verifies the sender, transaction, pet IDs, and its own
recent distance reading before accepting it.
Both devices keep their candidate across BLE disconnect, but discard it on
reboot. A discarded transaction ID is not recovered from the other Core2.
Moving farther than 0.15 m rearms another attempt after a terminal result.
If only one device saved the candidate before a disconnection, the other can
recover the same transaction from the peer's read only status on the next
close encounter.

After Android sends and Core2 acknowledges `pet_config` on characteristic
`...0003`, Core2 repeatedly notifies `exchange_pending` on `...0002` using the
20-byte `F` framing below. The payload has `transactionId`, `myDeviceId`,
`peerDeviceId`, `givenPetId`, `gotPetId`, and `distanceMeters`. A missing or
greater than 0.1 m distance is rejected by the frontend. Android responds on
`...0003` with `exchange_result` containing the same transaction and pet IDs
and `result: "done"`, `"already_done"`, `"rejected"`, or `"confirming"`.
Core2 changes the saved pet ID only for a confirmed result, retains the
candidate while confirming, and replies with `exchange_result_ack`. It accepts
repeated terminal results after reboot. Recording pauses while a candidate is
pending.

The distance is an RSSI estimate and needs calibration on the actual devices.
End-to-end exchange also needs the Android and backend changes to be deployed.

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
