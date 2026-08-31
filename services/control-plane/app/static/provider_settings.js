const list = document.querySelector("#provider-settings-list");
const banner = document.querySelector("#provider-restart-banner");
const toast = document.querySelector("#provider-toast");

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail?.code || `请求失败 (${response.status})`);
  return payload;
}

function notify(message) {
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

function renderProvider(provider) {
  return `<article class="provider-card" data-provider-id="${escapeHtml(provider.id)}">
    <header><div><h2>${escapeHtml(provider.name)}</h2><p>${escapeHtml(provider.summary)}</p></div><span class="provider-state ${provider.complete ? "ready" : "pending"}">${provider.complete ? "已配置" : provider.configured ? "配置不完整" : "未配置"}</span></header>
    <form>
      <div class="provider-fields">${provider.fields.map((field) => `<label>
        <span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
        <input name="${escapeHtml(field.name)}" type="${field.secret ? "password" : "text"}" autocomplete="off" placeholder="${escapeHtml(field.configured ? field.masked_value : field.placeholder)}">
        ${field.configured ? `<small>已保存：${escapeHtml(field.masked_value)} · 留空保持不变</small>` : ""}
      </label>`).join("")}</div>
      <div class="provider-actions"><button type="submit">加密保存</button><button type="button" class="provider-clear">清除此服务</button></div>
    </form>
  </article>`;
}

async function loadProviders() {
  const status = await api("/api/provider-settings");
  list.innerHTML = status.providers.map(renderProvider).join("");
  banner.hidden = !status.restart_required;
  bindForms();
}

function bindForms() {
  document.querySelectorAll(".provider-card").forEach((card) => {
    const providerId = card.dataset.providerId;
    card.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      const values = Object.fromEntries(Array.from(new FormData(event.currentTarget).entries()).filter(([, value]) => String(value).trim()));
      try {
        await api(`/api/provider-settings/${encodeURIComponent(providerId)}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
        });
        notify("配置已加密保存；重启本地服务后生效");
        await loadProviders();
      } catch (error) { notify(error.message); } finally { button.disabled = false; }
    });
    card.querySelector(".provider-clear").addEventListener("click", async (event) => {
      event.currentTarget.disabled = true;
      try {
        await api(`/api/provider-settings/${encodeURIComponent(providerId)}`, { method: "DELETE" });
        notify("该服务配置已清除；重启后生效");
        await loadProviders();
      } catch (error) { notify(error.message); } finally { event.currentTarget.disabled = false; }
    });
  });
}

loadProviders().catch((error) => { list.innerHTML = `<p class="provider-error">${escapeHtml(error.message)}</p>`; });
