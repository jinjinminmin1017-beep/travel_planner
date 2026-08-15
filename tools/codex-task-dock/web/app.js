const ui = {
  projectName: document.querySelector("#project-name"),
  branchName: document.querySelector("#branch-name"),
  syncLabel: document.querySelector("#sync-label"),
  syncMark: document.querySelector("#sync-mark"),
  summaryCount: document.querySelector("#summary-count"),
  summaryNote: document.querySelector("#summary-note"),
  batchAction: document.querySelector("#batch-action"),
  batchActionLabel: document.querySelector("#batch-action-label"),
  batchActionCount: document.querySelector("#batch-action-count"),
  focusTask: document.querySelector("#focus-task"),
  focusStatus: document.querySelector("#focus-status"),
  focusId: document.querySelector("#focus-id"),
  focusHeading: document.querySelector("#focus-heading"),
  focusDescription: document.querySelector("#focus-description"),
  focusSource: document.querySelector("#focus-source"),
  primaryAction: document.querySelector("#primary-action"),
  sourceAction: document.querySelector("#source-action"),
  safetyNote: document.querySelector("#safety-note"),
  taskList: document.querySelector("#task-list"),
  taskTotal: document.querySelector("#task-total"),
  statusFilter: document.querySelector("#status-filter"),
  emptyState: document.querySelector("#empty-state"),
  workingTree: document.querySelector("#working-tree"),
  refreshButton: document.querySelector("#refresh-button"),
  toast: document.querySelector("#toast"),
  actionDialog: document.querySelector("#action-dialog"),
  actionTitle: document.querySelector("#action-title"),
  viewDiffButton: document.querySelector("#view-diff-button"),
  revertButton: document.querySelector("#revert-button"),
  deleteButton: document.querySelector("#delete-button"),
  confirmDialog: document.querySelector("#confirm-dialog"),
  confirmTitle: document.querySelector("#confirm-title"),
  confirmMessage: document.querySelector("#confirm-message"),
  confirmButton: document.querySelector("#confirm-button"),
  diffDialog: document.querySelector("#diff-dialog"),
  diffTitle: document.querySelector("#diff-title"),
  diffContent: document.querySelector("#diff-content"),
};

const statusCopy = {
  pending: "待开发",
  running: "开发中",
  complete: "已完成",
  drift: "需检查",
};

const url = new URL(window.location.href);
const suppliedToken = url.searchParams.get("token");
if (suppliedToken) {
  sessionStorage.setItem("taskDockToken", suppliedToken);
  history.replaceState({}, "", url.pathname);
}
const token = sessionStorage.getItem("taskDockToken") || "";
let state = null;
let selectedTaskId = null;
let actionTaskId = null;
let toastTimer = null;
let requestInFlight = false;
let sourceRequestInFlight = false;
let statusFilter = "all";

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "X-Task-Dock-Token": token,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "操作失败");
  return payload;
}

async function loadState({ announce = false } = {}) {
  if (requestInFlight) return;
  requestInFlight = true;
  try {
    state = await api("/api/state");
    ui.syncMark.classList.remove("error");
    ui.syncMark.setAttribute("aria-label", "任务文档同步正常");
    render();
    if (announce) showToast("已检查任务文档，只读取发生变化的文件");
  } catch (error) {
    ui.syncMark.classList.add("error");
    ui.syncMark.setAttribute("aria-label", "任务文档同步失败");
    ui.summaryNote.textContent = error.message;
  } finally {
    requestInFlight = false;
  }
}

