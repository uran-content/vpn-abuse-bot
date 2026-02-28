# vpn-abuse-bot

Telegram bot + HTTPS API server:
- POST /api/webhook  (events from remnanode-watchdog)
- GET  /api/patterns (patterns for remnanode-watchdog)

## Env
Copy `.env.example` -> `.env` and fill:
- BOT_TOKEN
- ADMIN_TELEGRAM_ID
- WEBHOOK_TOKEN_IN / PATTERNS_TOKEN_IN
- SSL_CERT_FILE / SSL_KEY_FILE (mount certs into container)

## Endpoints
- https://<host>:<port>/api/webhook
  Authorization: Bearer <WEBHOOK_TOKEN_IN>

- https://<host>:<port>/api/patterns
  Authorization: Bearer <PATTERNS_TOKEN_IN>

## Docker compose example
```yaml
services:
  vpn_abuse_bot:
    build:
      context: https://github.com/uran-content/vpn-abuse-bot.git#main
    container_name: vpn_abuse_bot
    restart: always
    env_file: .env
    ports:
      - "8443:8443"
    volumes:
      - ./certs:/certs:ro
      - ./data:/data:ro