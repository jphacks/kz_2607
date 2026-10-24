// 本物のFirebaseで、手紙までの流れを試す。実機はいらない。
//
//  1) 準備(ユーザー2人・端末2台を作り、会話して、交換する)
//       FIREBASE_API_KEY=xxxx node scripts/letters.mjs start 録音.wav
//     録音は、talkToPet に送る WAV(16bit・モノラル)。省略すると、会話せずに交換だけ行う(要約は空になる)。
//  2) 数十秒待ってから、Google Cloud コンソールの Cloud Scheduler で sendLettersDaily を「強制実行」
//  3) 結果の確認
//       FIREBASE_API_KEY=xxxx node scripts/letters.mjs check
//
// 手紙をすぐ出すには、Firestore の config/game の letterIntervalDays を 0 にしておく。
import fs from "node:fs";

const PROJECT = process.env.FIREBASE_PROJECT || "pet-handoff-hack";
const KEY = process.env.FIREBASE_API_KEY;
const STATE = ".letters-test.json";
const mode = process.argv[2];
if (!KEY || !["start", "check"].includes(mode)) {
  console.error("使い方: FIREBASE_API_KEY=xxxx node scripts/letters.mjs start [録音.wav] | check");
  process.exit(1);
}

const fn = (name) => `https://asia-northeast1-${PROJECT}.cloudfunctions.net/${name}`;

async function post(url, body, token) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token && { Authorization: `Bearer ${token}` }) },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function call(name, data, token) {
  const res = await post(fn(name), { data: data ?? {} }, token);
  if (res.error) throw new Error(`${name}: ${res.error.status} ${res.error.message} ${JSON.stringify(res.error.details ?? "")}`);
  return res.result;
}

async function signUp() {
  const r = await post(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${KEY}`, {});
  if (!r.idToken) throw new Error("匿名ログインに失敗: " + JSON.stringify(r));
  return { token: r.idToken, refresh: r.refreshToken };
}

async function refresh(refreshToken) {
  const res = await fetch(`https://securetoken.googleapis.com/v1/token?key=${KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `grant_type=refresh_token&refresh_token=${encodeURIComponent(refreshToken)}`,
  });
  const r = await res.json();
  if (!r.id_token) throw new Error("トークンの更新に失敗: " + JSON.stringify(r));
  return r.id_token;
}

if (mode === "start") {
  const wav = process.argv[3];
  const audioBase64 = wav ? fs.readFileSync(wav).toString("base64") : null;
  const stamp = Date.now();
  const users = {};
  for (const name of ["A", "B"]) {
    const s = await signUp();
    const deviceId = `lt-${name.toLowerCase()}-${stamp}`;
    await call("registerDevice", { deviceId }, s.token);
    const pet = await call("getPet", { deviceId }, s.token);
    users[name] = { ...s, deviceId, petId: pet.petId };
    console.log(`ユーザー${name}: 端末 ${deviceId} / ペット ${pet.petId}`);
  }
  if (audioBase64) {
    for (const name of ["A", "B"]) {
      for (let i = 1; i <= Number(process.env.TALKS || 2); i++) {
        await new Promise((r) => setTimeout(r, Number(process.env.TALK_GAP_MS || 0)));
        try {
          const r = await call("talkToPet", { deviceId: users[name].deviceId, audioBase64, wantAudio: false }, users[name].token);
          console.log(`会話 ${name}-${i}: ${r.status} 「${r.transcript}」→「${r.replyText}」 gauge=${r.gauge}`);
        } catch (e) {
          console.log(`会話 ${name}-${i} が失敗: ${e.message}`);
        }
      }
    }
  } else {
    console.log("録音がないので、会話は飛ばします");
  }
  const ex = await call("reportExchange", {
    myDeviceId: users.A.deviceId, peerDeviceId: users.B.deviceId,
    givenPetId: users.A.petId, gotPetId: users.B.petId, transactionId: "lt-" + stamp,
  }, users.A.token);
  console.log(`交換: ${ex.status}  Aは ${ex.receivedPetId} を受け取りました`);
  fs.writeFileSync(STATE, JSON.stringify(users, null, 2));
  console.log(`\n状態を ${STATE} に保存しました(Gitには入れないでください)。`);
  console.log("次: 数十秒待ち、Cloud Scheduler で sendLettersDaily を強制実行 → node scripts/letters.mjs check");
} else {
  const users = JSON.parse(fs.readFileSync(STATE, "utf8"));
  for (const name of ["A", "B"]) {
    const token = await refresh(users[name].refresh);
    const { letters } = await call("getLetters", {}, token);
    console.log(`\n=== ユーザー${name} の手紙: ${letters.length}通 ===`);
    for (const l of letters) {
      console.log(`題: ${l.title}\n(ペット ${l.petId}・${l.generation}代目・${l.createdAt})\n${l.body}\n`);
    }
  }
}
