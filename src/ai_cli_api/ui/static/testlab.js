import { getWorkers, getWorkspaceInput } from "/static/request.js";

const testStoryEl = document.getElementById("test-story");
const testQAList = document.getElementById("test-qa-list");
const testModelGrid = document.getElementById("test-model-grid");
const testResultsBody = document.getElementById("test-results-body");
const testMetaEl = document.getElementById("test-meta");
const runTestBtn = document.getElementById("run-test-btn");
const addQABtn = document.getElementById("add-qa-btn");
const generateAllBtn = document.getElementById("generate-all-btn");
const generateModelSelect = document.getElementById("generate-model-select");
const selectAll = document.getElementById("test-select-all");

let qaCounter = 0;

function setTestMeta(msg, isError = false) {
  testMetaEl.textContent = msg;
  testMetaEl.className = isError ? "meta error" : "meta";
}

function clearTestResults() {
  testResultsBody.innerHTML = "";
}

export function addQAPair(question = "", expected = "") {
  qaCounter += 1;
  const div = document.createElement("div");
  div.className = "test-qa-row";
  div.innerHTML = `<div class="field"><label>Question ${qaCounter}</label><input type="text" class="test-question" value="${question.replaceAll('"', '&quot;')}"></div>
<div class="field"><label>Expected Keywords</label><input type="text" class="test-expected" value="${expected.replaceAll('"', '&quot;')}"></div>
<button type="button" class="qa-remove-btn">\u2715</button>`;
  div.querySelector(".qa-remove-btn").addEventListener("click", () => {
    div.remove();
    renumberQA();
  });
  testQAList.appendChild(div);
  renumberQA();
}

function renumberQA() {
  let i = 1;
  for (const row of testQAList.querySelectorAll(".test-qa-row")) {
    row.querySelector("label").textContent = `Question ${i}`;
    i += 1;
  }
}

function getQAPairs() {
  const pairs = [];
  for (const row of testQAList.querySelectorAll(".test-qa-row")) {
    const q = row.querySelector(".test-question").value.trim();
    const kws = row
      .querySelector(".test-expected")
      .value.split(",")
      .map((k) => k.trim())
      .filter(Boolean);
    if (q && kws.length) pairs.push({ question: q, keywords: kws });
  }
  return pairs;
}

// ---- Select All / Per-Provider toggles ----

function syncSelectAllState() {
  const allModels = testModelGrid.querySelectorAll("input[data-provider][data-model]");
  selectAll.checked = [...allModels].every((cb) => cb.checked);
}

function syncProviderCheckbox(provider) {
  const models = testModelGrid.querySelectorAll(`input[data-provider="${provider}"][data-model]`);
  const header = testModelGrid.querySelector(`input.provider-toggle[data-provider="${provider}"]`);
  if (header) header.checked = [...models].every((cb) => cb.checked);
}

function toggleProvider(provider, checked) {
  for (const cb of testModelGrid.querySelectorAll(`input[data-provider="${provider}"][data-model]`)) {
    cb.checked = checked;
  }
  syncSelectAllState();
}

function getSelectedTestModels() {
  const models = [];
  for (const cb of testModelGrid.querySelectorAll("input[data-provider][data-model]:checked")) {
    models.push({ provider: cb.dataset.provider, model: cb.dataset.model });
  }
  return models;
}

// ---- Results table ----

const SPINNER_HTML = '<span class="spinner"></span>';

function getOrCreateRow(provider, model) {
  const rowId = `test-row-${provider}-${model}`;
  let row = document.getElementById(rowId);
  if (!row) {
    row = document.createElement("tr");
    row.id = rowId;
    row.innerHTML = `<td>${testResultsBody.children.length + 1}</td><td>${provider}</td><td>${model}</td><td data-col="new">${SPINNER_HTML}</td><td data-col="resume">\u2014</td><td data-col="grade">\u2014</td>`;
    testResultsBody.appendChild(row);
  }
  return row;
}

function updateCell(row, col, value, className = "") {
  const cell = row.querySelector(`[data-col="${col}"]`);
  cell.textContent = value;
  cell.className = className;
}

// ---- Generate scenario ----

