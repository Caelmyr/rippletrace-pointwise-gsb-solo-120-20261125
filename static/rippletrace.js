"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "profile",
               busy: false, activePeak: null};
const settings = [...document.querySelectorAll("[data-setting]")];
const spacingFields = [...document.querySelectorAll("[data-spacing]")];

async function api(path, options) {
  const response = await fetch("/rippletrace" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
  }
}

async function library() {
  const {cards} = await api("/cards");
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {photo, card, probe, result} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo, 0, 0);
  const cfg = card.settings;
  ctx.strokeStyle = "#84aebc";
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 5]);
  for (const radius of [cfg.inner, cfg.outer]) {
    ctx.beginPath();
    ctx.arc(cfg.center_x, cfg.center_y, radius, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.strokeStyle = "#8de0cf";
  ctx.lineWidth = 2;
  ctx.strokeRect(cfg.center_x - 4, cfg.center_y - 4, 8, 8);
  ctx.beginPath();
  result.profile.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
  if (result.reading) {
    ctx.strokeStyle = "#ffc487";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(result.reading.x, result.reading.y, 6, 0, Math.PI * 2);
    ctx.stroke();
  }
  paintTrain(ctx);
  if (probe) {
    ctx.strokeStyle = "#f5e5e9";
    ctx.strokeRect(probe.x - 6, probe.y - 6, 12, 12);
  }
}

function trainPeaks() {
  return state.result?.train?.feasible ? state.result.train.peaks : [];
}

function trainAt(x, y) {
  return trainPeaks().find((peak) => peak.x === x && peak.y === y) || null;
}

function nearestPeak(x, y, reach) {
  let best = null;
  for (const peak of trainPeaks()) {
    const distance = Math.hypot(peak.x - x, peak.y - y);
    if (distance <= reach && (!best || distance < best.distance)) best = {peak, distance};
  }
  return best?.peak || null;
}

function paintTrain(ctx) {
  const train = state.result?.train;
  if (!train?.feasible) return;
  for (const peak of train.peaks) {
    const active = state.probe && peak.x === state.probe.x && peak.y === state.probe.y;
    ctx.strokeStyle = state.activePeak === peak.number ? "#ffe9a8" : active ? "#f3d47c" : "#e0b53f";
    ctx.lineWidth = active ? 3 : 2;
    ctx.beginPath();
    ctx.arc(peak.x, peak.y, active ? 9 : 6, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#1c3350";
    ctx.font = "bold 11px monospace";
    ctx.fillText(String(peak.number), peak.x + 8, peak.y - 7);
  }
  for (const hole of train.missing) {
    ctx.strokeStyle = "#f2a3a3";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(hole.x - 5, hole.y - 5);
    ctx.lineTo(hole.x + 5, hole.y + 5);
    ctx.moveTo(hole.x + 5, hole.y - 5);
    ctx.lineTo(hole.x - 5, hole.y + 5);
    ctx.stroke();
    ctx.fillStyle = "#f2a3a3";
    ctx.font = "bold 11px monospace";
    ctx.fillText("缺峰 " + hole.r_px, hole.x + 8, hole.y + 13);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const {result, card} = state;
  const cfg = card.settings;
  const angular = state.chart === "coverage";
  const lo = angular ? 0 : cfg.inner;
  const hi = angular ? 355 : cfg.outer;
  const observed = angular ? result.angular.map((row) => [row.angle, row.peak?.r_px ?? null])
    : result.profile.map((point) => [point.r_px, point.brightness]);
  const bound = angular ? cfg.outer : 255;
  const xAt = (x) => 44 + (width - 81) * (x - lo) / Math.max(1, hi - lo);
  const yAt = (y) => height - 26 - (height - 46) * y / bound;
  get("chart-title").textContent = angular ? "各方向最亮半径" : "单径向亮度";
  get("chart-caption").textContent = angular ? "半径 px · 顺时针角度" : "实际像素亮度 · 半径 px";
  ctx.fillStyle = "#eff6fc";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#3b536c";
  ctx.strokeStyle = "#ccdeeb";
  for (const level of [0, Math.round(bound / 2), bound]) {
    ctx.fillText(level, 8, yAt(level) + 3);
    ctx.beginPath();
    ctx.moveTo(xAt(lo), yAt(level));
    ctx.lineTo(xAt(hi), yAt(level));
    ctx.stroke();
  }
  ctx.fillText(String(lo), xAt(lo), height - 7);
  ctx.fillText(String(hi), xAt(hi) - 15, height - 7);
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#4674a3";
  ctx.beginPath();
  let prior = false;
  for (const [position, level] of observed) {
    if (level === null) {
      prior = false;
      continue;
    }
    if (prior) ctx.lineTo(xAt(position), yAt(level));
    else ctx.moveTo(xAt(position), yAt(level));
    prior = true;
  }
  ctx.stroke();
  if (!angular && result.reading) {
    ctx.fillStyle = "#b46d47";
    ctx.beginPath();
    ctx.arc(xAt(result.reading.r_px), yAt(result.reading.brightness), 4, 0, Math.PI * 2);
    ctx.fill();
  }
  if (!angular) paintTrainChart(ctx, xAt, yAt);
}

function paintTrainChart(ctx, xAt, yAt) {
  const train = state.result?.train;
  if (!train?.feasible) return;
  for (const peak of train.peaks) {
    const active = state.activePeak === peak.number;
    ctx.strokeStyle = active ? "#ffe9a8" : "#c99a2e";
    ctx.lineWidth = active ? 3 : 2;
    ctx.beginPath();
    ctx.arc(xAt(peak.r_px), yAt(peak.brightness), active ? 6 : 4, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#6a4a12";
    ctx.font = "bold 11px monospace";
    ctx.fillText(String(peak.number), xAt(peak.r_px) + 6, yAt(peak.brightness) - 6);
  }
  for (const hole of train.missing) {
    ctx.strokeStyle = "#c05252";
    ctx.lineWidth = 2;
    const x = xAt(hole.r_px);
    const y = yAt(255 * .5);
    ctx.beginPath();
    ctx.moveTo(x, y - 16);
    ctx.lineTo(x, y - 4);
    ctx.stroke();
    ctx.fillStyle = "#c05252";
    ctx.font = "11px monospace";
    ctx.fillText("缺", x - 4, y - 20);
  }
  ctx.fillStyle = "#6a4a12";
  ctx.font = "11px monospace";
  ctx.fillText("波距 " + train.spacing_px.toFixed(2) + " px / " + train.spacing_mm.toFixed(3) + " mm", 52, 16);
}

function paintProbeDetail() {
  const canvas = get("detail");
  const ctx = canvas.getContext("2d");
  const {photo, card, probe} = state;
  const peak = probe ? trainAt(probe.x, probe.y) : null;
  if (!photo || !peak) {
    get("detail-caption").textContent = state.probe
      ? "原片 (" + state.probe.x + ", " + state.probe.y + ") 不是已采用的亮峰。"
      : "选中已采用亮峰后，这里放大原片像素与两侧暗邻点。";
    canvas.width = 480;
    canvas.height = 120;
    ctx.fillStyle = "#eff6fc";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    return;
  }
  const scale = 9;
  const half = 3;
  canvas.width = (half * 2 + 1) * scale;
  canvas.height = canvas.width;
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "#16283d";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(photo, peak.x - half, peak.y - half, half * 2 + 1, half * 2 + 1,
                0, 0, canvas.width, canvas.height);
  const spot = (point, color, tag) => {
    const dx = point.x - (peak.x - half);
    const dy = point.y - (peak.y - half);
    if (dx < 0 || dy < 0 || dx > half * 2 || dy > half * 2) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.strokeRect(dx * scale + 1, dy * scale + 1, scale - 2, scale - 2);
    ctx.fillStyle = color;
    ctx.font = "10px monospace";
    ctx.fillText(tag, dx * scale + 2, dy * scale + 11);
  };
  spot(peak.before, "#9fc7e8", "L");
  spot(peak.after, "#9fc7e8", "R");
  spot(peak, "#ffe9a8", "P");
  get("detail-caption").textContent = "第 " + peak.number + " 峰原片像素 (" + peak.x + ", " + peak.y + ") · RGB " +
    peak.rgb.join("/") + " · 左(" + peak.before.x + ", " + peak.before.y + ") 亮度 " + peak.before.brightness.toFixed(1) +
    " · 右(" + peak.after.x + ", " + peak.after.y + ") 亮度 " + peak.after.brightness.toFixed(1) + " · 均比峰暗。";
}

function pointLabel(point) {
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · 距中心 " + point.distance_mm.toFixed(2) + " mm";
}

function show() {
  const {card, result} = state;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  for (const field of spacingFields) field.value = card.settings.spacing[field.dataset.spacing];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.reading?.x ?? card.settings.center_x;
  get("probe-y").value = state.probe?.y ?? result.reading?.y ?? card.settings.center_y;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  paintProbeDetail();
  const reading = result.reading;
  get("radius-value").textContent = reading ? reading.r_mm.toFixed(2) : "—";
  get("radius-unit").textContent = "mm";
  get("measurement-state").textContent = "径线 " + result.focus + "°";
  get("selected-level").textContent = reading
    ? reading.r_px + " px · 原片 (" + reading.x + ", " + reading.y + ") · 亮度 " + reading.brightness.toFixed(2)
    : "这个方向未覆盖原片像素";
  showTrain();
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv",
                                               "train-csv": "train.csv", zip: "observation.zip"})) {
    get(id).href = "/rippletrace" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
}

function showTrain() {
  const train = state.result?.train;
  const list = get("train-peaks");
  list.replaceChildren();
  if (!train || !train.feasible) {
    get("train-value").textContent = "—";
    get("train-unit").textContent = "";
    get("train-state").textContent = "不可行";
    get("train-note").textContent = train?.reason || "当前径线还没有可用亮峰。";
    if (train?.candidates.length) {
      const row = document.createElement("li");
      row.className = "train-hole";
      row.textContent = "可用亮峰半径：" + train.candidates.map((item) => item.r_px).join("、") +
        " px（" + train.candidate_count + " 个）";
      list.append(row);
    }
    return;
  }
  if (train.missing.length) {
    get("train-value").textContent = train.spacing_mm.toFixed(3);
    get("train-unit").textContent = "mm / 峰（一次两倍核对）";
  } else {
    get("train-value").textContent = train.spacing_mm.toFixed(3);
    get("train-unit").textContent = "mm / 峰";
  }
  get("train-state").textContent = train.peak_count + " 峰 · 最大偏差 " +
    train.worst_deviation_px.toFixed(2) + " px / " + train.worst_deviation_mm.toFixed(3) + " mm";
  get("train-note").textContent = train.note;
  for (const peak of train.peaks) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "train-peak";
    button.textContent = peak.number + " · " + peak.r_px + " px / " + peak.r_mm.toFixed(2) + " mm · (" +
      peak.x + ", " + peak.y + ") · 亮度 " + peak.brightness.toFixed(1);
    button.setAttribute("aria-pressed", String(state.activePeak === peak.number));
    button.addEventListener("click", () => action(() => pickPeak(peak)));
    item.append(button);
    list.append(item);
    const hole = train.missing.find((item) => item.after_peak === peak.number);
    if (hole) {
      const blank = document.createElement("li");
      blank.className = "train-hole";
      blank.textContent = "缺峰留空 · " + hole.r_px + " px / " + hole.r_mm.toFixed(2) + " mm · (" +
        hole.x + ", " + hole.y + ") · " + hole.note;
      list.append(blank);
    }
  }
}

async function pickPeak(peak) {
  await probe(peak.x, peak.y);
  showTrain();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/rippletrace" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null, activePeak: null});
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  const match = trainAt(x, y);
  state.activePeak = match ? match.number : null;
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
  paintProbeDetail();
}

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  const peak = trainAt(x, y);
  action(async () => {
    const picked = peak || nearestPeak(x, y, Math.max(2, Math.round(canvas.width / 240)));
    if (picked) {
      await pickPeak(picked);
      notice("已回到第 " + picked.number + " 峰的原片像素，可用点读核对两侧暗邻点。");
      return;
    }
    await probe(x, y);
    const field = (name) => settings.find((item) => item.dataset.setting === name);
    if (state.mode === "center") {
      field("center_x").value = x;
      field("center_y").value = y;
      notice("已填入原片中心。");
    }
    if (state.mode === "mark") {
      const angle = Math.atan2(y - Number(field("center_y").value),
                              x - Number(field("center_x").value)) * 180 / Math.PI;
      field("angle").value = (Math.round(angle) + 360) % 360;
      notice("已填入从中心到原片点的方向。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("suggest").addEventListener("click", () => action(async () => {
  const values = await api(route("/suggestion") + savedQuery());
  for (const field of spacingFields) field.value = values[field.dataset.spacing];
  notice("已按当前径线的候选峰距填入建议值，可再收窄后保存。");
}));
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [
      field.dataset.setting, Number(field.value),
    ]));
    fields.spacing = Object.fromEntries(spacingFields.map((field) => [
      field.dataset.spacing, Number(field.value),
    ]));
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));
action(library);
