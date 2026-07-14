(function initPopup() {
  const ext = globalThis.browser ?? globalThis.chrome;
  const { parseGithubRepoUrl } = globalThis.IWTBIRepo;

  const appBaseUrl = globalThis.IWTBI_CONFIG.appBaseUrl;
  const appHost = new URL(appBaseUrl).host;
  const analyzeBaseUrl = `${appBaseUrl}/analyze`;
  const libraryUrl = `${appBaseUrl}/biblioteca`;
  const DEFAULT_SETTINGS = {
    bannerEnabled: true,
    bannerMode: "showcase",
  };

  const titleNode = document.getElementById("popup-title");
  const descNode = document.getElementById("popup-desc");
  const slugNode = document.getElementById("repo-slug");
  const repoUrlNode = document.getElementById("repo-url");
  const chipNode = document.getElementById("popup-chip");
  const metaNode = document.getElementById("popup-meta");
  const footNode = document.getElementById("popup-foot");
  const analyzeButton = document.getElementById("analyze-btn");
  const openAppButton = document.getElementById("open-app-btn");
  const closeButton = document.getElementById("popup-close");
  const bannerEnabledInput = document.getElementById("banner-enabled");
  const switchTextNode = document.getElementById("switch-text");
  const modeButtons = Array.from(document.querySelectorAll(".mode-pill"));

  async function getActiveRepo() {
    const [tab] = await ext.tabs.query({ active: true, lastFocusedWindow: true });
    return parseGithubRepoUrl(tab?.url);
  }

  async function openUrl(url) {
    try {
      await ext.tabs.create({ url });
      window.close();
    } catch {
      footNode.textContent = "No se pudo abrir la pestaña. Revisa los permisos de la extensión.";
    }
  }

  async function getSettings() {
    const stored = await ext.storage.local.get(DEFAULT_SETTINGS);
    return {
      bannerEnabled: stored.bannerEnabled !== false,
      bannerMode: stored.bannerMode === "compact" ? "compact" : "showcase",
    };
  }

  async function saveSettings(patch) {
    try {
      await ext.storage.local.set(patch);
    } catch {
      footNode.textContent = "No se pudo guardar la preferencia en este navegador.";
    }
  }

  function renderSettings(settings) {
    bannerEnabledInput.checked = settings.bannerEnabled;
    switchTextNode.textContent = settings.bannerEnabled ? "Activa" : "Oculta";
    modeButtons.forEach((button) => {
      const isActive = button.dataset.mode === settings.bannerMode;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
      button.disabled = !settings.bannerEnabled;
      button.setAttribute("aria-disabled", String(!settings.bannerEnabled));
    });
  }

  function renderRepo(repoInfo) {
    document.body.classList.toggle("is-empty", !repoInfo);

    if (!repoInfo) {
      metaNode.textContent = "abre un repo de GitHub";
      chipNode.textContent = "extensión dormida";
      titleNode.textContent = "Abre un repositorio";
      descNode.textContent =
        "IWTBI se activa cuando estás navegando dentro de un repositorio de GitHub.";
      slugNode.textContent = "owner/repo";
      repoUrlNode.textContent = "https://github.com/owner/repo";
      footNode.textContent =
        "Cuando entres en un repo, el icono se activará y podrás lanzarlo en IWTBI con un clic.";
      analyzeButton.textContent = `Ir a ${appHost}`;
      openAppButton.textContent = "Abrir GitHub";
      analyzeButton.onclick = () => void openUrl(appBaseUrl);
      openAppButton.onclick = () => void openUrl("https://github.com");
      return;
    }

    metaNode.textContent = "repo detectado";
    chipNode.textContent = "repo detectado";
    titleNode.textContent = "Construir este repo";
    descNode.textContent =
      "Crea un documento Markdown autocontenido para reconstruir este repositorio con una IA.";
    slugNode.textContent = repoInfo.slug;
    repoUrlNode.textContent = repoInfo.normalizedUrl;
    footNode.textContent =
      `Abre una pestaña nueva con la URL ya preparada en ${appHost}/analyze.`;
    analyzeButton.textContent = "Crear documento →";
    openAppButton.textContent = "Abrir biblioteca";

    analyzeButton.onclick = () => {
      void openUrl(`${analyzeBaseUrl}?url=${encodeURIComponent(repoInfo.normalizedUrl)}`);
    };
    openAppButton.onclick = () => void openUrl(libraryUrl);
  }

  closeButton.addEventListener("click", () => {
    window.close();
  });

  bannerEnabledInput.addEventListener("change", async () => {
    const currentMode = document.querySelector(".mode-pill.is-active")?.dataset.mode ?? "showcase";
    renderSettings({
      bannerEnabled: bannerEnabledInput.checked,
      bannerMode: currentMode,
    });
    await saveSettings({ bannerEnabled: bannerEnabledInput.checked });
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const bannerMode = button.dataset.mode === "compact" ? "compact" : "showcase";
      renderSettings({
        bannerEnabled: bannerEnabledInput.checked,
        bannerMode,
      });
      await saveSettings({ bannerMode });
    });
  });

  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const [repoInfo, settings] = await Promise.all([getActiveRepo(), getSettings()]);
      renderRepo(repoInfo);
      renderSettings(settings);
    } catch {
      renderRepo(null);
      renderSettings(DEFAULT_SETTINGS);
      footNode.textContent = "No se pudo leer la pestaña actual. Abre el repositorio y vuelve a intentarlo.";
    }
  });
})();
