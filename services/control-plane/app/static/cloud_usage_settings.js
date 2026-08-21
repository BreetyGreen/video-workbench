const form = document.querySelector("#cloud-usage-form");
const result = document.querySelector("#settings-result");

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"})[character]);
}

function formatNumber(value, digits = 0) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", {maximumFractionDigits: digits}).format(value);
}

function formatTime(value) {
  if (!value) return "尚无官方更新时间";
  return new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "short"}).format(new Date(value));
}

function statusLabel(status) {
  return ({available: "可读取", unavailable: "暂不可读", configured: "已设置", not_configured: "未设置"})[status] || status;
}

function renderEvidenceLayers(layers = {}) {
  const labels = {
    official_balance: ["官方现金余额", "火山引擎费用中心接口"],
    gifted_entitlements: ["官方赠送资源", "免费额度、资源包与代金券"],
    configured_budgets: ["本地预算上限", "由你手动设置，不是官方额度"],
    local_metering: ["本地调用账本", "本机实际发出的服务调用"],
  };
  document.querySelector("#evidence-layers").innerHTML = Object.entries(labels).map(([key, label]) => {
    const layer = layers[key] || {status: "unavailable", reason: "missing"};
    const reason = layer.reason ? ` · ${escapeHtml(layer.reason)}` : "";
    return `<article class="evidence-layer ${escapeHtml(layer.status)}"><strong>${label[0]}</strong><span>${label[1]} · ${statusLabel(layer.status)}${reason}</span></article>`;
  }).join("");
}

function unknownBlock(section, fallback = "官方接口当前没有返回该字段") {
  const reason = section?.error ? ` · ${escapeHtml(section.error)}` : "";
  return `<strong class="unknown-value">未知</strong><p>${fallback}${reason}</p>`;
}

function renderOfficialCards(data) {
  const balance = data.balance || {};
  const entitlements = data.ark_entitlements || {};
  const packages = data.resource_packages || {};
  const coupons = data.coupons || {};
  let giftValue = "未知";
  let giftDetail = "官方赠送资源暂不可读";
  let giftUnknown = true;
  if (entitlements.available) {
    const hasGift = Number(entitlements.models_with_initial_free_usage || 0) > 0 || Number(entitlements.resource_pack_count || 0) > 0;
    giftValue = hasGift ? formatNumber(entitlements.total_remaining_tokens) : "未发现";
    giftDetail = hasGift ? `初始免费剩余 ${formatNumber(entitlements.initial_remaining_tokens)} · 模型 ${formatNumber(entitlements.models_with_initial_free_usage)}` : "官方已返回，当前未发现模型赠送额度";
    giftUnknown = false;
  }
  const packageParts = [];
  if (packages.available) packageParts.push(`${formatNumber(packages.count)} 个资源包`);
  if (coupons.available) packageParts.push(`${formatNumber(coupons.count)} 张代金券`);
  const packageValue = coupons.available ? `¥${formatNumber(coupons.total_remaining_amount, 2)}` : packages.available ? formatNumber(packages.count) : "未知";
  document.querySelector("#official-usage-cards").innerHTML = `
    <article class="usage-detail-card"><header><h3>账户可用余额</h3><span class="source-badge official">官方接口</span></header>${balance.available ? `<strong>¥${formatNumber(balance.available_balance, 2)}</strong><p>现金 ¥${formatNumber(balance.cash_balance, 2)} · 信控 ${balance.credit_limit === null || balance.credit_limit === undefined ? "未知" : `¥${formatNumber(balance.credit_limit, 2)}`}</p>` : unknownBlock(balance, "余额接口暂不可读")}</article>
    <article class="usage-detail-card"><header><h3>模型赠送额度</h3><span class="source-badge official">官方接口</span></header><strong class="${giftUnknown ? "unknown-value" : ""}">${giftValue}</strong><p>${giftDetail}</p></article>
    <article class="usage-detail-card"><header><h3>资源包与代金券</h3><span class="source-badge official">官方接口</span></header><strong class="${!packages.available && !coupons.available ? "unknown-value" : ""}">${packageValue}</strong><p>${packageParts.length ? packageParts.join(" · ") : "官方资源权益暂不可读"}</p></article>`;
}

function localMetricCard(title, metric, unit) {
  const hasBudget = metric?.remaining !== null && metric?.remaining !== undefined;
  const value = hasBudget ? metric.remaining : metric?.used;
  return `<article class="local-usage-card"><header><h3>${title}</h3><span class="source-badge local">本地计量</span></header><strong>${formatNumber(value, 1)}</strong><p>${hasBudget ? `剩余 ${unit} · 已用 ${formatNumber(metric.used, 1)}` : `已用 ${unit} · 尚未设置预算上限`}</p></article>`;
}