async function generateScenario() {
  generateAllBtn.disabled = true;
  setTestMeta("Generating scenario...");
  try {
    const payload = { field: "all", workspace_path: getWorkspaceInput().value.trim() };
    const selected = generateModelSelect.value;
    if (selected !== "auto") {
      const [provider, ...modelParts] = selected.split("/");
      payload.provider = provider;
      payload.model = modelParts.join("/");
    }
    const response = await fetch("/v1/test/generate-scenario", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    if (data.story) testStoryEl.value = data.story;
    if (Array.isArray(data.qa_pairs)) {
      testQAList.innerHTML = "";
      qaCounter = 0;
      for (const pair of data.qa_pairs) addQAPair(pair.question || "", pair.expected || "");
    }
    setTestMeta("Scenario generated.");
  } catch (error) {
    setTestMeta(error.message, true);
  } finally {
    generateAllBtn.disabled = false;
  }
}

// ---- Render model grid + generate model selector ----

export function renderTestLabModels() {
  testModelGrid.innerHTML = "";
  const workers = getWorkers();
  const groups = {};
  for (const worker of workers) {
    groups[worker.provider] = groups[worker.provider] || [];
    groups[worker.provider].push(worker);
  }

  for (const [provider, models] of Object.entries(groups)) {
    const group = document.createElement("div");
    group.className = "provider-group";

    const header = document.createElement("div");
    header.className = "provider-group-header";
    header.innerHTML = `<input type="checkbox" class="provider-toggle" data-provider="${provider}" checked> ${provider}`;
    header.querySelector("input").addEventListener("change", (e) => {
      toggleProvider(provider, e.target.checked);
    });
    group.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "provider-group-models";
    for (const model of models) {
      const id = `test-model-${provider}-${model.model}`;
      const label = document.createElement("label");
      label.innerHTML = `<input type="checkbox" id="${id}" data-provider="${provider}" data-model="${model.model}" checked> ${model.model}`;
      label.querySelector("input").addEventListener("change", () => {
        syncProviderCheckbox(provider);
        syncSelectAllState();
      });
      grid.appendChild(label);
    }
    group.appendChild(grid);
    testModelGrid.appendChild(group);
  }
  syncSelectAllState();

  // Populate generate model selector
  generateModelSelect.innerHTML = '<option value="auto">Auto (cheapest)</option>';
  for (const w of workers) {
    if (w.ready) {
      const opt = document.createElement("option");
      opt.value = `${w.provider}/${w.model}`;
      opt.textContent = `${w.provider} / ${w.model}`;
      generateModelSelect.appendChild(opt);
    }
  }
}

// ---- Run test ----

async function testSingleModel(selected, workspace, story, qaPairs) {
  const row = getOrCreateRow(selected.provider, selected.model);
  try {
    const newResp = await fetch("/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: selected.provider,
        model: selected.model,
        workspace_path: workspace,
        mode: "new",
        prompt: story,
        stream: false,
      }),
    });
    const newData = await newResp.json();
    const newOk = newResp.ok && newData.exit_code === 0;
    updateCell(row, "new", newOk ? "OK" : "FAIL", newOk ? "ok" : "error");
    let passed = 0;
    if (newOk && newData.provider_session_ref) {
      const resumeCell = row.querySelector('[data-col="resume"]');
      resumeCell.innerHTML = `<div class="resume-progress"><span>${SPINNER_HTML} 0/${qaPairs.length}</span><div class="resume-bar-track"><div class="resume-bar-fill" style="width:0%"></div></div></div>`;
      // Resume calls must be sequential per model (same session).
      let completed = 0;
      for (const qa of qaPairs) {
        const resumeResp = await fetch("/v1/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: selected.provider,
            model: selected.model,
            workspace_path: workspace,
            mode: "resume",
            provider_session_ref: newData.provider_session_ref,
            prompt: qa.question,
            stream: false,
          }),
        });
        const resumeData = await resumeResp.json();
        const text = (resumeData.final_text || "").toLowerCase();
        if (
          resumeResp.ok
          && resumeData.exit_code === 0
          && qa.keywords.every((kw) => text.includes(kw.toLowerCase()))
        ) {
          passed += 1;
        }
        completed += 1;
        const pct = Math.round((completed / qaPairs.length) * 100);
        const stillRunning = completed < qaPairs.length;
        resumeCell.innerHTML = `<div class="resume-progress"><span>${stillRunning ? SPINNER_HTML + ' ' : ''}${passed}/${qaPairs.length}</span><div class="resume-bar-track"><div class="resume-bar-fill" style="width:${pct}%"></div></div></div>`;
      }
    }
    const isPass = newOk && passed === qaPairs.length;
    row.querySelector('[data-col="grade"]').innerHTML = `<span class="${isPass ? "grade-pass" : "grade-fail"}">${isPass ? "PASS" : "FAIL"}</span>`;
    return isPass;
  } catch {
    updateCell(row, "new", "FAIL", "error");
    updateCell(row, "resume", "FAIL", "error");
    row.querySelector('[data-col="grade"]').innerHTML = '<span class="grade-fail">FAIL</span>';
    return false;
  }
}

export async function runTestLab() {
  const story = testStoryEl.value.trim();
  const qaPairs = getQAPairs();
  const selectedModels = getSelectedTestModels();
  const workspace = getWorkspaceInput().value.trim();
  if (!story) return setTestMeta("Story is required.", true);
  if (!qaPairs.length) return setTestMeta("Add at least one question with keywords.", true);
  if (!selectedModels.length) return setTestMeta("Select at least one model.", true);

  runTestBtn.disabled = true;
  clearTestResults();

  // Pre-create all rows so they appear immediately.
  for (const s of selectedModels) getOrCreateRow(s.provider, s.model);
  setTestMeta(`Running ${selectedModels.length} models in parallel...`);

  // Launch all models in parallel; resume calls within each model stay sequential.
  let doneCount = 0;
  const promises = selectedModels.map((selected) =>
    testSingleModel(selected, workspace, story, qaPairs).then((pass) => {
      doneCount += 1;
      setTestMeta(`Progress: ${doneCount}/${selectedModels.length} models completed...`);
      return pass;
    }),
  );

  const results = await Promise.allSettled(promises);
  const passCount = results.filter((r) => r.status === "fulfilled" && r.value).length;
  setTestMeta(`Done: ${passCount}/${selectedModels.length} PASS.`);
  runTestBtn.disabled = false;
}

// ---- Event listeners ----

addQABtn.addEventListener("click", () => addQAPair());
generateAllBtn.addEventListener("click", generateScenario);
runTestBtn.addEventListener("click", runTestLab);
selectAll.addEventListener("change", (event) => {
  for (const cb of testModelGrid.querySelectorAll("input[data-provider][data-model]")) {
    cb.checked = event.target.checked;
  }
  for (const toggle of testModelGrid.querySelectorAll("input.provider-toggle")) {
    toggle.checked = event.target.checked;
  }
  syncSelectAllState();
});
