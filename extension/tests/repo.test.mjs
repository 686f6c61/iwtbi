import assert from "node:assert/strict";
import test from "node:test";

await import("../src/common/repo.js");

const { parseGithubRepoUrl } = globalThis.IWTBIRepo;

test("detecta repositorios y normaliza subrutas", () => {
  assert.deepEqual(parseGithubRepoUrl("https://github.com/owner/repo/issues/12"), {
    owner: "owner",
    repo: "repo",
    slug: "owner/repo",
    normalizedUrl: "https://github.com/owner/repo",
  });
  assert.equal(
    parseGithubRepoUrl("https://www.github.com/owner/repo.git").normalizedUrl,
    "https://github.com/owner/repo",
  );
});

test("ignora páginas de producto de GitHub", () => {
  for (const url of [
    "https://github.com/settings/profile",
    "https://github.com/copilot/features",
    "https://github.com/marketplace/actions",
    "https://github.com/dashboard/activity",
  ]) {
    assert.equal(parseGithubRepoUrl(url), null, url);
  }
});

test("rechaza hosts, propietarios y nombres inválidos", () => {
  for (const url of [
    "https://example.com/owner/repo",
    "https://github.com/owner",
    "https://github.com/-owner/repo",
    "https://github.com/owner-/repo",
    "https://github.com/owner/repo%20name",
    "not-a-url",
  ]) {
    assert.equal(parseGithubRepoUrl(url), null, url);
  }
});
