const $ = (selector) => document.querySelector(selector);

const statusLabels = {
  received: "已接收",
  analyzing: "分析中",
  planning: "规划中",
  editing: "剪辑中",
  reviewing: "待审核",
  changes_requested: "待修改",
  approved: "已批准",
  delivered: "已交付",
  failed: "失败",
};

let showingArchivedTasks = false;

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch {
    return "#";
  }
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail?.message || payload.detail?.code || `请求失败 (${response.status})`);
  return payload;
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function updateCreationPreflight() {
  const form = $("#task-form");
  if (!form) return;
  const contentType = form.elements.content_type.value || "通用短视频";
  const files = Array.from(form.elements.files.files || []);
  const profile = form.elements.quality_profile.value;
  const voiceLabel = form.elements.voice_preset?.selectedOptions?.[0]?.textContent?.split("·")[0]?.trim() || "Vivi 2.0";
  const profileLabels = { production: "生产高质量", local_privacy: "本地隐私", fast_preview: "快速预览" };
  $("#asset-summary").textContent = files.length
    ? `已选择 ${files.length} 个文件 · ${files.map((file) => file.name).join("、")}`
    : "至少选择一个视频；素材只复制到本地任务目录。";
  $("#creation-preflight").innerHTML = [
    contentType,
    files.length ? `${files.length} 份素材` : "等待素材",
    voiceLabel,
    profileLabels[profile] || profile,
  ].map((item) => `<span>${escapeHtml(item)}</span>`).join("");
}

function bindCreationControls() {
  const form = $("#task-form");
  if (!form) return;
  document.querySelectorAll(".preset-chip").forEach((button) => {
    button.addEventListener("click", () => {
      form.elements.content_type.value = button.dataset.contentType;
      document.querySelectorAll(".preset-chip").forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      updateCreationPreflight();
    });
  });
  form.elements.files.addEventListener("change", updateCreationPreflight);
  form.elements.quality_profile.addEventListener("change", updateCreationPreflight);
  form.elements.voice_preset.addEventListener("change", updateCreationPreflight);
  updateCreationPreflight();
}

async function loadIntegrations() {
  const integrations = await api("/api/integrations/status");
  const names = {
    dify: "Dify 分析",
    dingtalk: "钉钉素材",
    douyin: "抖音热点",
    asr: "生产级转写",
    reference_intelligence: "参考片分析",
  };
  $("#integration-list").innerHTML = Object.entries(integrations).map(([key, item]) => {
    const ok = item.status === "configured";
    const label = ok ? "已配置" : item.status === "partially_configured" ? "部分配置" : "待配置";
    return `<div class="integration"><span class="status-dot ${ok ? "ok" : "warn"}"></span><strong>${names[key] || escapeHtml(key)}</strong><small>${label}</small></div>`;
  }).join("");
  $("#last-refresh").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
}

async function loadSetupProgress() {
  const setup = await api("/api/setup/status");
  const node = $("#setup-progress");
  const configured = setup.progress?.configured_optional || 0;
  const total = setup.progress?.optional_total || 0;
  node.querySelector("span").textContent = setup.local_mode?.ready
    ? `本地已就绪 · ${configured}/${total} 项增强`
    : "本机环境需要处理";
}

async function loadLocalRuntime() {
  const runtime = await api("/api/local-runtime");
  const jianying = runtime.jianying || {};
  const draftState = jianying.draft_root
    ? "草稿目录已发现"
    : jianying.installed
      ? "首次交付时选择一次草稿目录"
      : "未发现剪映，可先完成本地创作";
  const items = [
    ["本机平台", `${runtime.platform} · ${runtime.architecture}`, true],
    ["本地数据", runtime.runtime?.data_dir || "自动创建", true],
    ["剪映交付", draftState, Boolean(jianying.draft_root)],
  ];
  $("#local-runtime-status").innerHTML = items.map(([name, detail, ok]) => (
    `<div class="integration"><span class="status-dot ${ok ? "ok" : "warn"}"></span><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small></div>`
  )).join("");
}

function formatNumber(value, maximumFractionDigits = 0) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits }).format(value);
}

