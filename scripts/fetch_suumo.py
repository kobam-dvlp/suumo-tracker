import urllib.request
import re
import json
import os
import sys
import time
from datetime import datetime, timezone

SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
SEEN_IDS_PATH = "data/seen_ids.json"
MAX_PAGES = 20

# 千葉県全体を検索して後でフィルタリング
SUUMO_URL = (
    "https://suumo.jp/jj/chintai/ichiran/FR301FC001/"
    "?ar=030&bs=040&ta=12&ekname=%E6%9D%B1%E8%88%B9%E6%A9%8B"
    "&cb=0.0&ct=12.0&mb=0&mt=9999999"
    "&shkr1=03&shkr2=03&shkr3=03&shkr4=03&sngaiyn=0"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TARGET_STATION = "東船橋駅"
MAX_WALK_MIN = 10


def slack_notify(text):
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Slack error: {e}", file=sys.stderr)


def is_near_target(block_html):
    """東船橋駅 徒歩10分以内かチェック"""
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

        # 建物単位で分割してフィルタリング
        blocks = re.split(r'(?=<div[^>]*class="cassetteitem")', html)
        page_matched = 0
        for block in blocks:
            if is_near_target(block):
                ids = list(set(re.findall(r'jnc_[a-zA-Z0-9]+', block)))
                matched_ids.extend(ids)
                page_matched += len(ids)

        total_ids = len(re.findall(r'jnc_[a-zA-Z0-9]+', html))
        print(f"Page {page}: 全{total_ids}件中 東船橋10分以内={page_matched}件")

        has_next = bool(re.search(rf'page={page + 1}[^0-9]', html))
        if not has_next:
            break
        time.sleep(2)

    return list(set(matched_ids))


def load_seen_ids():
    if not os.path.exists(SEEN_IDS_PATH):
        return []
    with open(SEEN_IDS_PATH) as f:
        return json.load(f).get("ids", [])


def save_seen_ids(ids):
    os.makedirs("data", exist_ok=True)
    with open(SEEN_IDS_PATH, "w") as f:
        json.dump(
            {"ids": ids, "last_updated": datetime.now(timezone.utc).isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )


def main():
    print("SUUMOから東船橋駅10分以内の物件を取得中...")
    current_ids = fetch_suumo()
    print(f"条件一致: {len(current_ids)}件")

    if not current_ids:
        slack_notify("⚠ 東船橋駅周辺: 条件に合う物件が見つかりませんでした（築10年以内・1LDK以上・12万以下・徒歩10分以内）")
        save_seen_ids([])
        return

    seen_ids = load_seen_ids()
    seen_set = set(seen_ids)
    new_ids = [i for i in current_ids if i not in seen_set]
    print(f"新着: {len(new_ids)}件")

    if new_ids:
        lines = [f"🏠 *新着物件 {len(new_ids)}件*（東船橋駅 徒歩10分以内）\n"]
        for i, lid in enumerate(new_ids, 1):
            lines.append(f"{i}. https://suumo.jp/chintai/{lid}/")
        slack_notify("\n".join(lines))
        print("Slack通知完了")

    save_seen_ids(current_ids)
    print("seen_ids.json 更新完了")


if __name__ == "__main__":
    main()