const $ = (selector) => document.querySelector(selector);

const stateLabels = {
  configured: "已连接",
  partially_configured: "部分连接",
  not_configured: "未连接",
  oauth_required: "需要账号授权",
  permission_required: "需要申请权限",
  unreachable: "暂时无法连接",
};

const tierLabels = {
  local_no_key: "无需 Key",
  optional_key: "可选增强",
  external_authorization: "需要外部授权",
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
    ["本地数据", runtime.runtime?.data_dir || "等待创建", Boolean(runtime.runtime?.data_dir)],
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
      <p class="provider-detail"><strong>下一步：</strong>${escapeHtml(provider.next_action)}</p>
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

function capabilityMarkup(capability) {
  const requirements = capability.requires?.length
    ? capability.requires.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : "<li>无需账号或云端凭据</li>";
  return `
    <article class="capability-item">
      <div class="provider-top">
        <h3>${escapeHtml(capability.name)}</h3>
        <span class="capability-tier ${escapeHtml(capability.tier)}">${escapeHtml(tierLabels[capability.tier] || "待确认")}</span>
      </div>
      <p class="provider-summary">${escapeHtml(capability.summary)}</p>
      <div class="capability-block"><strong>支持</strong><ul>${(capability.features || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      <div class="capability-block"><strong>需要</strong><ul>${requirements}</ul></div>
      <p class="provider-detail"><strong>未配置时：</strong>${escapeHtml(capability.fallback)}</p>
      <p class="capability-boundary"><strong>数据边界：</strong>${escapeHtml(capability.data_boundary)}</p>
    </article>
  `;
}

function renderCapabilities(status) {
  const capabilities = status.capabilities || [];
  const tierOrder = ["local_no_key", "optional_key", "external_authorization"];
  $("#setup-capability-list").innerHTML = tierOrder.map((tier) => {
    const items = capabilities.filter((item) => item.tier === tier);
    if (!items.length) return "";
    return `
      <section class="capability-group" aria-label="${escapeHtml(tierLabels[tier])}">
        <header><span class="capability-tier ${escapeHtml(tier)}">${escapeHtml(tierLabels[tier])}</span><small>${items.length} 项</small></header>
        <div class="capability-grid">${items.map(capabilityMarkup).join("")}</div>
      </section>
    `;
  }).join("");
}

function renderSetup(status) {
  const ready = Boolean(status.local_mode?.ready);
  $("#local-ready-label").textContent = ready ? "本地环境已就绪" : "本地环境需要处理";
  $("#local-feature-list").innerHTML = (status.local_mode?.available_features || []).map((feature) => `<span>${escapeHtml(feature)}</span>`).join("");
  $("#confirm-local-mode").disabled = !ready;
  $("#finish-setup").disabled = !ready;
  renderRuntime(status);
  renderCapabilities(status);
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

async function createDevicePairingCode() {
  const button = $("#create-device-pairing-code");
  const output = $("#device-pairing-result");
  button.disabled = true;
  button.textContent = "正在生成…";
  try {
    const pairing = await api("/api/devices/pairing-codes", { method: "POST" });
    const expiry = new Date(pairing.expires_at).toLocaleString("zh-CN");
    output.hidden = false;
    output.innerHTML = `<span>一次性配对码</span><strong>${escapeHtml(pairing.code)}</strong><small>请在 ${escapeHtml(expiry)} 前输入同步助手；使用一次后立即失效。</small>`;
    await navigator.clipboard?.writeText(pairing.code).catch(() => {});
    toast("配对码已生成并尝试复制到剪贴板");
  } catch (error) {
    toast(`无法生成配对码：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "重新生成配对码";
  }
}

const tutorialStageLabels = {
  queued: "已进入队列",
  creating_course: "创建隔离演示课程",
  preparing_tutorial_video: "准备有声教学视频",
  preparing_licensed_materials: "下载并校验授权素材",
  transcribing_and_learning: "教学视频 ASR 与规则学习",
  editing_and_quality_gate: "基线对照、剪辑与质量门禁",
  collecting_acceptance_evidence: "整理验收证据",
  complete: "完整演示已通过",
  failed: "演示未通过",
};

function renderTutorialDemo(run) {
  const output = $("#tutorial-demo-result");
  output.hidden = false;
  const label = tutorialStageLabels[run.stage] || run.stage;
  if (run.state === "completed") {
    const links = [
      ["查看成片与质量报告", run.artifacts.review_url],
      ["教学视频", run.artifacts.tutorial_video_url],
      ["ASR 转写", run.artifacts.transcript_url],
      ["课程配方", run.artifacts.recipe_url],
      ["基线差异", run.artifacts.comparison_url],
      ["规则引用", run.artifacts.rule_trace_url],
      ["素材授权账本", run.artifacts.rights_ledger_url],
      ["剪映草稿", run.artifacts.draft_url],
    ].filter(([, url]) => url);
    output.innerHTML = `<strong>${escapeHtml(label)}</strong><span>教学视频、独立素材、规则证据、成片和剪映草稿均已落盘。</span><div class="tutorial-demo-links">${links.map(([name, url]) => `<a href="${safeUrl(url)}">${escapeHtml(name)}</a>`).join("")}</div>`;
    return;
  }
  if (run.state === "failed") {
    output.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(run.error_code || "请查看服务日志中的失败代码")}</span>`;
    return;
  }
  output.innerHTML = `<strong>${escapeHtml(label)}</strong><span>后台执行中，可以保留此页面等待结果。</span>`;
}

async function pollTutorialDemo(runId) {
  try {
    const run = await api(`/api/tutorial-learning-demo/${encodeURIComponent(runId)}`);
    renderTutorialDemo(run);
    if (!["completed", "failed"].includes(run.state)) {
      window.setTimeout(() => pollTutorialDemo(runId), 1500);
    } else {
      const button = $("#run-tutorial-demo");
      button.disabled = false;
      button.textContent = run.state === "completed" ? "重新运行完整演示" : "重新尝试完整演示";
    }
  } catch (error) {
    toast(`演示状态读取失败：${error.message}`);
    window.setTimeout(() => pollTutorialDemo(runId), 2500);
  }
}

async function startTutorialDemo() {
  const button = $("#run-tutorial-demo");
  button.disabled = true;
  button.textContent = "正在启动…";
  try {
    const run = await api("/api/tutorial-learning-demo", { method: "POST" });
    renderTutorialDemo(run);
    pollTutorialDemo(run.id);
  } catch (error) {
    toast(`无法启动教学演示：${error.message}`);
    button.disabled = false;
    button.textContent = "运行完整教学演示";
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
$("#device-server-url").textContent = window.location.origin;
$("#create-device-pairing-code").addEventListener("click", createDevicePairingCode);
$("#run-tutorial-demo").addEventListener("click", startTutorialDemo);
loadSetup();
