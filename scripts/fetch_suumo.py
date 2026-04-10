import urllib.request
import urllib.parse
import re
import json
import os
import sys
import base64
import time
from datetime import datetime, timezone

SLACK_WEBHOOK   = os.environ["SLACK_WEBHOOK_URL"]
GITHUB_TOKEN    = os.environ["GITHUB_TOKEN"]
GITHUB_REPO     = "kobam-dvlp/suumo-tracker"
SEEN_IDS_PATH   = "data/seen_ids.json"
MAX_PAGES       = 20
TARGET_STATION  = "東船橋駅"
MAX_WALK_MIN    = 10

SUUMO_URL = (
    "https://suumo.jp/jj/chintai/ichiran/FR301FC001/"
    "?ar=030&bs=040&ta=12&ekname=%E6%9D%B1%E8%88%B9%E6%A9%8B"
    "&cb=0.0&ct=12.0&mb=0&mt=9999999"
    "&shkr1=03&shkr2=03&shkr3=03&shkr4=03&sngaiyn=0"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9",
}


def slack_notify(text):
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(SLACK_WEBHOOK, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Slack error: {e}", file=sys.stderr)


def github_get_file():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SEEN_IDS_PATH}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            d = json.load(res)
        content = json.loads(base64.b64decode(d["content"]).decode())
        return content.get("ids", []), d["sha"]
    except Exception:
        return [], None


def github_put_file(ids, sha):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SEEN_IDS_PATH}"
    body = json.dumps({"ids": ids, "last_updated": datetime.now(timezone.utc).isoformat()},
                      ensure_ascii=False)
    content = base64.b64encode(body.encode()).decode()
    payload = {"message": "chore: update seen listings [skip ci]", "content": content}
    if sha:
        payload["sha"] = sha
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Authorization": f"token {GITHUB_TOKEN}",
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        print("seen_ids.json 更新完了")
    except Exception as e:
        print(f"GitHub API error: {e}", file=sys.stderr)


def is_near_target(block_html):
    texts = re.findall(r'cassetteitem_detail-text[^>]*>([^<]+)', block_html)
    for text in texts:
        m = re.search(r'東船橋駅\s*歩(\d+)分', text)
        if m and int(m.group(1)) <= MAX_WALK_MIN:
            return True
    return False


def fetch_suumo():
    matched_ids = []
    for page in range(1, MAX_PAGES + 1):
        url = SUUMO_URL + f"&page={page}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                html = res.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"Fetch error page {page}: {e}", file=sys.stderr)
            break

        blocks = re.split(r'(?=<div[^>]*class="cassetteitem")', html)
        page_matched = 0
        for block in blocks:
            if is_near_target(block):
                ids = list(set(re.findall(r'jnc_[a-zA-Z0-9]+', block)))
                matched_ids.extend(ids)
                page_matched += len(ids)

        total = len(re.findall(r'jnc_[a-zA-Z0-9]+', html))
        print(f"Page {page}: {total}件中 東船橋10分以内={page_matched}件")

        if not re.search(rf'page={page + 1}[^0-9]', html):
            break
        time.sleep(2)

    return list(set(matched_ids))


def main():
    print("取得開始...")
    current_ids = fetch_suumo()
    print(f"条件一致: {len(current_ids)}件")

    if not current_ids:
        slack_notify("⚠ 東船橋駅周辺: 条件に合う物件なし（築10年以内・1LDK以上・12万以下・徒歩10分以内）")
        github_put_file([], (github_get_file()[1]))
        return

    seen_ids, sha = github_get_file()
    seen_set = set(seen_ids)
    new_ids = [i for i in current_ids if i not in seen_set]
    print(f"新着: {len(new_ids)}件")

    if new_ids:
        lines = [f"🏠 *新着物件 {len(new_ids)}件*（東船橋駅 徒歩10分以内）\n"]
        for i, lid in enumerate(new_ids, 1):
            lines.append(f"{i}. https://suumo.jp/chintai/{lid}/")
        slack_notify("\n".join(lines))
        print("Slack通知完了")

    github_put_file(current_ids, sha)


if __name__ == "__main__":
    main()