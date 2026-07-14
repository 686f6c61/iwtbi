(function initInlineBanner() {
  const ext = globalThis.browser ?? globalThis.chrome;
  const { parseGithubRepoUrl } = globalThis.IWTBIRepo;
  const appBaseUrl = globalThis.IWTBI_CONFIG.appBaseUrl;
  const bannerSlotId = "iwtbi-inline-slot";
  const brandIconUrl = ext.runtime.getURL("assets/brand/icon-64.png");
  const DEFAULT_SETTINGS = {
    bannerEnabled: true,
    bannerMode: "showcase",
  };
  let awaitingAnchor = true;
  let lastObservedUrl = globalThis.location.href;

  function getRepoInfo() {
    return parseGithubRepoUrl(globalThis.location.href);
  }

  function getAnalyzeUrl(repoInfo) {
    return `${appBaseUrl}/analyze?url=${encodeURIComponent(repoInfo.normalizedUrl)}`;
  }

  async function getSettings() {
    try {
      const stored = await ext.storage.local.get(DEFAULT_SETTINGS);
      return {
        bannerEnabled: stored.bannerEnabled !== false,
        bannerMode: stored.bannerMode === "compact" ? "compact" : "showcase",
      };
    } catch {
      return DEFAULT_SETTINGS;
    }
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text) element.textContent = text;
    return element;
  }

  function buildBanner(repoInfo, settings) {
    const slot = document.createElement("section");
    slot.id = bannerSlotId;
    slot.setAttribute("aria-label", `IWTBI para ${repoInfo.slug}`);

    const banner = createElement("div", "");
    banner.id = "iwtbi-inline-banner";
    banner.classList.toggle(
      "iwtbi-inline-banner-compact",
      settings.bannerMode === "compact",
    );

    const main = createElement("div", "iwtbi-inline-main");
    const icon = createElement("div", "iwtbi-inline-icon");
    icon.setAttribute("aria-hidden", "true");
    const image = document.createElement("img");
    image.src = brandIconUrl;
    image.alt = "";
    icon.appendChild(image);

    const copy = createElement("div", "iwtbi-inline-copy");
    const brandLine = createElement("div", "iwtbi-inline-brandline");
    brandLine.append(
      createElement("span", "iwtbi-inline-wordmark", "IWTBI"),
      createElement("span", "iwtbi-inline-brandsub", "for GitHub"),
    );
    copy.append(
      brandLine,
      createElement("span", "iwtbi-inline-chip", "repo detectado"),
      createElement("div", "iwtbi-inline-title", `Analiza ${repoInfo.slug} con IWTBI`),
      createElement(
        "div",
        "iwtbi-inline-sub",
        "Crea un documento Markdown autocontenido para reconstruir este repositorio con una IA.",
      ),
    );
    main.append(icon, copy);

    const actions = createElement("div", "iwtbi-inline-actions");
    const analyzeLink = createElement(
      "a",
      "iwtbi-inline-btn iwtbi-inline-btn-primary",
      "Crear documento →",
    );
    analyzeLink.href = getAnalyzeUrl(repoInfo);
    analyzeLink.target = "_blank";
    analyzeLink.rel = "noreferrer noopener";
    const appLink = createElement(
      "a",
      "iwtbi-inline-btn iwtbi-inline-btn-secondary",
      "Abrir biblioteca",
    );
    appLink.href = `${appBaseUrl}/biblioteca`;
    appLink.target = "_blank";
    appLink.rel = "noreferrer noopener";
    actions.append(analyzeLink, appLink);

    banner.append(main, actions);
    slot.appendChild(banner);
    return slot;
  }

  function findAnchor() {
    return (
      document.querySelector("#repository-container-header") ||
      document.querySelector("main")
    );
  }

  async function renderBanner() {
    const existing = document.getElementById(bannerSlotId);
    const repoInfo = getRepoInfo();
    const settings = await getSettings();

    if (!repoInfo || !settings.bannerEnabled) {
      awaitingAnchor = false;
      existing?.remove();
      return;
    }

    const anchor = findAnchor();
    if (!anchor) {
      awaitingAnchor = true;
      return;
    }
    awaitingAnchor = false;

    if (existing) {
      if (existing.previousElementSibling !== anchor) {
        existing.remove();
      } else {
        const banner = existing.querySelector("#iwtbi-inline-banner");
        const title = existing.querySelector(".iwtbi-inline-title");
        const primary = existing.querySelector(".iwtbi-inline-btn-primary");
        banner?.classList.toggle("iwtbi-inline-banner-compact", settings.bannerMode === "compact");
        if (title) title.textContent = `Analiza ${repoInfo.slug} con IWTBI`;
        if (primary) primary.setAttribute("href", getAnalyzeUrl(repoInfo));
        return;
      }
    }

    anchor.insertAdjacentElement("afterend", buildBanner(repoInfo, settings));
  }

  let renderTimer = 0;
  function scheduleRender() {
    globalThis.clearTimeout(renderTimer);
    renderTimer = globalThis.setTimeout(renderBanner, 80);
  }

  renderBanner();
  globalThis.addEventListener("popstate", scheduleRender);
  globalThis.addEventListener("hashchange", scheduleRender);
  document.addEventListener("turbo:load", scheduleRender);
  document.addEventListener("pjax:end", scheduleRender);
  ext.storage?.onChanged?.addListener((changes, areaName) => {
    if (areaName !== "local") return;
    if (!("bannerEnabled" in changes) && !("bannerMode" in changes)) return;
    scheduleRender();
  });

  const observer = new MutationObserver(() => {
    const currentUrl = globalThis.location.href;
    if (currentUrl !== lastObservedUrl) {
      lastObservedUrl = currentUrl;
      scheduleRender();
      return;
    }
    if (awaitingAnchor) scheduleRender();
  });
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
