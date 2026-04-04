# Polymarket Sentiment Bot

AI-powered sentiment trading bot for Polymarket. Uses Claude via OpenRouter to analyze market sentiment from free data sources, then auto-executes trades via py-clob-client.

## Tech Stack
- Python 3.12, FastAPI
- OpenRouter (Claude) for sentiment analysis
- py-clob-client for Polymarket CLOB
- Docker + Zeabur

## Env Vars
- `ANTHROPIC_API_KEY` — For Claude API
- `POLYMARKET_API_KEY`, `POLYMARKET_SECRET`, `POLYMARKET_PASSPHRASE`, `POLYMARKET_PRIVATE_KEY`
- `DATABASE_URL` — Neon Postgres
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## Deployment
```bash
docker build -t sentiment-bot .
docker run -p 8080:8080 --env-file .env sentiment-bot
```
Deployed on Zeabur (project: phantom-pipeline).

