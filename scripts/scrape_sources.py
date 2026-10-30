#!/usr/bin/env python3
"""Multi-platform Web & Social Media Scraper for Antigravity Agent.

Supports:
1. Topic search across social & news platforms (--query):
   - Reddit (posts & top comments via public JSON API)
   - Hacker News (stories & discussion discussions via Algolia API)
   - Bluesky (posts via public AT Protocol API)
   - Mastodon (public statuses via mastodon.social API / tag timelines)
   - Google News RSS (latest news & blog articles)
2. Direct URL scraping (--urls):
   - General websites, blogs, and news articles (clean text & metadata extraction)
   - Reddit thread URLs (full post + comment tree extraction)
   - X / Twitter post URLs (via FixTweet/FxTwitter public API & oEmbed fallback)
   - RSS / Atom feeds
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
REDDIT_USER_AGENT = "mac:web-social-scraper:v1.0 (by /u/antigravity_researcher)"


class HTMLToMarkdownParser(HTMLParser):
    """Lightweight stdlib HTML-to-clean-text/markdown extractor."""

    IGNORE_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "iframe",
    }
    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "tr",
        "blockquote",
        "pre",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "br",
        "hr",
    }

    def __init__(self):
        super().__init__()
        self.ignore_depth = 0
        self.in_title = False
        self.title = ""
        self.chunks = []
        self.links = []
        self.meta_description = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in self.IGNORE_TAGS:
            self.ignore_depth += 1
            return
        if self.ignore_depth > 0:
            return

        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = attrs_dict.get("content") or ""
            if name in ("description", "og:description", "twitter:description") and not self.meta_description:
                self.meta_description = content.strip()
        elif tag in ("h1", "h2", "h3", "h4"):
            level = int(tag[1])
            self.chunks.append(f"\n\n{'#' * level} ")
        elif tag == "li":
            self.chunks.append("\n- ")
        elif tag in self.BLOCK_TAGS:
            self.chunks.append("\n")
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href and href.startswith(("http://", "https://")):
                self.links.append(href)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.IGNORE_TAGS and self.ignore_depth > 0:
            self.ignore_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        elif tag in self.BLOCK_TAGS and self.ignore_depth == 0:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.ignore_depth > 0:
            return
        cleaned = re.sub(r"[ \t\r]+", " ", data)
        if cleaned.strip():
            self.chunks.append(cleaned)

    def get_extracted_text(self, max_chars=8000):
        raw = "".join(self.chunks)
        lines = [line.strip() for line in raw.splitlines()]
        non_empty = [line for line in lines if line]
        text = "\n".join(non_empty)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
        return text


def fetch_url(url, headers=None, timeout=12):
    """Fetch URL bytes and content-type safely."""
    req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        raw_bytes = resp.read()
        return raw_bytes, content_type


def search_reddit(query, limit=8):
    """Search Reddit posts across all subreddits using Reddit's public JSON endpoint."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.reddit.com/search.json?q={encoded}&sort=relevance&t=year&limit={limit}"
    results = []
    try:
        raw, _ = fetch_url(url, headers={"User-Agent": REDDIT_USER_AGENT})
        data = json.loads(raw.decode("utf-8", errors="replace"))
        children = data.get("data", {}).get("children", [])
        for child in children:
            post = child.get("data", {})
            permalink = post.get("permalink", "")
            selftext = (post.get("selftext") or "").strip()
            if len(selftext) > 600:
                selftext = selftext[:600] + "..."
            created_utc = post.get("created_utc")
            created_str = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc).strftime("%Y-%m-%d")
                if created_utc
                else ""
            )
            results.append(
                {
                    "platform": "reddit",
                    "title": post.get("title", ""),
                    "subreddit": f"r/{post.get('subreddit', '')}",
                    "author": post.get("author", ""),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "date": created_str,
                    "url": f"https://www.reddit.com{permalink}" if permalink else post.get("url", ""),
                    "external_url": post.get("url", ""),
                    "snippet": selftext,
                }
            )
    except Exception as exc:
        return [{"platform": "reddit", "error": str(exc)}]
    return results