function render() {
  const tasks = state.tasks || [];
  if (!tasks.some((task) => task.id === selectedTaskId)) {
    selectedTaskId = state.active_task_id
      || tasks.find((task) => task.status === "pending")?.id
      || tasks[0]?.id
      || null;
  }
  const selected = tasks.find((task) => task.id === selectedTaskId) || null;
  const pending = state.counts.pending || 0;
  const batch = state.batch || { active: false, queued: 0, total: 0, completed: 0, failed: 0, skipped: 0 };
  ui.projectName.textContent = state.project;
  ui.projectName.title = state.project;
  ui.branchName.textContent = state.branch;
  ui.branchName.title = state.branch;
  ui.syncLabel.textContent = `每 ${state.scanner.poll_seconds} 秒增量同步`;
  if (batch.active) {
    const handled = batch.completed + batch.failed + batch.skipped;
    ui.summaryCount.textContent = `正在开发全部任务 · ${handled}/${batch.total}`;
    ui.summaryNote.textContent = batch.cancelling
      ? "正在等待当前任务安全结束"
      : `${batch.queued} 个排队中，${batch.failed} 个失败，${batch.skipped} 个已跳过`;
    ui.batchAction.className = "batch-action cancel";
    ui.batchActionLabel.textContent = batch.cancelling ? "正在停止队列" : "停止后续任务";
    ui.batchActionCount.textContent = String(batch.queued);
    ui.batchAction.disabled = batch.cancelling;
  } else {
    ui.summaryCount.textContent = pending ? `${pending} 个任务可以开始` : "开发任务已处理完毕";
    ui.summaryNote.textContent = `${state.counts.running || 0} 个开发中，${state.counts.complete || 0} 个已完成，${state.counts.drift || 0} 个需检查`;
    ui.batchAction.className = "batch-action";
    ui.batchActionLabel.textContent = "一键开发全部";
    ui.batchActionCount.textContent = String(pending);
    ui.batchAction.disabled = pending === 0 || Boolean(state.active_task_id);
  }
  ui.workingTree.textContent = state.working_tree_changes
    ? `工作区有 ${state.working_tree_changes} 处未提交改动`
    : "工作区干净";
  renderFocus(selected);
  renderList(tasks, selected);
}

function renderFocus(task) {
  if (!task) {
    ui.focusTask.className = "focus-task";
    ui.focusStatus.className = "status-chip";
    ui.focusStatus.querySelector("span").textContent = "等待任务";
    ui.focusId.textContent = "";
    ui.focusHeading.textContent = "开发任务列表为空";
    ui.focusDescription.textContent = "Task Dock 会继续监听 docs/Dev/task*.md。";
    ui.focusSource.textContent = "无需手动添加任务";
    ui.primaryAction.textContent = "交给 Codex";
    ui.primaryAction.disabled = true;
    ui.primaryAction.className = "primary-action";
    ui.sourceAction.disabled = true;
    ui.sourceAction.title = "";
    return;
  }

  ui.focusTask.className = `focus-task status-${task.status}`;
  ui.focusStatus.className = `status-chip status-${task.status}`;
  ui.focusStatus.querySelector("span").textContent = statusCopy[task.status] || task.status;
  ui.focusId.textContent = task.display_id || task.id;
  ui.focusId.title = task.display_id && task.display_id !== task.id
    ? `${task.display_id} · ${task.source_name}`
    : task.id;
  ui.focusHeading.textContent = task.title;
  ui.focusDescription.textContent = task.managed.last_error
    || (task.status === "complete" ? task.managed.result_summary : null)
    || task.description
    || task.status_detail;
  ui.focusSource.textContent = `${task.source_name} · 第 ${task.start_line} 行 · ${task.status_detail}`;
  ui.focusSource.title = ui.focusSource.textContent;
  ui.primaryAction.className = "primary-action";
  ui.primaryAction.disabled = false;
  ui.sourceAction.disabled = sourceRequestInFlight;
  ui.sourceAction.title = `在 VS Code 中打开 ${task.source_name} 第 ${task.start_line} 行`;
  ui.safetyNote.textContent = "开始前会创建隔离工作区并检查 Git 补丁";

  if (task.status === "pending") {
    ui.primaryAction.textContent = "交给 Codex";
  } else if (task.status === "running") {
    ui.primaryAction.textContent = task.managed.last_message || "Codex 正在开发";
    ui.primaryAction.disabled = true;
    ui.safetyNote.textContent = "当前只允许一条任务运行";
  } else if (task.status === "complete") {
    ui.primaryAction.textContent = "Revert 此任务";
    ui.primaryAction.classList.add("revert");
    ui.safetyNote.textContent = "回退前会验证代码与任务补丁仍完全一致";
  } else {
    const retryable = Boolean(task.managed.last_error && !task.managed.has_patch);
    ui.primaryAction.textContent = retryable ? "重新交给 Codex" : "需要人工检查";
    ui.primaryAction.disabled = !retryable;
    ui.safetyNote.textContent = retryable
      ? "上次未产生补丁，可以安全重新尝试"
      : "代码与任务记录不一致时不会强制覆盖";
  }

  if (state.batch?.active && task.status !== "running") {
    const queued = state.batch.queued_task_ids?.includes(task.id);
    ui.primaryAction.textContent = queued ? "已加入开发队列" : "全部任务队列运行中";
    ui.primaryAction.disabled = true;
    ui.safetyNote.textContent = queued ? "会按列表顺序在隔离工作区中开发" : "停止后续任务后可单独操作";
  }
}

