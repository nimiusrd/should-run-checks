# 26.12.1は侵害されたeMudhra中間CAを信頼しないセキュリティリリース。
FROM node:26.12.1-bookworm

USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*
USER node
