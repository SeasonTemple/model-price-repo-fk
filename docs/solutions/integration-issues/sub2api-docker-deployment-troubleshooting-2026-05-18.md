---
title: "sub2api Docker 部署排障实录：数据库重建、Viper 配置、Bind Mount 与模型映射"
date: 2026-05-18
category: integration-issues
module: sub2api/deployment
problem_type: integration_issue
component: tooling
severity: critical
symptoms:
  - PostgreSQL 数据库被重新初始化，所有用户数据丢失
  - docker-compose.yml 中 PRICING_REMOTE_URL 环境变量不生效
  - Docker bind mount 将 config.yaml 创建为目录而非文件
  - Codex CLI 使用 gpt-5.5 模型时被 OpenAI 拒绝 (502 Bad Gateway)
  - glm-5.1 模型定价数据缺失
root_cause: config_error
resolution_type: config_change
related_components:
  - database
  - service_object
  - authentication
tags:
  - docker
  - sub2api
  - viper
  - postgresql
  - bind-mount
  - codex
  - model-pricing
  - glm-5.1
---

# sub2api Docker 部署排障实录

## Problem

在 sub2api Docker Compose 部署中，添加 PRICING_REMOTE_URL/PRICING_HASH_URL 环境变量后执行 `docker compose up -d`，引发连锁问题：PostgreSQL 数据库被重建导致数据全量丢失；Viper 配置库的环境变量对嵌套 key 无效；Docker bind mount 在宿主机文件不存在时自动创建目录；Docker 镜像版本过旧导致 Codex CLI 模型映射错误。

## Symptoms

- **数据库清空**: `docker compose up -d` 后 PostgreSQL 18-alpine 执行了完整 initdb，用户表、订阅数据全部丢失
- **环境变量无效**: docker-compose.yml 中 `PRICING_REMOTE_URL` 和 `PRICING_HASH_URL` 被忽略，sub2api 使用内置 fallback 定价（无国产模型定价）
- **bind mount 异常**: `./config.yaml:/app/data/config.yaml` 声明后，宿主机上 `config.yaml` 变成了目录，`docker cp` 只是把文件拷进目录而非替换
- **502 Bad Gateway**: Codex CLI 用 `gpt-5.5` 模型时，sub2api 日志显示 `Codex model normalization: gpt-5.5 -> gpt-5.1`，OpenAI 返回 `"The 'gpt-5.1' model is not supported when using Codex with a ChatGPT account."`
- **定价数据缺失**: glm-5.1 在 LiteLLM 上游 PR #26673 仍未合并，fork 仓库缺少该模型定价

## What Didn't Work

1. **docker-compose.yml 环境变量覆盖 Viper 嵌套配置** — Viper 的 `AutomaticEnv()` + `Unmarshal(&cfg)` 不支持嵌套 key 的环境变量绑定。`Unmarshal` 仅从 config 文件和 defaults 读取，`pricing.remote_url` 这类嵌套 key 永远不会被环境变量填充。这是 Viper 的已知设计限制，不是 bug。

2. **`docker exec` 追加配置到容器内 config.yaml** — 临时生效，但容器重建后丢失。本质上是把持久化配置放在了 ephemeral 容器层。

3. **Codex CLI 调整模型** — 治标不治本，根本原因是 Docker 镜像 (2026-01-30 构建) 的 `codexModelMap` 没有 `gpt-5.5` 条目。

4. **直接 `docker cp` 覆盖 config.yaml** — 因为宿主机上 `config.yaml` 已被 Docker 创建为目录，`docker cp` 只是把文件拷进该目录而非替换。

## Solution

### Fix 1: AUTO_SETUP 恢复管理员

数据库重建后，删除 lock 文件启用自动设置：

```bash
sudo docker exec sub2api rm /app/data/.installed /app/data/config.yaml
```

在 docker-compose.yml 中确保：

```yaml
environment:
  - AUTO_SETUP=true
  - ADMIN_EMAIL=admin@example.com
  - ADMIN_PASSWORD=<your-password>
```

