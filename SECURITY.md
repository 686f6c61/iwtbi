# Security Policy

## Reporting a vulnerability

Please report vulnerabilities through GitHub's private security advisory
feature for this repository. Do not open a public issue containing exploit
details, credentials or personal data.

Include the affected version, reproduction steps, impact and any proposed
mitigation. Maintainers should acknowledge a complete report within seven days.

## Self-host responsibilities

- Keep PostgreSQL and Redis on a private network.
- Use HTTPS and restrict `CORS_ORIGINS` and `ALLOWED_HOSTS` to your domains.
- Set unique values for every secret in `.env` and never commit that file.
- Enable Cloudflare client headers only when traffic actually passes through a
  trusted Cloudflare or sanitizing proxy.
- Rotate provider and Resend keys if they are exposed.
