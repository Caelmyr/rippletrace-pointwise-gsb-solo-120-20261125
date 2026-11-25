"use strict";

const get = (id) => document.getElementById(id);
const state = {
  card: null, result: null, photo: null, probe: null,
  mode: "probe", chart: "profile", busy: false,
  anchorRadius: null, trace: null, adopted: null,
  ray: null, inspectAngle: null,
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

function activeResult() {
  return state.ray || state.result;
}

function activeReading() {
  if (state.ray && state.adopted) {
    if (state.inspectAngle === null || state.inspectAngle === undefined) return null;
    return state.adopted.byAngle?.[state.inspectAngle] || null;
  }
  return activeResult()?.reading || null;
}

function setChartMode(mode) {
  state.chart = mode;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item.dataset.chart === mode)));
}

function chartPointFromEvent(event, lo, hi) {
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * canvas.width / rect.width;
  const y = (event.clientY - rect.top) * canvas.height / rect.height;
  const ratio = Math.max(0, Math.min(1, (x - 44) / Math.max(1, canvas.width - 81)));
  return {x, y, value: lo + ratio * (hi - lo)};
}

function angularDistance(a, b) {
  return Math.abs(((Number(a) - Number(b) + 540) % 360) - 180);
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
    const targetElement = get(target);
    if (targetElement) targetElement.dataset.tone = "error";
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
  const {photo, card, probe, adopted} = state;
  if (!photo) return;
  const view = activeResult();
  const reading = activeReading();
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
  if (view?.profile?.length) {
    ctx.strokeStyle = "#8de0cf";
    ctx.lineWidth = 2;
    ctx.beginPath();
    view.profile.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
  }
  if (adopted?.steps?.length) {
    ctx.strokeStyle = "#f0a35e";
    ctx.lineWidth = 2;
    ctx.beginPath();
    let drawing = false;
    for (const step of adopted.steps) {
      if (!step.peak) {
        drawing = false;
        continue;
      }
      if (drawing) ctx.lineTo(step.peak.x, step.peak.y);
      else ctx.moveTo(step.peak.x, step.peak.y);
      drawing = true;
    }
    ctx.stroke();
    for (const step of adopted.steps) {
      if (!step.peak) continue;
      ctx.fillStyle = "#f6c177";
      ctx.beginPath();
      ctx.arc(step.peak.x, step.peak.y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  if (reading) {
    ctx.strokeStyle = "#ffc487";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(reading.x, reading.y, 6, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(reading.x - 10, reading.y);
    ctx.lineTo(reading.x + 10, reading.y);
    ctx.moveTo(reading.x, reading.y - 10);
    ctx.lineTo(reading.x, reading.y + 10);
    ctx.stroke();
  }
  if (probe) {
    ctx.strokeStyle = "#f5e5e9";
    ctx.strokeRect(probe.x - 6, probe.y - 6, 12, 12);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const {result, card, adopted} = state;
  const view = activeResult();
  const reading = activeReading();
  const cfg = card.settings;
  const angular = state.chart === "coverage";
  const lo = angular ? 0 : cfg.inner;
  const hi = angular ? 355 : cfg.outer;
  const bound = angular ? cfg.outer : 255;
  const xAt = (x) => 44 + (width - 81) * (x - lo) / Math.max(1, hi - lo);
  const yAt = (y) => height - 26 - (height - 46) * y / bound;
  get("chart-title").textContent = angular ? "各方向最亮半径 · 跟踪建议" : `单径向亮度 · ${view.focus}°`;
  get("chart-caption").textContent = angular
    ? "半径 px · 顺时针角度 · 橙线为跟踪链，点击方向查看实际峰"
    : "实际像素亮度 · 半径 px · 点击剖面确认起步半径";
  ctx.fillStyle = "#eff6fc";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#3b536c";
  ctx.strokeStyle = "#ccdeeb";
  ctx.lineWidth = 1;
  for (const level of [0, Math.round(bound / 2), bound]) {
    ctx.fillText(level, 8, yAt(level) + 3);
    ctx.beginPath();
    ctx.moveTo(xAt(lo), yAt(level));
    ctx.lineTo(xAt(hi), yAt(level));
    ctx.stroke();
  }
  ctx.fillText(String(lo), xAt(lo), height - 7);
  ctx.fillText(String(hi), xAt(hi) - 15, height - 7);

  if (angular) {
    const observed = result.angular.map((row) => [row.angle, row.peak?.r_px ?? null]);
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

    const preview = adopted || state.trace?.suggestion ||
      (state.trace && !state.trace.can_suggest ? state.trace : null);
    const steps = preview?.steps || preview?.directions || [];
    if (steps.length) {
      const tentative = !adopted && !state.trace?.suggestion;
      ctx.lineWidth = adopted ? 3 : 2;
      ctx.strokeStyle = tentative ? "#8a98a8" : "#c96f2c";
      ctx.setLineDash(tentative ? [4, 4] : adopted ? [] : [7, 4]);
      ctx.beginPath();
      let previousAngle = null;
      for (const step of steps) {
        if (!step.peak) {
          previousAngle = null;
          continue;
        }
        const px = xAt(step.angle);
        const py = yAt(step.peak.r_px);
        if (previousAngle !== null && step.angle >= previousAngle) ctx.lineTo(px, py);
        else ctx.moveTo(px, py);
        previousAngle = step.angle;
      }
      ctx.stroke();
      ctx.setLineDash([]);
      for (const step of steps) {
        if (!step.peak) continue;
        ctx.fillStyle = tentative ? "#8a98a8" : "#c96f2c";
        ctx.beginPath();
        ctx.arc(xAt(step.angle), yAt(step.peak.r_px), adopted ? 4 : 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    if (state.inspectAngle !== null && state.inspectAngle !== undefined) {
      ctx.strokeStyle = adopted && !reading ? "#9aa7b4" : "#7d3f16";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(xAt(state.inspectAngle), yAt(0));
      ctx.lineTo(xAt(state.inspectAngle), yAt(bound));
      ctx.stroke();
      ctx.setLineDash([]);
      if (reading) {
        ctx.fillStyle = "#b45309";
        ctx.beginPath();
        ctx.arc(xAt(reading.angle ?? state.inspectAngle), yAt(reading.r_px), 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#fff4e6";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  } else {
    const observed = view.profile.map((point) => [point.r_px, point.brightness]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#4674a3";
    ctx.beginPath();
    observed.forEach(([position, level], index) => {
      if (index === 0) ctx.moveTo(xAt(position), yAt(level));
      else ctx.lineTo(xAt(position), yAt(level));
    });
    ctx.stroke();

    if (state.anchorRadius !== null && state.anchorRadius !== undefined) {
      ctx.strokeStyle = "#7d94aa";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(xAt(state.anchorRadius), yAt(0));
      ctx.lineTo(xAt(state.anchorRadius), yAt(bound));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#536b84";
      ctx.fillText("r=" + state.anchorRadius, xAt(state.anchorRadius) + 4, 14);
    }
    if (reading) {
      ctx.fillStyle = "#b46d47";
      ctx.beginPath();
      ctx.arc(xAt(reading.r_px), yAt(reading.brightness), 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#fff2df";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    } else if (state.ray && state.adopted) {
      ctx.fillStyle = "#7a8794";
      ctx.font = "13px sans-serif";
      ctx.fillText("这个方向未跟到，峰位留空", xAt(lo) + 10, 24);
    }
  }
}

function pointLabel(point) {
  const distanceMm = point.distance_mm ?? point.r_mm ?? 0;
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · 距中心 " + distanceMm.toFixed(2) + " mm";
}

function show() {
  const {card, result} = state;
  const view = activeResult();
  const reading = activeReading();
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) {
    if (field.dataset.setting === "angle" && state.ray) {
      field.value = view.focus;
    } else {
      field.value = card.settings[field.dataset.setting];
    }
  }
  if (state.anchorRadius === null || state.anchorRadius === undefined) {
    state.anchorRadius = result.reading?.r_px ?? card.settings.inner;
  }
  get("trace-radius").min = card.settings.inner;
  get("trace-radius").max = card.settings.outer;
  if (document.activeElement !== get("trace-radius")) {
    get("trace-radius").value = state.anchorRadius;
  }
  get("trace-adopt").hidden = !state.trace?.suggestion || Boolean(state.adopted);
  get("trace-clear").hidden = !state.trace && !state.adopted;
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? reading?.x ?? card.settings.center_x;
  get("probe-y").value = state.probe?.y ?? reading?.y ?? card.settings.center_y;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  get("radius-value").textContent = reading && reading.r_mm !== undefined ? reading.r_mm.toFixed(2) : "—";
  get("radius-unit").textContent = "mm";
  get("measurement-state").textContent = "径线 " + view.focus + "°";
  if (state.adopted && state.ray && !reading) {
    get("selected-level").textContent = "这个方向未跟到；跟踪峰和原片亮点留空";
  } else {
    get("selected-level").textContent = reading
      ? reading.r_px + " px · 原片 (" + reading.x + ", " + reading.y + ") · 亮度 " + reading.brightness.toFixed(2)
      : "这个方向未覆盖原片像素";
  }
  const selected = get("selected-level");
  selected.dataset.angle = String(state.inspectAngle ?? view.focus ?? "");
  selected.dataset.rPx = reading?.r_px ?? "";
  selected.dataset.x = reading?.x ?? "";
  selected.dataset.y = reading?.y ?? "";
  selected.dataset.tracked = reading && state.adopted ? "true" : "false";
  get("measurement-state").dataset.angle = selected.dataset.angle;
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/rippletrace" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/rippletrace" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {
    card, result, photo, probe: null,
    anchorRadius: result.reading?.r_px ?? card.settings.inner,
    trace: null, adopted: null, ray: null, inspectAngle: null,
  });
  get("trace-status").textContent = "可直接点上方径向剖面确认原半径步。";
  get("trace-status").dataset.tone = "";
  get("library").value = card.id;
  setChartMode("profile");
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

function selectAnchorFromChart(event) {
  const cfg = state.card.settings;
  const position = chartPointFromEvent(event, cfg.inner, cfg.outer);
  const radius = Math.max(cfg.inner, Math.min(cfg.outer, Math.round(position.value)));
  const view = activeResult();
  const sourcePoint = view.profile.find((point) => point.r_px === radius);
  state.anchorRadius = radius;
  get("trace-radius").value = radius;
  if (sourcePoint) {
    state.probe = sourcePoint;
    get("probe-x").value = sourcePoint.x;
    get("probe-y").value = sourcePoint.y;
    get("probe-result").textContent = pointLabel(sourcePoint);
  }
  notice(`已确认 ${view.focus}° 径线上的原半径步 ${radius} px。`, "trace-status");
  get("trace-status").dataset.tone = "ok";
  paintChart();
  paintSource();
}

async function selectAngleFromChart(event) {
  const position = chartPointFromEvent(event, 0, 355);
  const rawAngle = Math.max(0, Math.min(355, position.value));
  let angle = ((Math.round(rawAngle / 5) * 5) % 360 + 360) % 360;
  let tracePoint = state.adopted?.byAngle?.[angle] || null;

  if (state.adopted?.steps?.length) {
    let nearest = null;
    let nearestDistance = 3.01;
    for (const step of state.adopted.steps) {
      if (!step.peak) continue;
      const distance = angularDistance(rawAngle, step.angle);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = step;
      }
    }
    if (nearest) {
      angle = nearest.angle;
      tracePoint = nearest.peak;
    } else {
      tracePoint = null;
    }
  }

  const ray = await api(route("/measurement") + savedQuery() + "&angle=" + angle);
  state.ray = ray;
  state.inspectAngle = angle;
  state.probe = state.adopted ? (tracePoint || null) : ray.reading;
  setChartMode("profile");
  show();
  if (state.adopted && !tracePoint) {
    notice(`${angle}° 不在已跟到的方向中；峰位留空，没有跨过断点。`, "trace-status");
    get("trace-status").dataset.tone = "";
  } else if (tracePoint) {
    notice(`${angle}° · 实际峰 ${tracePoint.r_px} px / 原片 (${tracePoint.x}, ${tracePoint.y})。`, "trace-status");
    get("trace-status").dataset.tone = "ok";
  }
}

async function runTrace() {
  const radius = Number(get("trace-radius").value);
  const cfg = state.card.settings;
  if (!Number.isInteger(radius) || radius < cfg.inner || radius > cfg.outer) {
    throw new Error(`起步半径须是 ${cfg.inner}–${cfg.outer} px 之间的整数原半径步。`);
  }
  const angle = activeResult()?.focus ?? cfg.angle;
  state.anchorRadius = radius;
  const trace = await api(route("/trace") + savedQuery() +
    "&angle=" + angle + "&r_px=" + radius);
  state.trace = trace;
  state.adopted = null;
  state.ray = null;
  state.inspectAngle = null;
  setChartMode("coverage");
  get("trace-adopt").hidden = !trace.suggestion;
  get("trace-clear").hidden = false;
  if (trace.suggestion) {
    notice(`已连续跟到 ${trace.followed_directions} 个后续方向（${trace.suggestion.turn_degrees}°），可采用建议。`, "trace-status");
    get("trace-status").dataset.tone = "ok";
  } else {
    notice(`只连续跟到 ${trace.followed_directions} 个后续方向；至少跟到三个后续方向才给建议，断点后已留空。`, "trace-status");
    get("trace-status").dataset.tone = "error";
  }
  show();
}

function adoptTrace() {
  const suggestion = state.trace?.suggestion;
  if (!suggestion) return;
  const byAngle = {};
  for (const step of suggestion.steps || []) {
    if (step.peak) byAngle[step.angle] = step.peak;
  }
  state.adopted = {...suggestion, byAngle};
  state.ray = null;
  state.inspectAngle = null;
  get("trace-adopt").hidden = true;
  get("trace-clear").hidden = false;
  setChartMode("coverage");
  notice("已采用。点击按角度图上的方向，查看该方向径向剖面和原片实际峰；未跟到的方向留空。", "trace-status");
  get("trace-status").dataset.tone = "ok";
  show();
}

function clearTrace() {
  state.trace = null;
  state.adopted = null;
  state.ray = null;
  state.inspectAngle = null;
  get("trace-adopt").hidden = true;
  get("trace-clear").hidden = true;
  get("trace-status").textContent = "可直接点上方径向剖面确认原半径步。";
  get("trace-status").dataset.tone = "";
  setChartMode("profile");
  show();
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
    if (state.mode === "anchor" && state.card) {
      const cfg = state.card.settings;
      const radius = Math.max(cfg.inner, Math.min(cfg.outer,
        Math.round(Math.hypot(x - cfg.center_x, y - cfg.center_y))));
      state.anchorRadius = radius;
      get("trace-radius").value = radius;
      notice(`已确认当前径线上的原半径步 ${radius} px；点击“跟踪这条水纹”继续。`, "trace-status");
      get("trace-status").dataset.tone = "ok";
      paintChart();
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
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
  setChartMode(button.dataset.chart);
  if (state.card) paintChart();
}));
get("chart").addEventListener("click", (event) => {
  if (!state.card || state.busy) return;
  if (state.chart === "profile") selectAnchorFromChart(event);
  else action(() => selectAngleFromChart(event));
});
get("trace-run").addEventListener("click", () => action(runTrace, "trace-status"));
get("trace-adopt").addEventListener("click", () => action(adoptTrace, "trace-status"));
get("trace-clear").addEventListener("click", () => action(clearTrace, "trace-status"));
get("trace-radius").addEventListener("change", () => {
  const radius = Number(get("trace-radius").value);
  if (Number.isInteger(radius)) state.anchorRadius = radius;
});
action(library);
