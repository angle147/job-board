const SESSION_DAYS = 30;
const STATE_RETENTION_DAYS = 90;
const PASSWORD_ITERATIONS = 210000;
const RESET_MINUTES = 20;
const USERNAME_RE = /^[A-Za-z0-9_]{3,24}$/;

const encoder = new TextEncoder();

export function normalizeUsername(value) {
  const display = String(value || "").trim();
  if (!USERNAME_RE.test(display)) throw new ApiError(400, "账号名须为3至24位字母、数字或下划线");
  return { display, normalized: display.toLowerCase() };
}

export function validatePassword(value) {
  const password = String(value || "");
  if (password.length < 8 || password.length > 128) {
    throw new ApiError(400, "密码须为8至128个字符");
  }
  return password;
}

export function isNewer(incoming, existing) {
  const a = Date.parse(incoming || "");
  const b = Date.parse(existing || "");
  return Number.isFinite(a) && (!Number.isFinite(b) || a > b);
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function nowIso() {
  return new Date().toISOString();
}

function futureIso({ days = 0, minutes = 0 }) {
  return new Date(Date.now() + days * 86400000 + minutes * 60000).toISOString();
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomToken(bytes = 32) {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return bytesToBase64(value);
}

async function sha256(value) {
  return bytesToBase64(new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value))));
}

async function passwordDigest(password, salt, iterations = PASSWORD_ITERATIONS) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: encoder.encode(salt), iterations },
    key,
    256,
  );
  return bytesToBase64(new Uint8Array(bits));
}

async function newPasswordRecord(password) {
  const salt = randomToken(18);
  return { salt, hash: await passwordDigest(password, salt), iterations: PASSWORD_ITERATIONS };
}

async function verifyPassword(password, user) {
  const actual = await passwordDigest(password, user.password_salt, user.password_iterations);
  const left = encoder.encode(actual);
  const right = encoder.encode(user.password_hash);
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let i = 0; i < left.length; i += 1) difference |= left[i] ^ right[i];
  return difference === 0;
}

function allowedOrigins(env) {
  return new Set(String(env.ALLOWED_ORIGINS || "").split(",").map((x) => x.trim().replace(/\/$/, "")).filter(Boolean));
}

function requestOrigin(request) {
  return (request.headers.get("Origin") || "").replace(/\/$/, "");
}

function corsHeaders(request, env) {
  const origin = requestOrigin(request);
  const selfOrigin = new URL(request.url).origin;
  const headers = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
  if (origin && (origin === selfOrigin || allowedOrigins(env).has(origin))) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Vary"] = "Origin";
    headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type";
    headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS";
  }
  return headers;
}

function assertOrigin(request, env) {
  const origin = requestOrigin(request);
  const selfOrigin = new URL(request.url).origin;
  if (origin && origin !== selfOrigin && !allowedOrigins(env).has(origin)) throw new ApiError(403, "此网页无权访问同步服务");
}

function jsonResponse(request, env, data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: corsHeaders(request, env) });
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    throw new ApiError(400, "请求内容格式错误");
  }
}

async function setting(env, key) {
  return (await env.DB.prepare("SELECT value FROM settings WHERE key = ?").bind(key).first())?.value ?? null;
}

async function setSetting(env, key, value) {
  await env.DB.prepare(
    "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
  ).bind(key, value, nowIso()).run();
}

async function makeSecretRecord(secret) {
  const record = await newPasswordRecord(secret);
  return `${record.iterations}:${record.salt}:${record.hash}`;
}

async function verifySecret(secret, record) {
  if (!record) return false;
  const [iterations, salt, hash] = record.split(":");
  return verifyPassword(secret, {
    password_salt: salt,
    password_hash: hash,
    password_iterations: Number(iterations),
  });
}

async function ensureBootstrap(env) {
  if ((await setting(env, "registration_open")) === null) await setSetting(env, "registration_open", "1");
  if ((await setting(env, "invite_hash")) === null) {
    if (!env.INITIAL_INVITE_CODE) throw new ApiError(503, "服务尚未完成邀请码初始化");
    await setSetting(env, "invite_hash", await makeSecretRecord(env.INITIAL_INVITE_CODE));
  }
}

