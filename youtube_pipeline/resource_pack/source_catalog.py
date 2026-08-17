from __future__ import annotations


KISHIMI_SOURCE_CATALOG = [
    {
        "title": "岸見一郎公式ホームページ",
        "url": "https://kishimi.com/",
        "supports": "岸見一郎の公式プロフィール、著作・講演情報",
    },
    {
        "title": "嫌われる勇気｜ダイヤモンド社",
        "url": "https://www.diamond.co.jp/book/9784478025819.html",
        "supports": "岸見一郎・古賀史健の共著情報と課題の分離を含む目次",
        "publication_year": 2013,
        "authors": ["岸見一郎", "古賀史健"],
        "publisher": "ダイヤモンド社",
        "citation_hint": "岸見一郎・古賀史健（2013）『嫌われる勇気』ダイヤモンド社",
    },
    {
        "title": "岸見一郎｜Wikipedia日本語版",
        "url": "https://ja.wikipedia.org/wiki/岸見一郎",
        "supports": "経歴の補助確認。主張の一次根拠には使わない",
    },
    {
        "title": "嫌われる勇気｜Wikipedia日本語版",
        "url": "https://ja.wikipedia.org/wiki/嫌われる勇気",
        "supports": "書籍の基本情報の補助確認。主張の一次根拠には使わない",
        "publication_year": 2013,
        "citation_hint": "『嫌われる勇気』（2013年）",
    },
]

KNOWN_SOURCE_URLS = {row["url"] for row in KISHIMI_SOURCE_CATALOG}
