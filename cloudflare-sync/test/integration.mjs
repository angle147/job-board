import assert from "node:assert/strict";
import fs from "node:fs";

const base = process.env.SYNC_TEST_URL || "http://127.0.0.1:8787";
const suffix = Date.now().toString(36);
const username = `test_${suffix}`;
const password = "Test-password-1";
const deploymentSecrets = process.env.USE_DEPLOYMENT_SECRETS === "1"
  ? JSON.parse(fs.readFileSync(new URL("../DEPLOYMENT_SECRETS.local.json", import.meta.url), "utf8"))
  : {};
const inviteCode = deploymentSecrets.INITIAL_INVITE_CODE || "local-invite-2026";
const adminUsername = deploymentSecrets.ADMIN_USERNAME || "local_admin";
const adminPassword = deploymentSecrets.ADMIN_PASSWORD || "local-admin-password";

async function call(path, { token, ...options } = {}) {
  const response = await fetch(`${base}/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${response.status} ${JSON.stringify(payload)}`);
  return payload;
}

const registered = await call("/register", {
  method: "POST",
  body: JSON.stringify({ username, password, inviteCode, consent: true }),
});
assert.ok(registered.token);

const updatedAt = new Date().toISOString();
await call("/state", {
  method: "PUT",
  token: registered.token,
  body: JSON.stringify({
    items: [
      { kind: "job_status", key: "job_status_v2|review|test-job", value: { status: "已报名" }, updatedAt },
      { kind: "offline_plan", key: "test-event", value: true, updatedAt },
    ],
    activeKeys: [
      { kind: "job_status", key: "job_status_v2|review|test-job" },
      { kind: "offline_plan", key: "test-event" },
    ],
  }),
});

const secondDevice = await call("/login", {
  method: "POST",
  body: JSON.stringify({ username: username.toUpperCase(), password }),
});
const state = await call("/state", { token: secondDevice.token });
assert.equal(state.items.length, 2);
assert.equal(state.items.find((x) => x.kind === "job_status").value.status, "已报名");

const admin = await call("/admin/login", {
  method: "POST",
  body: JSON.stringify({ username: adminUsername, password: adminPassword }),
});
const stats = await call("/admin/stats", { token: admin.token });
assert.ok(stats.registered >= 1);
assert.ok(stats.active7Days >= 1);

const reset = await call("/admin/reset-code", {
  method: "POST",
  token: admin.token,
  body: JSON.stringify({ username }),
});
const resetLogin = await call("/reset/consume", {
  method: "POST",
  body: JSON.stringify({ username, resetCode: reset.resetCode, newPassword: "Changed-password-2" }),
});
assert.ok(resetLogin.token);

await call("/account", {
  method: "DELETE",
  token: resetLogin.token,
  body: JSON.stringify({ password: "Changed-password-2" }),
});

console.log("integration OK", { username, stateItems: state.items.length });
