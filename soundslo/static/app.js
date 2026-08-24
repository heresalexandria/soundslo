const MEDIUM_MODEL_ID = "stable-audio-3-medium";
const UPDATE_POLL_INTERVAL_MS = 6 * 60 * 60 * 1000;
if (window.location.protocol === "file:") {
  window.location.replace("http://127.0.0.1:8733/");
}
const FALLBACK_MODEL_NAMES = {
  "stable-audio-3-small-music": "Small Music",
  "stable-audio-3-medium": "Medium",
  "stable-audio-3-large-api": "Large API",
};

const state = {
  generations: [],
  models: [],
  modelData: null,
  selectedModelId: null,
  search: "",
  pollTimer: null,
  modelPollTimer: null,
  renameId: null,
  ready: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const list = $("#generation-list");
const emptyState = $("#empty-state");
const form = $("#generation-form");
const promptInput = $("#prompt");
const durationInput = $("#duration");
const durationMinutes = $("#duration-minutes");
const durationSeconds = $("#duration-seconds");

const promptIdeas = [
  "A widescreen 1960s science-fiction orchestral score, eerie strings, bold brass swells, theremin-like electronics, slow and ominous, instrumental",
  "1980s action movie chase score, pulsing analog synth bass, gated drums, distorted electric guitar, urgent and heroic, instrumental",
  "Nocturnal darkwave, icy drum machine, chorus-soaked bass guitar, haunted analog pads, hypnotic 105 BPM, instrumental",
  "Dusty spiritual jazz at midnight, modal upright bass, brushed drums, warm tenor saxophone, shimmering vibraphone, spacious tape sound, instrumental",
  "Minimalist chamber ensemble slowly building, interlocking marimba and piano patterns, low strings, tense but luminous, cinematic instrumental",
  "Retro-futurist documentary score, modular synthesizer sequences, gentle woodwinds, tape loops, curious and optimistic, instrumental",
];

async function api(path, options = {}) {
  const headers = { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

async function loadSystem({ quiet = false } = {}) {
  const pill = $("#system-pill");
  try {
    const [system, modelData] = await Promise.all([api("/api/system"), api("/api/models")]);
    state.modelData = modelData;
    state.models = modelData.models;
    chooseInitialModel();
    renderModelSettings();
    applySelectedModel(system);
    renderGenerations();
    scheduleModelPolling();
  } catch (error) {
    state.ready = false;
    pill.className = "system-pill error";
    $("#system-label").textContent = "Local service unavailable";
    if (!quiet) toast(error.message, true);
  }
}

function chooseInitialModel() {
  let saved = null;
  try {
    saved = window.localStorage.getItem("soundslo-model");
  } catch (_) {}
  const preferredId = state.selectedModelId || saved || MEDIUM_MODEL_ID;
  const preferred = modelById(preferredId);
  const fallback = modelById(MEDIUM_MODEL_ID) || state.models.find((model) => model.ready) || state.models[0];
  state.selectedModelId = preferred?.ready ? preferred.id : fallback?.id || preferredId;
}

function modelById(modelId) {
  return state.models.find((model) => model.id === modelId);
}

function selectedModel() {
  return modelById(state.selectedModelId) || modelById(MEDIUM_MODEL_ID) || state.models[0];
}

function selectModel(modelId) {
  const model = modelById(modelId);
  if (!model?.ready) {
    toast(`${model?.short_name || "That model"} is not ready yet.`, true);
    return;
  }
  state.selectedModelId = modelId;
  try {
    window.localStorage.setItem("soundslo-model", modelId);
  } catch (_) {}
  renderModelSettings();
  applySelectedModel();
}

function applySelectedModel(system = null) {
  const model = selectedModel();
  if (!model) return;
  const pill = $("#system-pill");
  state.ready = model.ready;
  pill.className = `system-pill ${model.ready ? "ready" : "error"}`;
  if (model.deployment === "cloud") {
    $("#system-label").textContent = model.ready
      ? `${model.short_name} ready · ${model.credits_per_generation} credits / generation`
      : "Large needs an API key · open Settings";
    $("#model-eyebrow").textContent = "STABLE AUDIO 3 LARGE · STABILITY CLOUD";
    $("#model-lede").textContent = "Highest-musicality generation through Stability AI's hosted API.";
    $("#privacy-note").innerHTML = `<span>↗</span> Prompt sent to Stability AI · ${model.credits_per_generation} credits`;
  } else {
    const freeDisk = state.modelData?.free_disk_bytes || system?.free_disk_bytes;
    const installation = model.installation || {};
    $("#system-label").textContent = model.ready
      ? `${model.short_name} ready · ${formatBytes(freeDisk)} free`
      : installation.state === "installing"
        ? `Downloading ${model.short_name} · ${Math.round(installation.progress || 0)}%`
        : installation.state === "failed"
          ? `${model.short_name} setup failed · open Settings`
          : `${model.short_name} not installed · open Settings`;
    if (installation.state === "installing" && window.soundsloDesktop) {
      $("#settings-panel").open = true;
    }
    $("#model-eyebrow").textContent = `STABLE AUDIO 3 ${model.short_name.toUpperCase()} · ON YOUR COMPUTER`;
    $("#model-lede").textContent = "Instrumental scores generated privately on your computer.";
    $("#privacy-note").innerHTML = "<span>⌁</span> Audio never leaves this computer";
  }
  pill.title = model.tradeoff;
  $("#settings-model-name").textContent = model.name;
  applyModelLimits(model);
}

function applyModelLimits(model) {
  const maximum = model.max_duration_seconds;
  durationInput.max = maximum;
  durationMinutes.max = Math.floor(maximum / 60);
  $("#duration-range-label").textContent = `1 second–${formatDuration(maximum)}`;
  $("#duration-note").textContent = `${model.short_name} supports exact lengths up to ${formatDuration(maximum)}.`;
  if (currentDuration() > maximum) setDuration(maximum);
  renderDurationPresets();

  const stepInput = $("#steps");
  stepInput.max = Math.min(model.max_steps, 16);
  if (Number(stepInput.value) > Number(stepInput.max)) stepInput.value = stepInput.max;

  const negative = $("#negative-prompt");
  negative.disabled = !model.supports_negative_prompt;
  $("#negative-field").classList.toggle("disabled", !model.supports_negative_prompt);
  $("#negative-prompt-note").textContent = model.supports_negative_prompt
    ? "Used when guidance is above 1. The default steers away from voices."
    : "The hosted Large API does not expose negative prompting. Put “instrumental, no vocals” in the main prompt.";
  $("#seed").min = model.deployment === "cloud" ? 1 : 0;
  $("#seed").max = model.deployment === "cloud" ? 4294967294 : 4294967295;
  updateControls();
}

function renderModelSettings() {
  const grid = $("#model-grid");
  grid.replaceChildren(...state.models.map(modelCard));
}

function modelCard(model) {
  const card = document.createElement("article");
  card.className = `model-card ${model.deployment} ${model.id === state.selectedModelId ? "selected" : ""}`;
  card.dataset.modelId = model.id;

  const header = document.createElement("div");
  header.className = "model-card-header";
  const title = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.textContent = `${model.deployment} · ${model.parameter_label} parameters`;
  const heading = document.createElement("h3");
  heading.textContent = model.name;
  title.append(eyebrow, heading);
  const badge = document.createElement("span");
  badge.className = `model-state ${model.ready ? "ready" : ""}`;
  badge.textContent = model.id === state.selectedModelId
    ? "Selected"
    : model.ready
      ? model.deployment === "local" ? "Installed" : "API ready"
      : model.deployment === "local" ? "Not installed" : "API key needed";
  header.append(title, badge);

  const description = document.createElement("p");
  description.className = "model-description";
  description.textContent = model.description;

  const facts = document.createElement("dl");
  facts.className = "model-facts";
  addFact(facts, "Max length", formatDuration(model.max_duration_seconds));
  addFact(facts, model.deployment === "local" ? "Weight download" : "Local download", model.download_bytes ? formatModelBytes(model.download_bytes) : "None");
  addFact(facts, "Negative prompt", model.supports_negative_prompt ? "Supported" : "Not exposed");
  addFact(
    facts,
    model.deployment === "local" ? "Runs" : "Cost",
    model.deployment === "local" ? "On this computer" : `${model.credits_per_generation} credits / gen`,
  );

  const tradeoff = document.createElement("p");
  tradeoff.className = "model-tradeoff";
  tradeoff.textContent = model.tradeoff;

  const install = model.installation || { state: "idle", progress: 0, stage: "" };
  const installArea = document.createElement("div");
  installArea.className = "model-install-area";
  if (install.state === "installing") {
    const label = document.createElement("div");
    label.className = "model-install-label";
    const stage = document.createElement("span");
    stage.textContent = install.stage;
    const percent = document.createElement("b");
    percent.textContent = `${Math.round(install.progress)}%`;
    label.append(stage, percent);
    const track = document.createElement("div");
    track.className = "progress-track";
    const fill = document.createElement("div");
    fill.className = "progress-fill";
    fill.style.width = `${install.progress}%`;
    track.append(fill);
    installArea.append(label, track);
  } else if (install.state === "failed") {
    const error = document.createElement("p");
    error.className = "model-install-error";
    error.textContent = install.error;
    installArea.append(error);
  }

  const credential = document.createElement("p");
  credential.className = "model-credential";
  credential.textContent = model.credential_note;
  if (model.deployment === "cloud" && !model.ready) {
    const command = document.createElement("code");
    command.textContent = "STABILITY_API_KEY=… ./scripts/run.sh";
    credential.append(document.createElement("br"), command);
  }

  const actions = document.createElement("div");
  actions.className = "model-actions";
  if (model.deployment === "local" && !model.ready && install.state !== "installing") {
    const installButton = document.createElement("button");
    installButton.type = "button";
    installButton.className = "ghost-button";
    installButton.dataset.modelAction = "install";
    installButton.dataset.modelId = model.id;
    installButton.disabled = !model.runtime_installed;
    installButton.textContent = model.runtime_installed
      ? `Install ${formatModelBytes(model.download_bytes)}`
      : "Run setup first";
    actions.append(installButton);
  }
  if (model.ready) {
    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = model.id === state.selectedModelId ? "selected-model-button" : "ghost-button";
    selectButton.dataset.modelAction = "select";
    selectButton.dataset.modelId = model.id;
    selectButton.disabled = model.id === state.selectedModelId;
    selectButton.textContent = model.id === state.selectedModelId ? "Using this model" : "Use this model";
    actions.append(selectButton);
  }
  const official = document.createElement("a");
  official.href = model.official_url;
  official.target = "_blank";
  official.rel = "noreferrer";
  official.textContent = "Official details ↗";
  actions.append(official);

  card.append(header, description, facts, tradeoff, installArea, credential, actions);
  return card;
}

function addFact(root, term, detail) {
  const wrapper = document.createElement("div");
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = detail;
  wrapper.append(dt, dd);
  root.append(wrapper);
}

$("#model-grid").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-model-action]");
  if (!button) return;
  const modelId = button.dataset.modelId;
  if (button.dataset.modelAction === "select") {
    selectModel(modelId);
    return;
  }
  button.disabled = true;
  try {
    await api(`/api/models/${modelId}/install`, { method: "POST", body: JSON.stringify({}) });
    toast("Model download started. You can keep Soundslo open.");
    await loadSystem({ quiet: true });
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
});

function scheduleModelPolling() {
  clearTimeout(state.modelPollTimer);
  const active = state.models.some((model) => model.installation?.state === "installing");
  if (active) state.modelPollTimer = setTimeout(() => loadSystem({ quiet: true }), 1000);
}

let desktopUpdate = null;
let updateBusy = false;

async function initDesktop() {
  const desktop = window.soundsloDesktop;
  if (!desktop) return;
  document.body.classList.add("desktop", `desktop-${desktop.platform}`);
  const version = $("#desktop-version");
  version.hidden = false;
  version.textContent = `v${desktop.version}`;
  if (desktop.smoke) return;
  desktop.onUpdateProgress(({ fraction = 0 }) => {
    $("#update-progress").hidden = false;
    $("#update-progress-fill").style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`;
    $("#update-status").textContent = `Downloading update… ${Math.round(fraction * 100)}%`;
  });
  const info = await desktop.updateInfo();
  window.setInterval(() => checkDesktopUpdate(false).catch(() => {}), UPDATE_POLL_INTERVAL_MS);
  if (info.staged) {
    desktopUpdate = { staged: info.staged };
    showUpdateChip(`Install v${info.staged.version}`);
    return;
  }
  if (info.stale) await checkDesktopUpdate(false);
}

function showUpdateChip(label) {
  const chip = $("#update-chip");
  chip.textContent = label;
  chip.hidden = false;
}

async function checkDesktopUpdate(force = true) {
  const result = await window.soundsloDesktop.updateCheck({ force });
  desktopUpdate = result;
  if (result.ok && result.available) showUpdateChip(`Update to v${result.latest}`);
  return result;
}

function renderUpdateDialog() {
  const status = $("#update-status");
  const action = $("#update-action");
  $("#update-progress").hidden = true;
  action.disabled = updateBusy;
  if (desktopUpdate?.staged) {
    status.textContent = `Version ${desktopUpdate.staged.version} is downloaded and checksum-verified.`;
    action.textContent = "Install and restart";
  } else if (desktopUpdate?.ok && desktopUpdate.available) {
    const size = desktopUpdate.asset?.size ? ` (${formatBytes(desktopUpdate.asset.size)})` : "";
    status.textContent = `Version ${desktopUpdate.latest} is ready to download${size}.`;
    action.textContent = "Download update";
  } else if (desktopUpdate?.ok) {
    status.textContent = `Soundslo ${desktopUpdate.current} is the latest version.`;
    action.textContent = "Check again";
  } else if (desktopUpdate?.error) {
    status.textContent = desktopUpdate.error;
    action.textContent = "Try again";
  } else {
    status.textContent = "Check GitHub Releases for a newer version.";
    action.textContent = "Check for updates";
  }
}

function openUpdateDialog() {
  renderUpdateDialog();
  $("#update-dialog").showModal();
}

$("#update-chip").addEventListener("click", openUpdateDialog);
$("#desktop-version").addEventListener("click", openUpdateDialog);
$("#update-close").addEventListener("click", () => $("#update-dialog").close());

$("#update-action").addEventListener("click", async () => {
  if (updateBusy || !window.soundsloDesktop) return;
  updateBusy = true;
  $("#update-action").disabled = true;
  try {
    if (desktopUpdate?.staged) {
      $("#update-status").textContent = "Installing the verified update…";
      await window.soundsloDesktop.updateInstall();
      return;
    }
    if (desktopUpdate?.ok && desktopUpdate.available) {
      const staged = await window.soundsloDesktop.updateDownload();
      desktopUpdate = { staged };
      showUpdateChip(`Install v${staged.version}`);
    } else {
      $("#update-status").textContent = "Checking GitHub Releases…";
      desktopUpdate = await checkDesktopUpdate(true);
    }
  } catch (error) {
    desktopUpdate = { error: error.message };
  } finally {
    updateBusy = false;
    renderUpdateDialog();
  }
});

async function loadGenerations({ quiet = false } = {}) {
  try {
    state.generations = await api("/api/generations?limit=200");
    renderGenerations();
    schedulePolling();
  } catch (error) {
    if (!quiet) toast(error.message, true);
  }
}

function renderGenerations() {
  const filtered = state.generations.filter((generation) => {
    const haystack = `${generation.name} ${generation.prompt}`.toLowerCase();
    return haystack.includes(state.search.toLowerCase());
  });
  emptyState.hidden = filtered.length > 0;

  const wantedIds = new Set(filtered.map((item) => item.id));
  [...list.children].forEach((card) => {
    if (!wantedIds.has(card.dataset.id)) card.remove();
  });

  filtered.forEach((generation, index) => {
    const version = [
      generation.status,
      generation.name,
      generation.model,
      Math.floor(generation.progress || 0),
      generation.stage,
      generation.error,
      generation.file_size,
    ].join("|");
    let card = list.querySelector(`[data-id="${generation.id}"]`);
    if (!card || card.dataset.version !== version) {
      const fresh = generationCard(generation);
      if (card) card.replaceWith(fresh);
      card = fresh;
    }
    const atIndex = list.children[index];
    if (atIndex !== card) list.insertBefore(card, atIndex || null);
  });
}

function generationCard(generation) {
  const card = document.createElement("article");
  card.className = "generation-card";
  card.dataset.id = generation.id;
  card.dataset.version = [
    generation.status,
    generation.name,
    generation.model,
    Math.floor(generation.progress || 0),
    generation.stage,
    generation.error,
    generation.file_size,
  ].join("|");

  const cover = document.createElement("div");
  cover.className = "cover";
  cover.innerHTML = '<span class="wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>';

  const main = document.createElement("div");
  main.className = "generation-main";
  const titleRow = document.createElement("div");
  titleRow.className = "title-row";
  const title = document.createElement("h3");
  title.className = "generation-title";
  title.textContent = generation.name;
  title.title = generation.prompt;
  const badge = document.createElement("span");
  badge.className = `status-badge ${generation.status}`;
  badge.textContent = generation.status;
  titleRow.append(title, badge);

  const meta = document.createElement("p");
  meta.className = "generation-meta";
  const generationModel = modelById(generation.model);
  const bits = [
    generationModel?.short_name || FALLBACK_MODEL_NAMES[generation.model] || "Medium",
    formatDuration(generation.duration_seconds),
    `seed ${generation.seed}`,
    `${generation.steps} steps`,
  ];
  if (generation.elapsed_seconds) bits.push(`${formatDuration(generation.elapsed_seconds)} render`);
  if (generation.file_size) bits.push(formatBytes(generation.file_size));
  bits.push(formatDate(generation.created_at));
  meta.textContent = bits.join("  ·  ");
  main.append(titleRow, meta);

  if (generation.status === "completed") {
    const audioRow = document.createElement("div");
    audioRow.className = "audio-row";
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = `/api/generations/${generation.id}/audio`;
    audioRow.append(audio);
    main.append(audioRow);
  } else if (["queued", "running"].includes(generation.status)) {
    const progress = document.createElement("div");
    progress.className = "progress-wrap";
    const queueLabel = generation.status === "queued" ? queuedLabel(generation) : generation.stage;
    progress.innerHTML = `
      <div class="progress-label"><span></span><b>${Math.round(generation.progress || 0)}%</b></div>
      <div class="progress-track"><div class="progress-fill" style="width:${generation.progress || 0}%"></div></div>`;
    progress.querySelector("span").textContent = queueLabel;
    main.append(progress);
  }

  if (generation.error) {
    const error = document.createElement("p");
    error.className = "generation-error";
    error.textContent = generation.error;
    main.append(error);
  }

  const actions = document.createElement("div");
  actions.className = "card-actions";
  addAction(actions, "Prompt", "reuse", generation.id, "Load these settings into the composer");
  if (generation.status === "completed") {
    addLink(actions, "Download", `/api/generations/${generation.id}/download`);
    addAction(actions, "Show file", "reveal", generation.id, "Reveal WAV in the file manager");
  }
  if (["queued", "running"].includes(generation.status)) {
    addAction(actions, "Cancel", "cancel", generation.id);
  } else {
    addAction(actions, "Retry", "retry", generation.id, "Generate again with the same seed");
  }
  addAction(actions, "Rename", "rename", generation.id);
  addAction(actions, "Log", "log", generation.id);
  if (generation.status !== "running") addAction(actions, "Delete", "delete", generation.id, "", "danger");

  card.append(cover, main, actions);
  return card;
}

function addAction(root, label, action, id, title = "", className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.action = action;
  button.dataset.id = id;
  button.textContent = label;
  button.title = title;
  button.className = className;
  root.append(button);
}

function addLink(root, label, href) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = label;
  link.setAttribute("download", "");
  root.append(link);
}

function queuedLabel(generation) {
  const queued = state.generations
    .filter((item) => item.status === "queued")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const position = queued.findIndex((item) => item.id === generation.id) + 1;
  return position > 1 ? `Queued · ${position - 1} ahead` : "Queued · next up";
}

function schedulePolling() {
  clearTimeout(state.pollTimer);
  const hasActive = state.generations.some((item) => ["queued", "running"].includes(item.status));
  if (hasActive) state.pollTimer = setTimeout(() => loadGenerations({ quiet: true }), 800);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const model = selectedModel();
  if (!state.ready) {
    $("#settings-panel").open = true;
    $("#settings-panel").scrollIntoView({ behavior: "smooth", block: "center" });
    toast(`${model?.short_name || "The selected model"} is not ready. Check Settings.`, true);
    return;
  }
  const button = $("#generate-button");
  button.disabled = true;
  button.querySelector("span").textContent = "Adding to queue…";
  try {
    const seedValue = $("#seed").value.trim();
    const generation = await api("/api/generations", {
      method: "POST",
      body: JSON.stringify({
        prompt: promptInput.value,
        negative_prompt: $("#negative-prompt").value,
        model: model.id,
        duration_seconds: currentDuration(),
        seed: seedValue ? Number(seedValue) : null,
        steps: Number($("#steps").value),
        cfg_scale: Number($("#guidance").value),
      }),
    });
    state.generations.unshift(generation);
    renderGenerations();
    schedulePolling();
    toast(`${model.short_name} generation queued.`);
    $("#library-title").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Generate music";
  }
});

list.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const generation = state.generations.find((item) => item.id === button.dataset.id);
  if (!generation) return;
  const action = button.dataset.action;
  button.disabled = true;
  try {
    if (action === "reuse") {
      const originalModel = modelById(generation.model);
      if (originalModel?.ready) selectModel(originalModel.id);
      else if (generation.model) toast("That generation's model is not currently ready; keeping the current model.", true);
      promptInput.value = generation.prompt;
      $("#negative-prompt").value = generation.negative_prompt;
      setDuration(generation.duration_seconds);
      $("#seed").value = generation.seed;
      $("#steps").value = generation.steps;
      $("#guidance").value = generation.cfg_scale;
      updateControls();
      form.scrollIntoView({ behavior: "smooth", block: "center" });
      promptInput.focus();
    } else if (action === "reveal") {
      await api(`/api/generations/${generation.id}/reveal`, { method: "POST" });
    } else if (action === "cancel") {
      await api(`/api/generations/${generation.id}/cancel`, { method: "POST" });
      await loadGenerations();
    } else if (action === "retry") {
      const created = await api(`/api/generations/${generation.id}/retry`, { method: "POST" });
      state.generations.unshift(created);
      renderGenerations();
      schedulePolling();
      toast("Retry queued with the same model and seed.");
    } else if (action === "rename") {
      state.renameId = generation.id;
      $("#rename-input").value = generation.name;
      $("#rename-dialog").showModal();
      $("#rename-input").select();
    } else if (action === "log") {
      const data = await api(`/api/generations/${generation.id}/log`);
      $("#log-output").textContent = data.log;
      $("#log-dialog").showModal();
    } else if (action === "delete") {
      if (!confirm(`Delete “${generation.name}” and its WAV file? This cannot be undone.`)) return;
      await api(`/api/generations/${generation.id}`, { method: "DELETE" });
      state.generations = state.generations.filter((item) => item.id !== generation.id);
      renderGenerations();
      toast("Generation deleted.");
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#rename-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api(`/api/generations/${state.renameId}`, {
      method: "PATCH",
      body: JSON.stringify({ name: $("#rename-input").value }),
    });
    $("#rename-dialog").close();
    await loadGenerations();
  } catch (error) {
    toast(error.message, true);
  }
});

document.addEventListener("click", (event) => {
  const close = event.target.closest("[data-close-dialog]");
  if (close) close.closest("dialog").close();
});

promptInput.addEventListener("input", updateControls);
durationInput.addEventListener("input", () => setDuration(durationInput.value));
durationMinutes.addEventListener("input", updateDurationFromParts);
durationSeconds.addEventListener("input", updateDurationFromParts);
$("#guidance").addEventListener("input", updateControls);
$("#steps").addEventListener("input", updateControls);
$("#search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderGenerations();
});
$("#refresh-button").addEventListener("click", () => Promise.all([loadSystem(), loadGenerations()]));
$("#surprise-button").addEventListener("click", () => {
  promptInput.value = promptIdeas[Math.floor(Math.random() * promptIdeas.length)];
  updateControls();
  promptInput.focus();
});
$("#random-seed").addEventListener("click", () => {
  const cloud = selectedModel()?.deployment === "cloud";
  const minimum = cloud ? 1 : 0;
  const maximum = cloud ? 4294967294 : 4294967295;
  $("#seed").value = minimum + Math.floor(Math.random() * (maximum - minimum + 1));
});
$("#duration-presets").addEventListener("click", (event) => {
  const button = event.target.closest("[data-duration]");
  if (button) setDuration(button.dataset.duration);
});

function currentDuration() {
  return Math.max(1, Math.round(Number(durationInput.value) || 1));
}

function updateDurationFromParts() {
  let minutes = Math.max(0, Math.floor(Number(durationMinutes.value) || 0));
  let seconds = Math.max(0, Math.floor(Number(durationSeconds.value) || 0));
  minutes += Math.floor(seconds / 60);
  seconds %= 60;
  setDuration(minutes * 60 + seconds);
}

function setDuration(seconds) {
  const model = selectedModel();
  const maximum = model?.max_duration_seconds || 380;
  const value = Math.min(maximum, Math.max(1, Math.round(Number(seconds) || 1)));
  durationInput.max = maximum;
  durationInput.value = value;
  durationMinutes.value = Math.floor(value / 60);
  durationSeconds.value = value % 60;
  $("#duration-output").textContent = formatDuration(value);
  document.querySelectorAll("[data-duration]").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.duration) === value);
  });
}

function renderDurationPresets() {
  const model = selectedModel();
  const maximum = model?.max_duration_seconds || 380;
  const values = [...new Set([30, 60, 120, 180, 360, maximum].filter((value) => value <= maximum))];
  const buttons = values.map((value) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.duration = value;
    button.textContent = shortDuration(value);
    return button;
  });
  $("#duration-presets").replaceChildren(...buttons);
  setDuration(currentDuration());
}

function updateControls() {
  $("#char-count").textContent = promptInput.value.length;
  $("#duration-output").textContent = formatDuration(currentDuration());
  $("#guidance-output").textContent = Number($("#guidance").value).toFixed(1);
  $("#steps-output").textContent = $("#steps").value;
  document.querySelectorAll("[data-duration]").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.duration) === currentDuration());
  });
}

function formatDuration(seconds) {
  const value = Math.max(0, Math.round(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

function shortDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return formatDuration(seconds);
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

function formatModelBytes(bytes) {
  return bytes ? `${(bytes / 1_000_000_000).toFixed(1)} GB` : "0 GB";
}

function formatDate(value) {
  const date = new Date(value);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function toast(message, error = false) {
  const element = document.createElement("div");
  element.className = `toast ${error ? "error" : ""}`;
  element.textContent = message;
  $("#toast-region").append(element);
  setTimeout(() => element.remove(), 4500);
}

setDuration(30);
updateControls();
Promise.all([loadSystem(), loadGenerations()]);
initDesktop();