async function ensureAdmin(env) {
  if (!env.ADMIN_USERNAME || !env.ADMIN_PASSWORD) throw new ApiError(503, "管理员账号尚未初始化");
  const { display, normalized } = normalizeUsername(env.ADMIN_USERNAME);
  const existing = await env.DB.prepare("SELECT id FROM users WHERE username_norm = ?").bind(normalized).first();
  if (existing) return;
  const password = newPasswordRecord(validatePassword(env.ADMIN_PASSWORD));
  const record = await password;
  await env.DB.prepare(
    "INSERT INTO users(username_display,username_norm,password_salt,password_hash,password_iterations,role,created_at) VALUES(?,?,?,?,?,'admin',?)",
  ).bind(display, normalized, record.salt, record.hash, record.iterations, nowIso()).run();
}

async function issueSession(env, user) {
  const token = randomToken();
  await env.DB.prepare(
    "INSERT INTO sessions(token_hash,user_id,auth_version,created_at,expires_at) VALUES(?,?,?,?,?)",
  ).bind(await sha256(token), user.id, user.auth_version, nowIso(), futureIso({ days: SESSION_DAYS })).run();
  return token;
}

async function authenticate(request, env, requiredRole = null) {
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Bearer ")) throw new ApiError(401, "请先登录");
  const row = await env.DB.prepare(
    `SELECT u.id,u.username_display,u.username_norm,u.role,u.auth_version,s.expires_at
       FROM sessions s JOIN users u ON u.id=s.user_id
      WHERE s.token_hash=? AND s.expires_at>? AND s.auth_version=u.auth_version`,
  ).bind(await sha256(header.slice(7)), nowIso()).first();
  if (!row || (requiredRole && row.role !== requiredRole)) throw new ApiError(401, "登录已失效");
  return row;
}

async function rateKey(request, env, suffix = "") {
  const network = request.headers.get("CF-Connecting-IP") || "unknown";
  return sha256(`${env.RATE_LIMIT_SECRET || "job-board"}|${network}|${suffix}`);
}

async function checkRegistrationRate(request, env) {
  const key = await rateKey(request, env);
  const since = new Date(Date.now() - 3600000).toISOString();
  const count = await env.DB.prepare(
    "SELECT COUNT(*) AS count FROM registration_attempts WHERE network_hash=? AND attempted_at>?",
  ).bind(key, since).first();
  if (Number(count?.count || 0) >= 5) throw new ApiError(429, "注册尝试过多，请稍后再试");
  await env.DB.prepare("INSERT INTO registration_attempts(network_hash,attempted_at) VALUES(?,?)").bind(key, nowIso()).run();
}

async function checkLoginRate(request, env, usernameNorm) {
  const key = await rateKey(request, env, usernameNorm);
  const since = new Date(Date.now() - 15 * 60000).toISOString();
  const count = await env.DB.prepare(
    "SELECT COUNT(*) AS count FROM login_attempts WHERE attempt_key=? AND succeeded=0 AND attempted_at>?",
  ).bind(key, since).first();
  if (Number(count?.count || 0) >= 8) throw new ApiError(429, "登录尝试过多，请稍后再试");
  return key;
}

async function recordLoginAttempt(env, key, succeeded) {
  await env.DB.prepare("INSERT INTO login_attempts(attempt_key,succeeded,attempted_at) VALUES(?,?,?)")
    .bind(key, succeeded ? 1 : 0, nowIso()).run();
}

