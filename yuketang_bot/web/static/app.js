/* 雨课堂本地控制台前端 */

const PAGE_META = {
  overview: { title: "概览", desc: "账号状态、任务进度与快捷操作" },
  login: { title: "扫码登录", desc: "打开 Chromium，手机扫码后点击确认" },
  discover: { title: "课程发现", desc: "从主页抓取课程并爬取视频链接" },
  run: { title: "刷课任务", desc: "筛选、分页查看清单，断点续刷 pending 视频" },
  settings: { title: "设置", desc: "修改 config.yaml 中的常用参数" },
};

const STATUS_LABEL = {
  pending: "待刷",
  done: "已完成",
  failed: "失败",
  skipped: "跳过",
};

const videoState = {
  all: [],
  status: "",
  account: "",
  search: "",
  page: 1,
  pageSize: 30,
};

let unreadLogs = 0;
let lastSummary = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText;
    const text = typeof msg === "string" ? msg : JSON.stringify(msg);
    if (res.status === 404 && text === "Not Found") {
      throw new Error("接口不存在，请重启控制台后再试");
    }
    throw new Error(text);
  }
  return data;
}

function $(id) { return document.getElementById(id); }

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function shortCourse(url) {
  if (!url) return "—";
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    return parts.slice(-2).join("/") || u.pathname;
  } catch {
    return String(url).slice(-36);
  }
}

function ratePct(v) {
  if (v.status === "done" || v.completed === 1 || v.completed === true) {
    const r = Number(v.rate);
    if (!Number.isNaN(r) && r > 0) return Math.min(100, Math.round(r * 1000) / 10);
    return 100;
  }
  const r = Number(v.rate);
  if (Number.isNaN(r) || r <= 0) return null;
  return Math.min(100, Math.round(r * 1000) / 10);
}

function isLogDockOpen() {
  return $("log-dock").classList.contains("is-open");
}

function appendLog(line) {
  const view = $("log-view");
  view.textContent += line + "\n";
  view.scrollTop = view.scrollHeight;
  if (!isLogDockOpen()) {
    unreadLogs += 1;
    const badge = $("log-badge");
    badge.hidden = false;
    badge.textContent = String(unreadLogs > 99 ? "99+" : unreadLogs);
  }
}

function setLogDockOpen(open) {
  const dock = $("log-dock");
  const btn = $("btn-log-toggle");
  const shell = document.body;
  dock.classList.toggle("is-open", !!open);
  shell.classList.toggle("log-dock-open", !!open);
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    unreadLogs = 0;
    $("log-badge").hidden = true;
  }
}

function clampLogDockPosition(left, top) {
  const dock = $("log-dock");
  const rect = dock.getBoundingClientRect();
  const pad = 8;
  const maxLeft = Math.max(pad, window.innerWidth - rect.width - pad);
  const maxTop = Math.max(pad, window.innerHeight - rect.height - pad);
  return {
    left: Math.min(Math.max(pad, left), maxLeft),
    top: Math.min(Math.max(pad, top), maxTop),
  };
}

function applyLogDockPosition(left, top) {
  const dock = $("log-dock");
  const pos = clampLogDockPosition(left, top);
  dock.style.left = `${pos.left}px`;
  dock.style.top = `${pos.top}px`;
  dock.style.right = "auto";
  dock.style.bottom = "auto";
  try {
    localStorage.setItem("ykt-log-dock-pos", JSON.stringify(pos));
  } catch {}
}

function restoreLogDockPosition() {
  try {
    const raw = localStorage.getItem("ykt-log-dock-pos");
    if (!raw) return;
    const pos = JSON.parse(raw);
    if (typeof pos.left === "number" && typeof pos.top === "number") {
      applyLogDockPosition(pos.left, pos.top);
    }
  } catch {}
}

