"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = { snapshot: null, view: "ports", filter: "all", query: "", protocol: "all", containerQuery: "" };
let toastTimer;

const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2200);
}

function snapshotAgeSeconds(snapshot) {
  if (!snapshot?.generated_at) return Infinity;
  const timestamp = Date.parse(snapshot.generated_at);
  return Number.isFinite(timestamp) ? Math.max(0, (Date.now() - timestamp) / 1000) : Infinity;
}

function sourcesHealthy(snapshot) {
  return !!snapshot && snapshotAgeSeconds(snapshot) < 30 &&
    snapshot.sources?.docker === true && snapshot.sources?.linux === true;
}

function updateStatus() {
  const snap = state.snapshot;
  const healthy = sourcesHealthy(snap);
  const age = snapshotAgeSeconds(snap);
  $("#server-name").textContent = snap?.hostname || "Sin identificar";
  $("#server-state").textContent = healthy ? "Lectura completa" : snap ? "Lectura incompleta o antigua" : "Esperando el recolector";
  $("#side-dot").classList.toggle("online", healthy);
  $(".pulse-dot").classList.toggle("online", healthy);
  $("#top-status").textContent = healthy ? "Datos en directo" : "Revisar conexión";
  $("#last-updated").textContent = Number.isFinite(age)
    ? `Lectura hace ${Math.floor(age)} s` : "Esperando primera lectura";

  const messages = [];
  if (Number.isFinite(age) && age >= 30) messages.push("La lectura tiene más de 30 segundos. Es posible que el recolector esté detenido.");
  for (const error of snap?.errors || []) messages.push(error);
  for (const warning of snap?.warnings || []) messages.push(warning);
  if (!snap) messages.push("Todavía no hay un inventario disponible. Comprueba el estado del contenedor collector.");
  const notice = $("#notice");
  notice.textContent = messages.join("\n");
  notice.classList.toggle("hidden", messages.length === 0);
}

function portRows() {
  let rows = state.snapshot?.ports || [];
  if (state.filter !== "all") rows = rows.filter((row) => row.owner_type === state.filter);
  if (state.protocol !== "all") rows = rows.filter((row) => row.protocol === state.protocol);
  const needle = state.query.trim().toLowerCase();
  if (needle) rows = rows.filter((row) => [
    row.port, row.protocol, row.address, row.service, row.process,
    row.image, row.project, row.target_port, row.pid,
  ].some((item) => String(item ?? "").toLowerCase().includes(needle)));
  return rows;
}

function serviceBadge(row) {
  const docker = row.owner_type === "docker";
  const service = escapeHTML(row.service || "Desconocido");
  const detail = docker
    ? (row.project ? `Compose · ${row.project}` : row.image || "Contenedor Docker")
    : (row.pid ? `PID ${row.pid}` : "Nombre no disponible");
  return `<div class="service-cell"><div class="service-icon ${docker ? "docker" : "host"}">${docker ? "⬡" : "⌁"}</div><div><div class="service-primary" title="${service}">${service}</div><div class="service-secondary" title="${escapeHTML(detail)}">${escapeHTML(detail)}</div></div></div>`;
}

function renderPorts() {
  const snap = state.snapshot;
  const rows = portRows();
  const counts = snap?.counts || {};
  $("#metric-ports").textContent = counts.unique_ports ?? "—";
  $("#metric-docker").textContent = snap?.sources?.docker ? (counts.docker_bindings ?? 0) : "—";
  $("#metric-host").textContent = snap?.sources?.linux ? (counts.host_sockets ?? 0) : "—";
  $("#metric-containers").textContent = snap?.sources?.docker ? (counts.containers_running ?? 0) : "—";
  $("#metric-containers-total").textContent = snap?.sources?.docker ? (counts.containers_total ?? 0) : "—";
  $("#nav-ports").textContent = counts.unique_ports ?? "—";
  $("#nav-containers").textContent = snap?.sources?.docker ? (counts.containers_total ?? 0) : "—";
  $("#table-count").textContent = `${rows.length} ${rows.length === 1 ? "asignación" : "asignaciones"}`;

  $("#port-rows").innerHTML = rows.length ? rows.map((row) => {
    const label = row.owner_type === "docker" ? "Docker" : "Sistema";
    const details = row.target_port != null ? `→ ${row.target_port}/${escapeHTML(row.protocol)}` :
      row.scope === "local" ? "Solo loopback" : row.scope === "all" ? "Todas las interfaces" : "Interfaz específica";
    const copyValue = `${row.address}:${row.port}/${row.protocol}`;
    return `<tr>
      <td><span class="port-number">${escapeHTML(row.port)}</span></td>
      <td>${serviceBadge(row)}</td>
      <td><span class="type-badge ${row.owner_type === "host" ? "host" : ""}">${label}</span></td>
      <td><div class="binding-main">${escapeHTML(row.address)}:${escapeHTML(row.port)}</div><div class="binding-sub">${details}</div></td>
      <td><span class="protocol-pill">${escapeHTML(row.protocol)}</span></td>
      <td><button class="copy-button" type="button" title="Copiar dirección y puerto" aria-label="Copiar dirección y puerto" data-copy="${escapeHTML(copyValue)}"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg></button></td>
    </tr>`;
  }).join("") : `<tr><td class="empty-cell" colspan="6">${snap ? "No hay puertos que coincidan con los filtros." : "Esperando información del servidor…"}</td></tr>`;
}

