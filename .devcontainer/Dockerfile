FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

# CIと同じuvを使い、開発用の依存関係だけを管理する。
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/
