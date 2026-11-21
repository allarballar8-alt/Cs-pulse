"""Collects the latest CS-student alerts and writes data.json.
- Free news feeds (Google News RSS) are always used.
- If the ANTHROPIC_API_KEY secret is set, Claude cleans up titles and summaries.
- Your own hand-written alerts in manual.json are always kept."""
import json, os, re, sys, zlib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERIES = {
    "Jobs": ["computer science recruitment notification India", "IT technical assistant recruitment apply online", "software developer government recruitment India"],
    "Exams": ["GATE exam date", "UGC NET exam date", "CSIR NET exam date", "CUET PG exam date"],
    "Admit Cards": ["admit card released NTA", "GATE admit card", "UGC NET admit card"],
    "Results": ["result declared NTA", "UGC NET result", "GATE result"],
}
CS_WORDS = re.compile(r"computer|\bit\b|software|technical|programmer|developer|data|cyber|engineer|nielit|isro|drdo|gate|net\b|nta|cuet", re.I)
PER_CATEGORY, MAX_AGE_DAYS = 6, 21

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (CS-Pulse updater)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def fetch_news():
    out, seen = [], set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    for cat, qs in QUERIES.items():
        found = []
        for q in qs:
            url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:14d") + "&hl=en-IN&gl=IN&ceid=IN:en"
            try:
                root = ET.fromstring(get(url))
            except Exception as e:
                print("feed failed:", q, e, file=sys.stderr); continue
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                src = (it.findtext("source") or "").strip()
                try:
                    when = parsedate_to_datetime(it.findtext("pubDate"))
                except Exception:
                    continue
                if when.tzinfo is None: when = when.replace(tzinfo=timezone.utc)
                if when < cutoff or not title or not link: continue
                if src and title.endswith(" - " + src): title = title[: -len(src) - 3]
                key = re.sub(r"\W+", "", title.lower())[:60]
                if key in seen: continue
                if cat == "Jobs" and not CS_WORDS.search(title): continue
                seen.add(key)
                found.append({"id": 100000 + zlib.crc32(link.encode()) % 900000000, "t": title[:90], "c": cat,
                              "d": when.astimezone().strftime("%Y-%m-%d"), "s": src or "News",
                              "x": "Reported by %s. Open the link for the full notice." % (src or "the source"),
                              "l": link, "n": 1, "_w": when.timestamp()})
        found.sort(key=lambda i: -i["_w"])
        out += found[:PER_CATEGORY]
    for i in out: i.pop("_w", None)
    return out

def ai_clean(items):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not items: return items
    prompt = ("You help Indian computer science students. For each news headline below return a JSON array of objects "
              '{"id":number,"keep":true/false,"c":"Jobs|Exams|Admit Cards|Results","t":"clean title under 70 chars","x":"one factual sentence under 140 chars"}. '
              "Use ONLY information in the headline. Never invent dates, numbers or deadlines. keep=false if it is not useful for CS students. "
              "Return only the JSON array.\n\n" + json.dumps([{"id": i["id"], "headline": i["t"], "source": i["s"], "category": i["c"]} for i in items]))
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            text = json.loads(r.read())["content"][0]["text"]
        arr = json.loads(text[text.index("["): text.rindex("]") + 1])
        by = {a["id"]: a for a in arr if isinstance(a, dict) and "id" in a}
    except Exception as e:
        print("AI step skipped:", e, file=sys.stderr); return items
    res = []
    for i in items:
        a = by.get(i["id"])
        if a is None: res.append(i); continue
        if a.get("keep") is False: continue
        if a.get("c") in QUERIES: i["c"] = a["c"]
        if a.get("t"): i["t"] = str(a["t"])[:90]
        if a.get("x"): i["x"] = str(a["x"])[:200]
        res.append(i)
    return res

def main():
    manual = json.load(open(os.path.join(ROOT, "manual.json"), encoding="utf-8")).get("items", [])
    today = datetime.now().date()
    manual = [m for m in manual if (today - datetime.strptime(m["d"], "%Y-%m-%d").date()).days <= 14]
    news = ai_clean(fetch_news())
    taken = {m["id"] for m in manual}
    items = manual + [n for n in news if n["id"] not in taken]
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items}
    json.dump(out, open(os.path.join(ROOT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", len(items), "items (%d from news)" % len(news))

if __name__ == "__main__":
    main()