function renderContainers() {
  const snap = state.snapshot;
  const containers = (snap?.containers || []).filter((item) => [
    item.name, item.image, item.project, item.compose_service, item.status,
  ].some((value) => String(value || "").toLowerCase().includes(state.containerQuery.trim().toLowerCase())));
  $("#container-list-total").textContent = `${containers.length} contenedores`;
  $("#container-list").innerHTML = containers.length ? containers.map((container) => {
    const running = container.status === "running";
    return `<div class="container-item">
      <div class="container-avatar">⬡</div>
      <div class="container-info">
        <div class="container-name" title="${escapeHTML(container.name)}">${escapeHTML(container.name)}</div>
        <div class="container-image" title="${escapeHTML(container.image)}">${escapeHTML(container.image || "Imagen no disponible")}</div>
        <div class="container-tags">
          <span class="container-tag ${running ? "running" : "stopped"}">${running ? "● En ejecución" : escapeHTML(container.status)}</span>
          <span class="container-tag">${container.published_count} ${container.published_count === 1 ? "publicación" : "publicaciones"}</span>
          ${container.project ? `<span class="container-tag">${escapeHTML(container.project)}</span>` : ""}
          ${container.network_mode === "host" ? '<span class="container-tag">Red host</span>' : ""}
        </div>
      </div>
    </div>`;
  }).join("") : `<div class="empty-cell">${snap?.sources?.docker ? "No hay contenedores que coincidan." : "Docker no ha proporcionado información."}</div>`;
}

function render() {
  updateStatus();
  renderPorts();
  renderContainers();
  if (!$("#check-result").classList.contains("hidden")) checkPort();
}

async function refresh() {
  $("#refresh-button").classList.add("loading");
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data?.ready || !Array.isArray(data.ports)) throw new Error("Datos incompletos");
    state.snapshot = data;
  } catch (error) {
    // Retain the last successful snapshot, but mark it as potentially stale.
    if (!state.snapshot) console.warn("Esperando inventario:", error.message);
  } finally {
    $("#refresh-button").classList.remove("loading");
    render();
  }
}

function checkPort() {
  const output = $("#check-result");
  const input = $("#check-port");
  const port = Number(input.value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    output.className = "check-result unknown";
    output.textContent = "Introduce un número de puerto entre 1 y 65535.";
    return;
  }
  const protocol = $("#check-protocol").value;
  const snap = state.snapshot;
  const matches = (snap?.ports || []).filter((row) => row.port === port && row.protocol === protocol);
  if (matches.length) {
    output.className = "check-result busy";
    const owners = matches.slice(0, 3).map((row) => `${row.service} (${row.address})`).join(", ");
    output.textContent = `${port}/${protocol.toUpperCase()}: ${matches.length} coincidencia(s) detectada(s). ${owners}${matches.length > 3 ? "…" : ""}. Revisa las direcciones de escucha.`;
  } else if (sourcesHealthy(snap)) {
    output.className = "check-result";
    output.textContent = `${port}/${protocol.toUpperCase()}: no se detecta ninguna publicación Docker ni socket Linux en la última lectura. No es una reserva ni una garantía de disponibilidad.`;
  } else {
    output.className = "check-result unknown";
    output.textContent = `${port}/${protocol.toUpperCase()}: información insuficiente o desactualizada. No se puede confirmar si está libre.`;
  }
}

function switchView(view) {
  state.view = view;
  $("#ports-view").classList.toggle("hidden", view !== "ports");
  $("#containers-view").classList.toggle("hidden", view !== "containers");
  $$(".nav-button").forEach((button) => button.classList.toggle("selected", button.dataset.view === view));
  const name = view === "ports" ? "Visión general" : "Contenedores";
  $("#breadcrumb-current").textContent = name;
  $("#page-title").innerHTML = view === "ports" ? 'Mapa de puertos<span class="title-period">.</span>' : 'Contenedores<span class="title-period">.</span>';
  $("#page-description").textContent = view === "ports"
    ? "Controla las conexiones de Docker y los procesos de tu servidor desde un mismo lugar."
    : "Consulta el estado de los servicios desplegados con Docker.";
}

function csvExport() {
  const columns = ["port", "protocol", "address", "owner_type", "service", "target_port", "process", "pid", "image", "project"];
  const encode = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const content = [columns.join(","), ...portRows().map((row) => columns.map((key) => encode(row[key])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob(["\uFEFF" + content], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `port-manager-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  showToast("Inventario exportado");
}

$("#refresh-button").addEventListener("click", refresh);
$("#export-button").addEventListener("click", csvExport);
$("#search-input").addEventListener("input", (event) => { state.query = event.target.value; renderPorts(); });
$("#container-search").addEventListener("input", (event) => { state.containerQuery = event.target.value; renderContainers(); });
$("#protocol-filter").addEventListener("change", (event) => { state.protocol = event.target.value; renderPorts(); });
$("#check-form").addEventListener("submit", (event) => { event.preventDefault(); checkPort(); });
$$(".filter-tab").forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  $$(".filter-tab").forEach((item) => item.classList.toggle("active", item === button));
  renderPorts();
}));
$$(".nav-button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
$("#port-rows").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    showToast("Dirección copiada al portapapeles");
  } catch {
    showToast("No se ha podido copiar automáticamente");
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "/" || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  if (state.view !== "ports") return;
  event.preventDefault();
  $("#search-input").focus();
});

refresh();
setInterval(refresh, 5000);
setInterval(updateStatus, 1000);
