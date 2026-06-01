/** paper-reviewer local dashboard client */

const $ = (id) => document.getElementById(id);

let pollTimer = null;
let currentJobId = null;
let defaultsCache = null;

function currentRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  return ["home", "run", "config", "logs"].includes(raw) ? raw : "home";
}

function showRoute(routeName = currentRoute()) {
  document.querySelectorAll(".route").forEach((route) => {
    route.classList.remove("active");
    route.hidden = true;
  });
  const route = $(`route-${routeName}`);
  if (route) {
    route.hidden = false;
    route.classList.add("active");
  }

  $("statusStrip").classList.toggle("visible", routeName === "run");

  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === routeName);
  });

  if (routeName === "logs") loadLogListPage();
  if (routeName === "config" && !$("configEditor").value) loadConfig();
}

function setupHeroTextEffect() {
  const target = $("heroKeyword");
  if (!target) return;
  const words = (target.dataset.words || "").split(",").filter(Boolean);
  if (!words.length) return;
  let index = 0;
  const glyphs = "01<>/{}[]#$%";

  setInterval(() => {
    index = (index + 1) % words.length;
    const next = words[index];
    let frame = 0;
    const timer = setInterval(() => {
      const revealed = next.slice(0, frame);
      const scrambled = next
        .slice(frame)
        .split("")
        .map(() => glyphs[Math.floor(Math.random() * glyphs.length)])
        .join("");
      target.textContent = revealed + scrambled;
      frame += 1;
      if (frame > next.length) {
        target.textContent = next;
        clearInterval(timer);
      }
    }, 45);
  }, 2200);
}

function setupMagneticButtons() {
  document.querySelectorAll(".magnetic").forEach((button) => {
    button.addEventListener("pointermove", (event) => {
      const rect = button.getBoundingClientRect();
      const x = event.clientX - rect.left - rect.width / 2;
      const y = event.clientY - rect.top - rect.height / 2;
      button.style.transform = `translate(${x * 0.08}px, ${y * 0.12}px)`;
    });
    button.addEventListener("pointerleave", () => {
      button.style.transform = "";
    });
  });
}

function highlightLog(text) {
  if (!text) return "—";
  return text
    .split("\n")
    .map((line) => {
      let cls = "";
      if (/ERROR|DEGRADED|failed/i.test(line)) cls = "line-error";
      else if (/WARNING|WARN/i.test(line)) cls = "line-warn";
      else if (/accepted|glossary merge|run complete/i.test(line)) cls = "line-ok";
      const esc = line
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return cls ? `<span class="${cls}">${esc}</span>` : esc;
    })
    .join("\n");
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || res.statusText || "Request failed");
  }
  return data;
}

function payloadFromForm() {
  return {
    input_path: $("inputPath").value.trim(),
    output_path: $("outputPath").value.trim(),
    config_path: $("configPath").value.trim(),
    mode: $("mode").value,
    max_iterations: parseInt($("maxIterations").value, 10) || 1,
    max_no_improve: parseInt($("maxNoImprove").value, 10) || 100,
    log_level: $("logLevel").value,
    post_proofread: $("postProofread").checked,
    allow_llm_failures: $("allowFailures").checked,
    demo: $("demoMode").checked,
  };
}

function setRunning(running) {
  $("btnRun").disabled = running;
  $("btnStop").disabled = !running;
  const pill = $("statusPill");
  if (running) {
    pill.textContent = "运行中";
    pill.className = "pill pill-running";
  }
}

function setStatusFromJob(st) {
  const pill = $("statusPill");
  if (st.running) {
    pill.textContent = "运行中";
    pill.className = "pill pill-running";
    $("elapsedMeta").textContent = `${st.elapsed_s}s`;
    $("exitMeta").textContent = "";
  } else if (st.job_id) {
    const ok = st.exit_code === 0;
    pill.textContent = ok ? "完成" : "结束";
    pill.className = ok ? "pill pill-done" : "pill pill-fail";
    $("elapsedMeta").textContent = `${st.elapsed_s}s`;
    $("exitMeta").textContent =
      st.exit_code != null ? `退出码 ${st.exit_code}` : "";
    $("btnRun").disabled = false;
    $("btnStop").disabled = true;
  }
  if (st.log_file) {
    $("logFileMeta").textContent = st.log_file.split(/[/\\]/).pop();
  }
  $("logView").innerHTML = highlightLog(st.log_tail || "");
  $("logView").scrollTop = $("logView").scrollHeight;
}

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const st = await api(`/api/status/${currentJobId}`);
    setStatusFromJob(st);
    if (!st.running) {
      clearInterval(pollTimer);
      pollTimer = null;
      if (st.output_exists) await refreshOutput();
      await refreshGlossary();
      await loadLogList();
    }
  } catch (e) {
    console.warn(e);
  }
}

async function startRun() {
  try {
    const body = payloadFromForm();
    const { job_id } = await api("/api/run", {
      method: "POST",
      body: JSON.stringify(body),
    });
    currentJobId = job_id;
    setRunning(true);
    $("logView").textContent = "任务已启动…";
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 1500);
    await pollStatus();
  } catch (e) {
    alert(e.message);
    setRunning(false);
  }
}