function renderLocalCards(local = {}) {
  document.querySelector("#local-usage-cards").innerHTML = [
    localMetricCard("语音识别 ASR", local.asr, "秒"),
    localMetricCard("语音合成 TTS", local.tts, "字符"),
    `<article class="local-usage-card"><header><h3>Dify 工作流</h3><span class="source-badge local">本地计量</span></header><strong>${formatNumber(local.tokens)}</strong><p>已记录 Token · 未应用调用 ${formatNumber(local.unapplied_calls)}</p></article>`,
  ].join("");
}

function renderTaskLedger(tasks = []) {
  const body = document.querySelector("#task-usage-ledger tbody");
  if (!tasks.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty-state">还没有可显示的视频调用记录。</td></tr>';
    return;
  }
  body.innerHTML = tasks.map((task) => {
    const totals = task.totals || {};
    return `<tr>
      <td><div class="ledger-title"><strong><a href="/review/${encodeURIComponent(task.task_id)}">${escapeHtml(task.title)}</a></strong><small>${escapeHtml(task.content_type)} · ${escapeHtml(task.status)}</small></div></td>
      <td class="${totals.asr_audio_seconds ? "" : "ledger-zero"}">${formatNumber(totals.asr_audio_seconds, 1)} 秒</td>
      <td class="${totals.tts_characters ? "" : "ledger-zero"}">${formatNumber(totals.tts_characters)} 字符</td>
      <td class="${totals.total_tokens ? "" : "ledger-zero"}">${formatNumber(totals.total_tokens)} Token</td>
      <td>${formatNumber(task.event_count)}</td>
      <td>${task.last_event_at ? formatTime(task.last_event_at) : "尚无云端调用"}</td>
    </tr>`;
  }).join("");
}

async function loadSettings() {
  const response = await fetch("/api/cloud-usage/settings");
  const data = await response.json();
  document.querySelector("#credential-state").textContent = data.configured ? `已连接 ${data.access_key_id_masked}` : "官方凭证待配置";
  document.querySelector(".credential-settings").open = !data.configured;
  form.elements.asr_total_seconds.value = data.asr_total_seconds || "";
  form.elements.tts_total_characters.value = data.tts_total_characters || "";
  form.elements.ark_monthly_tokens.value = data.ark_monthly_tokens || "";
  form.elements.warning_threshold_percent.value = data.warning_threshold_percent ?? 20;
  form.elements.critical_threshold_percent.value = data.critical_threshold_percent ?? 10;
}

async function loadUsageCenter({force = false} = {}) {
  const response = await fetch(force ? "/api/cloud-usage/refresh" : "/api/cloud-usage/summary", {method: force ? "POST" : "GET"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail?.code || `读取失败 (${response.status})`);
  renderEvidenceLayers(data.evidence_layers);
  renderOfficialCards(data);
  renderLocalCards(data.local);
  renderTaskLedger(data.recent_tasks);
  document.querySelector("#usage-updated-at").textContent = data.updated_at ? `官方更新 ${formatTime(data.updated_at)}` : "官方数据未连接，本地账本可用";
}

document.querySelectorAll(".clipboard").forEach((button) => button.addEventListener("click", async () => {
  try { form.elements[button.dataset.target].value = await navigator.clipboard.readText(); result.textContent = "已从剪贴板读取"; }
  catch { result.textContent = "浏览器未允许读取剪贴板，请在输入框按 Ctrl+V"; }
}));

document.querySelector("#refresh-usage").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "正在刷新…";
  try { await loadUsageCenter({force: true}); }
  catch (error) { document.querySelector("#usage-updated-at").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "刷新官方数据"; }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault(); result.textContent = "正在验证只读权限…";
  const payload = Object.fromEntries(new FormData(form));
  ["asr_total_seconds", "tts_total_characters", "ark_monthly_tokens", "warning_threshold_percent", "critical_threshold_percent"].forEach((key) => payload[key] = Number(payload[key] || 0));
  const response = await fetch("/api/cloud-usage/settings", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
  const data = await response.json();
  const stageNames = {balance: "账户余额", ark_usage: "方舟用量"};
  const detail = data.detail || {};
  const failure = `验证失败（${stageNames[detail.stage] || "凭证"}）：${detail.reason || detail.code || response.status}${detail.http_status ? ` · HTTP ${detail.http_status}` : ""}`;
  result.textContent = response.ok ? `保存成功：${data.access_key_id_masked}` : failure;
  if (response.ok) {
    form.elements.access_key_id.value = "";
    form.elements.secret_access_key.value = "";
    await Promise.all([loadSettings(), loadUsageCenter({force: true})]);
  }
});

Promise.allSettled([loadSettings(), loadUsageCenter()]);
