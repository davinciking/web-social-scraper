# Web & Social Intelligence Agent Rules

You are configured with the **Web & Social Scraper** workflow in this workspace. When the user gives you a topic, company, technology, trend, or URL(s) to investigate:

1. **Combine Search + Multi-Platform Scraping**:
   - Use `search_web` for broad web coverage and search-indexed social pages (`site:x.com`, `site:reddit.com`, `site:news.ycombinator.com`).
   - Run [scrape_sources.py](file:///Users/dee/.gemini/antigravity/scratch/web-social-scraper/scripts/scrape_sources.py) (`--query` and `--urls`) to fetch structured posts, scores, and comment threads from Reddit, Hacker News, Bluesky, Mastodon, X/Twitter, and Google News RSS.
   - For JavaScript-heavy or login-gated social feeds, fall back to the `chrome-devtools` MCP browser tools if needed.

2. **Parallel Subagent Delegation**:
   - For broad or multi-topic research requests, spawn the `web-social-scraper` subagent via `invoke_subagent` so scraping and deep-dive URL reading happen in an isolated context without cluttering the main chat.

3. **Evidence-Backed Synthesis**:
   - Always cite every claim, quote, or sentiment point with a direct clickable link to the original article or social post.
   - Distinguish clearly between official/editorial coverage (blogs, press releases, news) and grassroots community sentiment (Reddit threads, HN comments, Bluesky/Mastodon/X posts).
