---
name: pa-pa-le
---

# 爬爬乐 Bundled Reference

Use this reference as the shared crawling layer when `$pa-pa-le` is not installed in the current agent runtime.

## Core Rules

- Separate official announcements, news, institution views, structured data, retail posts, social posts, and comments.
- Escalate from light to heavy methods: local cache/API/static HTML first, dynamic rendering/CDP/login/browser tools only when needed.
- Record source name, URL, method, login state, timestamp, status, sample count, and failure reason for every attempt.
- Keep source links and timestamps beside each fact.
- Do not bypass paywalls, CAPTCHA, access controls, or anti-abuse mechanisms.
- Do not use future-dated content for historical reports unless the user explicitly asks for latest-as-of-now.

## Crawl Ladder

1. Existing project data, MCP resources, local cache, configured APIs.
2. Official APIs, RSS, downloadable JSON/CSV/PDF, static HTML.
3. Public JSON endpoints, search pages, sitemap pages, static forum/list pages.
4. Dynamic rendering with Browser, Playwright, browser-use, or CDP.
5. Logged-in Chrome/CDP using the user's existing authenticated session.
6. Specialized crawling tooling: OpenCli, Scrapling, xcral, Agent Reach, site-specific CLIs or SDKs.
7. User-assisted login, token/API permission request, or manual source confirmation.

## Evidence Package

Save or return data in this shape when scripts need manual crawler support:

```json
{
  "generated_at": "YYYY-MM-DD HH:MM:SS",
  "target": {"topic": "...", "date_window": "..."},
  "quality": {"level": "ok|partial|empty|blocked", "summary": "..."},
  "source_status": [
    {"source": "...", "category": "...", "method": "...", "status": "ok|empty|blocked|failed", "detail": "..."}
  ],
  "items": [
    {
      "category": "official|news|institution_view|structured_data|retail_post|social_post|comment|macro",
      "source": "...",
      "url": "...",
      "published_at": "...",
      "fetched_at": "...",
      "title": "...",
      "summary": "...",
      "evidence": "...",
      "confidence": "high|medium|low"
    }
  ],
  "errors": []
}
```

## Evolution

When a new source pattern, comment endpoint, successful CDP method, Scrapling/xcral tactic, or blocker signature is discovered, add the smallest reusable note to this reference or to the standalone `pa-pa-le` skill.
