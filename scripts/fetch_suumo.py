import urllib.request
import re
import json
import os
import sys
import time
from datetime import datetime, timezone

SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
SEEN_IDS_PATH = "data/seen_ids.json"

SUUMO_URL = (
    "https://suumo.jp/jj/chintai/ichiran/FR301FC001/"
    "?ar=030&bs=040&ta=12&ekname=%E6%9D%B1%E8%88%B9%E6%A9%8B"
    "&cb=0.0&ct=12.0&mb=0&mt=9999999&et=10&cn=10"
    "&shkr1=03&shkr2=03&shkr3=03&shkr4=03&sngaiyn=0"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def slack_notify(text):
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def fetch_suumo():
    all_ids = []
    page = 1
    while True:
        url = SUUMO_URL + f"&page={page}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                html = res.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"Fetch error on page {page}: {e}", file=sys.stderr)
            break

        ids = list(set(re.findall(r"/chintai/(jnc_[^/\"]+)/", html)))
        if not ids:
            break

        all_ids.extend(ids)
        if f"page={page + 1}" not in html and "次へ" not in html:
            break
        page += 1
        time.sleep(2)

    return list(set(all_ids))


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
    print("SUUMOから物件を取得中...")
    current_ids = fetch_suumo()
    print(f"取得件数: {len(current_ids)}")

    if not current_ids:
        slack_notify("⚠ SUUMO取得失敗: 物件数0件（ブロックされた可能性あり）")
        sys.exit(1)

    seen_ids = load_seen_ids()
    seen_set = set(seen_ids)
    new_ids = [i for i in current_ids if i not in seen_set]

    print(f"新着件数: {len(new_ids)}")

    if new_ids:
        lines = [f"🏠 *新着物件 {len(new_ids)}件*（東船橋駅周辺）\n"]
        for i, lid in enumerate(new_ids, 1):
            lines.append(f"{i}. https://suumo.jp/chintai/{lid}/")
        slack_notify("\n".join(lines))
        print("Slack通知送信完了")

    save_seen_ids(current_ids)
    print("seen_ids.json 更新完了")


if __name__ == "__main__":
    main()