async function stopRun() {
  if (!currentJobId) return;
  try {
    await api(`/api/stop/${currentJobId}`, { method: "POST" });
    await pollStatus();
  } catch (e) {
    alert(e.message);
  }
}

async function refreshOutput() {
  const path = $("outputPath").value.trim();
  if (!path) return;
  try {
    const data = await api(`/api/output?path=${encodeURIComponent(path)}`);
    let head = `# ${data.path} (${data.size} bytes)`;
    if (data.truncated) head += "\n# preview truncated\n";
    $("outputView").textContent = `${head}\n\n${data.content}`;
  } catch (e) {
    $("outputView").textContent = e.message;
  }
}

async function refreshGlossary() {
  try {
    const data = await api("/api/glossary");
    $("glossaryView").textContent = data.content;
  } catch (e) {
    $("glossaryView").textContent = e.message;
  }
}

async function loadLogList() {
  try {
    const { logs } = await api("/api/logs");
    const ul = $("logList");
    ul.innerHTML = "";
    logs.forEach((item) => {
      const li = document.createElement("li");
      const d = new Date(item.mtime * 1000);
      li.textContent = `${item.name} · ${(item.size / 1024).toFixed(1)} KB · ${d.toLocaleString()}`;
      li.addEventListener("click", async () => {
        const log = await api(`/api/log?path=${encodeURIComponent(item.path)}`);
        $("logView").innerHTML = highlightLog(log.content);
        $("logFileMeta").textContent = item.name;
      });
      ul.appendChild(li);
    });
  } catch (e) {
    $("logList").innerHTML = `<li>${e.message}</li>`;
  }
}

async function loadLogListPage() {
  try {
    const { logs } = await api("/api/logs");
    const ul = $("logListPage");
    ul.innerHTML = "";
    logs.forEach((item) => {
      const li = document.createElement("li");
      const d = new Date(item.mtime * 1000);
      li.textContent = `${item.name} · ${(item.size / 1024).toFixed(1)} KB · ${d.toLocaleString()}`;
      li.addEventListener("click", async () => {
        const log = await api(`/api/log?path=${encodeURIComponent(item.path)}`);
        $("logPageView").innerHTML = highlightLog(log.content);
      });
      ul.appendChild(li);
    });
    if (!logs.length) ul.innerHTML = "<li>暂无日志</li>";
  } catch (e) {
    $("logListPage").innerHTML = `<li>${e.message}</li>`;
  }
}

async function loadConfig(path = $("configEditPath").value.trim()) {
  if (!path) return;
  $("configSaveMeta").textContent = "读取中…";
  try {
    const data = await api(`/api/config?path=${encodeURIComponent(path)}`);
    $("configEditPath").value = data.path;
    $("configEditor").value = data.content;
    $("configSaveMeta").textContent = "已读取";
  } catch (e) {
    $("configSaveMeta").textContent = e.message;
  }
}

async function saveConfig() {
  const path = $("configEditPath").value.trim();
  const content = $("configEditor").value;
  if (!path) return;
  $("configSaveMeta").textContent = "保存中…";
  try {
    const data = await api("/api/config", {
      method: "PUT",
      body: JSON.stringify({ path, content }),
    });
    $("configEditPath").value = data.path;
    $("configSaveMeta").textContent = `已保存 (${data.bytes} bytes)`;
  } catch (e) {
    $("configSaveMeta").textContent = e.message;
  }
}

async function loadDefaults() {
  const d = await api("/api/defaults");
  defaultsCache = d;
  $("version").textContent = `v${d.version}`;
  if (!$("inputPath").value) $("inputPath").value = d.sample_input;
  if (!$("outputPath").value) $("outputPath").value = d.default_output;
  if (!$("configPath").value) {
    $("configPath").value = d.has_private_config
      ? d.private_config
      : d.has_config_local
        ? d.default_config
        : "config/local.example.yaml";
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $(`pane-${name}`).classList.add("active");
    });
  });
}

$("btnRun").addEventListener("click", startRun);
$("btnStop").addEventListener("click", stopRun);
$("btnRefreshOutput").addEventListener("click", refreshOutput);
$("btnRefreshGlossary").addEventListener("click", refreshGlossary);
$("btnLoadPrivate").addEventListener("click", () => {
  $("configPath").value = "private/run_config.yaml";
});
$("btnLoadConfig").addEventListener("click", () => loadConfig());
$("btnSaveConfig").addEventListener("click", saveConfig);
$("btnRefreshLogsPage").addEventListener("click", loadLogListPage);
$("quickMockRun").addEventListener("click", () => {
  $("demoMode").checked = true;
  $("inputPath").value = "sample_manuscript.tex";
  $("outputPath").value = "output.tex";
  $("configPath").value = "config/local.example.yaml";
});
document.querySelectorAll(".config-preset").forEach((button) => {
  button.addEventListener("click", () => {
    $("configEditPath").value = button.dataset.path;
    loadConfig(button.dataset.path);
  });
});

setupTabs();
setupHeroTextEffect();
setupMagneticButtons();
window.addEventListener("hashchange", () => showRoute());
loadDefaults()
  .then(() => {
    showRoute();
  })
  .catch((e) => {
    $("version").textContent = "offline?";
    console.error(e);
    showRoute();
  });
