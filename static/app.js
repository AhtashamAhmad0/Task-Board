const STATUSES = ["todo", "doing", "done"];
const $ = (selector) => document.querySelector(selector);

let tasks = [];
let stats = null;

// ---------- Helpers ----------
async function api(path, options = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function showMessage(text) {
  const box = $("#message");
  box.textContent = text;
  box.hidden = false;
  setTimeout(() => (box.hidden = true), 4000);
}

// textContent (not innerHTML) keeps user input from running as HTML
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function iconButton(label, title, handler) {
  const b = el("button", "icon", label);
  b.type = "button";
  b.title = title;
  b.onclick = handler;
  return b;
}

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD

// ---------- Loading and rendering ----------
async function load() {
  try {
    const q = encodeURIComponent($("#search").value.trim());
    [tasks, stats] = await Promise.all([api("/tasks?q=" + q), api("/stats")]);
    renderStats();
    renderBoard();
  } catch (err) {
    showMessage("Cannot load tasks: " + err.message);
  }
}

function renderStats() {
  $("#stat-total").textContent = stats.total;
  $("#stat-doing").textContent = stats.by_status.doing;
  $("#stat-done").textContent = stats.by_status.done;
  $("#stat-overdue").textContent = stats.overdue;
  $("#stat-completion").textContent = stats.completion + "%";
}

function renderBoard() {
  for (const status of STATUSES) {
    const column = $("#col-" + status);
    const items = tasks.filter((t) => t.status === status);
    column.replaceChildren();
    $("#count-" + status).textContent = items.length;
    if (!items.length) column.append(el("p", "empty", "Nothing here"));
    items.forEach((t) => column.append(buildCard(t)));
  }
}

function buildCard(t) {
  const card = el("article", "card priority-" + t.priority);
  card.append(el("h3", "", t.title));
  if (t.description) card.append(el("p", "desc", t.description));

  const meta = el("div", "meta");
  meta.append(el("span", "badge " + t.priority, t.priority));
  if (t.due_date) {
    const overdue = t.status !== "done" && t.due_date < today();
    meta.append(el("span", "due" + (overdue ? " overdue" : ""), "Due " + t.due_date));
  }
  card.append(meta);

  const actions = el("div", "actions");
  const index = STATUSES.indexOf(t.status);
  if (index > 0) actions.append(iconButton("◀", "Move back", () => move(t, STATUSES[index - 1])));
  actions.append(iconButton("✎", "Edit", () => openForm(t)));
  actions.append(iconButton("🗑", "Delete", () => remove(t)));
  if (index < STATUSES.length - 1) actions.append(iconButton("▶", "Move forward", () => move(t, STATUSES[index + 1])));
  card.append(actions);
  return card;
}

// ---------- Actions ----------
async function move(task, status) {
  try {
    await api("/tasks/" + task.id, { method: "PUT", body: JSON.stringify({ ...task, status }) });
    await load();
  } catch (err) {
    showMessage(err.message);
  }
}

async function remove(task) {
  if (!confirm(`Delete "${task.title}"?`)) return;
  try {
    await api("/tasks/" + task.id, { method: "DELETE" });
    await load();
  } catch (err) {
    showMessage(err.message);
  }
}

// ---------- Add / edit form ----------
const dialog = $("#dialog");
const form = $("#form");

function openForm(task = null) {
  form.reset();
  $("#form-error").textContent = "";
  $("#form-title").textContent = task ? "Edit task" : "New task";
  const values = task ?? { status: "todo", priority: "medium" };
  for (const name of ["title", "description", "status", "priority", "due_date"]) {
    form.elements[name].value = values[name] ?? "";
  }
  form.elements.task_id.value = task ? task.id : "";
  dialog.showModal();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  const id = data.task_id;
  delete data.task_id;
  data.due_date = data.due_date || null;
  try {
    if (id) await api("/tasks/" + id, { method: "PUT", body: JSON.stringify(data) });
    else await api("/tasks", { method: "POST", body: JSON.stringify(data) });
    dialog.close();
    await load();
  } catch (err) {
    $("#form-error").textContent = err.message;
  }
});

$("#add-btn").addEventListener("click", () => openForm());
$("#cancel-btn").addEventListener("click", () => dialog.close());

let timer;
$("#search").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(load, 250); // wait until the user stops typing
});

load();