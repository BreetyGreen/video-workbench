const results = document.querySelector("#trend-results");

function escapeHtml(value) { const span = document.createElement("span"); span.textContent = String(value ?? ""); return span.innerHTML; }
function formatCount(value) { return new Intl.NumberFormat("zh-CN", { notation: Number(value) >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(Number(value) || 0); }
function sourceLabel(source) { return source === "douyin_official_search" ? "抖音官方" : source === "xiaohongshu_evidence" ? "小红书证据" : source; }

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) { let payload = {}; try { payload = await response.json(); } catch (_) {} const error = new Error(payload?.detail?.code || `HTTP ${response.status}`); error.detail = payload?.detail || {}; throw error; }
  return response.json();
}

async function loadTrends() {
  const rows = await api("/api/trends?limit=100");
  if (!rows.length) { results.innerHTML = '<p class="empty-state">还没有证据。可以先用抖音官方搜索，或导入一条已核对的小红书公开链接。</p>'; return; }
  results.innerHTML = rows.map((item) => `<article class="trend-card">
    ${item.cover_url ? `<img class="trend-cover" src="${escapeHtml(item.cover_url)}" alt="" loading="lazy">` : '<div class="trend-cover"></div>'}
    <div class="trend-copy"><div class="trend-meta"><span>${escapeHtml(sourceLabel(item.source))}</span><span>${escapeHtml(item.keyword)}</span><span>${escapeHtml(item.author || "作者未记录")}</span></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.evidence)}</p></div>
    <div class="trend-score"><strong>${formatCount(item.digg_count)}</strong><span>公开热度</span><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">查看证据 ↗</a></div>
  </article>`).join("");
}

document.querySelector("#douyin-discovery-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget; const status = document.querySelector("#douyin-status"); const button = form.querySelector("button"); button.disabled = true; status.textContent = "正在通过抖音开放平台检索…";
  try { const payload = await api("/api/trends/discover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keyword: form.elements.keyword.value.trim(), count: Number(form.elements.count.value), publish_days: Number(form.elements.publish_days.value) }) }); status.textContent = `找到 ${payload.results.length} 条，新入库 ${payload.inserted} 条。`; await loadTrends(); }
  catch (error) { status.textContent = error.message === "douyin_not_configured" ? "抖音开放平台尚未配置，需要 Client Key、Client Secret 和 Device ID。" : `检索失败：${error.detail?.reason || error.message}`; }
  finally { button.disabled = false; }
});

document.querySelector("#xhs-import-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget; const status = document.querySelector("#xhs-status"); const button = form.querySelector("button"); button.disabled = true; status.textContent = "正在保存公开证据…";
  try { const body = Object.fromEntries(new FormData(form).entries()); body.engagement_count = Number(body.engagement_count || 0); const payload = await api("/api/trends/xiaohongshu/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); status.textContent = payload.inserted ? "已入库，可用于热点结构分析。" : "该链接已经收录。"; form.reset(); await loadTrends(); }
  catch (error) { status.textContent = error.message === "HTTP 422" ? "请检查是否为小红书 HTTPS 公开链接，且必填项已完整。" : `导入失败：${error.message}`; }
  finally { button.disabled = false; }
});

document.querySelector("#refresh-trends").addEventListener("click", loadTrends);
loadTrends().catch((error) => { results.innerHTML = `<p class="empty-state">读取失败：${escapeHtml(error.message)}</p>`; });
