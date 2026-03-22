import { getWorkspaceInput, refreshState } from "/static/request.js";
import { addQAPair, renderTestLabModels } from "/static/testlab.js";

function switchTab(tabName) {
  for (const panel of document.querySelectorAll(".tab-panel")) panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  for (const btn of document.querySelectorAll(".tab-btn")) btn.classList.toggle("active", btn.dataset.tab === tabName);
}

for (const btn of document.querySelectorAll(".tab-btn")) {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
}

window.addEventListener("load", async () => {
  const workspace = getWorkspaceInput();
  const saved = sessionStorage.getItem("workspace_path");
  if (saved) workspace.value = saved;
  // workspace_path is set by refreshState() from the health endpoint when still empty.

  addQAPair("What is my responsibility in the fintech?", "PF, ATM, Transit");
  addQAPair("What is my car's color?", "grey");
  addQAPair("Where am I a director at?", "fintech");

  try {
    await refreshState();
    renderTestLabModels();
  } catch {
    // request.js handles visible errors through request-meta.
  }
});