def search_hackernews(query, limit=8):
    """Search Hacker News stories and discussions via Algolia API."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=story&hitsPerPage={limit}"
    results = []
    try:
        raw, _ = fetch_url(url)
        data = json.loads(raw.decode("utf-8", errors="replace"))
        for hit in data.get("hits", []):
            object_id = hit.get("objectID", "")
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            story_text = re.sub(r"<[^>]+>", " ", hit.get("story_text") or "").strip()
            if len(story_text) > 500:
                story_text = story_text[:500] + "..."
            results.append(
                {
                    "platform": "hackernews",
                    "title": hit.get("title", ""),
                    "author": hit.get("author", ""),
                    "score": hit.get("points", 0),
                    "num_comments": hit.get("num_comments", 0),
                    "date": (hit.get("created_at") or "")[:10],
                    "url": hn_url,
                    "external_url": hit.get("url") or hn_url,
                    "snippet": story_text,
                }
            )
    except Exception as exc:
        return [{"platform": "hackernews", "error": str(exc)}]
    return results


def search_bluesky(query, limit=8):
    """Search Bluesky social posts via public AT Protocol endpoint."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q={encoded}&limit={limit}"
    results = []
    try:
        raw, _ = fetch_url(url)
        data = json.loads(raw.decode("utf-8", errors="replace"))
        for post in data.get("posts", []):
            author = post.get("author", {}).get("handle", "")
            record = post.get("record", {})
            text = (record.get("text") or "").strip()
            created_at = (record.get("createdAt") or "")[:10]
            uri = post.get("uri", "")
            rkey = uri.split("/")[-1] if "/" in uri else ""
            web_url = f"https://bsky.app/profile/{author}/post/{rkey}" if author and rkey else uri
            results.append(
                {
                    "platform": "bluesky",
                    "author": f"@{author}" if author else "",
                    "score": post.get("likeCount", 0),
                    "reposts": post.get("repostCount", 0),
                    "num_comments": post.get("replyCount", 0),
                    "date": created_at,
                    "url": web_url,
                    "snippet": text,
                }
            )
    except Exception as exc:
        return [{"platform": "bluesky", "error": str(exc)}]
    return results


def search_mastodon(query, limit=8):
    """Search public Mastodon statuses by hashtag/keyword via mastodon.social."""
    tag = re.sub(r"[^a-zA-Z0-9_]", "", query.split()[0]) if query.strip() else "tech"
    url = f"https://mastodon.social/api/v1/timelines/tag/{tag}?limit={limit}"
    results = []
    try:
        raw, _ = fetch_url(url)
        statuses = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(statuses, list):
            for st in statuses:
                content_html = st.get("content") or ""
                text = re.sub(r"<[^>]+>", " ", content_html)
                text = re.sub(r"\s+", " ", text).strip()
                acct = st.get("account", {}).get("acct", "")
                results.append(
                    {
                        "platform": "mastodon",
                        "author": f"@{acct}" if acct else "",
                        "score": st.get("favourites_count", 0),
                        "reposts": st.get("reblogs_count", 0),
                        "num_comments": st.get("replies_count", 0),
                        "date": (st.get("created_at") or "")[:10],
                        "url": st.get("url", ""),
                        "snippet": text[:500],
                    }
                )
    except Exception as exc:
        return [{"platform": "mastodon", "error": str(exc)}]
    return results


