if (typeof importScripts === "function") {
  importScripts("./repo.js");
}

const ext = globalThis.browser ?? globalThis.chrome;
const { parseGithubRepoUrl } = globalThis.IWTBIRepo;

const ACTIVE_ICONS = {
  16: "assets/icons/active-16.png",
  32: "assets/icons/active-32.png",
  48: "assets/icons/active-48.png",
  128: "assets/icons/active-128.png",
};

const IDLE_ICONS = {
  16: "assets/icons/idle-16.png",
  32: "assets/icons/idle-32.png",
  48: "assets/icons/idle-48.png",
  128: "assets/icons/idle-128.png",
};

function runSafely(task) {
  Promise.resolve(task).catch(() => {
    // La pestaña puede cerrarse o cambiar mientras se actualiza el icono.
  });
}

async function setActionState(tabId, repoInfo) {
  if (typeof tabId !== "number") return;

  if (repoInfo) {
    await ext.action.enable(tabId);
    await ext.action.setIcon({ tabId, path: ACTIVE_ICONS });
    await ext.action.setTitle({
      tabId,
      title: `IWTBI listo para analizar ${repoInfo.slug}`,
    });
    return;
  }

  await ext.action.disable(tabId);
  await ext.action.setIcon({ tabId, path: IDLE_ICONS });
  await ext.action.setTitle({
    tabId,
    title: "IWTBI se activa solo sobre repositorios de GitHub",
  });
}

async function refreshTab(tabId) {
  if (typeof tabId !== "number") return;
  const tab = await ext.tabs.get(tabId);
  const repoInfo = parseGithubRepoUrl(tab?.url);
  await setActionState(tabId, repoInfo);
}

async function refreshActiveTab() {
  const [tab] = await ext.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab?.id) return;
  await refreshTab(tab.id);
}

ext.runtime.onInstalled.addListener(() => {
  runSafely(refreshActiveTab());
});

ext.runtime.onStartup?.addListener(() => {
  runSafely(refreshActiveTab());
});

ext.tabs.onActivated.addListener(({ tabId }) => {
  runSafely(refreshTab(tabId));
});

ext.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!changeInfo.url && changeInfo.status !== "complete") return;
  runSafely(setActionState(tabId, parseGithubRepoUrl(tab?.url)));
});

ext.windows?.onFocusChanged?.addListener(() => {
  runSafely(refreshActiveTab());
});
