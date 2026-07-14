import { marked, type Renderer } from "marked";
import DOMPurify from "dompurify";

const renderer: Partial<Renderer> = {
  code({ text, lang }) {
    if (lang === "mermaid") {
      const normalized = normalizeMermaidSource(text);
      const escaped = normalized
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return `<div class="mermaid">${escaped}</div>`;
    }

    const escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return `<pre><code class="language-${lang ?? ""}">${escaped}</code></pre>`;
  },
};

marked.use({ renderer });

const markdownPurifyConfig: DOMPurify.Config = {
  USE_PROFILES: { html: true },
  ADD_ATTR: ["class", "id", "target", "rel"],
  FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "svg", "math", "foreignObject"],
};

const mermaidPurifyConfig: DOMPurify.Config = {
  USE_PROFILES: { svg: true, svgFilters: true },
  ADD_TAGS: ["marker"],
  ADD_ATTR: ["class", "id", "role", "aria-roledescription", "aria-label", "marker-end"],
  FORBID_TAGS: ["script", "style", "foreignObject"],
};

let mermaidModulePromise: Promise<typeof import("mermaid")> | null = null;
const MAX_READABLE_DIAGRAM_WIDTH = 1800;
const WIDTH_PER_TEXT_LABEL = 40;

function normalizeMermaidSource(src: string): string {
  const normalized = src
    .replace(/\binteger\b/g, "int")
    .replace(/\btimestamp\b/g, "datetime")
    .replace(/\bbytea\b/g, "blob")
    .replace(/\bjsonb?\b/g, "string")
    .replace(/\btext\b/g, "string")
    .replace(/\bboolean\b/g, "bool")
    .replace(/\bbigint\b/g, "int")
    .replace(/\bnumeric\b/g, "float")
    .replace(/\[([^\]]*?)@([^\]]*?)\]/g, (_m, pre, post) => `[${(pre + post).trim() || "?"}]`)
    .replace(/\[([^\]]*?)\/([^\]]*?)\]/g, (_m, pre, post) => `[${pre}-${post}]`)
    .replace(/:\s*"([^"]*?)\/([^"]*?)"/g, (_m, pre, post) => `: "${pre}-${post}"`)
    .replace(/:\s*"([^"]+)"/g, (_m, label) => `: "${label.replace(/\s+/g, "-")}"`)
    .replace(/\b(PK|FK|UK)\s+(PK|FK|UK)\b/g, (_m, _first, second) => second);

  return normalizeFlowchartNodeIds(normalized);
}

function normalizeFlowchartNodeIds(src: string): string {
  const diagramType = src.trimStart().match(/^(graph|flowchart)\b/);
  if (!diagramType) {
    return src;
  }

  const aliases = new Map<string, string>();
  const definedAliases = new Set<string>();

  const normalizeEndpoint = (segment: string): string => {
    const match = segment.match(/^(\s*(?:\|[^|]*\|\s*)?)(.*?)(\s*)$/s);
    if (!match) {
      return segment;
    }

    const [, prefix, endpoint, suffix] = match;
    const shapeIndex = endpoint.search(/[\[({]/);
    const rawId = (shapeIndex === -1 ? endpoint : endpoint.slice(0, shapeIndex)).trim();
    if (!rawId || /^[A-Za-z_][A-Za-z0-9_-]*$/.test(rawId)) {
      return segment;
    }

    let alias = aliases.get(rawId);
    if (!alias) {
      const asciiId = rawId
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^A-Za-z0-9_-]+/g, "_")
        .replace(/^_+|_+$/g, "") || "node";
      alias = `node_${asciiId}`;
      aliases.set(rawId, alias);
    }

    const idStart = endpoint.indexOf(rawId);
    const shouldAddLabel = shapeIndex === -1 && !definedAliases.has(rawId);
    if (shapeIndex !== -1 || shouldAddLabel) {
      definedAliases.add(rawId);
    }
    const readableLabel = rawId.replace(/"/g, "&quot;");
    const normalizedEndpoint =
      endpoint.slice(0, idStart) +
      alias +
      (shouldAddLabel ? `["${readableLabel}"]` : "") +
      endpoint.slice(idStart + rawId.length);
    return prefix + normalizedEndpoint + suffix;
  };

  const normalizedIds = src
    .split("\n")
    .map((line) =>
      line.includes("-->")
        ? line.split("-->").map(normalizeEndpoint).join("-->")
        : line,
    )
    .join("\n");

  return normalizedIds
    .replace(/\[([^\]\n]+)\]/g, (_match, label: string) => {
      const trimmed = label.trim();
      return trimmed.startsWith('"') ? `[${label}]` : `["${label.replace(/"/g, "&quot;")}"]`;
    })
    .replace(/\{([^}\n]+)\}/g, (_match, label: string) => {
      const trimmed = label.trim();
      return trimmed.startsWith('"') ? `{${label}}` : `{"${label.replace(/"/g, "&quot;")}"}`;
    });
}

