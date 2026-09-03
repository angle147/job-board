(function () {
  "use strict";

  const TOKEN_KEY = "job_board_sync_token";
  const USER_KEY = "job_board_sync_user";
  const META_KEY = "job_board_sync_meta";
  const GUEST_ACTION_KEY = "job_board_guest_action_count";
  const GUEST_ACTION_LIMIT = 20;
  const API_BASE = String(window.JOB_BOARD_SYNC_CONFIG?.apiBase || "").replace(/\/$/, "");
  const state = { token: localStorage.getItem(TOKEN_KEY) || "", username: localStorage.getItem(USER_KEY) || "", status: "local", timer: null, callbacks: null };

  function loadJson(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key) || "") || fallback; } catch { return fallback; }
  }

  function saveJson(key, value) { localStorage.setItem(key, JSON.stringify(value)); }
  function guestActionCount() {
    const value = Number.parseInt(localStorage.getItem(GUEST_ACTION_KEY) || "0", 10);
    return Number.isFinite(value) && value > 0 ? Math.min(value, GUEST_ACTION_LIMIT) : 0;
  }

  function isAuthenticated() { return Boolean(state.token); }

  function consumeGuestAction(label = "此操作") {
    if (isAuthenticated()) return true;
    const next = guestActionCount() + 1;
    localStorage.setItem(GUEST_ACTION_KEY, String(Math.min(next, GUEST_ACTION_LIMIT)));
    renderAccount();
    // 第 20 次点击开始锁定；游客可正常完成前 19 次受限操作。
    if (next >= GUEST_ACTION_LIMIT) {
      openModal("register");
      message(`${label}需要登录。游客试用次数已用完，创建账号后可继续使用全部功能并跨设备同步。`, true);
      return false;
    }
    return true;
  }
  function meta() { return loadJson(META_KEY, {}); }
  function stamp(kind, key, updatedAt = new Date().toISOString()) {
    const values = meta();
    values[`${kind}|${key}`] = updatedAt;
    saveJson(META_KEY, values);
    return updatedAt;
  }

  async function api(path, options = {}) {
    if (!API_BASE) throw new Error("同步服务尚未启用");
    const response = await fetch(`${API_BASE}/api${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && state.token) clearSession(false);
      throw new Error(payload.error || "同步请求失败");
    }
    return payload;
  }

  function setSession(payload) {
    state.token = payload.token;
    state.username = payload.username;
    localStorage.setItem(TOKEN_KEY, state.token);
    localStorage.setItem(USER_KEY, state.username);
    renderAccount();
  }

  function clearSession(clearPersonal = false) {
    state.token = "";
    state.username = "";
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    if (clearPersonal) {
      ["job_statuses", "job_status_snapshots", "offline_event_plans", META_KEY].forEach((key) => localStorage.removeItem(key));
    }
    state.status = "local";
    renderAccount();
  }

  function setSyncStatus(value, message = "") {
    state.status = value;
    const label = document.getElementById("syncStateLabel");
    if (label) {
      label.textContent = value === "synced" ? "已同步" : value === "syncing" ? "同步中…" : value === "pending" ? "离线使用，待同步" : "仅本机保存";
      label.title = message;
    }
    renderAccount();
  }

  function localItems() {
    const metadata = meta();
    const statuses = loadJson("job_statuses", {});
    const snapshots = loadJson("job_status_snapshots", {});
    const plans = new Set(loadJson("offline_event_plans", []));
    const now = new Date().toISOString();
    const items = [];
    for (const [key, status] of Object.entries(statuses)) {
      if (!key.startsWith("job_status_v2|")) continue;
      const mapKey = `job_status|${key}`;
      if (!metadata[mapKey]) metadata[mapKey] = now;
      items.push({ kind: "job_status", key, value: { status, snapshot: snapshots[key] || null }, updatedAt: metadata[mapKey] });
    }
    for (const id of plans) {
      const mapKey = `offline_plan|${id}`;
      if (!metadata[mapKey]) metadata[mapKey] = now;
      items.push({ kind: "offline_plan", key: id, value: true, updatedAt: metadata[mapKey] });
    }
    saveJson(META_KEY, metadata);
    return items;
  }

  function applyRemote(items) {
    const metadata = meta();
    const statuses = loadJson("job_statuses", {});
    const snapshots = loadJson("job_status_snapshots", {});
    const plans = new Set(loadJson("offline_event_plans", []));
    let changed = false;
    for (const item of items || []) {
      const mapKey = `${item.kind}|${item.key}`;
      const localTime = Date.parse(metadata[mapKey] || "");
      const remoteTime = Date.parse(item.updatedAt || "");
      if (Number.isFinite(localTime) && localTime >= remoteTime) continue;
      if (item.kind === "job_status") {
        const value = typeof item.value === "string" ? { status: item.value } : (item.value || {});
        if (value.status) statuses[item.key] = value.status;
        if (value.snapshot) snapshots[item.key] = value.snapshot;
      } else if (item.kind === "offline_plan") {
        item.value ? plans.add(item.key) : plans.delete(item.key);
      }
      metadata[mapKey] = item.updatedAt;
      changed = true;
    }
    if (changed) {
      saveJson("job_statuses", statuses);
      saveJson("job_status_snapshots", snapshots);
      saveJson("offline_event_plans", [...plans]);
      saveJson(META_KEY, metadata);
      state.callbacks?.onStateApplied?.();
    }
  }

  async function syncNow() {
    if (!state.token || !API_BASE) return;
    setSyncStatus("syncing");
    try {
      const remote = await api("/state");
      applyRemote(remote.items);
      await api("/state", {
        method: "PUT",
        body: JSON.stringify({ items: localItems(), activeKeys: state.callbacks?.getActiveKeys?.() || [] }),
      });
      const latest = await api("/state");
      applyRemote(latest.items);
      setSyncStatus("synced");
    } catch (error) {
      setSyncStatus("pending", error.message);
    }
  }

  function queueSync() {
    if (!state.token) return;
    setSyncStatus("pending");
    clearTimeout(state.timer);
    state.timer = setTimeout(syncNow, 700);
  }

  function recordJobStatus(key, status, snapshot) {
    stamp("job_status", key);
    const snapshots = loadJson("job_status_snapshots", {});
    if (snapshot) {
      snapshots[key] = snapshot;
      saveJson("job_status_snapshots", snapshots);
    }
    queueSync();
  }

  function recordOfflinePlan(key, planned) {
    stamp("offline_plan", key);
    if (!planned) {
      // 取消计划也必须作为显式 false 同步，不能只从本地数组删除。
      const pending = loadJson("job_board_sync_tombstones", {});
      pending[key] = new Date().toISOString();
      saveJson("job_board_sync_tombstones", pending);
    }
    queueSync();
  }

  function localItemsWithTombstones() {
    const items = localItems();
    const pending = loadJson("job_board_sync_tombstones", {});
    for (const [key, updatedAt] of Object.entries(pending)) {
      items.push({ kind: "offline_plan", key, value: false, updatedAt });
    }
    return items;
  }

  // 用包含取消记录的实现替换同步上传部分。
  async function fullSync() {
    if (!state.token || !API_BASE) return;
    setSyncStatus("syncing");
    try {
      const remote = await api("/state");
      applyRemote(remote.items);
      await api("/state", {
        method: "PUT",
        body: JSON.stringify({ items: localItemsWithTombstones(), activeKeys: state.callbacks?.getActiveKeys?.() || [] }),
      });
      localStorage.removeItem("job_board_sync_tombstones");
      const latest = await api("/state");
      applyRemote(latest.items);
      setSyncStatus("synced");
    } catch (error) {
      setSyncStatus("pending", error.message);
    }
  }

  function formValue(id) { return document.getElementById(id)?.value || ""; }
  function message(text, error = false) {
    const target = document.getElementById("accountMessage");
    if (target) { target.textContent = text; target.className = `account-message${error ? " error" : ""}`; }
  }

  function showPane(name) {
    document.querySelectorAll(".account-pane").forEach((pane) => pane.classList.toggle("active", pane.dataset.pane === name));
    message("");
  }

  function openModal(pane = "login") {
    showPane(pane);
    document.getElementById("accountModal")?.classList.add("open");
  }

  function closeModal() { document.getElementById("accountModal")?.classList.remove("open"); }

  async function submitLogin() {
    try {
      const result = await api("/login", { method: "POST", body: JSON.stringify({ username: formValue("loginUsername"), password: formValue("loginPassword") }) });
      setSession(result); closeModal(); await fullSync();
    } catch (error) { message(error.message, true); }
  }

  async function submitRegister() {
    if (!document.getElementById("privacyConsent")?.checked) return message("请先确认数据与隐私说明", true);
    try {
      const result = await api("/register", { method: "POST", body: JSON.stringify({ username: formValue("registerUsername"), password: formValue("registerPassword"), inviteCode: formValue("registerInvite"), consent: true }) });
      setSession(result); closeModal(); await fullSync();
    } catch (error) { message(error.message, true); }
  }

  async function submitReset() {
    try {
      const result = await api("/reset/consume", { method: "POST", body: JSON.stringify({ username: formValue("resetUsername"), resetCode: formValue("resetCode"), newPassword: formValue("resetPassword") }) });
      setSession(result); closeModal(); await fullSync();
    } catch (error) { message(error.message, true); }
  }

  async function submitPasswordChange() {
    try {
      const result = await api("/change-password", { method: "POST", body: JSON.stringify({ currentPassword: formValue("currentPassword"), newPassword: formValue("newPassword") }) });
      setSession(result); message("密码已修改，其他设备需要重新登录");
    } catch (error) { message(error.message, true); }
  }

  async function doLogout() {
    try { await api("/logout", { method: "POST" }); } catch {}
    clearSession(false); closeModal();
  }

  async function deleteAccount() {
    if (!confirm("账号和云端个人状态将永久删除，且无法恢复。确定继续吗？")) return;
    try {
      await api("/account", { method: "DELETE", body: JSON.stringify({ password: formValue("deletePassword") }) });
      clearSession(true); closeModal(); state.callbacks?.onStateApplied?.();
    } catch (error) { message(error.message, true); }
  }

  function renderAccount() {
    const button = document.getElementById("accountButton");
    if (!button) return;
    button.textContent = state.token
      ? `${state.username} · ${state.status === "synced" ? "已同步" : state.status === "syncing" ? "同步中" : "待同步"}`
      : `登录 / 注册 · 游客剩余 ${Math.max(0, GUEST_ACTION_LIMIT - guestActionCount())} 次`;
    button.classList.toggle("pending", state.token && state.status !== "synced");
  }

  function installUi() {
    const host = document.querySelector(".header-actions");
    if (!host || document.getElementById("accountButton")) return;
    const button = document.createElement("button");
    button.id = "accountButton";
    button.className = "account-button";
    button.addEventListener("click", () => openModal(state.token ? "account" : "login"));
    host.appendChild(button);
    document.body.insertAdjacentHTML("beforeend", `<div class="account-modal" id="accountModal"><div class="account-dialog">
      <button class="account-close" id="accountClose" aria-label="关闭">×</button>
      <div class="account-pane" data-pane="login"><h2>登录同步</h2><p>登录后在不同设备同步个人岗位状态和招聘会计划。</p><input id="loginUsername" autocomplete="username" placeholder="账号名"><input id="loginPassword" type="password" autocomplete="current-password" placeholder="密码"><button class="primary" id="loginSubmit">登录</button><div class="account-links"><button data-show="register">创建账号</button><button data-show="reset">使用重置码</button><button data-show="privacy">数据与隐私</button></div></div>
      <div class="account-pane" data-pane="register"><h2>创建班级账号</h2><input id="registerUsername" autocomplete="username" placeholder="账号名（3–24位字母、数字或下划线）"><input id="registerPassword" type="password" autocomplete="new-password" placeholder="密码（至少8位）"><input id="registerInvite" type="password" placeholder="班级邀请码"><label class="consent"><input id="privacyConsent" type="checkbox"> 我已了解平台仅保存账号验证信息、岗位状态和线下活动计划；管理员只能查看汇总人数。</label><button class="primary" id="registerSubmit">注册并同步</button><div class="account-links"><button data-show="login">返回登录</button><button data-show="privacy">数据与隐私</button></div></div>
      <div class="account-pane" data-pane="reset"><h2>使用一次性重置码</h2><p>向管理员提供准确账号名，获得20分钟内有效的重置码。</p><input id="resetUsername" autocomplete="username" placeholder="账号名"><input id="resetCode" placeholder="一次性重置码"><input id="resetPassword" type="password" autocomplete="new-password" placeholder="新密码（至少8位）"><button class="primary" id="resetSubmit">重置密码并登录</button><div class="account-links"><button data-show="login">返回登录</button></div></div>
      <div class="account-pane" data-pane="account"><h2 id="accountTitle">个人同步</h2><p id="syncStateLabel">${state.status}</p><button class="primary" id="syncNow">立即同步</button><hr><h3>修改密码</h3><input id="currentPassword" type="password" autocomplete="current-password" placeholder="当前密码"><input id="newPassword" type="password" autocomplete="new-password" placeholder="新密码（至少8位）"><button id="passwordSubmit">修改密码</button><hr><button id="logoutSubmit">退出登录</button><h3>删除账号</h3><input id="deletePassword" type="password" autocomplete="current-password" placeholder="输入当前密码确认"><button class="danger" id="deleteSubmit">永久删除账号及个人数据</button><div class="account-links"><button data-show="privacy">数据与隐私</button></div></div>
      <div class="account-pane" data-pane="privacy"><h2>数据与隐私</h2><p>公共岗位和招聘会不按成员重复保存。云端只保存账号验证信息、岗位处理状态和线下活动计划。</p><p>管理员只能查看注册总人数、近7天和近30天登录人数，不能查看成员个人操作。登录会话有效30天；公共记录移除90天后，其关联个人状态自动清理。成员可自行删除账号和数据。</p><div class="account-links"><button data-show="${state.token ? "account" : "login"}">返回</button></div></div>
      <div id="accountMessage" class="account-message"></div></div></div>`);
    const style = document.createElement("style");
    style.textContent = `.account-button{border:1px solid #ffffff66;background:#ffffff18;color:#fff;border-radius:7px;padding:7px 11px;cursor:pointer}.account-button.pending{border-color:#fbbf24}.account-modal{display:none;position:fixed;inset:0;background:#0f172acc;z-index:1000;align-items:center;justify-content:center;padding:16px}.account-modal.open{display:flex}.account-dialog{position:relative;background:#fff;color:#1e293b;width:min(440px,100%);max-height:90vh;overflow:auto;border-radius:12px;padding:24px;box-shadow:0 20px 50px #0005}.account-close{position:absolute;right:12px;top:9px;border:0;background:none;font-size:25px;cursor:pointer;color:#64748b}.account-pane{display:none}.account-pane.active{display:block}.account-pane h2{margin-bottom:8px}.account-pane h3{margin:14px 0 6px}.account-pane p{font-size:13px;color:#64748b;margin:7px 0}.account-pane input{display:block;width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:7px;margin:9px 0}.account-pane>button{border:1px solid #cbd5e1;background:#fff;border-radius:7px;padding:9px 12px;cursor:pointer;margin:4px 4px 4px 0}.account-pane>button.primary{background:#2563eb;border-color:#2563eb;color:#fff}.account-pane>button.danger{background:#fee2e2;border-color:#fecaca;color:#b91c1c}.account-pane hr{border:0;border-top:1px solid #e2e8f0;margin:16px 0}.account-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.account-links button{border:0;background:none;color:#2563eb;cursor:pointer;padding:0}.consent{display:flex;gap:8px;font-size:12px;color:#475569;align-items:flex-start;margin:10px 0}.consent input{width:auto;margin:3px 0}.account-message{font-size:13px;color:#047857;margin-top:12px}.account-message.error{color:#b91c1c}`;
    document.head.appendChild(style);
    document.getElementById("accountClose").onclick = closeModal;
    document.getElementById("accountModal").addEventListener("click", (event) => { if (event.target.id === "accountModal") closeModal(); });
    document.querySelectorAll("[data-show]").forEach((el) => el.addEventListener("click", () => showPane(el.dataset.show)));
    document.getElementById("loginSubmit").onclick = submitLogin;
    document.getElementById("registerSubmit").onclick = submitRegister;
    document.getElementById("resetSubmit").onclick = submitReset;
    document.getElementById("syncNow").onclick = fullSync;
    document.getElementById("passwordSubmit").onclick = submitPasswordChange;
    document.getElementById("logoutSubmit").onclick = doLogout;
    document.getElementById("deleteSubmit").onclick = deleteAccount;
    document.addEventListener("click", (event) => {
      const link = event.target.closest?.("a.link-apply, a.link-notice");
      if (!link || !link.href) return;
      if (!consumeGuestAction("查看报名或公告")) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
    renderAccount();
  }

  async function init(callbacks) {
    state.callbacks = callbacks;
    installUi();
    if (!API_BASE) { setSyncStatus("local", "同步服务尚未部署"); return; }
    if (state.token) {
      try {
        const current = await api("/me");
        state.username = current.username;
        localStorage.setItem(USER_KEY, state.username);
        await fullSync();
      } catch (error) {
        setSyncStatus("local", error.message);
      }
    }
    window.addEventListener("online", fullSync);
  }

  window.BoardSync = {
    init,
    recordJobStatus,
    recordOfflinePlan,
    syncNow: fullSync,
    open: openModal,
    isAuthenticated,
    consumeGuestAction,
  };
})();