function bindLogDockDrag() {
  const dock = $("log-dock");
  const handle = $("log-drag-handle");
  const toggle = $("btn-log-toggle");
  const DRAG_THRESHOLD = 6;

  const beginDrag = (clientX, clientY) => {
    const rect = dock.getBoundingClientRect();
    dock.classList.add("is-dragging");
    applyLogDockPosition(rect.left, rect.top);
    return { startX: clientX, startY: clientY, originLeft: rect.left, originTop: rect.top };
  };

  const bindDragTarget = (el, { onTap } = {}) => {
    let dragState = null;
    let moved = false;

    const onMove = (e) => {
      if (!dragState) return;
      const dx = e.clientX - dragState.startX;
      const dy = e.clientY - dragState.startY;
      if (!moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      if (!moved) moved = true;
      applyLogDockPosition(
        dragState.originLeft + dx,
        dragState.originTop + dy,
      );
    };

    const onStop = (e) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onStop);
      window.removeEventListener("pointercancel", onStop);
      dock.classList.remove("is-dragging");
      if (!moved && onTap) onTap(e);
      dragState = null;
      moved = false;
    };

    el.addEventListener("pointerdown", (e) => {
      if (el === handle && e.target.closest("button")) return;
      if (e.button != null && e.button !== 0) return;
      dragState = beginDrag(e.clientX, e.clientY);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onStop);
      window.addEventListener("pointercancel", onStop);
      e.preventDefault();
    });
  };

  bindDragTarget(handle);
  bindDragTarget(toggle, {
    onTap: () => setLogDockOpen(!isLogDockOpen()),
  });

  window.addEventListener("resize", () => {
    const rect = dock.getBoundingClientRect();
    if (dock.style.left || dock.style.top) {
      applyLogDockPosition(rect.left, rect.top);
    }
  });
}

function setJobPill(job) {
  const el = $("job-pill");
  const dock = $("log-dock");
  dock.classList.remove("is-running", "is-success", "is-error");
  if (!job || job.state === "idle" || !job.action) {
    el.textContent = "空闲";
    el.className = "job-chip idle";
    return;
  }
  const actionMap = { login: "登录", discover: "发现", crawl: "爬取", run: "刷课" };
  const label = actionMap[job.action] || job.action;
  el.textContent = `${label} · ${job.state}`;
  el.className = "job-chip " + (job.state || "idle");
  if (job.state === "running") dock.classList.add("is-running");
  else if (job.state === "success") dock.classList.add("is-success");
  else if (job.state === "failed" || job.state === "cancelled") dock.classList.add("is-error");
}

function showPage(name) {
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
  const page = $("page-" + name);
  if (page) page.classList.add("active");
  const nav = document.querySelector(`.nav-item[data-page="${name}"]`);
  if (nav) nav.classList.add("active");
  const meta = PAGE_META[name] || { title: name, desc: "" };
  $("page-title").textContent = meta.title;
  $("page-desc").textContent = meta.desc;
  if (name === "overview") refreshOverview();
  if (name === "login" || name === "discover" || name === "run") fillAccountSelects();
  if (name === "run") refreshVideos();
  if (name === "settings") loadSettings();
  if (name === "settings") renderSettingsAccounts();
  if (name === "discover") refreshCourses();
}

function renderSetupSteps(summary, accounts) {
  const loggedIn = (accounts || []).some((a) => a.logged_in);
  const hasCourses = (summary.courses || []).length > 0;
  const hasPending = (summary.totals?.pending || 0) > 0;
  const hasVideos = (summary.totals?.total || 0) > 0;
  const steps = [
    {
      title: "扫码登录",
      desc: "打开浏览器，用雨课堂 App 扫码",
      done: loggedIn,
      goto: "login",
      action: "去登录",
    },
    {
      title: "发现课程",
      desc: "拉取「我听的课」列表",
      done: hasCourses || hasVideos,
      goto: "discover",
      action: "去发现",
    },
    {
      title: "爬取视频",
      desc: "将章节视频写入本地清单",
      done: hasVideos,
      goto: "discover",
      action: "去爬取",
    },
    {
      title: "开始刷课",
      desc: hasPending ? `还有 ${summary.totals.pending} 个待刷` : "已全部完成或暂无任务",
      done: hasVideos && !hasPending,
      goto: "run",
      action: "去刷课",
    },
  ];
  $("setup-steps").innerHTML = steps.map((s, i) => `
    <div class="setup-step ${s.done ? "done" : ""}">
      <div class="idx">${s.done ? "✓" : i + 1}</div>
      <div class="body">
        <strong>${esc(s.title)}</strong>
        <span>${esc(s.desc)}</span>
      </div>
      <button class="btn ${s.done ? "ghost" : ""} small" data-goto="${s.goto}" type="button" ${s.done ? "disabled" : ""}>
        ${s.done ? "已完成" : s.action}
      </button>
    </div>
  `).join("");
  $("setup-steps").querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => showPage(btn.dataset.goto));
  });
  const doneCount = steps.filter((s) => s.done).length;
  $("setup-hint").textContent = `引导进度 ${doneCount}/${steps.length} · 数据仅保存在本机`;
}

