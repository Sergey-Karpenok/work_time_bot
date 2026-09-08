#!/bin/bush

docker run -d \
  --name worktime-bot \
  --restart unless-stopped \
  -e DEFAULT_TIMEZONE=Europe/Moscow \
  -v /srv/worktime-bot/data:/data \
  worktime-bot