function localBudgetCard(title, metric, unit) {
  const remaining = metric?.remaining;
  const value = remaining === null || remaining === undefined ? formatNumber(metric?.used, 1) : formatNumber(remaining, 1);
  const label = remaining === null || remaining === undefined ? `已用 ${unit}` : `剩余 ${unit}`;
  return `<article class="usage-card level-${escapeHtml(metric?.level || "unknown")}">
    <div><span class="source-badge local">本地计量</span><h3>${escapeHtml(title)}</h3></div>
    <strong>${value}</strong><p>${label}${metric?.remaining_percent === null || metric?.remaining_percent === undefined ? " · 尚未设置总额度" : ` · ${formatNumber(metric.remaining_percent, 1)}%`}</p>
  </article>`;
}

function officialBadge(section) {
  if (!section?.available) return "官方不可读";
  return section.stale ? "官方缓存" : "官方接口";
}

function officialUnavailable(section) {
  const reason = section?.error ? ` · ${escapeHtml(section.error)}` : "";
  return `<strong>未知</strong><p>当前凭证暂不可读${reason}</p>`;
}

async function loadCloudUsage() {
  const usage = await api("/api/cloud-usage/summary");
  const cards = [];
  if (!usage.configured) {
    cards.push(`<article class="usage-card setup"><span class="source-badge">待配置</span><h3>火山引擎只读查询</h3><strong>尚未连接</strong><p><a href="/settings/cloud-usage">填写 AK/SK 并验证权限</a></p></article>`);
  } else {
    cards.push(`<article class="usage-card">
      <div><span class="source-badge official">${officialBadge(usage.balance)}</span><h3>账户可用余额</h3></div>
      ${usage.balance?.available ? `<strong>¥${formatNumber(usage.balance.available_balance, 2)}</strong><p>现金 ¥${formatNumber(usage.balance.cash_balance, 2)} · 信控 ${usage.balance.credit_limit === null || usage.balance.credit_limit === undefined ? "未知" : `¥${formatNumber(usage.balance.credit_limit, 2)}`}</p>` : officialUnavailable(usage.balance)}
    </article>`);
    cards.push(`<article class="usage-card">
      <div><span class="source-badge official">${officialBadge(usage.ark_entitlements)}</span><h3>方舟免费额度</h3></div>
      ${usage.ark_entitlements?.available
        ? `<strong>${usage.ark_entitlements.models_with_initial_free_usage > 0 || usage.ark_entitlements.resource_pack_count > 0 ? formatNumber(usage.ark_entitlements.total_remaining_tokens) : "未发现"}</strong><p>跨模型合计 · 初始 ${formatNumber(usage.ark_entitlements.initial_remaining_tokens)} · 资源包 ${formatNumber(usage.ark_entitlements.resource_pack_remaining_tokens)}</p>`
        : officialUnavailable(usage.ark_entitlements)}
    </article>`);
    cards.push(`<article class="usage-card">
      <div><span class="source-badge official">${officialBadge(usage.resource_packages)}</span><h3>有效资源包</h3></div>
      ${usage.resource_packages?.available
        ? `<strong>${formatNumber(usage.resource_packages.count)}</strong><p>${usage.resource_packages.count ? `${escapeHtml(usage.resource_packages.items?.[0]?.product_name || "资源包")} · 剩余 ${formatNumber(usage.resource_packages.items?.[0]?.available_amount, 1)} ${escapeHtml(usage.resource_packages.items?.[0]?.unit || "")}` : "未发现有效资源包"}</p>`
        : officialUnavailable(usage.resource_packages)}
    </article>`);
    cards.push(`<article class="usage-card">
      <div><span class="source-badge official">${officialBadge(usage.coupons)}</span><h3>代金券余额</h3></div>
      ${usage.coupons?.available
        ? `<strong>¥${formatNumber(usage.coupons.total_remaining_amount, 2)}</strong><p>${formatNumber(usage.coupons.count)} 张代金券</p>`
        : officialUnavailable(usage.coupons)}
    </article>`);
    cards.push(`<article class="usage-card">
      <div><span class="source-badge official">${officialBadge(usage.ark_usage)}</span><h3>方舟推理活动</h3></div>
      ${usage.ark_usage?.available
        ? `<strong>${usage.ark_usage.total_tokens === null || usage.ark_usage.total_tokens === undefined ? (usage.ark_usage.data_count ? `${formatNumber(usage.ark_usage.data_count)} 条记录` : "未返回记录") : formatNumber(usage.ark_usage.total_tokens)}</strong><p>${usage.ark_usage.total_tokens === null || usage.ark_usage.total_tokens === undefined ? "官方未返回 Token 明细" : `输入 ${formatNumber(usage.ark_usage.input_tokens)} · 输出 ${formatNumber(usage.ark_usage.output_tokens)}`}</p>`
        : officialUnavailable(usage.ark_usage)}
    </article>`);
  }
  cards.push(localBudgetCard("语音识别 ASR", usage.local?.asr, "秒"));
  cards.push(localBudgetCard("语音合成 TTS", usage.local?.tts, "字符"));
  cards.push(`<article class="usage-card"><span class="source-badge local">本地计量</span><h3>Dify 工作流</h3><strong>${formatNumber(usage.local?.tokens)}</strong><p>Token · 未应用调用 ${formatNumber(usage.local?.unapplied_calls)}</p></article>`);
  $("#cloud-usage-cards").innerHTML = cards.join("");
}

