import type { APIRoute } from "astro";

export const prerender = true;

export const GET: APIRoute = () => {
  const appUrl = (import.meta.env.PUBLIC_APP_URL ?? "http://localhost:3410").replace(/\/+$/, "");
  const body = [
    "User-agent: *",
    "Allow: /",
    "Disallow: /analyze",
    `Sitemap: ${appUrl}/sitemap-index.xml`,
    "",
  ].join("\n");

  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
