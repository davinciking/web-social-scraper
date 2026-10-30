---
name: web-social-scraper
description: >-
  Scrape and synthesize information from general websites, blogs, news articles,
  and social media platforms (Reddit, Hacker News, Bluesky, Mastodon, X/Twitter)
  on demand for any topic, query, or list of URLs. Use when the user asks to
  research a topic across the web and social media, monitor community sentiment,
  or extract full text and comments from URLs.
---

# Web & Social Platform Scraper Skill

Use this skill whenever the user gives you a topic, product, event, or list of URLs and wants information gathered from both the web (blogs, news, documentation) and social platforms (Reddit, Hacker News, Bluesky, Mastodon, X/Twitter).

## Workflow

### Step 1: Broad Discovery (`search_web` + Multi-Platform Scraper)

1. Run the built-in `search_web` tool for general web/blog/article discovery and X/Twitter/LinkedIn indexed posts (e.g., `site:x.com <topic>` or `site:reddit.com <topic>`).
2. Run the bundled multi-platform scraper script [scrape_sources.py](../../scripts/scrape_sources.py) to pull live social posts, scores, engagement metrics, and news RSS items concurrently:

```bash
python3 /Users/dee/.gemini/antigravity/scratch/web-social-scraper/scripts/scrape_sources.py \
  --query "<YOUR_TOPIC>" \
  --platforms reddit hackernews bluesky mastodon news \
  --limit 8 \
  --format markdown
```

> [!NOTE]
> Because `scrape_sources.py` makes live HTTP requests to external APIs, run it with `BypassSandbox: true` if standard sandbox mode blocks outbound network access.

### Step 2: Deep Dive into Promising URLs & Threads

Take the highest-signal URLs (blog posts, news articles, Reddit threads with `/comments/`, or X/Twitter status URLs) discovered in Step 1 and extract their full article text and top comment trees:

```bash
python3 /Users/dee/.gemini/antigravity/scratch/web-social-scraper/scripts/scrape_sources.py \
  --urls "https://www.reddit.com/r/.../comments/..." "https://example.com/blog-post" \
  --format markdown
```

### Step 3: Browser Fallback for JS-Heavy or Authenticated Pages

If a target page requires client-side JavaScript rendering, infinite scroll, or logged-in session cookies (such as LinkedIn feeds, Instagram, or X timelines):
- Use the `chrome-devtools` MCP tools (`new_page` / `navigate_page` / `take_snapshot` / `evaluate_script`) to render the live DOM and extract visible posts.

### Step 4: Synthesize an Actionable Briefing

Organize findings into a clear Markdown report or artifact with:
- **Executive Summary**: Key takeaways across official/editorial sources vs. community chatter.
- **Web, Blogs & News Highlights**: Key claims and findings with clickable source links.
- **Social Pulse & Sentiment**: What people on Reddit, Hacker News, Bluesky, Mastodon, and X are saying (praise, complaints, debates), citing specific threads and scores.