async function loadSchedule() {
  const schedule = await api("/api/automations/daily");
  const form = $("#schedule-form");
  form.elements.enabled.checked = schedule.enabled;
  form.elements.hour.value = schedule.hour;
  form.elements.minute.value = schedule.minute;
  form.elements.timezone.value = schedule.timezone;
  form.elements.keywords.value = schedule.keywords.join("\n");
}

async function loadTasks() {
  const response = await api(`/api/tasks?limit=100&include_archived=${showingArchivedTasks}`);
  const tasks = showingArchivedTasks ? response.filter((task) => task.archived_at) : response;
  const list = $("#task-list");
  if (!tasks.length) {
    list.innerHTML = `<tr><td colspan="6" class="empty-state">${showingArchivedTasks ? "还没有归档任务。" : "队列还没有任务。上传第一段素材，或从钉钉发送文件。"}</td></tr>`;
    return;
  }
  list.innerHTML = tasks.map((task) => {
    const source = task.source_type === "dingtalk" ? "钉钉" : task.source_type || "本地上传";
    const processAction = task.status === "received" || task.status === "changes_requested"
      ? `<button class="button quiet process-task" data-task-id="${escapeHtml(task.id)}" type="button">开始处理</button>` : "";
    const reviewAction = ["reviewing", "approved", "changes_requested"].includes(task.status)
      ? `<a href="/review/${encodeURIComponent(task.id)}">打开审核</a>` : "";
    const archiveAction = task.archived_at
      ? `<button class="button quiet restore-task" data-task-id="${escapeHtml(task.id)}" type="button">恢复</button>`
      : `<button class="button quiet archive-task" data-task-id="${escapeHtml(task.id)}" type="button">归档</button>`;
    const profileLabels = { production: "生产高质量", local_privacy: "本地隐私", fast_preview: "快速预览" };
    return `<tr>
      <td><div class="task-name"><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.content_type)} · ${task.materials.length} 个文件 · ${profileLabels[task.quality_profile] || escapeHtml(task.quality_profile)}</small></div></td>
      <td>${escapeHtml(source)}</td>
      <td>${task.rights_confirmed ? "已确认" : "待确认"}</td>
      <td><span class="status-pill ${escapeHtml(task.status)}">${statusLabels[task.status] || escapeHtml(task.status)}</span></td>
      <td><time datetime="${escapeHtml(task.updated_at)}">${formatTime(task.updated_at)}</time></td>
      <td><div class="row-actions">${processAction}${reviewAction}${archiveAction}</div></td>
    </tr>`;
  }).join("");
  document.querySelectorAll(".process-task").forEach((button) => button.addEventListener("click", () => processTask(button)));
  document.querySelectorAll(".archive-task").forEach((button) => button.addEventListener("click", () => archiveTask(button)));
  document.querySelectorAll(".restore-task").forEach((button) => button.addEventListener("click", () => restoreTask(button)));
}

