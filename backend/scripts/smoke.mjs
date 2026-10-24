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

console.log(failed ? "\n失敗あり" : "\nすべて成功");
process.exit(failed ? 1 : 0);
