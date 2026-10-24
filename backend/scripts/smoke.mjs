// 本物のFirebaseに対する動作確認。使い方:
//   FIREBASE_API_KEY=xxxx node scripts/smoke.mjs
// 匿名ログインして、registerDevice を2回呼ぶ。
const PROJECT = process.env.FIREBASE_PROJECT || "pet-handoff-hack";
const REGION = "asia-northeast1";
const KEY = process.env.FIREBASE_API_KEY;
if (!KEY) {
  console.error("FIREBASE_API_KEY を設定してください");
  process.exit(1);
}

async function signInAnonymously() {
  const res = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${KEY}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
  );
  const body = await res.json();
  if (!res.ok) throw new Error("匿名ログイン失敗: " + JSON.stringify(body));
  return body.idToken;
}

async function call(name, token, data) {
  const res = await fetch(
    `https://${REGION}-${PROJECT}.cloudfunctions.net/${name}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ data }),
    },
  );
  return { status: res.status, body: await res.json() };
}

let failed = false;
function check(label, ok, detail) {
  console.log(`${ok ? "OK " : "NG "} ${label}${ok ? "" : "  " + JSON.stringify(detail)}`);
  if (!ok) failed = true;
}

const token = await signInAnonymously();
const deviceId = "smoke-" + Date.now();

const ping = await call("ping", token, {});
check("ping", ping.body.result?.ok === true, ping);

const first = await call("registerDevice", token, { deviceId });
check("registerDevice 1回目: 新規作成", first.body.result?.isNew === true && !!first.body.result?.petId, first);

const second = await call("registerDevice", token, { deviceId });
check(
  "registerDevice 2回目: 同じペット",
  second.body.result?.isNew === false && second.body.result?.petId === first.body.result?.petId,
  second,
);

const bad = await call("registerDevice", token, { deviceId: "a b" });
check("不正なdeviceIdは拒否", bad.body.error?.status === "INVALID_ARGUMENT", bad);

const otherToken = await signInAnonymously();
const other = await call("registerDevice", otherToken, { deviceId });
check("別ユーザーは拒否", other.body.error?.status === "PERMISSION_DENIED", other);

// --- すれ違い交換 ---
const tokenB = otherToken;
const devA = "smokeA-" + Date.now();
const devB = "smokeB-" + Date.now();
const petA = (await call("registerDevice", token, { deviceId: devA })).body.result?.petId;
const petB = (await call("registerDevice", tokenB, { deviceId: devB })).body.result?.petId;
const tid = "tx-" + Date.now();
const ex = { transactionId: tid, myDeviceId: devA, peerDeviceId: devB, givenPetId: petA, gotPetId: petB };

const rep = await call("reportExchange", token, ex);
check("reportExchange: 確定", rep.body.result?.status === "done" && rep.body.result?.receivedPetId === petB, rep);

const rep2 = await call("reportExchange", token, ex);
check("reportExchange: 再送は同じ結果", rep2.body.result?.replayed === true, rep2);

const repB = await call("reportExchange", tokenB, {
  transactionId: tid, myDeviceId: devB, peerDeviceId: devA, givenPetId: petB, gotPetId: petA,
});
check("reportExchange: 相手端末の報告は already_done", repB.body.result?.status === "already_done" && repB.body.result?.receivedPetId === petA, repB);

const got = await call("getExchangeResult", tokenB, { transactionId: tid, myDeviceId: devB });
check("getExchangeResult: 確定済み", got.body.result?.status === "confirmed" && got.body.result?.currentPetId === petA, got);

const unk = await call("getExchangeResult", token, { transactionId: "none-" + Date.now(), myDeviceId: devA });
check("getExchangeResult: 未知", unk.body.result?.status === "unknown", unk);

const cc = await call("cancelExchange", token, { transactionId: tid, myDeviceId: devA, peerDeviceId: devB });
check("cancelExchange: 確定後は取り消せない", cc.body.result?.status === "confirmed", cc);

const tid2 = "tx2-" + Date.now();
const c2 = await call("cancelExchange", token, { transactionId: tid2, myDeviceId: devA, peerDeviceId: devB });
check("cancelExchange: 取り消し", c2.body.result?.status === "cancelled", c2);
const after = await call("reportExchange", token, { ...ex, transactionId: tid2 });
check("取り消し後の報告は拒否", after.body.error?.status === "FAILED_PRECONDITION", after);

// --- 音声会話(無音の録音は、聞き取れなかった扱いになる) ---
function silentWav(seconds, rate = 16000) {
  const n = seconds * rate;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  return buf;
}
const talkRes = await call("talkToPet", token, { deviceId: devA, audioBase64: silentWav(1).toString("base64") });
check("talkToPet: 無音は no_speech(音声認識APIにつながっている)", talkRes.body.result?.status === "no_speech", talkRes);
const badTalk = await call("talkToPet", token, { deviceId: devA, audioBase64: "AAAA" });
check("talkToPet: 壊れた録音は拒否", badTalk.body.error?.status === "INVALID_ARGUMENT", badTalk);

console.log(failed ? "\n失敗あり" : "\nすべて成功");
process.exit(failed ? 1 : 0);