async function archiveTask(button) {
  button.disabled = true;
  try {
    await api(`/api/tasks/${button.dataset.taskId}/archive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "manual" }),
    });
    await loadTasks();
    toast("任务已归档，可随时恢复");
  } catch (error) {
    toast(error.message);
    button.disabled = false;
  }
}

async function restoreTask(button) {
  button.disabled = true;
  try {
    await api(`/api/tasks/${button.dataset.taskId}/restore`, { method: "POST" });
    await loadTasks();
    toast("任务已恢复到队列");
  } catch (error) {
    toast(error.message);
    button.disabled = false;
  }
}

async function processTask(button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "处理中…";
  try {
    const task = await api(`/api/tasks/${button.dataset.taskId}/process`, { method: "POST" });
    toast("预览与剪映草稿已生成，等待人工审核");
    window.location.href = `/review/${task.id}`;
  } catch (error) {
    toast(error.message);
    button.disabled = false;
    button.textContent = original;
  }
}

async function loadTrends() {
  const trends = await api("/api/trends?limit=8");
  const list = $("#trend-list");
  if (!trends.length) {
    list.innerHTML = '<div class="empty-state">热点库还是空的。配置抖音开放平台搜索，或通过 API 导入公开记录。</div>';
    return;
  }
  list.innerHTML = trends.map((trend) => `<article class="evidence-item">
    <div><h3><a href="${safeExternalUrl(trend.url)}" target="_blank" rel="noreferrer">${escapeHtml(trend.title)}</a></h3><p>${escapeHtml(trend.keyword)} · ${escapeHtml(trend.author || "未知作者")} · 抓取于 ${formatTime(trend.captured_at)}</p></div>
    <div class="evidence-metric">${new Intl.NumberFormat("zh-CN").format(trend.digg_count)} 赞</div>
  </article>`).join("");
}

async function loadRuns() {
  const runs = await api("/api/automations/runs?limit=1");
  if (!runs.length) return;
  const run = runs[0];
  const materialLabel = run.material_status === "pexels_official" ? "Pexels 官方" : run.material_status === "local_catalog" ? "本地授权目录" : "未匹配素材";
  const taskLinks = (run.created_task_ids || []).map((id) => `<a href="/review/${encodeURIComponent(id)}">查看新成片</a>`).join(" · ");
  $("#latest-run").innerHTML = `<div class="run-metrics"><strong>${run.status === "completed" ? "运行完成" : "完成但有警告"}</strong><span>${formatTime(run.started_at)}</span><span>热点 ${run.trend_records} · 素材 ${run.sourced_assets}（${materialLabel}）· 新建 ${run.created_task_ids?.length || 0} · 处理 ${run.processed_tasks} · 失败 ${run.failed_tasks}</span>${taskLinks ? `<span>${taskLinks}</span>` : ""}</div>`;
}

async function loadWorkbench() {
  const results = await Promise.allSettled([loadIntegrations(), loadSetupProgress(), loadLocalRuntime(), loadCloudUsage(), loadSchedule(), loadTasks(), loadTrends(), loadRuns()]);
  const failed = results.filter((result) => result.status === "rejected");
  if (failed.length) toast(`有 ${failed.length} 项数据读取失败，请刷新重试`);
}

$("#task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const status = $("#task-form-status");
  button.disabled = true;
  status.textContent = "正在保存素材…";
  const data = new FormData(form);
  if (!form.elements.rights_confirmed.checked) data.set("rights_confirmed", "false");
  if (!form.elements.cloud_processing_allowed.checked) data.set("cloud_processing_allowed", "false");
  try {
    const task = await api("/api/tasks", { method: "POST", body: data });
    status.textContent = `已创建：${task.title}`;
    form.reset();
    const defaultPreset = document.querySelector('.preset-chip[data-content-type="通用短视频"]');
    if (defaultPreset) defaultPreset.click();
    updateCreationPreflight();
    await loadTasks();
    toast("任务已进入队列");
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("#schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api("/api/automations/daily", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: form.elements.enabled.checked,
        hour: Number(form.elements.hour.value),
        minute: Number(form.elements.minute.value),
        timezone: form.elements.timezone.value.trim(),
        keywords: form.elements.keywords.value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean),
      }),
    });
    $("#schedule-status").textContent = "设置已保存";
    toast("每日自动化设置已更新");
  } catch (error) {
    $("#schedule-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("#run-daily").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "正在运行…";
  try {
    const run = await api("/api/automations/daily/run", { method: "POST" });
    toast(`流程完成：获取 ${run.sourced_assets} 条素材，新建 ${run.created_task_ids?.length || 0} 个任务，处理 ${run.processed_tasks} 个任务`);
    await Promise.all([loadRuns(), loadTasks(), loadTrends()]);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "立即运行每日流程";
  }
});

$("#refresh").addEventListener("click", loadWorkbench);
$("#show-archived").addEventListener("click", async (event) => {
  showingArchivedTasks = !showingArchivedTasks;
  event.currentTarget.setAttribute("aria-pressed", String(showingArchivedTasks));
  event.currentTarget.textContent = showingArchivedTasks ? "返回任务队列" : "查看归档";
  await loadTasks();
});
$("#refresh-cloud-usage").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api("/api/cloud-usage/refresh", { method: "POST" });
    await loadCloudUsage();
    toast("云端余量已刷新");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});
bindCreationControls();
loadWorkbench();
