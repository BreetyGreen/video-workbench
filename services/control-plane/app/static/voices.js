const voiceState = { voices: [], filter: "all" };
const voiceGrid = document.querySelector("#voice-grid");
const voiceStatus = document.querySelector("#voice-status");

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = String(value ?? "");
  return span.innerHTML;
}

async function voiceApi(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    const code = payload?.detail?.code || `HTTP ${response.status}`;
    throw new Error(code);
  }
  return response.json();
}

function matchesFilter(voice) {
  return voiceState.filter === "all" || voice.use_cases.includes(voiceState.filter);
}

function renderVoices() {
  const rows = voiceState.voices.filter(matchesFilter);
  voiceGrid.innerHTML = "";
  const template = document.querySelector("#voice-card-template");
  rows.forEach((voice) => {
    const card = template.content.firstElementChild.cloneNode(true);
    card.dataset.useCases = voice.use_cases.join("|");
    card.querySelector(".voice-kicker").textContent = voice.use_cases.slice(0, 2).join(" / ");
    card.querySelector("h2").textContent = voice.name;
    card.querySelector(".voice-description").textContent = voice.description;
    const availability = card.querySelector(".availability");
    availability.textContent = voice.availability === "configured_default" ? "当前默认" : "试听后验证";
    availability.classList.toggle("verified", voice.availability === "configured_default");
    card.querySelector(".voice-tags").innerHTML = voice.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
    const textarea = card.querySelector("textarea");
    textarea.value = voice.preview_text;
    const source = card.querySelector(".source-link");
    source.href = voice.source_url;
    const button = card.querySelector(".preview-button");
    const audio = card.querySelector("audio");
    const status = card.querySelector(".card-status");
    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "正在生成，首次试听会记入 TTS 字符用量…";
      try {
        const result = await voiceApi(`/api/voices/${encodeURIComponent(voice.preset_id)}/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: textarea.value.trim() }),
        });
        audio.src = `${result.audio_url}?v=${Date.now()}`;
        audio.hidden = false;
        await audio.play().catch(() => {});
        availability.textContent = "已试听验证";
        availability.classList.add("verified");
        status.textContent = result.cached
          ? "已从本地缓存读取，未重复调用。"
          : `已生成 · 本次记入 ${result.character_count} 字符。`;
      } catch (error) {
        const labels = { tts_not_configured: "尚未配置火山 TTS API Key。", voice_preview_failed: "当前账号未授权该音色，或云端调用失败。" };
        status.textContent = labels[error.message] || `试听失败：${error.message}`;
      } finally {
        button.disabled = false;
      }
    });
    voiceGrid.appendChild(card);
  });
  voiceStatus.textContent = `显示 ${rows.length} / ${voiceState.voices.length} 个官方音色`;
}

document.querySelectorAll(".filter-chip").forEach((button) => {
  button.addEventListener("click", () => {
    voiceState.filter = button.dataset.filter;
    document.querySelectorAll(".filter-chip").forEach((item) => item.classList.toggle("active", item === button));
    renderVoices();
  });
});

voiceApi("/api/voices")
  .then((payload) => { voiceState.voices = payload.voices; renderVoices(); })
  .catch((error) => { voiceStatus.textContent = `读取失败：${error.message}`; voiceGrid.innerHTML = ""; });
