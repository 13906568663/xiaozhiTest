/* 闪购派单中心 管理后台前端(无依赖,轮询刷新) */

const $ = (sel) => document.querySelector(sel);
let state = null;

// ── 请求封装 ──────────────────────────────

async function api(path, options) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = `请求失败(${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => (el.className = "toast"), 3200);
}

async function act(fn) {
  try {
    const result = await fn();
    if (result && result.message) toast(result.message);
    await refresh();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── 渲染 ─────────────────────────────────

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderStats() {
  const s = state.stats;
  $("#statChips").innerHTML = `
    <div class="statchip"><b>${s.pending_count}</b>待接单</div>
    <div class="statchip"><b>${s.active_count}</b>在途</div>
    <div class="statchip"><b>${s.delivered_count}</b>已送达</div>
    <div class="statchip"><b>¥${s.income}</b>今日收入</div>
    <div class="statchip"><b>${s.late_count}</b>超时单</div>
    <div class="statchip"><b>${s.total_wait_minutes}分</b>累计干等</div>`;
}

function pickupRow(order, p) {
  const readyText = p.status === "PICKED"
    ? ""
    : p.is_ready
      ? '<span class="ready-ok">✔ 已备好</span>'
      : `<span class="ready-wait">⏳ 还需 ${p.ready_in_minutes.toFixed(1)} 分备货</span>`;
  const waited = p.wait_minutes > 0 ? `<span class="waited">干等 ${p.wait_minutes} 分</span>` : "";
  const actionable = order.status === "ACCEPTED" || order.status === "DELIVERING";
  let buttons = "";
  if (actionable && p.status === "PENDING") {
    buttons = `<button class="mini-btn" onclick="orderAction('${order.id}','arrive_shop','${p.shop_id}')">到店</button>
               <button class="mini-btn" onclick="orderAction('${order.id}','pick_up','${p.shop_id}')">取货</button>`;
  } else if (actionable && p.status === "ARRIVED") {
    buttons = `<button class="mini-btn" onclick="orderAction('${order.id}','pick_up','${p.shop_id}')">取货</button>`;
  }
  return `<div class="pickup">
    <span class="shop">${esc(p.shop_name)}</span>
    <span class="pk-status">[${p.status_label}]</span>
    ${readyText}
    <span class="travel">骑行 ${p.travel_from_rider_minutes} 分</span>
    ${waited}
    ${buttons}
    <span class="items">${esc(p.items.join("、"))}</span>
  </div>`;
}

function orderCard(order) {
  const deadline = order.overdue
    ? `<span class="overdue-text">已超时 ${Math.abs(order.deadline_left_minutes).toFixed(1)} 分!</span>`
    : `剩 ${order.deadline_left_minutes.toFixed(1)} 分`;
  let actions = "";
  if (order.status === "PENDING") {
    actions = `<button class="mini-btn" onclick="orderAction('${order.id}','accept')">接单</button>
               <button class="mini-btn gray" onclick="orderAction('${order.id}','reject')">拒单</button>`;
  } else if (order.status === "DELIVERING") {
    actions = `<button class="mini-btn" onclick="orderAction('${order.id}','deliver')">送达</button>`;
  }
  const lateBadge = order.late ? '<span class="badge late">超时送达</span>' : "";
  return `<div class="order-card st-${order.status}${order.overdue ? " overdue" : ""}">
    <div class="order-head">
      <span class="order-id">${order.id}</span>
      <span class="badge">${esc(order.kind)}</span>
      <span class="badge status-${order.status}">${order.status_label}</span>
      ${lateBadge}
      <span class="order-fee">¥${order.delivery_fee}</span>
    </div>
    <div class="order-buyer">📍 ${esc(order.buyer.name)} · ${esc(order.buyer.address)}
      <span class="travel">(骑手过去 ${order.travel_to_buyer_from_rider_minutes} 分)</span></div>
    <div class="order-deadline">时限 ${order.deadline} · ${deadline}</div>
    ${order.pickups.map((p) => pickupRow(order, p)).join("")}
    ${actions ? `<div class="order-actions">${actions}</div>` : ""}
  </div>`;
}

function renderOrders() {
  const orders = state.orders;
  $("#orderCount").textContent = `共 ${orders.length} 单`;
  $("#orderList").innerHTML = orders.length
    ? orders.map(orderCard).join("")
    : '<div class="card muted">暂无订单,点击上方按钮生成</div>';
}

function renderEvents() {
  const actorClass = (actor) =>
    actor.includes("AI") ? "actor-ai" : actor === "管理后台" ? "actor-admin" : actor === "自动派单" ? "actor-auto" : "actor-sys";
  $("#eventList").innerHTML = state.events
    .map((e) => `<div class="event"><time>${e.time}</time><span class="actor ${actorClass(e.actor)}">${esc(e.actor)}</span><span>${esc(e.text)}</span></div>`)
    .join("") || '<div class="muted">暂无事件</div>';
}

function renderRider() {
  const r = state.rider;
  const s = state.stats;
  $("#riderCard").innerHTML = `<b>🛵 ${esc(r.name)}</b><br/>
    当前位置:${esc(r.location)}<br/>
    在途订单:${s.active_count} 单 · 已完成:${s.delivered_count} 单 · 收入:¥${s.income}`;
}

// ── 地图 ─────────────────────────────────

const WORLD = 5000, PAD = 30;
function toCanvas(v, size) { return PAD + (v / WORLD) * (size - PAD * 2); }

function drawMap() {
  const canvas = $("#map");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  ctx.strokeStyle = "#eef1f6";
  ctx.lineWidth = 1;
  for (let m = 0; m <= WORLD; m += 1000) {
    const x = toCanvas(m, W);
    ctx.beginPath(); ctx.moveTo(x, PAD); ctx.lineTo(x, H - PAD); ctx.stroke();
    const y = toCanvas(m, H);
    ctx.beginPath(); ctx.moveTo(PAD, y); ctx.lineTo(W - PAD, y); ctx.stroke();
  }

  // 在途订单路线(骑手 → 未取点 → 买家)
  const colors = ["#ff7e32", "#9b51e0", "#13c2c2", "#2f80ed", "#eb2f96"];
  const active = state.orders.filter((o) => o.status === "ACCEPTED" || o.status === "DELIVERING");
  active.forEach((o, i) => {
    ctx.strokeStyle = colors[i % colors.length] + "88";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(toCanvas(state.rider.x, W), toCanvas(state.rider.y, H));
    o.pickups.filter((p) => p.status !== "PICKED").forEach((p) => ctx.lineTo(toCanvas(p.x, W), toCanvas(p.y, H)));
    ctx.lineTo(toCanvas(o.buyer.x, W), toCanvas(o.buyer.y, H));
    ctx.stroke();
    ctx.setLineDash([]);
  });

  const label = (text, x, y, color) => {
    ctx.fillStyle = color;
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(text, x, y);
  };

  state.shops.forEach((s) => {
    const x = toCanvas(s.x, W), y = toCanvas(s.y, H);
    ctx.fillStyle = s.category === "充电宝" ? "#13c2c2" : "#ff7e32";
    ctx.fillRect(x - 6, y - 6, 12, 12);
    label(s.name, x, y - 11, "#8c5b3f");
  });

  state.buyers.forEach((b) => {
    const x = toCanvas(b.x, W), y = toCanvas(b.y, H);
    ctx.fillStyle = "#2f80ed";
    ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
    label(b.name, x, y + 20, "#2f5c9e");
  });

  const rx = toCanvas(state.rider.x, W), ry = toCanvas(state.rider.y, H);
  ctx.fillStyle = "#faad14";
  ctx.beginPath(); ctx.arc(rx, ry, 9, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
  ctx.font = "13px sans-serif";
  ctx.fillText("🛵", rx - 7, ry + 4);
  label(state.rider.name, rx, ry - 14, "#b07908");
}

// ── 控件 ─────────────────────────────────

window.orderAction = (orderId, type, shopId = "") => {
  const body = { type, shop_id: shopId };
  if (type === "reject") body.reason = prompt("拒单原因(可留空):") || "";
  act(() => api(`/orders/${orderId}/action`, { method: "POST", body: JSON.stringify(body) }));
};

$("#btnPreset").onclick = () => act(async () => {
  const r = await api("/orders/preset", { method: "POST" });
  return { message: `演示场景已生成:${r.created.join(" / ")}` };
});
$("#btnRandom").onclick = () => act(() => api("/orders/random", { method: "POST" }));
$("#btnReset").onclick = () => {
  if (confirm("确认清空所有订单和事件,恢复初始状态?")) {
    act(() => api("/reset", { method: "POST" }));
  }
};

$("#autogenSwitch").onchange = applyAutogen;
$("#autogenInterval").onchange = applyAutogen;
function applyAutogen() {
  act(() => api("/autogen", {
    method: "POST",
    body: JSON.stringify({
      enabled: $("#autogenSwitch").checked,
      interval_seconds: Number($("#autogenInterval").value) || 40,
    }),
  }));
}

$("#scaleGroup").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-scale]");
  if (btn) act(() => api("/clock", { method: "POST", body: JSON.stringify({ scale: Number(btn.dataset.scale) }) }));
});

// ── 主循环 ───────────────────────────────

async function refresh() {
  try {
    state = await api("/state");
  } catch (e) {
    return; // 服务暂不可达,下个周期再试
  }
  $("#simClock").textContent = state.sim_time;
  document.querySelectorAll("#scaleGroup button").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.scale) === state.time_scale);
  });
  const sw = $("#autogenSwitch");
  if (document.activeElement !== sw) sw.checked = state.autogen.enabled;
  renderStats();
  renderOrders();
  renderEvents();
  renderRider();
  drawMap();
}

refresh();
setInterval(refresh, 2000);