def search_news_rss(query, limit=8):
    """Search Google News RSS feed for recent blog posts and news articles."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    results = []
    try:
        raw, _ = fetch_url(url)
        root = ET.fromstring(raw)
        items = root.findall(".//item")[:limit]
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
            desc_html = item.findtext("description") or ""
            desc_text = re.sub(r"<[^>]+>", " ", desc_html)
            desc_text = re.sub(r"\s+", " ", desc_text).strip()
            results.append(
                {
                    "platform": "news_rss",
                    "title": title,
                    "source": source_name,
                    "date": pub_date,
                    "url": link,
                    "snippet": desc_text[:400],
                }
            )
    except Exception as exc:
        return [{"platform": "news_rss", "error": str(exc)}]
    return results


def scrape_reddit_thread(url, max_comments=15):
    """Scrape a specific Reddit thread URL including top comments."""
    parsed = urllib.parse.urlparse(url)
    clean_path = parsed.path.rstrip("/")
    if not clean_path.endswith(".json"):
        json_url = f"https://www.reddit.com{clean_path}.json?limit={max_comments}"
    else:
        json_url = url

    raw, _ = fetch_url(json_url, headers={"User-Agent": REDDIT_USER_AGENT})
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    post_data = payload[0]["data"]["children"][0]["data"]
    comments_raw = payload[1]["data"]["children"] if len(payload) > 1 else []

    comments = []
    for c in comments_raw[:max_comments]:
        if c.get("kind") != "t1":
            continue
        cd = c.get("data", {})
        body = (cd.get("body") or "").strip()
        if body:
            comments.append(
                {
                    "author": cd.get("author", ""),
                    "score": cd.get("score", 0),
                    "body": body[:1000],
                }
            )

    return {
        "url": url,
        "type": "reddit_thread",
        "title": post_data.get("title", ""),
        "subreddit": f"r/{post_data.get('subreddit', '')}",
        "author": post_data.get("author", ""),
        "score": post_data.get("score", 0),
        "selftext": post_data.get("selftext", ""),
        "top_comments": comments,
    }


def scrape_x_post(url):
    """Scrape an X/Twitter status URL using FxTwitter public API with oEmbed fallback."""
    match = re.search(r"(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)", url)
    if match:
        user, status_id = match.group(1), match.group(2)
        fx_url = f"https://api.fxtwitter.com/{user}/status/{status_id}"
        try:
            raw, _ = fetch_url(fx_url)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            tweet = data.get("tweet", {})
            return {
                "url": url,
                "type": "x_post",
                "author": f"@{tweet.get('author', {}).get('screen_name', user)}",
                "author_name": tweet.get("author", {}).get("name", ""),
                "date": tweet.get("created_at", ""),
                "text": tweet.get("text", ""),
                "likes": tweet.get("likes", 0),
                "retweets": tweet.get("retweets", 0),
                "replies": tweet.get("replies", 0),
                "views": tweet.get("views", 0),
            }
        except Exception:
            pass

    # Fallback to publish.twitter.com oEmbed
    oembed_url = f"https://publish.twitter.com/oembed?url={urllib.parse.quote_plus(url)}"
    raw, _ = fetch_url(oembed_url)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    html_snippet = data.get("html", "")
    text = re.sub(r"<[^>]+>", " ", html_snippet)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "url": url,
        "type": "x_post",
        "author": data.get("author_name", ""),
        "text": text,
    }


def scrape_single_url(url, max_chars=8000):
    """Scrape a general webpage, blog post, Reddit thread, or X post."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if "reddit.com" in host and "/comments/" in url:
            return scrape_reddit_thread(url)
        if any(d in host for d in ("twitter.com", "x.com")) and "/status/" in url:
            return scrape_x_post(url)

        raw, content_type = fetch_url(url)
        decoded = raw.decode("utf-8", errors="replace")

        if "json" in content_type.lower():
            return {
                "url": url,
                "type": "json",
                "content": decoded[:max_chars],
            }

        parser = HTMLToMarkdownParser()
        parser.feed(decoded)
        unique_links = list(dict.fromkeys(parser.links))[:25]
        return {
            "url": url,
            "type": "webpage",
            "title": parser.title.strip(),
            "description": parser.meta_description,
            "content": parser.get_extracted_text(max_chars=max_chars),
            "outbound_links": unique_links,
        }
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def format_markdown(report):
    """Render the collected scrape report as clean Markdown."""
    lines = ["# Web & Social Intelligence Report\n"]
    if report.get("query"):
        lines.append(f"**Query:** `{report['query']}`  ")
    lines.append(f"**Generated:** {report.get('timestamp', '')}\n")

    for platform, items in report.get("search_results", {}).items():
        lines.append(f"## {platform.upper()} Results ({len(items)})\n")
        for item in items:
            if "error" in item:
                lines.append(f"- ⚠️ Error querying {platform}: `{item['error']}`")
                continue
            title = item.get("title") or item.get("snippet", "")[:80]
            url = item.get("url", "")
            meta_parts = []
            if item.get("subreddit"):
                meta_parts.append(item["subreddit"])
            if item.get("source"):
                meta_parts.append(item["source"])
            if item.get("author"):
                meta_parts.append(f"by {item['author']}")
            if item.get("score") is not None:
                meta_parts.append(f"score: {item['score']}")
            if item.get("num_comments") is not None:
                meta_parts.append(f"comments: {item['num_comments']}")
            if item.get("date"):
                meta_parts.append(str(item["date"]))
            meta_str = " | ".join(meta_parts)

            lines.append(f"### [{title}]({url})")
            if meta_str:
                lines.append(f"*{meta_str}*")
            if item.get("snippet"):
                lines.append(f"> {item['snippet']}\n")
            else:
                lines.append("")

    if report.get("scraped_urls"):
        lines.append("## Direct URL Extractions\n")
        for page in report["scraped_urls"]:
            if "error" in page:
                lines.append(f"### ❌ {page['url']}\n- Error: `{page['error']}`\n")
                continue
            title = page.get("title") or page.get("type", "URL")
            lines.append(f"### [{title}]({page['url']})")
            if page.get("description"):
                lines.append(f"*{page['description']}*\n")
            if page.get("type") == "reddit_thread":
                lines.append(
                    f"**{page.get('subreddit')}** | Posted by u/{page.get('author')} | Score: {page.get('score')}\n"
                )
                if page.get("selftext"):
                    lines.append(f"{page['selftext']}\n")
                if page.get("top_comments"):
                    lines.append("#### Top Comments")
                    for c in page["top_comments"]:
                        lines.append(f"- **u/{c['author']}** ({c['score']} pts): {c['body']}")
                    lines.append("")
            elif page.get("type") == "x_post":
                lines.append(
                    f"**{page.get('author_name', '')} ({page.get('author', '')})** — {page.get('date', '')}"
                )
                lines.append(f"> {page.get('text', '')}\n")
            else:
                lines.append(f"{page.get('content', '')}\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Scrape web and social platforms for a topic or URLs.")
    parser.add_argument("--query", "-q", type=str, help="Topic or search query to scrape across platforms.")
    parser.add_argument(
        "--platforms",
        "-p",
        nargs="+",
        default=["reddit", "hackernews", "bluesky", "mastodon", "news"],
        choices=["reddit", "hackernews", "bluesky", "mastodon", "news"],
        help="Platforms to search when --query is provided.",
    )
    parser.add_argument("--urls", "-u", nargs="+", help="Specific URLs (articles, blogs, Reddit, X) to scrape.")
    parser.add_argument("--limit", "-l", type=int, default=8, help="Max results per platform (default: 8).")
    parser.add_argument(
        "--max-chars", type=int, default=8000, help="Max characters extracted per webpage (default: 8000)."
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (markdown or json).",
    )
    parser.add_argument("--out", "-o", type=str, help="Optional file path to save output.")
    args = parser.parse_args()

    if not args.query and not args.urls:
        parser.error("Provide at least --query or --urls.")

    report = {
        "query": args.query,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "search_results": {},
        "scraped_urls": [],
    }

    if args.query:
        dispatch = {
            "reddit": search_reddit,
            "hackernews": search_hackernews,
            "bluesky": search_bluesky,
            "mastodon": search_mastodon,
            "news": search_news_rss,
        }
        with ThreadPoolExecutor(max_workers=5) as pool:
            future_map = {
                pool.submit(dispatch[p], args.query, args.limit): p
                for p in args.platforms
                if p in dispatch
            }
            for future in as_completed(future_map):
                platform = future_map[future]
                report["search_results"][platform] = future.result()

    if args.urls:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(scrape_single_url, u, args.max_chars) for u in args.urls]
            for f in futures:
                report["scraped_urls"].append(f.result())

    output_text = (
        json.dumps(report, indent=2, ensure_ascii=False)
        if args.format == "json"
        else format_markdown(report)
    )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output_text)
        print(f"Saved report to {args.out}", file=sys.stderr)

    print(output_text)


if __name__ == "__main__":
    main()
