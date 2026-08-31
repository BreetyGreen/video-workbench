const reviewMain = document.querySelector(".review-main");
const reviewVideo = document.querySelector("#review-video");

document.querySelectorAll("[data-seek-seconds], [data-timeline-start]").forEach((control) => {
  control.addEventListener("click", () => {
    if (!reviewVideo) return;
    const value = control.dataset.seekSeconds ?? control.dataset.timelineStart;
    reviewVideo.currentTime = Math.max(0, Number(value) || 0);
    reviewVideo.play().catch(() => {});
    reviewVideo.scrollIntoView({behavior: "smooth", block: "center"});
  });
});

document.querySelectorAll("[data-decision]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    const response = await fetch(`/api/tasks/${encodeURIComponent(reviewMain.dataset.taskId)}/review`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({decision: button.dataset.decision, comment: document.querySelector("#comment").value}),
    });
    const payload = await response.json();
    document.querySelector("#result").textContent = response.ok ? `已更新：${payload.status}` : `操作失败：${JSON.stringify(payload.detail)}`;
    if (response.ok) window.setTimeout(() => window.location.reload(), 700);
    else button.disabled = false;
  });
});

const deliverButton = document.querySelector("#deliver-douyin");
if (deliverButton) {
  deliverButton.addEventListener("click", async () => {
    deliverButton.disabled = true;
    const result = document.querySelector("#delivery-result");
    result.textContent = "正在上传并创建抖音视频…";
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(reviewMain.dataset.taskId)}/deliver/douyin`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: document.querySelector("#douyin-title").value,
          visibility: document.querySelector("#douyin-visibility").value,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.code || "douyin_delivery_failed");
      result.textContent = `已交付：${payload.delivery_state} · ${payload.delivery_provider_id || "等待平台回执"}`;
    } catch (error) {
      result.textContent = error.message === "douyin_oauth_required"
        ? "需要先在抖音开放平台完成应用权限与用户 OAuth。"
        : `交付失败：${error.message}`;
      deliverButton.disabled = false;
    }
  });
}

const jianyingButton = document.querySelector("#jianying-handoff");
if (jianyingButton) {
  jianyingButton.addEventListener("click", async () => {
    const result = document.querySelector("#jianying-result");
    jianyingButton.disabled = true;
    result.textContent = "正在安全导入草稿并唤起剪映…";
    try {
      const response = await fetch(jianyingButton.dataset.endpoint, {method: "POST"});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.code || "jianying_handoff_failed");
      if (payload.status === "waiting") {
        result.textContent = "尚未检测到可写的剪映草稿目录，请保持本机启动器运行。";
      } else {
        result.textContent = payload.idempotent ? "草稿已存在，正在打开剪映。" : "草稿已导入，正在打开剪映。";
        jianyingButton.textContent = "再次打开剪映";
      }
    } catch (error) {
      result.textContent = `导入失败：${error.message}`;
    } finally {
      jianyingButton.disabled = false;
    }
  });
}
