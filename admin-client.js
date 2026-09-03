(function () {
  "use strict";
  const API_BASE = String(window.JOB_BOARD_SYNC_CONFIG?.apiBase || "").replace(/\/$/, "");
  let token = sessionStorage.getItem("job_board_admin_token") || "";
  let stats = null;
  const byId = (id) => document.getElementById(id);

  async function api(path, options = {}) {
    if (!API_BASE) throw new Error("同步服务尚未配置");
    const response = await fetch(`${API_BASE}/api${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "请求失败");
    return payload;
  }

  function message(id, text, error = false) {
    const target = byId(id); target.textContent = text; target.classList.toggle("error", error);
  }

  async function loadStats() {
    stats = await api("/admin/stats");
    byId("loginPanel").classList.add("hidden"); byId("adminPanel").classList.remove("hidden");
    byId("registered").textContent = stats.registered; byId("active7").textContent = stats.active7Days; byId("active30").textContent = stats.active30Days;
    byId("registrationState").textContent = stats.registrationOpen ? "当前允许新账号注册" : "当前已暂停新账号注册";
    byId("toggleRegistration").textContent = stats.registrationOpen ? "暂停注册" : "恢复注册";
  }

  byId("loginButton").onclick = async () => { try { const data = await api("/admin/login", { method: "POST", body: JSON.stringify({ username: byId("adminUsername").value, password: byId("adminPassword").value }) }); token = data.token; sessionStorage.setItem("job_board_admin_token", token); byId("adminPassword").value = ""; await loadStats(); } catch (error) { message("loginMessage", error.message, true); } };
  byId("toggleRegistration").onclick = async () => { try { await api("/admin/settings", { method: "PUT", body: JSON.stringify({ registrationOpen: !stats.registrationOpen }) }); await loadStats(); } catch (error) { message("settingsMessage", error.message, true); } };
  byId("rotateInvite").onclick = async () => { try { await api("/admin/settings", { method: "PUT", body: JSON.stringify({ newInviteCode: byId("newInviteCode").value }) }); byId("newInviteCode").value = ""; message("settingsMessage", "邀请码已更换"); } catch (error) { message("settingsMessage", error.message, true); } };
  byId("createResetCode").onclick = async () => { try { const data = await api("/admin/reset-code", { method: "POST", body: JSON.stringify({ username: byId("memberUsername").value }) }); message("resetMessage", `一次性重置码：${data.resetCode}（${data.expiresInMinutes}分钟内有效）`); } catch (error) { message("resetMessage", error.message, true); } };
  byId("logoutButton").onclick = () => { token = ""; stats = null; sessionStorage.removeItem("job_board_admin_token"); location.reload(); };
  if (token) loadStats().catch(() => { token = ""; sessionStorage.removeItem("job_board_admin_token"); });
})();