async function refreshOverview() {
  const [summary, accounts] = await Promise.all([
    api("/api/summary"),
    api("/api/accounts"),
  ]);
  lastSummary = summary;
  const t = summary.totals || {};
  $("stat-cards").innerHTML = `
    <div class="stat-card pending"><div class="label">待刷</div><div class="num">${t.pending || 0}</div></div>
    <div class="stat-card done"><div class="label">已完成</div><div class="num">${t.done || 0}</div></div>
    <div class="stat-card failed"><div class="label">失败</div><div class="num">${t.failed || 0}</div></div>
    <div class="stat-card"><div class="label">总计</div><div class="num">${t.total || 0}</div></div>
  `;

  const accList = accounts.accounts || [];
  $("overview-accounts").innerHTML = accList.map((a) => `
    <div class="list-item">
      <div class="title">${esc(a.display_name || a.yuketang_name || a.name)}</div>
      <div class="meta">本地账号=${esc(a.name)} · profile=${esc(a.profile)} · ${a.logged_in ? "已登录" : "未检测登录"} ${a.login_session_active ? "· 扫码窗口打开中" : ""}</div>
    </div>
  `).join("") || '<div class="muted">无账号</div>';

  $("overview-courses").innerHTML = (summary.courses || []).map((c) => {
    const pct = c.total ? Math.round((c.done / c.total) * 100) : 0;
    return `
      <div class="list-item">
        <div class="title">[${esc(c.account_name)}] ${c.done}/${c.total} · ${pct}%</div>
        <div class="meta">${esc(shortCourse(c.course_url))}</div>
        <div class="progress-line"><i style="width:${pct}%"></i></div>
      </div>
    `;
  }).join("") || '<div class="muted">暂无课程，请先「课程发现」</div>';

  renderSetupSteps(summary, accList);
  setJobPill(summary.job);
  updateSidebarAccount(accList);

  const job = summary.job;
  if (job && job.action) {
    $("run-status").textContent = `${job.action} · ${job.state}${job.message ? " · " + job.message : ""}`;
    $("run-status").className = "job-chip " + (job.state || "idle");
  }
}

function accountLabel(a) {
  const ykt = (a.yuketang_name || "").trim();
  const local = a.name || "";
  if (a.logged_in && ykt) return `${ykt} 已登录`;
  if (ykt) return `${ykt} · ${local}`;
  if (a.logged_in) return `${local} 已登录`;
  return `未登录 · ${local}`;
}

function updateSidebarAccount(accounts) {
  const el = $("sidebar-account");
  const text = $("sidebar-account-text");
  el.classList.remove("is-ready", "is-warn");
  if (!accounts?.length) {
    text.textContent = "无账号";
    return;
  }
  const ready = accounts.filter((a) => a.logged_in);
  if (ready.length) {
    el.classList.add("is-ready");
    text.textContent = ready.map((a) => accountLabel(a).replace(" 已登录", "")).join("、");
  } else {
    el.classList.add("is-warn");
    text.textContent = accountLabel(accounts[0]);
  }
}

async function loadAccounts() {
  const data = await api("/api/accounts");
  return data.accounts || [];
}

