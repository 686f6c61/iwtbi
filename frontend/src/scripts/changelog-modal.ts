import { CHANGELOG } from "../data/changelog";

const CATEGORY_META = {
  added: { label: "Añadido", cls: "cl-cat-added" },
  changed: { label: "Modificado", cls: "cl-cat-changed" },
  fixed: { label: "Corregido", cls: "cl-cat-fixed" },
};

function buildVersionBlock(entry: (typeof CHANGELOG)[number], isLatest: boolean) {
  const wrap = document.createElement("div");
  wrap.className = "cl-version";

  const head = document.createElement("div");
  head.className = "cl-version-head";

  const badge = document.createElement("span");
  badge.className = isLatest ? "cl-badge cl-badge-latest" : "cl-badge";
  badge.textContent = `v${entry.version}`;
  head.appendChild(badge);

  const date = document.createElement("span");
  date.className = "cl-date";
  date.textContent = entry.date;
  head.appendChild(date);

  wrap.appendChild(head);

  for (const section of entry.sections) {
    const meta = CATEGORY_META[section.type] ?? CATEGORY_META.added;

    const catLabel = document.createElement("span");
    catLabel.className = `cl-cat ${meta.cls}`;
    catLabel.textContent = meta.label;
    wrap.appendChild(catLabel);

    const list = document.createElement("ul");
    list.className = "cl-list";
    for (const item of section.items) {
      const li = document.createElement("li");
      li.textContent = item;
      list.appendChild(li);
    }
    wrap.appendChild(list);
  }

  return wrap;
}

function renderChangelog() {
  const scroll = document.getElementById("cl-scroll");
  if (!scroll || scroll.childElementCount > 0) {
    return;
  }

  CHANGELOG.forEach((entry, index) => {
    if (index > 0) {
      const sep = document.createElement("hr");
      sep.className = "cl-sep";
      scroll.appendChild(sep);
    }
    scroll.appendChild(buildVersionBlock(entry, index === 0));
  });
}

export function openChangelog() {
  renderChangelog();
  document.getElementById("cl-overlay")?.classList.remove("cl-hidden");
  document.body.style.overflow = "hidden";
}

export function closeChangelog() {
  document.getElementById("cl-overlay")?.classList.add("cl-hidden");
  document.body.style.overflow = "";
}