async function register(request, env) {
  await ensureBootstrap(env);
  if ((await setting(env, "registration_open")) !== "1") throw new ApiError(403, "新账号注册目前已暂停");
  await checkRegistrationRate(request, env);
  const body = await readJson(request);
  if (body.consent !== true) throw new ApiError(400, "请先确认数据与隐私说明");
  const { display, normalized } = normalizeUsername(body.username);
  const password = validatePassword(body.password);
  if (!(await verifySecret(String(body.inviteCode || ""), await setting(env, "invite_hash")))) {
    throw new ApiError(403, "班级邀请码无效");
  }
  const record = await newPasswordRecord(password);
  let result;
  try {
    result = await env.DB.prepare(
      "INSERT INTO users(username_display,username_norm,password_salt,password_hash,password_iterations,role,created_at,last_login_at) VALUES(?,?,?,?,?,'member',?,?)",
    ).bind(display, normalized, record.salt, record.hash, record.iterations, nowIso(), nowIso()).run();
  } catch (error) {
    if (String(error).toLowerCase().includes("unique")) throw new ApiError(409, "该账号名已被使用");
    throw error;
  }
  const user = { id: result.meta.last_row_id, username_display: display, role: "member", auth_version: 1 };
  return { token: await issueSession(env, user), username: display, expiresInDays: SESSION_DAYS };
}

async function login(request, env, adminOnly = false) {
  if (adminOnly) await ensureAdmin(env);
  const body = await readJson(request);
  let names;
  try { names = normalizeUsername(body.username); } catch { throw new ApiError(401, "账号或密码错误"); }
  const attemptKey = await checkLoginRate(request, env, names.normalized);
  const user = await env.DB.prepare("SELECT * FROM users WHERE username_norm=?").bind(names.normalized).first();
  const ok = Boolean(user && (!adminOnly || user.role === "admin") && await verifyPassword(String(body.password || ""), user));
  await recordLoginAttempt(env, attemptKey, ok);
  if (!ok) throw new ApiError(401, "账号或密码错误");
  await env.DB.prepare("UPDATE users SET last_login_at=? WHERE id=?").bind(nowIso(), user.id).run();
  return { token: await issueSession(env, user), username: user.username_display, role: user.role, expiresInDays: SESSION_DAYS };
}

async function logout(request, env) {
  const token = (request.headers.get("Authorization") || "").slice(7);
  if (token) await env.DB.prepare("DELETE FROM sessions WHERE token_hash=?").bind(await sha256(token)).run();
  return { ok: true };
}

function validateStateItem(item) {
  if (!item || !["job_status", "offline_plan"].includes(item.kind)) return false;
  if (typeof item.key !== "string" || item.key.length < 1 || item.key.length > 1000) return false;
  if (!isNewer(item.updatedAt, "1970-01-01T00:00:00.000Z")) return false;
  const encoded = JSON.stringify(item.value);
  return encoded.length <= 4000;
}

async function getState(request, env, user) {
  const result = await env.DB.prepare(
    "SELECT kind,item_key AS key,value_json,client_updated_at AS updatedAt FROM state_items WHERE user_id=? ORDER BY updated_at",
  ).bind(user.id).all();
  return {
    items: (result.results || []).map((row) => ({
      kind: row.kind, key: row.key, value: JSON.parse(row.value_json), updatedAt: row.updatedAt,
    })),
  };
}

async function putState(request, env, user) {
  const body = await readJson(request);
  const items = Array.isArray(body.items) ? body.items : [];
  const active = Array.isArray(body.activeKeys) ? body.activeKeys : [];
  if (items.length > 1000 || active.length > 5000 || !items.every(validateStateItem)) {
    throw new ApiError(400, "同步数据超出允许范围");
  }
  const now = nowIso();
  const statements = [];
  for (const item of items) {
    statements.push(env.DB.prepare(
      `INSERT INTO state_items(user_id,kind,item_key,value_json,client_updated_at,last_seen_public_at,updated_at)
       VALUES(?,?,?,?,?,?,?)
       ON CONFLICT(user_id,kind,item_key) DO UPDATE SET
         value_json=excluded.value_json,
         client_updated_at=excluded.client_updated_at,
         last_seen_public_at=excluded.last_seen_public_at,
         updated_at=excluded.updated_at
       WHERE excluded.client_updated_at > state_items.client_updated_at`,
    ).bind(user.id, item.kind, item.key, JSON.stringify(item.value), item.updatedAt, now, now));
  }
  for (const item of active) {
    if (!item || !["job_status", "offline_plan"].includes(item.kind) || typeof item.key !== "string") continue;
    statements.push(env.DB.prepare(
      "UPDATE state_items SET last_seen_public_at=? WHERE user_id=? AND kind=? AND item_key=?",
    ).bind(now, user.id, item.kind, item.key));
  }
  for (let offset = 0; offset < statements.length; offset += 80) {
    await env.DB.batch(statements.slice(offset, offset + 80));
  }
  return { ok: true, accepted: items.length };
}