function toggleAccountAddBox(show, target = "login") {
  const loginBox = $("account-add-box");
  const settingsBox = $("settings-account-add-box");
  if (loginBox) loginBox.hidden = !(show && target === "login");
  if (settingsBox) settingsBox.hidden = !(show && target === "settings");
  if (show) {
    const nameInput = target === "settings"
      ? $("settings-new-account-name")
      : $("new-account-name");
    nameInput?.focus();
    if (target === "settings") {
      $("settings-account-add-msg").textContent = "";
    } else if ($("account-add-msg")) {
      $("account-add-msg").textContent = "";
    }
  }
}

async function addAccount(options = {}) {
  const fromSettings = options.from === "settings";
  const nameEl = fromSettings ? $("settings-new-account-name") : $("new-account-name");
  const profileEl = fromSettings ? $("settings-new-account-profile") : $("new-account-profile");
  const name = (nameEl?.value || options.name || "").trim();
  const profile = (profileEl?.value || options.profile || "").trim();
  const body = {};
  if (name) body.name = name;
  if (profile) body.profile = profile;
  const res = await api("/api/accounts/add", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (nameEl) nameEl.value = "";
  if (profileEl) profileEl.value = "";
  toggleAccountAddBox(false, fromSettings ? "settings" : "login");
  await fillAccountSelects();
  await renderSettingsAccounts();
  if (res.account?.name) {
    const sel = $("login-account");
    if (sel) sel.value = res.account.name;
    const discoverSel = $("discover-account");
    if (discoverSel) discoverSel.value = res.account.name;
  }
  return res;
}

async function renderSettingsAccounts() {
  const list = $("settings-account-list");
  if (!list) return;
  const accounts = await loadAccounts();
  if (!accounts.length) {
    list.innerHTML = '<div class="muted">暂无账号，请点击「添加账号」</div>';
    return;
  }
  list.innerHTML = accounts.map((a) => `
    <div class="account-row">
      <div>
        <div class="title">${esc(a.display_name || a.yuketang_name || a.name)}</div>
        <div class="meta">本地名 ${esc(a.name)} · profile=${esc(a.profile)} · 端口 ${a.port ?? "自动"}</div>
      </div>
      <div class="account-row-tags">
        <span class="account-tag ${a.logged_in ? "ok" : ""}">${a.logged_in ? "已登录" : "未登录"}</span>
        ${a.yuketang_name ? `<span class="account-tag">${esc(a.yuketang_name)}</span>` : ""}
        <button type="button" class="btn danger small btn-account-delete" data-name="${esc(a.name)}">删除</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll(".btn-account-delete").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.name;
      if (!name) return;
      if (!confirm(`确定删除账号「${name}」？\n\n仅从配置移除，浏览器 profile 与视频记录仍保留。`)) return;
      try {
        await deleteAccount(name);
        $("settings-account-add-msg").textContent = `已删除 ${name}`;
        appendLog(`[ui] 已删除账号 ${name}`);
      } catch (e) {
        alert(e.message);
      }
    });
  });
}

async function deleteAccount(name) {
  const res = await api("/api/accounts/delete", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await fillAccountSelects();
  await renderSettingsAccounts();
  await loadSettings();
  await refreshOverview();
  return res;
}

async function fillAccountSelects() {
  const accounts = await loadAccounts();
  const opts = accounts.map((a) => {
    const label = a.yuketang_name ? `${a.yuketang_name} (${a.name})` : a.name;
    return `<option value="${esc(a.name)}">${esc(label)}</option>`;
  }).join("");
  $("login-account").innerHTML = opts;
  $("discover-account").innerHTML = opts;
  $("run-account").innerHTML = `<option value="">全部账号</option>` + opts;
  $("video-account-filter").innerHTML = `<option value="">全部账号</option>` + opts;
  updateSidebarAccount(accounts);
}

async function refreshCourses() {
  const account = $("discover-account")?.value || "";
  const q = account ? `?account=${encodeURIComponent(account)}` : "";
  const data = await api("/api/discover/courses" + q);
  const list = $("course-list");
  const courses = data.courses || [];
  if (!courses.length) {
    list.innerHTML = '<div class="muted">暂无课程列表，请先点击「开始发现」</div>';
    list.dataset.courses = "";
    updateCrawlButtonState();
    return;
  }
  list.innerHTML = courses.map((c, i) => {
    const done = !!c.completed && !c.no_videos;
    const noVideos = !!c.no_videos;
    const handled = done || noVideos;
    const hasVideos = (c.video_total || 0) > 0;
    let progress = "";
    if (noVideos) {
      progress = `<span class="course-progress empty" title="${esc(c.crawl_note || "")}">无视频</span>`;
    } else if (hasVideos) {
      progress = `<span class="course-progress ${done ? "done" : ""}">${done ? "已刷完" : `${c.video_done}/${c.video_total}`}</span>`;
    } else if (c.crawl_status === "crawled") {
      progress = `<span class="course-progress empty">无视频</span>`;
    }
    return `
    <label class="course-item ${handled ? "is-done" : ""} ${noVideos ? "is-empty" : ""}">
      <input type="checkbox" class="course-check" data-idx="${i}" ${handled ? "disabled" : ""} />
      <div class="course-item-body">
        <div class="course-item-head">
          <div class="name">${esc(c.name || "(未命名)")}</div>
          ${progress}
        </div>
        <div class="url">${esc(c.url)}</div>
      </div>
    </label>
  `;
  }).join("");
  list.dataset.courses = JSON.stringify(courses);
  list.querySelectorAll(".course-check").forEach((el) => {
    el.addEventListener("change", updateCrawlButtonState);
  });
  if (data.persisted && !data.session_active) {
    list.insertAdjacentHTML("afterbegin",
      '<div class="muted">已加载上次发现的课程（默认不勾选）。勾选后可直接「爬取选中课程」，将自动打开浏览器。</div>');
  }
  updateCrawlButtonState();
}

function updateCrawlButtonState() {
  const raw = $("course-list")?.dataset.courses;
  const selected = document.querySelectorAll(
    ".course-check:checked:not(:disabled)"
  ).length;
  $("btn-discover-crawl").disabled = !raw || selected === 0;
}

function filteredVideos() {
  const q = videoState.search.trim().toLowerCase();
  return videoState.all.filter((v) => {
    if (videoState.status && v.status !== videoState.status) return false;
    if (videoState.account && v.account_name !== videoState.account) return false;
    if (!q) return true;
    const hay = `${v.title || ""} ${v.video_id || ""} ${v.video_url || ""}`.toLowerCase();
    return hay.includes(q);
  });
}

function renderVideoTable() {
  const list = filteredVideos();
  const total = list.length;
  const pages = Math.max(1, Math.ceil(total / videoState.pageSize));
  if (videoState.page > pages) videoState.page = pages;
  const start = (videoState.page - 1) * videoState.pageSize;
  const slice = list.slice(start, start + videoState.pageSize);

  const counts = { pending: 0, done: 0, failed: 0, total: videoState.all.length };
  videoState.all.forEach((v) => {
    if (counts[v.status] != null) counts[v.status] += 1;
  });
  $("run-mini-stats").innerHTML = `
    <span class="mini-stat">待刷 <b>${counts.pending}</b></span>
    <span class="mini-stat">已完成 <b>${counts.done}</b></span>
    <span class="mini-stat">失败 <b>${counts.failed}</b></span>
    <span class="mini-stat">总计 <b>${counts.total}</b></span>
  `;
  $("video-summary").textContent = `筛选结果 ${total} 条 · 第 ${videoState.page}/${pages} 页`;

  const tbody = $("video-tbody");
  const empty = $("video-empty");
  if (!slice.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
  } else {
    empty.hidden = true;
    tbody.innerHTML = slice.map((v) => {
      const pct = ratePct(v);
      const progressHtml = pct == null
        ? '<span class="pct">—</span>'
        : `<div class="bar"><i style="width:${pct}%"></i></div><span class="pct">${pct}%</span>`;
      const title = v.title || v.video_id || "(无标题)";
      return `
        <tr class="is-${esc(v.status)}">
          <td><span class="badge ${esc(v.status)}">${STATUS_LABEL[v.status] || esc(v.status)}</span></td>
          <td>
            <div class="video-title">${esc(title)}</div>
            <div class="video-sub">${esc(v.video_id)}</div>
          </td>
          <td>${esc(v.account_name)}</td>
          <td class="cell-progress">${progressHtml}</td>
          <td title="${esc(v.course_url)}">${esc(shortCourse(v.course_url))}</td>
        </tr>
      `;
    }).join("");
  }

  const pag = $("video-pagination");
  if (total <= videoState.pageSize) {
    pag.innerHTML = `<span class="muted">共 ${total} 条</span>`;
    return;
  }
  const btns = [];
  btns.push(`<button type="button" class="page-btn" data-page="${videoState.page - 1}" ${videoState.page <= 1 ? "disabled" : ""}>上一页</button>`);
  const windowSize = 5;
  let from = Math.max(1, videoState.page - 2);
  let to = Math.min(pages, from + windowSize - 1);
  from = Math.max(1, to - windowSize + 1);
  for (let p = from; p <= to; p++) {
    btns.push(`<button type="button" class="page-btn ${p === videoState.page ? "active" : ""}" data-page="${p}">${p}</button>`);
  }
  btns.push(`<button type="button" class="page-btn" data-page="${videoState.page + 1}" ${videoState.page >= pages ? "disabled" : ""}>下一页</button>`);
  pag.innerHTML = `
    <span class="muted">共 ${total} 条 · 每页 ${videoState.pageSize}</span>
    <div class="pages">${btns.join("")}</div>
  `;
  pag.querySelectorAll(".page-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = Number(btn.dataset.page);
      if (!p || p < 1 || p > pages) return;
      videoState.page = p;
      renderVideoTable();
    });
  });
}

async function refreshVideos() {
  const data = await api("/api/videos");
  videoState.all = data.videos || [];
  renderVideoTable();
}

async function loadSettings() {
  const s = await api("/api/settings");
  $("set-base-url").value = s.base_url || "";
  $("set-home-url").value = s.home_url || "";
  $("set-hb-count").value = s.loop?.heartbeat_count ?? 10;
  $("set-target-rate").value = s.loop?.target_rate ?? 0.95;
  $("set-playback").value = s.loop?.playback_rate ?? 1;
  $("set-batch-sleep").value = s.loop?.batch_sleep ?? 2;
  $("set-accounts").value = JSON.stringify(s.accounts || [], null, 2);
  $("settings-msg").textContent = "";
}

async function pollJobUntilDone() {
  for (let i = 0; i < 600; i++) {
    const job = await api("/api/jobs/current");
    setJobPill(job);
    if (job && job.message) {
      if (job.action === "login") $("login-status").textContent = `[${job.state}] ${job.message}`;
      if (job.action === "run") {
        $("run-status").textContent = `[${job.state}] ${job.message}`;
        $("run-status").className = "job-chip " + (job.state || "idle");
      }
    }
    if (!job || job.state !== "running") {
      if (job?.action === "discover" && job.state === "success") await refreshCourses();
      if (job?.action === "crawl" && job.state === "success") {
        await refreshVideos();
        await refreshOverview();
      }
      if (job?.action === "run") {
        await refreshVideos();
        await refreshOverview();
      }
      if (job?.action === "login") await fillAccountSelects();
      return job;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

function connectSSE() {
  const es = new EventSource("/api/events");
  es.addEventListener("log", (ev) => {
    try {
      const data = JSON.parse(ev.data);
      appendLog(data.line || `[${data.tag}] ${data.msg}`);
    } catch {}
  });
  es.addEventListener("job", (ev) => {
    try {
      const job = JSON.parse(ev.data);
      setJobPill(job);
      if (job.message) appendLog(`[job] ${job.action} ${job.state}: ${job.message}`);
      if (job.action === "run" && job.state === "running") {
        // 刷课中周期性刷新列表进度
      }
    } catch {}
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("ykt-theme", theme); } catch {}
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showPage(btn.dataset.page));
  });
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => showPage(btn.dataset.goto));
  });
  $("btn-refresh").addEventListener("click", async () => {
    const active = document.querySelector(".nav-item.active");
    showPage(active ? active.dataset.page : "overview");
  });
  $("btn-sidebar").addEventListener("click", () => {
    const shell = $("app-shell");
    if (window.matchMedia("(max-width: 720px)").matches) {
      shell.classList.toggle("sidebar-open");
    } else {
      shell.classList.toggle("sidebar-collapsed");
      try {
        localStorage.setItem(
          "ykt-sidebar-collapsed",
          shell.classList.contains("sidebar-collapsed") ? "1" : "0"
        );
      } catch {}
    }
  });
  $("btn-theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    applyTheme(cur === "light" ? "dark" : "light");
  });
  $("btn-log-toggle").addEventListener("click", (e) => {
    // 拖拽结束也会触发 click，由 pointer 逻辑处理；此处仅防重复
    e.preventDefault();
  });
  $("btn-log-close").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    setLogDockOpen(false);
  });
  $("btn-log-clear").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    $("log-view").textContent = "";
  });
  bindLogDockDrag();

  $("btn-login-start").addEventListener("click", async () => {
    try {
      $("login-status").textContent = "正在打开浏览器...";
      const account = $("login-account").value || null;
      await api("/api/login/start", {
        method: "POST",
        body: JSON.stringify({ account }),
      });
      setLogDockOpen(true);
      pollJobUntilDone();
    } catch (e) {
      $("login-status").textContent = "错误: " + e.message;
    }
  });
  $("btn-login-confirm").addEventListener("click", async () => {
    try {
      await api("/api/login/confirm", { method: "POST", body: "{}" });
      $("login-status").textContent = "已发送确认，正在检测登录态...";
    } catch (e) {
      $("login-status").textContent = "错误: " + e.message;
    }
  });
  $("btn-login-cancel").addEventListener("click", async () => {
    await api("/api/jobs/cancel", { method: "POST", body: "{}" });
  });

  $("btn-discover-start").addEventListener("click", async () => {
    try {
      const account = $("discover-account").value || null;
      appendLog("[ui] 开始发现课程...");
      setLogDockOpen(true);
      await api("/api/discover/start", {
        method: "POST",
        body: JSON.stringify({ account }),
      });
      await pollJobUntilDone();
      await refreshCourses();
    } catch (e) {
      appendLog("[ui] 错误: " + e.message);
      alert(e.message);
    }
  });

  $("btn-discover-crawl").addEventListener("click", async () => {
    try {
      const raw = $("course-list").dataset.courses;
      if (!raw) throw new Error("没有课程数据");
      const courses = JSON.parse(raw);
      const selected = [];
      document.querySelectorAll(".course-check:checked").forEach((el) => {
        const idx = Number(el.dataset.idx);
        if (courses[idx]) selected.push(courses[idx]);
      });
      if (!selected.length) throw new Error("请至少选择一门课程");
      setLogDockOpen(true);
      await api("/api/discover/crawl", {
        method: "POST",
        body: JSON.stringify({
          courses: selected,
          account: $("discover-account").value || null,
          sync_all: $("discover-sync-all").checked,
        }),
      });
      await pollJobUntilDone();
      await refreshCourses();
      await refreshVideos();
      await refreshOverview();
    } catch (e) {
      alert(e.message);
    }
  });

  $("btn-discover-cancel").addEventListener("click", async () => {
    await api("/api/jobs/cancel", { method: "POST", body: "{}" });
  });

  $("btn-run-start").addEventListener("click", async () => {
    try {
      const account = $("run-account").value || null;
      setLogDockOpen(true);
      await api("/api/jobs/run", {
        method: "POST",
        body: JSON.stringify({ account: account || null }),
      });
      $("run-status").textContent = "刷课进行中...";
      $("run-status").className = "job-chip running";
      await pollJobUntilDone();
    } catch (e) {
      $("run-status").textContent = "错误: " + e.message;
      $("run-status").className = "job-chip failed";
      alert(e.message);
    }
  });
  $("btn-run-cancel").addEventListener("click", async () => {
    await api("/api/jobs/cancel", { method: "POST", body: "{}" });
  });
  $("btn-videos-refresh").addEventListener("click", refreshVideos);

  document.querySelectorAll("#video-filters .filter-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll("#video-filters .filter-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      videoState.status = pill.dataset.status || "";
      videoState.page = 1;
      renderVideoTable();
    });
  });
  $("video-account-filter").addEventListener("change", () => {
    videoState.account = $("video-account-filter").value || "";
    videoState.page = 1;
    renderVideoTable();
  });
  let searchTimer = null;
  $("video-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      videoState.search = $("video-search").value || "";
      videoState.page = 1;
      renderVideoTable();
    }, 180);
  });

  $("discover-account").addEventListener("change", refreshCourses);

  $("btn-login-add-account").addEventListener("click", () => toggleAccountAddBox(true, "login"));
  $("btn-settings-add-account")?.addEventListener("click", () => toggleAccountAddBox(true, "settings"));
  $("btn-account-add-cancel").addEventListener("click", () => toggleAccountAddBox(false, "login"));
  $("btn-settings-account-add-cancel")?.addEventListener("click", () => toggleAccountAddBox(false, "settings"));
  $("btn-account-add-confirm").addEventListener("click", async () => {
    try {
      const res = await addAccount({ from: "login" });
      $("account-add-msg").textContent = `已添加 ${res.account.name}（${res.account.profile}）`;
      appendLog(`[ui] 已添加账号 ${res.account.name}`);
    } catch (e) {
      $("account-add-msg").textContent = "错误: " + e.message;
    }
  });
  $("btn-settings-account-add-confirm")?.addEventListener("click", async () => {
    try {
      const res = await addAccount({ from: "settings" });
      $("settings-account-add-msg").textContent = `已添加 ${res.account.name}（${res.account.profile}）`;
      appendLog(`[ui] 已添加账号 ${res.account.name}`);
    } catch (e) {
      $("settings-account-add-msg").textContent = "错误: " + e.message;
    }
  });

  $("btn-settings-save").addEventListener("click", async () => {
    try {
      let accounts;
      try {
        accounts = JSON.parse($("set-accounts").value);
      } catch {
        throw new Error("accounts JSON 格式错误");
      }
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          base_url: $("set-base-url").value.trim(),
          home_url: $("set-home-url").value.trim(),
          accounts,
          loop: {
            heartbeat_count: Number($("set-hb-count").value),
            heartbeat_interval: 5,
            playback_rate: Number($("set-playback").value),
            batch_sleep: Number($("set-batch-sleep").value),
            target_rate: Number($("set-target-rate").value),
            max_batches: 200,
          },
        }),
      });
      $("settings-msg").textContent = "已保存";
      await renderSettingsAccounts();
      await fillAccountSelects();
    } catch (e) {
      $("settings-msg").textContent = "错误: " + e.message;
    }
  });
}

async function init() {
  try {
    const theme = localStorage.getItem("ykt-theme") || "light";
    applyTheme(theme);
    if (localStorage.getItem("ykt-sidebar-collapsed") === "1") {
      $("app-shell").classList.add("sidebar-collapsed");
    }
  } catch {}

  bindEvents();
  restoreLogDockPosition();
  connectSSE();
  try {
    const rt = await api("/api/runtime");
    $("runtime-label").textContent = `${rt.bind_host}:${rt.bind_port} · v${rt.version}`;
  } catch {
    $("runtime-label").textContent = "API 连接失败";
  }
  showPage("overview");
  setInterval(async () => {
    try {
      const job = await api("/api/jobs/current");
      setJobPill(job.state === "idle" ? null : job);
      if (job?.state === "running" && job.action === "run") {
        const active = document.querySelector(".nav-item.active");
        if (active?.dataset.page === "run") refreshVideos();
      }
    } catch {}
  }, 3000);
}

init();
