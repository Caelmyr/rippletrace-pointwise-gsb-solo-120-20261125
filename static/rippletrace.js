"use strict";

const get = (id) => document.getElementById(id);
const state = {
  card: null, result: null, photo: null, probe: null,
  mode: "probe", chart: "profile", busy: false,
  marks: [], fit: null, ring: null, fitStale: false,
};
const settings = [...document.querySelectorAll("[data-setting]")];

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
    const apply = get("apply-fit");
    if (apply) apply.disabled = !(state.card && state.fit?.feasible);
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
  const fit = activeFit();
  ctx.strokeStyle = "#84aebc";
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 5]);
  for (const radius of [cfg.inner, cfg.outer]) {
    ctx.beginPath();
    ctx.arc(cfg.center_x, cfg.center_y, radius, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (fit?.feasible && Number.isFinite(fit.radius_px)) {
    ctx.strokeStyle = "#ffd166";
    ctx.lineWidth = 2;
    ctx.setLineDash([9, 5]);
    ctx.beginPath();
    ctx.arc(fit.center_x, fit.center_y, fit.radius_px, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "#ffd166";
    ctx.lineWidth = 2;
    ctx.strokeRect(fit.center_x - 5, fit.center_y - 5, 10, 10);
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
  state.marks.forEach((mark, index) => {
    const annotation = fitAnnotation(mark);
    let color = "#f5e5e9";
    if (annotation?.rgb_clipped) color = "#9aa7b4";
    else if (annotation?.adopted === true) color = "#7dffb0";
    else if (annotation?.adopted === false) color = "#ff7b7b";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(mark.x, mark.y, 6, 0, Math.PI * 2);
    ctx.stroke();
    ctx.font = "bold 11px monospace";
    ctx.fillText(String(index + 1), mark.x + 8, mark.y - 7);
  });
  if (probe) {
    ctx.strokeStyle = "#f5e5e9";
    ctx.strokeRect(probe.x - 6, probe.y - 6, 12, 12);
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
}

function activeFit() {
  if (state.fit && !state.fitStale) return state.fit;
  return state.card?.ring_fit || null;
}

function samePoint(item, mark) {
  return item && (String(item.id || "") === String(mark.id || "") ||
    (Number(item.x) === Number(mark.x) && Number(item.y) === Number(mark.y)));
}

function fitAnnotation(mark) {
  const fit = activeFit();
  const sources = [fit?.points, state.ring?.points, state.card?.ring_fit?.points];
  for (const points of sources) {
    const found = (points || []).find((item) => samePoint(item, mark));
    if (found) return found;
  }
  return null;
}

function markRgb(mark, annotation) {
  const rgb = annotation?.original_rgb || annotation?.rgb || mark.rgb ||
    state.ring?.points?.find((p) => samePoint(p, mark))?.rgb;
  return Array.isArray(rgb) ? rgb : null;
}

function formatError(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "—";
}

function quadrantText(value) {
  return ({
    right_down: "右下 Q1",
    left_down: "左下 Q2",
    left_up: "左上 Q3",
    right_up: "右上 Q4",
    axis: "坐标轴",
  })[value] || "—";
}

function markQuadrant(mark, annotation) {
  if (annotation?.quadrant) return annotation.quadrant;
  const cfg = state.card?.settings;
  if (!cfg) return null;
  if (mark.x > cfg.center_x && mark.y > cfg.center_y) return "right_down";
  if (mark.x < cfg.center_x && mark.y > cfg.center_y) return "left_down";
  if (mark.x < cfg.center_x && mark.y < cfg.center_y) return "left_up";
  if (mark.x > cfg.center_x && mark.y < cfg.center_y) return "right_up";
  return "axis";
}

function renderFitSummary() {
  const element = get("fit-summary");
  const apply = get("apply-fit");
  const fit = state.fit;
  if (!fit) {
    element.hidden = true;
    element.textContent = "";
    apply.disabled = true;
    return;
  }
  element.hidden = false;
  if (fit.feasible) {
    const quadrants = fit.quadrants?.counts?.join("/") || "—";
    element.textContent = (state.fitStale ? "限差或标点已改动，旧建议仅供参考，请重新建议。 " : "") +
      `${fit.message} 四象限采用点数 ${quadrants}（右下/左下/左上/右上），RMSE ${formatError(fit.rmse_px)} px。`;
    apply.disabled = state.busy;
  } else {
    element.textContent = fit.message || "没有满足全部约束的圆心。";
    apply.disabled = true;
  }
}

function renderMarks() {
  const rows = get("mark-rows");
  rows.replaceChildren();
  get("marks-empty").hidden = state.marks.length > 0;
  state.marks.forEach((mark, index) => {
    const annotation = fitAnnotation(mark);
    const rgb = markRgb(mark, annotation);
    const tr = document.createElement("tr");
    tr.dataset.markId = mark.id;
    tr.dataset.x = String(mark.x);
    tr.dataset.y = String(mark.y);

    const indexCell = document.createElement("td");
    indexCell.textContent = String(index + 1);
    tr.append(indexCell);

    for (const value of [mark.x, mark.y]) {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      tr.append(cell);
    }

    const rgbCell = document.createElement("td");
    rgbCell.className = "rgb-cell";
    rgbCell.textContent = rgb ? rgb.join("/") : "读取中";
    if (annotation?.rgb_clipped || rgb?.some((v) => v === 0 || v === 255)) {
      rgbCell.classList.add("rgb-clipped");
      rgbCell.title = "任一通道为 0 或 255，该点不会用于拟合";
    }
    tr.append(rgbCell);

    const toleranceCell = document.createElement("td");
    const tolerance = document.createElement("input");
    tolerance.className = "mark-tolerance";
    tolerance.type = "number";
    tolerance.min = "0";
    tolerance.step = "any";
    tolerance.required = true;
    tolerance.placeholder = "最大像素数";
    tolerance.value = mark.tolerance_px ?? 2;
    tolerance.dataset.markId = mark.id;
    tolerance.setAttribute("aria-label", `标点 ${index + 1} 的最大像素差`);
    toleranceCell.append(tolerance);
    tr.append(toleranceCell);

    const quadrantCell = document.createElement("td");
    quadrantCell.className = "quadrant-cell";
    quadrantCell.textContent = quadrantText(markQuadrant(mark, annotation));
    tr.append(quadrantCell);

    const statusCell = document.createElement("td");
    statusCell.className = "mark-status";
    const status = document.createElement("span");
    status.classList.add("status-pill");
    const error = annotation?.radius_difference_px ?? annotation?.radius_error_px;
    const toleranceLimit = mark.tolerance_px ?? annotation?.tolerance_px;
    const errorNumber = Number(error);
    const limitNumber = Number(toleranceLimit);
    const hasError = Number.isFinite(errorNumber);
    const withinCurrentLimit = hasError && Number.isFinite(limitNumber) &&
      errorNumber <= limitNumber + 1e-8;
    if (annotation?.rgb_clipped || rgb?.some((v) => v === 0 || v === 255)) {
      status.classList.add("status-excluded");
      status.textContent = "不采用 · RGB 端点 0/255";
    } else if (annotation?.adopted === true && withinCurrentLimit) {
      status.classList.add("status-adopted");
      status.textContent = (state.fitStale ? "采用（限差已改，待重新拟合）" : "采用") +
        ` · 实际半径差 ${formatError(error)} px / 限差 ${formatError(toleranceLimit)} px`;
    } else if (hasError) {
      status.classList.add("status-rejected");
      status.textContent = `未采用 · 实际半径差 ${formatError(error)} px / 限差 ${formatError(toleranceLimit)} px`;
    } else if (annotation?.adopted === false) {
      status.classList.add("status-rejected");
      status.textContent = "未采用 · 不满足约束";
    } else {
      status.classList.add("status-pending");
      status.textContent = "待建议";
    }
    tr.dataset.state = [...status.classList].find((name) => name.startsWith("status-")) || "pending";
    tr.dataset.adopted = status.classList.contains("status-adopted") ? "true" : "false";
    statusCell.append(status);
    tr.append(statusCell);

    const actionCell = document.createElement("td");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-mark";
    remove.dataset.markId = mark.id;
    remove.setAttribute("aria-label", `删除标点 ${index + 1}`);
    remove.textContent = "×";
    actionCell.append(remove);
    tr.append(actionCell);

    rows.append(tr);
  });
  renderFitSummary();
}

function pointLabel(point) {
  const parts = [
    "(" + point.x + ", " + point.y + ")",
    "原 RGB " + point.rgb.join("/"),
    "亮度 " + point.brightness.toFixed(2),
    "距当前中心 " + point.distance_mm.toFixed(2) + " mm",
  ];
  if (point.marked) {
    const difference = point.radius_difference_px ?? point.radius_error_px;
    const signed = point.radius_delta_px ?? point.signed_radius_difference_px;
    const limit = point.tolerance_px;
    if (point.rgb_clipped) {
      parts.push("我标过的点：不采用（任一 RGB 通道为 0 或 255）");
    } else if (point.adopted === true) {
      parts.push("我标过的点：采用");
      parts.push("实际半径差绝对值 " + formatError(difference) + " px" +
        "（有符号 " + (Number(signed) >= 0 ? "+" : "") + formatError(signed) +
        " / 限差 " + formatError(limit) + " px）");
    } else if (point.adopted === false) {
      parts.push("我标过的点：未采用");
      if (Number.isFinite(Number(difference))) {
        parts.push("实际半径差绝对值 " + formatError(difference) + " px" +
          "（有符号 " + (Number(signed) >= 0 ? "+" : "") + formatError(signed) +
          " / 限差 " + formatError(limit) + " px）");
      }
    } else {
      parts.push("我标过的点：已保存，尚未采用拟合");
    }
  } else if (point.rgb_clipped) {
    parts.push("RGB 含 0 或 255；若标为明纹点也不会采用");
  }
  return parts.join(" · ");
}

function show() {
  const {card, result} = state;
  state.marks = card.ring_marks || result.ring_marks || result.ring?.marks || [];
  state.ring = result.ring || null;
  state.fit = card.ring_fit || result.ring_fit || result.ring?.fit || null;
  state.fitStale = false;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.reading?.x ?? card.settings.center_x;
  get("probe-y").value = state.probe?.y ?? result.reading?.y ?? card.settings.center_y;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const reading = result.reading;
  get("radius-value").textContent = reading ? reading.r_mm.toFixed(2) : "—";
  get("radius-unit").textContent = "mm";
  get("measurement-state").textContent = "径线 " + result.focus + "°";
  get("selected-level").textContent = reading
    ? reading.r_px + " px · 原片 (" + reading.x + ", " + reading.y + ") · 亮度 " + reading.brightness.toFixed(2)
    : "这个方向未覆盖原片像素";
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/rippletrace" + route("/export/" + filename) + savedQuery();
  }
  renderMarks();
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/rippletrace" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null});
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

async function persistMarks() {
  const card = await api(route(""), {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, ring_marks: state.marks}),
  });
  state.card = card;
  state.marks = card.ring_marks || state.marks;
  return card;
}

async function addMarkFromProbe(x, y) {
  const existing = state.marks.find((mark) => mark.x === x && mark.y === y);
  if (existing) {
    notice("这个原片坐标已经标过；可在标点表中修改容差。", "fit-summary");
    return;
  }
  state.marks.push({
    id: "web-" + Date.now() + "-" + Math.random().toString(16).slice(2, 8),
    x, y, tolerance_px: 2,
    rgb: state.probe?.rgb || null,
  });
  state.fitStale = true;
  renderMarks();
  paintSource();
  await persistMarks();
  show();
  state.fitStale = true;
  renderFitSummary();
  notice("已保存标点。请填写该点可差的最大像素数，然后点击“建议圆心（整数）与拟合半径”。", "fit-summary");
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
  action(async () => {
    await probe(x, y);
    if (state.mode === "ring") {
      await addMarkFromProbe(x, y);
      return;
    }
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

get("mark-rows").addEventListener("input", (event) => {
  const input = event.target.closest(".mark-tolerance");
  if (!input) return;
  const mark = state.marks.find((item) => String(item.id) === input.dataset.markId);
  if (!mark) return;
  const value = Number(input.value);
  if (Number.isFinite(value) && value >= 0) mark.tolerance_px = value;
});

get("mark-rows").addEventListener("change", (event) => {
  const input = event.target.closest(".mark-tolerance");
  if (!input) return;
  const mark = state.marks.find((item) => String(item.id) === input.dataset.markId);
  const value = Number(input.value);
  if (!mark || !Number.isFinite(value) || value < 0) {
    input.value = mark?.tolerance_px ?? 2;
    notice("容差必须是不小于 0 的像素数。", "fit-summary");
    return;
  }
  mark.tolerance_px = value;
  state.fitStale = true;
  renderFitSummary();
});

get("mark-rows").addEventListener("click", (event) => {
  const button = event.target.closest(".remove-mark");
  if (!button) return;
  action(async () => {
    state.marks = state.marks.filter((item) => String(item.id) !== button.dataset.markId);
    state.fitStale = true;
    await persistMarks();
    show();
    state.fitStale = true;
    renderFitSummary();
    paintSource();
  }, "fit-summary");
});

get("clear-marks").addEventListener("click", () => action(async () => {
  state.marks = [];
  state.fit = null;
  state.ring = null;
  state.fitStale = false;
  const card = await api(route(""), {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      revision: state.card.revision,
      ring_marks: [],
      ring_fit: null,
    }),
  });
  await open(card);
}, "fit-summary"));

get("suggest-fit").addEventListener("click", () => action(async () => {
  if (!state.marks.length) throw new Error("请先在“标明纹点”模式下点至少四处。");
  for (const mark of state.marks) {
    if (!Number.isFinite(Number(mark.tolerance_px)) || Number(mark.tolerance_px) < 0) {
      throw new Error("每个标点都要填写不小于 0 的最大像素差。");
    }
  }
  const fit = await api(route("/ring-fit/suggest"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, marks: state.marks}),
  });
  state.fit = fit;
  state.fitStale = false;
  renderMarks();
  renderFitSummary();
  paintSource();
}, "fit-summary"));

get("apply-fit").addEventListener("click", () => action(async () => {
  if (!state.fit?.feasible) throw new Error("请先得到可行建议。");
  const card = await api(route("/ring-fit/apply"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, marks: state.marks}),
  });
  await open(card);
  await library();
  notice("已采用新整数圆心；原片测量图和径向图均已按新中心重新读取。", "fit-summary");
}, "fit-summary"));
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [
      field.dataset.setting, Number(field.value),
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