function renderList(tasks, selected) {
  ui.taskList.replaceChildren();
  const visibleTasks = statusFilter === "all"
    ? tasks
    : tasks.filter((task) => task.status === statusFilter);
  ui.taskTotal.textContent = statusFilter === "all"
    ? `${visibleTasks.length} 条`
    : `${visibleTasks.length} / ${tasks.length} 条`;
  ui.emptyState.hidden = visibleTasks.length !== 0;
  ui.emptyState.querySelector("strong").textContent = statusFilter === "all"
    ? "当前没有任务"
    : `没有${statusCopy[statusFilter] || statusFilter}的任务`;
  for (const task of visibleTasks) {
    const isSelected = task.id === selected?.id;
    const row = document.createElement("div");
    row.className = `task-row status-${task.status}${isSelected ? " selected" : ""}`;
    row.setAttribute("role", "listitem");

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "task-select";
    selectButton.setAttribute("aria-label", `选择任务：${task.title}`);
    selectButton.setAttribute("aria-pressed", String(isSelected));
    selectButton.addEventListener("click", () => {
      selectedTaskId = task.id;
      render();
    });

    const dot = document.createElement("span");
    dot.className = "task-status-dot";
    dot.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    copy.className = "task-copy";
    const title = document.createElement("strong");
    title.textContent = task.title;
    title.title = task.title;
    const meta = document.createElement("span");
    const queued = state.batch?.queued_task_ids?.includes(task.id);
    const rowStatus = queued ? "已排队" : (statusCopy[task.status] || task.status);
    meta.textContent = `${rowStatus} · ${task.source_name}`;
    meta.title = `${statusCopy[task.status] || task.status} · ${task.source_name} · 第 ${task.start_line} 行`;
    copy.append(title, meta);
    const more = document.createElement("button");
    more.type = "button";
    more.className = "more-button";
    more.setAttribute("aria-label", `打开任务操作：${task.title}`);
    more.textContent = "•••";
    more.addEventListener("click", () => openActions(task));
    selectButton.append(dot, copy);
    selectButton.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openActions(task);
    });
    selectButton.addEventListener("dblclick", () => openActions(task));
    row.append(selectButton, more);
    ui.taskList.append(row);
  }
}

function selectedTask() {
  return state?.tasks.find((task) => task.id === selectedTaskId) || null;
}

async function performPrimaryAction() {
  const task = selectedTask();
  if (!task) return;
  if (task.status === "pending") {
    await mutate(`/api/tasks/${encodeURIComponent(task.id)}/run`, "POST", "Codex 已开始处理此任务");
  } else if (task.status === "drift" && task.managed.last_error && !task.managed.has_patch) {
    await mutate(`/api/tasks/${encodeURIComponent(task.id)}/run`, "POST", "Codex 已重新开始处理此任务");
  } else if (task.status === "complete") {
    confirmAction(
      "回退此任务代码？",
      "只会反向应用这条任务对应的独立补丁。任务文档保留，状态会回到待开发。",
      "确认 Revert",
      () => mutate(`/api/tasks/${encodeURIComponent(task.id)}/revert`, "POST", "此任务代码已回退"),
    );
  }
}

async function openSelectedSource() {
  const task = selectedTask();
  if (!task || sourceRequestInFlight) return;
  sourceRequestInFlight = true;
  ui.sourceAction.disabled = true;
  try {
    await api(`/api/tasks/${encodeURIComponent(task.id)}/open-source`, { method: "POST" });
    showToast(`已跳转到 ${task.source_name} 第 ${task.start_line} 行`);
  } catch (error) {
    showToast(error.message);
  } finally {
    sourceRequestInFlight = false;
    renderFocus(selectedTask());
  }
}

