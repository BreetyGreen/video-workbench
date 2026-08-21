const $ = (selector) => document.querySelector(selector);

const stateLabels = {
  configured: "已连接",
  partially_configured: "部分连接",
  not_configured: "未连接",
  oauth_required: "需要账号授权",
  permission_required: "需要申请权限",
  unreachable: "暂时无法连接",
};

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function safeUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch {
    return "#";
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail?.message || payload.detail?.code || `请求失败 (${response.status})`);
  return payload;
}

function toast(message) {
  const node = $("#setup-toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("show"), 3200);
}

function renderRuntime(status) {
  const runtime = status.runtime || {};
  const tools = runtime.tools || {};
  const jianying = runtime.jianying || {};
  const rows = [
    ["FFmpeg 视频引擎", tools.ffmpeg && tools.ffprobe ? "已发现 FFmpeg 与 FFprobe" : "未发现完整视频工具，请重新运行启动脚本", tools.ffmpeg && tools.ffprobe],
    ["本地数据", runtime.runtime?.data_dir || "等待创建", runtime.local_mode?.ready !== false],
    ["素材收件箱", runtime.runtime?.inbox_dir || "等待创建", Boolean(runtime.runtime?.inbox_dir)],
    ["剪映交付", jianying.draft_root ? "草稿目录已发现" : jianying.installed ? "已安装；首次导入时选择草稿目录" : "未安装；仍可生成草稿 ZIP", Boolean(jianying.installed || jianying.draft_root)],
  ];
  $("#setup-runtime-list").innerHTML = rows.map(([name, detail, ok]) => `
    <div class="runtime-item">
      <span class="state-dot ${ok ? "ok" : ""}" aria-hidden="true"></span>
      <div><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small></div>
    </div>
  `).join("");
}

function providerMarkup(provider) {
  const secondaryLink = provider.secondary_official_url
    ? `<a href="${safeUrl(provider.secondary_official_url)}" target="_blank" rel="noreferrer">第二官方入口 ↗</a>`
    : "";
  const settingsLink = provider.id === "volcengine"
    ? '<a href="/settings/cloud-usage">配置只读用量</a>'
    : "";
  return `
    <article class="provider-item" data-provider-id="${escapeHtml(provider.id)}">
      <div class="provider-top">
        <h3>${escapeHtml(provider.name)}</h3>
        <span class="provider-status ${escapeHtml(provider.status)}">${escapeHtml(stateLabels[provider.status] || "待检查")}</span>
      </div>
      <p class="provider-summary">${escapeHtml(provider.summary)}</p>
      <p class="provider-detail">${escapeHtml(provider.detail)}</p>
      <ul class="provider-meta">${(provider.fields || []).map((field) => `<li>${escapeHtml(field)}</li>`).join("")}</ul>
      <p class="provider-fallback">未连接时：${escapeHtml(provider.fallback)}</p>
      <div class="provider-actions">
        <a href="${safeUrl(provider.official_url)}" target="_blank" rel="noreferrer">打开官方申请页 ↗</a>
        ${secondaryLink}${settingsLink}
        <button type="button" data-validate-provider="${escapeHtml(provider.id)}">重新检测</button>
      </div>
    </article>
  `;
}

function renderProviders(status) {
  $("#setup-provider-list").innerHTML = status.providers.map(providerMarkup).join("");
  $("#setup-completion").textContent = `${status.progress.configured_optional} / ${status.progress.optional_total} 已连接`;
  document.querySelectorAll("[data-validate-provider]").forEach((button) => {
    button.addEventListener("click", () => validateProvider(button));
  });
}

function renderSetup(status) {
  const ready = Boolean(status.local_mode?.ready);
  $("#local-ready-label").textContent = ready ? "本地环境已就绪" : "本地环境需要处理";
  $("#local-feature-list").innerHTML = (status.local_mode?.available_features || []).map((feature) => `<span>${escapeHtml(feature)}</span>`).join("");
  $("#confirm-local-mode").disabled = !ready;
  $("#finish-setup").disabled = !ready;
  renderRuntime(status);
  renderProviders(status);
}

async function validateProvider(button) {
  const providerId = button.dataset.validateProvider;
  button.disabled = true;
  button.textContent = "检测中…";
  try {
    const provider = await api(`/api/setup/validate/${encodeURIComponent(providerId)}`, { method: "POST" });
    const existing = document.querySelector(`[data-provider-id="${CSS.escape(providerId)}"]`);
    existing.outerHTML = providerMarkup(provider);
    const replacement = document.querySelector(`[data-provider-id="${CSS.escape(providerId)}"] [data-validate-provider]`);
    replacement.addEventListener("click", () => validateProvider(replacement));
    toast(stateLabels[provider.status] || "检测完成");
  } catch (error) {
    toast(error.message);
    button.disabled = false;
    button.textContent = "重新检测";
  }
}

async function confirmLocalMode() {
  const buttons = [$("#confirm-local-mode"), $("#finish-setup")];
  buttons.forEach((button) => { button.disabled = true; });
  try {
    await api("/api/setup/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ local_mode_confirmed: true }),
    });
    window.location.assign("/");
  } catch (error) {
    toast(error.message);
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function loadSetup() {
  try {
    renderSetup(await api("/api/setup/status"));
  } catch (error) {
    toast(`无法读取本机状态：${error.message}`);
    $("#setup-runtime-list").innerHTML = '<p class="provider-detail">请确认本地服务仍在运行，然后刷新页面。</p>';
  }
}

$("#confirm-local-mode").addEventListener("click", confirmLocalMode);
$("#finish-setup").addEventListener("click", confirmLocalMode);
loadSetup();