async function changePassword(request, env, user) {
  const body = await readJson(request);
  const current = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(user.id).first();
  if (!await verifyPassword(String(body.currentPassword || ""), current)) throw new ApiError(401, "当前密码错误");
  const record = await newPasswordRecord(validatePassword(body.newPassword));
  await env.DB.batch([
    env.DB.prepare("UPDATE users SET password_salt=?,password_hash=?,password_iterations=?,auth_version=auth_version+1 WHERE id=?")
      .bind(record.salt, record.hash, record.iterations, user.id),
    env.DB.prepare("DELETE FROM sessions WHERE user_id=?").bind(user.id),
  ]);
  const refreshed = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(user.id).first();
  return { token: await issueSession(env, refreshed), username: refreshed.username_display, expiresInDays: SESSION_DAYS };
}

async function deleteAccount(request, env, user) {
  if (user.role !== "member") throw new ApiError(403, "管理员账号不能从成员入口删除");
  const body = await readJson(request);
  const current = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(user.id).first();
  if (!await verifyPassword(String(body.password || ""), current)) throw new ApiError(401, "密码错误");
  await env.DB.prepare("DELETE FROM users WHERE id=?").bind(user.id).run();
  return { ok: true };
}

async function adminStats(env) {
  const seven = new Date(Date.now() - 7 * 86400000).toISOString();
  const thirty = new Date(Date.now() - 30 * 86400000).toISOString();
  const [total, active7, active30] = await env.DB.batch([
    env.DB.prepare("SELECT COUNT(*) AS count FROM users WHERE role='member'"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM users WHERE role='member' AND last_login_at>=?").bind(seven),
    env.DB.prepare("SELECT COUNT(*) AS count FROM users WHERE role='member' AND last_login_at>=?").bind(thirty),
  ]);
  return {
    registered: Number(total.results?.[0]?.count || 0),
    active7Days: Number(active7.results?.[0]?.count || 0),
    active30Days: Number(active30.results?.[0]?.count || 0),
    registrationOpen: (await setting(env, "registration_open")) === "1",
  };
}

async function updateAdminSettings(request, env) {
  const body = await readJson(request);
  if (typeof body.registrationOpen === "boolean") {
    await setSetting(env, "registration_open", body.registrationOpen ? "1" : "0");
  }
  if (body.newInviteCode !== undefined) {
    const invite = String(body.newInviteCode || "");
    if (invite.length < 8 || invite.length > 128) throw new ApiError(400, "新邀请码须为8至128个字符");
    await setSetting(env, "invite_hash", await makeSecretRecord(invite));
  }
  return { ok: true, registrationOpen: (await setting(env, "registration_open")) === "1" };
}

async function createResetCode(request, env) {
  const body = await readJson(request);
  const { normalized } = normalizeUsername(body.username);
  const user = await env.DB.prepare("SELECT id FROM users WHERE username_norm=? AND role='member'").bind(normalized).first();
  if (!user) throw new ApiError(404, "未找到该成员账号");
  const code = `${randomToken(6).slice(0, 8)}-${randomToken(6).slice(0, 8)}`;
  await env.DB.prepare("INSERT INTO reset_codes(code_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)")
    .bind(await sha256(code), user.id, nowIso(), futureIso({ minutes: RESET_MINUTES })).run();
  return { resetCode: code, expiresInMinutes: RESET_MINUTES };
}

async function consumeResetCode(request, env) {
  const body = await readJson(request);
  const { normalized } = normalizeUsername(body.username);
  const codeHash = await sha256(String(body.resetCode || ""));
  const record = await env.DB.prepare(
    `SELECT r.code_hash,r.user_id FROM reset_codes r JOIN users u ON u.id=r.user_id
      WHERE r.code_hash=? AND u.username_norm=? AND r.used_at IS NULL AND r.expires_at>?`,
  ).bind(codeHash, normalized, nowIso()).first();
  if (!record) throw new ApiError(400, "重置码无效或已过期");
  const password = await newPasswordRecord(validatePassword(body.newPassword));
  await env.DB.batch([
    env.DB.prepare("UPDATE reset_codes SET used_at=? WHERE code_hash=?").bind(nowIso(), codeHash),
    env.DB.prepare("UPDATE users SET password_salt=?,password_hash=?,password_iterations=?,auth_version=auth_version+1 WHERE id=?")
      .bind(password.salt, password.hash, password.iterations, record.user_id),
    env.DB.prepare("DELETE FROM sessions WHERE user_id=?").bind(record.user_id),
  ]);
  const user = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(record.user_id).first();
  return { token: await issueSession(env, user), username: user.username_display, expiresInDays: SESSION_DAYS };
}

async function cleanup(env) {
  const threshold = new Date(Date.now() - STATE_RETENTION_DAYS * 86400000).toISOString();
  const now = nowIso();
  await env.DB.batch([
    env.DB.prepare("DELETE FROM state_items WHERE last_seen_public_at<?").bind(threshold),
    env.DB.prepare("DELETE FROM sessions WHERE expires_at<?").bind(now),
    env.DB.prepare("DELETE FROM reset_codes WHERE expires_at<? OR used_at IS NOT NULL").bind(now),
    env.DB.prepare("DELETE FROM registration_attempts WHERE attempted_at<?").bind(new Date(Date.now() - 86400000).toISOString()),
    env.DB.prepare("DELETE FROM login_attempts WHERE attempted_at<?").bind(new Date(Date.now() - 86400000).toISOString()),
  ]);
}

function adminPage() {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>看板管理后台</title><style>
  body{font-family:system-ui,sans-serif;background:#f1f5f9;color:#172033;margin:0}.wrap{max-width:760px;margin:40px auto;padding:20px}.card{background:#fff;padding:24px;border-radius:12px;box-shadow:0 2px 12px #0001;margin-bottom:16px}input,button{font:inherit;padding:10px 12px;border:1px solid #cbd5e1;border-radius:7px;margin:5px 3px}button{background:#2563eb;color:#fff;cursor:pointer}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.metric{background:#eff6ff;padding:18px;border-radius:8px;text-align:center}.metric b{font-size:28px;display:block}.hidden{display:none}.msg{margin-top:10px;color:#475569}@media(max-width:600px){.stats{grid-template-columns:1fr}}
  </style></head><body><main class="wrap"><section class="card" id="login"><h1>管理员登录</h1><input id="u" placeholder="管理员账号"><input id="p" type="password" placeholder="密码"><button onclick="login()">登录</button><div class="msg" id="loginMsg"></div></section><div id="panel" class="hidden"><section class="card"><h2>使用概览</h2><div class="stats"><div class="metric"><b id="total">-</b>注册总人数</div><div class="metric"><b id="d7">-</b>近7天登录</div><div class="metric"><b id="d30">-</b>近30天登录</div></div><p class="msg" id="regState"></p></section><section class="card"><h2>注册管理</h2><button onclick="toggleRegistration()" id="toggle">暂停注册</button><input id="invite" type="password" placeholder="新邀请码（至少8位）"><button onclick="rotateInvite()">更换邀请码</button><div class="msg" id="settingsMsg"></div></section><section class="card"><h2>密码重置</h2><input id="member" placeholder="成员准确账号名"><button onclick="resetCode()">生成一次性重置码</button><div class="msg" id="resetMsg"></div></section></div></main><script>
  let token=sessionStorage.getItem('admin_token')||'',stats=null; const api=async(path,options={})=>{const r=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...(options.headers||{})}});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d};
  async function login(){try{const d=await api('/admin/login',{method:'POST',body:JSON.stringify({username:u.value,password:p.value})});token=d.token;sessionStorage.setItem('admin_token',token);await load()}catch(e){loginMsg.textContent=e.message}}
  async function load(){try{stats=await api('/admin/stats');document.getElementById('login').classList.add('hidden');document.getElementById('panel').classList.remove('hidden');total.textContent=stats.registered;d7.textContent=stats.active7Days;d30.textContent=stats.active30Days;regState.textContent=stats.registrationOpen?'当前允许新账号注册':'当前已暂停新账号注册';toggle.textContent=stats.registrationOpen?'暂停注册':'恢复注册'}catch(e){loginMsg.textContent=e.message}}
  async function toggleRegistration(){try{await api('/admin/settings',{method:'PUT',body:JSON.stringify({registrationOpen:!stats.registrationOpen})});await load()}catch(e){settingsMsg.textContent=e.message}}
  async function rotateInvite(){try{await api('/admin/settings',{method:'PUT',body:JSON.stringify({newInviteCode:invite.value})});invite.value='';settingsMsg.textContent='邀请码已更换'}catch(e){settingsMsg.textContent=e.message}}
  async function resetCode(){try{const d=await api('/admin/reset-code',{method:'POST',body:JSON.stringify({username:member.value})});resetMsg.textContent='一次性重置码：'+d.resetCode+'（'+d.expiresInMinutes+'分钟内有效）'}catch(e){resetMsg.textContent=e.message}}
  if(token)load();
  </script></body></html>`;
}

async function route(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") {
    assertOrigin(request, env);
    return new Response(null, { status: 204, headers: corsHeaders(request, env) });
  }
  if (url.pathname === "/admin" && request.method === "GET") {
    return new Response(adminPage(), { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
  }
  assertOrigin(request, env);
  if (url.pathname === "/health" && request.method === "GET") return { ok: true };
  if (url.pathname === "/api/register" && request.method === "POST") return register(request, env);
  if (url.pathname === "/api/login" && request.method === "POST") return login(request, env);
  if (url.pathname === "/api/admin/login" && request.method === "POST") return login(request, env, true);
  if (url.pathname === "/api/reset/consume" && request.method === "POST") return consumeResetCode(request, env);
  if (url.pathname === "/api/logout" && request.method === "POST") return logout(request, env);
  const user = await authenticate(request, env);
  if (url.pathname === "/api/me" && request.method === "GET") return { username: user.username_display, role: user.role };
  if (url.pathname === "/api/state" && request.method === "GET") return getState(request, env, user);
  if (url.pathname === "/api/state" && request.method === "PUT") return putState(request, env, user);
  if (url.pathname === "/api/change-password" && request.method === "POST") return changePassword(request, env, user);
  if (url.pathname === "/api/account" && request.method === "DELETE") return deleteAccount(request, env, user);
  if (url.pathname.startsWith("/api/admin/")) {
    await authenticate(request, env, "admin");
    if (url.pathname === "/api/admin/stats" && request.method === "GET") return adminStats(env);
    if (url.pathname === "/api/admin/settings" && request.method === "PUT") return updateAdminSettings(request, env);
    if (url.pathname === "/api/admin/reset-code" && request.method === "POST") return createResetCode(request, env);
  }
  throw new ApiError(404, "接口不存在");
}

export default {
  async fetch(request, env) {
    try {
      const result = await route(request, env);
      return result instanceof Response ? result : jsonResponse(request, env, result);
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 500;
      if (status === 500) console.error(error);
      return jsonResponse(request, env, { error: status === 500 ? "服务暂时不可用" : error.message }, status);
    }
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(cleanup(env));
  },
};
