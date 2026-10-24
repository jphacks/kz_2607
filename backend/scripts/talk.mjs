// 本物のFirebaseで、音声会話を試す。使い方:
//   FIREBASE_API_KEY=xxxx node scripts/talk.mjs 録音.wav
// 録音は、16bit・モノラル・8000〜48000HzのWAV。返事の声は reply.wav に保存する。
import fs from "node:fs";

const PROJECT = process.env.FIREBASE_PROJECT || "pet-handoff-hack";
const KEY = process.env.FIREBASE_API_KEY;
const file = process.argv[2];
if (!KEY || !file) {
  console.error("使い方: FIREBASE_API_KEY=xxxx node scripts/talk.mjs 録音.wav");
  process.exit(1);
}

async function post(url, body, token) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token && { Authorization: `Bearer ${token}` }) },
    body: JSON.stringify(body),
  });
  return res.json();
}

const login = await post(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${KEY}`, {});
const token = login.idToken;
const fn = (name) => `https://asia-northeast1-${PROJECT}.cloudfunctions.net/${name}`;

const deviceId = "talk-" + Date.now();
await post(fn("registerDevice"), { data: { deviceId } }, token);

const started = Date.now();
const res = await post(
  fn("talkToPet"),
  {
    data: {
      deviceId,
      audioBase64: fs.readFileSync(file).toString("base64"),
      replyFormat: process.env.REPLY_FORMAT || "wav", // Core2向けは ima_adpcm
    },
  },
  token,
);
if (res.error) {
  console.error("エラー:", JSON.stringify(res.error));
  process.exit(1);
}
const r = res.result;
console.log(`状態: ${r.status}  (${((Date.now() - started) / 1000).toFixed(1)}秒)`);
console.log("聞き取り:", r.transcript);
console.log("返事:", r.replyText);
console.log("音声:", r.audioStatus);
console.log("覚えた言葉:", JSON.stringify(r.learnedWords));
if (r.replyAudioBase64) {
  const adpcm = r.replyAudio?.format === "ima_adpcm";
  const name = adpcm ? "reply.adpcm" : "reply.wav";
  fs.writeFileSync(name, Buffer.from(r.replyAudioBase64, "base64"));
  console.log(`返事の声を ${name} に保存しました`, JSON.stringify(r.replyAudio));
}