async function getMermaid() {
  if (!mermaidModulePromise) {
    mermaidModulePromise = import("mermaid").then((module) => {
      module.default.initialize({
        startOnLoad: false,
        theme: "base",
        securityLevel: "strict",
        htmlLabels: false,
        flowchart: {
          htmlLabels: false,
        },
        themeVariables: {
          background: "transparent",
          primaryColor: "#fffaf7",
          primaryTextColor: "#222222",
          primaryBorderColor: "#222222",
          lineColor: "#222222",
          secondaryColor: "#eef5ff",
          tertiaryColor: "#f2fcf5",
          fontFamily: "inherit",
        },
      });
      return module;
    });
  }

  return mermaidModulePromise;
}

async function renderMermaidDiagrams(root: HTMLElement) {
  const mermaidNodes = root.querySelectorAll<HTMLElement>(".mermaid");
  if (mermaidNodes.length === 0) {
    return;
  }

  const { default: mermaid } = await getMermaid();

  for (const [index, node] of Array.from(mermaidNodes).entries()) {
    const source = node.textContent ?? "";
    const renderId = `mermaid-${Date.now()}-${index}`;
    try {
      const { svg } = await mermaid.render(renderId, source);
      node.innerHTML = DOMPurify.sanitize(svg, mermaidPurifyConfig);
      node.classList.add("mermaid-rendered");
      sizeMermaidForReadability(node);
    } catch {
      document.getElementById(renderId)?.remove();
      document.getElementById(`d${renderId}`)?.remove();
      const pre = document.createElement("pre");
      pre.className = "mermaid-error";
      const code = document.createElement("code");
      code.textContent = source;
      pre.appendChild(code);
      node.replaceWith(pre);
    }
  }
}

function sizeMermaidForReadability(node: HTMLElement) {
  const svg = node.querySelector<SVGSVGElement>("svg");
  const viewBox = svg?.viewBox.baseVal;
  if (!svg || !viewBox || viewBox.width <= 0) {
    return;
  }

  const availableWidth = Math.max(node.clientWidth - 32, 1);
  const textLabels = svg.querySelectorAll("text").length;
  const densityWidth = Math.min(
    MAX_READABLE_DIAGRAM_WIDTH,
    textLabels * WIDTH_PER_TEXT_LABEL,
  );
  const readableWidth = Math.ceil(
    Math.min(viewBox.width, Math.max(availableWidth, densityWidth)),
  );

  svg.style.width = `${readableWidth}px`;
  svg.style.maxWidth = "none";
  svg.style.height = "auto";

  const isScrollable = readableWidth > availableWidth + 1;
  node.classList.toggle("mermaid-scrollable", isScrollable);
  if (isScrollable) {
    node.tabIndex = 0;
    node.setAttribute("aria-label", "Diagrama desplazable");
  }
}

export async function renderMarkdownInto(
  target: HTMLElement,
  markdown: string,
  wrapperClass = "prose",
) {
  const wrapper = document.createElement("div");
  wrapper.className = wrapperClass;

  try {
    const rawHtml = await marked.parse(markdown);
    wrapper.innerHTML = DOMPurify.sanitize(rawHtml, markdownPurifyConfig);
    target.replaceChildren(wrapper);
    await new Promise<void>((resolve) => {
      window.requestAnimationFrame(() => resolve());
    });
    await renderMermaidDiagrams(wrapper);
  } catch {
    const pre = document.createElement("pre");
    pre.className = "doc-markdown-fallback";
    pre.textContent = markdown;
    wrapper.replaceChildren(pre);
    target.replaceChildren(wrapper);
  }
}