### Fix 2: Bind mount config.yaml（正确的持久化方式）

```bash
# 1. 先从容器导出配置（确保是文件而非目录）
sudo rm -rf ./config.yaml  # 清理可能的目录
sudo docker cp sub2api:/app/data/config.yaml ./config.yaml
sudo chmod 644 ./config.yaml

# 2. 确认 pricing 段在配置中
grep -A 7 "^pricing:" ./config.yaml
```

docker-compose.yml：

```yaml
services:
  sub2api:
    volumes:
      - sub2api_data:/app/data
      - ./config.yaml:/app/data/config.yaml:ro  # bind mount
```

config.yaml 中的 pricing 段：

```yaml
pricing:
    remote_url: https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.json
    hash_url: https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.sha256
    data_dir: ./data
    update_interval_hours: 24
    hash_check_interval_minutes: 10
```

### Fix 3: 手动添加 glm-5.1 定价到 fork 仓库

在 `model_prices_and_context_window.json` 中 `glm-5` 和 `glm-5-code` 之间添加：

```json
"glm-5.1": {
    "cache_creation_input_token_cost": 0,
    "cache_read_input_token_cost": 5.25e-7,
    "input_cost_per_token": 1.05e-6,
    "output_cost_per_token": 3.5e-6,
    "litellm_provider": "zai",
    "max_input_tokens": 202752,
    "max_output_tokens": 131072,
    "mode": "chat",
    "supports_function_calling": true,
    "supports_prompt_caching": true,
    "supports_reasoning": true,
    "supports_tool_choice": true,
    "source": "https://docs.z.ai/guides/overview/pricing"
}
```

更新 SHA256 哈希文件并推送。

### Fix 4: 拉取最新 Docker 镜像

```bash
sudo docker pull weishaw/sub2api:latest
cd ~/netops/sub2api/deploy
sudo docker compose up -d sub2api
```

## Why This Works

- **Viper 限制**: Go Viper 库的 `Unmarshal(&cfg)` 使用 mapstructure 解码器，仅从 config 文件值和 defaults 填充 struct。`AutomaticEnv()` 使环境变量可通过 `viper.Get("key")` 访问，但 mapstructure 不读此路径。解决方案是直接写 config.yaml 并 bind mount。

- **Docker bind mount 语义**: 当 bind mount 的宿主机路径不存在时，Docker 默认创建为目录。这是 Docker 的文档行为。必须先创建文件再 `docker compose up`。

- **PostgreSQL 数据持久化**: 命名卷 (named volume) 在容器生命周期变更时持久化，除非显式 `docker compose down -v`。`AUTO_SETUP=true` 作为安全网，不是替代方案。

- **Codex 模型归一化**: sub2api 源码 `openai_codex_transform.go` 的 `codexModelMap` 维护模型名映射。旧镜像缺少 `gpt-5.5` 条目导致 fallback 到 `gpt-5.1`。新版镜像已修正。

## Prevention

1. **生产环境禁止 `docker compose down -v`** — `down` 停止容器但保留卷；`-v` 删除命名卷导致数据库重建
2. **bind mount 前确保宿主机文件存在** — 始终先 `touch` 或 `docker cp` 创建文件，再声明在 docker-compose.yml 中
3. **不要依赖 Viper 环境变量覆盖嵌套配置** — 对 sub2api 的 `pricing.*` 配置，使用 config.yaml + bind mount
4. **定期拉取 Docker 镜像** — `weishaw/sub2api:latest` 是浮动 tag，至少每月 `docker pull` 一次以获取模型映射修复
5. **监控上游 PR 状态** — glm-5.1 定价等关键模型，跟踪 LiteLLM 上游 PR。合并后 fork 的自动同步流水线会自动获取

## Related Issues

- LiteLLM PR #26673: glm-5.1 定价（未合并）
- sub2api 源码: `openai_codex_transform.go` codexModelMap 映射表
- sub2api 源码: `config.go` Viper 配置加载逻辑
