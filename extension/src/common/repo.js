(function initRepoHelpers(globalScope) {
  const RESERVED_TOP_LEVEL = new Set([
    "about",
    "account",
    "apps",
    "codespaces",
    "copilot",
    "dashboard",
    "discussions",
    "gist",
    "marketplace",
    "models",
    "readme",
    "collections",
    "contact",
    "customer-stories",
    "enterprise",
    "events",
    "explore",
    "features",
    "issues",
    "login",
    "new",
    "notifications",
    "orgs",
    "organizations",
    "pricing",
    "pulls",
    "search",
    "security",
    "sessions",
    "settings",
    "signup",
    "site",
    "sponsors",
    "team",
    "teams",
    "topics",
    "trending",
    "users",
  ]);

  const REPO_PART_PATTERN = /^[A-Za-z0-9_.-]+$/;
  const OWNER_PATTERN = /^(?!-)[A-Za-z0-9-]{1,39}$/;

  function parseGithubRepoUrl(rawUrl) {
    if (!rawUrl) return null;

    let parsedUrl;
    try {
      parsedUrl = new URL(rawUrl);
    } catch {
      return null;
    }

    const hostname = parsedUrl.hostname.toLowerCase();
    if (hostname !== "github.com" && hostname !== "www.github.com") return null;

    const parts = parsedUrl.pathname.split("/").filter(Boolean);
    if (parts.length < 2) return null;

    const owner = parts[0];
    let repo = parts[1];

    if (!owner || !repo) return null;
    if (RESERVED_TOP_LEVEL.has(owner.toLowerCase())) return null;

    if (repo.endsWith(".git")) {
      repo = repo.slice(0, -4);
    }

    if (!repo) return null;
    if (!OWNER_PATTERN.test(owner) || owner.endsWith("-")) return null;
    if (!REPO_PART_PATTERN.test(repo)) return null;
    if (repo.length > 100 || repo === "." || repo === "..") return null;

    return {
      owner,
      repo,
      slug: `${owner}/${repo}`,
      normalizedUrl: `https://github.com/${owner}/${repo}`,
    };
  }

  globalScope.IWTBIRepo = {
    parseGithubRepoUrl,
  };
})(
  typeof self !== "undefined"
    ? self
    : typeof window !== "undefined"
      ? window
      : globalThis,
);