function openActions(task) {
  actionTaskId = task.id;
  ui.actionTitle.textContent = task.title;
  ui.viewDiffButton.disabled = !task.managed.has_patch && !task.commit;
  ui.revertButton.disabled = task.status !== "complete" || Boolean(state.batch?.active);
  ui.deleteButton.disabled = task.status === "running" || Boolean(state.batch?.active);
  ui.actionDialog.showModal();
}

function confirmAction(title, message, buttonCopy, handler, tone = "danger") {
  ui.confirmTitle.textContent = title;
  ui.confirmMessage.textContent = message;
  ui.confirmButton.textContent = buttonCopy;
  ui.confirmButton.className = tone === "primary" ? "confirm-primary" : "danger-action";
  ui.confirmButton.onclick = async () => {
    ui.confirmButton.disabled = true;
    try {
      await handler();
      ui.confirmDialog.close();
    } finally {
      ui.confirmButton.disabled = false;
    }
  };
  ui.confirmDialog.showModal();
}

function performBatchAction() {
  const batch = state?.batch;
  if (!batch) return;
  if (batch.active) {
    confirmAction(
      "停止后续任务？",
      "尚未开始的任务会移出队列。当前正在开发的任务不会被强制终止，会继续完成补丁校验。",
      "停止后续任务",
      () => mutate("/api/batch/cancel", "POST", "后续任务已停止排队"),
    );
    return;
  }
  const pending = state.counts.pending || 0;
  if (!pending) return;
  confirmAction(
    `开发全部 ${pending} 个待办任务？`,
    "任务会按当前列表顺序逐个交给 Codex。每条任务仍使用独立工作区，上一条安全应用后才会开始下一条。",
    "开始全部开发",
    () => mutate("/api/batch/run-all", "POST", `${pending} 个任务已加入开发队列`),
    "primary",
  );
}

async function mutate(path, method, successMessage) {
  try {
    await api(path, { method });
    showToast(successMessage);
    await loadState();
  } catch (error) {
    showToast(error.message);
  }
}

function showToast(message) {
  clearTimeout(toastTimer);
  ui.toast.textContent = message;
  ui.toast.hidden = false;
  toastTimer = setTimeout(() => {
    ui.toast.hidden = true;
  }, 3600);
}

ui.primaryAction.addEventListener("click", performPrimaryAction);
ui.batchAction.addEventListener("click", performBatchAction);
ui.sourceAction.addEventListener("click", openSelectedSource);
ui.refreshButton.addEventListener("click", () => loadState({ announce: true }));
ui.statusFilter.addEventListener("change", (event) => {
  statusFilter = event.target.value;
  render();
});
ui.viewDiffButton.addEventListener("click", async () => {
  const task = state?.tasks.find((item) => item.id === actionTaskId);
  if (!task) return;
  try {
    const payload = await api(`/api/tasks/${encodeURIComponent(task.id)}/diff`);
    ui.actionDialog.close();
    ui.diffTitle.textContent = task.title;
    ui.diffContent.textContent = payload.diff;
    ui.diffDialog.showModal();
  } catch (error) {
    showToast(error.message);
  }
});
ui.revertButton.addEventListener("click", () => {
  const task = state?.tasks.find((item) => item.id === actionTaskId);
  if (!task) return;
  ui.actionDialog.close();
  selectedTaskId = task.id;
  confirmAction(
    "回退此任务代码？",
    "只会反向应用这条任务对应的独立补丁。若代码已经交叉修改，Task Dock 会停止操作。",
    "确认 Revert",
    () => mutate(`/api/tasks/${encodeURIComponent(task.id)}/revert`, "POST", "此任务代码已回退"),
  );
});
ui.deleteButton.addEventListener("click", () => {
  const task = state?.tasks.find((item) => item.id === actionTaskId);
  if (!task) return;
  ui.actionDialog.close();
  confirmAction(
    "删除任务记录？",
    `会从 ${task.source_name} 中删除这条任务记录，但不会删除或回退任何代码。此操作无法由 Task Dock 恢复。`,
    "确认删除记录",
    async () => {
      await mutate(`/api/tasks/${encodeURIComponent(task.id)}`, "DELETE", "任务记录已从开发文档删除");
      selectedTaskId = null;
    },
  );
});

loadState();
setInterval(loadState, 1000);
