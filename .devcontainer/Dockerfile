# 24.22.1は侵害されたeMudhra中間CAを信頼しないセキュリティリリース。
FROM node:24.22.1-bookworm

USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*
USER node
