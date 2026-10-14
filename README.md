# Defence Tracker

A **defense-news aggregation dashboard**. It scrapes and collects defense &
security news from multiple web sources, optionally pulls posts from Twitter/X,
de-duplicates and stores everything in a local database, and presents it in a
searchable Streamlit dashboard — with a background scheduler that keeps the
feed fresh automatically.

## Features
- Web scraping of defense-news sites (`requests` + BeautifulSoup/lxml)
- Optional Twitter/X integration (`tweepy`)
- De-duplication + persistence in SQLite (`defense_news.db`)
- Background scheduler service for periodic refresh (`scheduler_service.py`)
- Interactive Streamlit UI (filter, search, browse)

## Stack
Python · Streamlit · pandas · BeautifulSoup · SQLite

## Getting started
```bash
pip install -r requirements.txt
streamlit run app_latest1.py
```

## Notes
- Configure any API keys (Twitter/X, news sources) before first run.
- Intended for open-source news aggregation from public sources.
