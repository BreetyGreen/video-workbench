const statusNode = document.querySelector("#material-status");
const grid = document.querySelector("#material-grid");
const template = document.querySelector("#material-card-template");

function labelProvider(provider) {
  if (provider === "pexels") return "PEXELS 官方";
  if (provider === "pixabay") return "PIXABAY 官方";
  if (provider === "merchant_authorized") return "商家授权";
  return "本地授权";
}

function renderAssets(assets) {
  grid.replaceChildren();
  document.querySelector("#catalog-count").textContent = `${assets.length} 条可用`;
  for (const asset of assets) {
    const card = template.content.firstElementChild.cloneNode(true);
    const video = card.querySelector("video");
    video.src = asset.file_url;
    video.addEventListener("pointerenter", () => video.play().catch(() => {}));
    video.addEventListener("pointerleave", () => { video.pause(); video.currentTime = 0; });
    card.querySelector(".provider").textContent = labelProvider(asset.provider);
    card.querySelector(".usage").textContent = `已使用 ${asset.use_count} 次`;
    card.querySelector("h3").textContent = asset.original_name;
    card.querySelector(".rights").textContent = asset.rights_basis === "pexels_license" ? "依据 Pexels License 使用" : "用户已确认拥有使用权";
    card.querySelector(".attribution").textContent = asset.attribution || "来源记录完整";
    const source = card.querySelector(".source-link");
    source.href = asset.source_url || asset.creator_url || "#";
    source.hidden = !asset.source_url && !asset.creator_url;
    const license = card.querySelector(".license-link");
    license.href = asset.license_url || "#";
    license.hidden = !asset.license_url;
    grid.append(card);
  }
  if (!assets.length) grid.innerHTML = '<p class="empty-state">暂无匹配素材。先同步已确认素材，或配置 Pexels API Key。</p>';
}

async function loadStatus() {
  const response = await fetch("/api/materials/status");
  const data = await response.json();
  document.querySelector("#material-total").textContent = data.total;
  document.querySelector("#pexels-state").textContent = data.pexels.status === "configured" ? "已连接" : "本地回退";
}

async function loadAssets(query = "") {
  const response = await fetch(`/api/materials?query=${encodeURIComponent(query)}`);
  const data = await response.json();
  renderAssets(data.assets);
  statusNode.textContent = data.assets.length ? "素材目录已就绪。" : "还没有匹配素材。";
}

document.querySelector("#material-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = document.querySelector("#material-query").value.trim();
  statusNode.textContent = "正在获取并登记授权素材…";
  const response = await fetch("/api/materials/acquire", { headers: { "content-type": "application/json" }, method: "POST", body: JSON.stringify({ query, count: 6 }) });
  const data = await response.json();
  if (!response.ok) { statusNode.textContent = "获取失败，请检查连接配置。"; return; }
  renderAssets(data.assets);
  statusNode.textContent = data.status === "pexels_official" ? `已从 Pexels 官方 API 获取 ${data.count} 条素材。` : `已从本地授权目录匹配 ${data.count} 条素材。`;
  await loadStatus();
});

document.querySelector("#reindex-button").addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  statusNode.textContent = "正在同步任务中已确认版权的素材…";
  const response = await fetch("/api/materials/reindex", { method: "POST" });
  const data = await response.json();
  statusNode.textContent = `新增 ${data.imported} 条，跳过 ${data.skipped_duplicates} 条重复素材。`;
  event.currentTarget.disabled = false;
  await Promise.all([loadStatus(), loadAssets(document.querySelector("#material-query").value.trim())]);
});

document.querySelector("#authorized-video-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  statusNode.textContent = "正在校验授权信息并登记视频…";
  const data = new FormData(form);
  if (!data.get("rights_expires_at")) data.delete("rights_expires_at");
  try {
    const response = await fetch("/api/materials/authorized-video", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail?.code || "登记失败");
    statusNode.textContent = `已登记：${payload.original_name}`;
    form.reset();
    form.elements.allowed_platforms.value = "douyin,xiaohongshu";
    await Promise.all([loadStatus(), loadAssets()]);
  } catch (error) {
    statusNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

Promise.all([loadStatus(), loadAssets()]).catch(() => { statusNode.textContent = "素材目录暂时无法读取。"; });
