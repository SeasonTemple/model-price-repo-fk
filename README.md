# model-price-repo (fork)

> Fork of [Wei-Shaw/model-price-repo](https://github.com/Wei-Shaw/model-price-repo) with **Chinese domestic model pricing support**.

Filtered model pricing data for CRS and sub2api projects. Syncs from the upstream [litellm](https://github.com/BerriAI/litellm) pricing file on a schedule, applying configurable prefix rules to keep only the models you actually use.

**What's different from upstream:**

- Replaced `prefix_filters` with `prefix_rules` (keep/strip/both actions) — based on [upstream PR #2](https://github.com/Wei-Shaw/model-price-repo/pull/2)
- Added Chinese domestic model providers: Qwen (dashscope), Moonshot/Kimi, Zhipu/GLM (zai), MiniMax, Doubao (volcengine)
- `strip` action removes provider prefix so bare model names (e.g. `qwen-max`, `glm-5`) match directly without code changes in sub2api

## Supported Models

| Provider | Prefix Rule | Example Models |
|----------|------------|----------------|
| Anthropic | `claude-` keep | claude-opus-4-7, claude-sonnet-4-5 |
| OpenAI | `gpt-`, `o1-`, `o3-`, `o4-` keep | gpt-5.5, o3, o4-mini |
| Google | `gemini-` keep | gemini-2.5-pro, gemini-3.1-pro |
| DeepSeek | `deepseek-` keep | deepseek-chat, deepseek-reasoner |
| Qwen/Alibaba | `dashscope/` strip | qwen-max, qwen-plus, qwen3-coder-flash |
| Moonshot/Kimi | `moonshot/` strip | kimi-k2.5, moonshot-v1-128k |
| Zhipu/GLM | `zai/` strip | glm-5, glm-4.7, glm-4.5-air |
| MiniMax | `minimax/` both | MiniMax-M2.5, minimax-m2.5 |
| Doubao/ByteDance | `volcengine/` strip | doubao-seed-2-0-pro |

## How it works

A GitHub Actions workflow runs every 10 minutes (and on manual trigger):

1. Downloads the full `model_prices_and_context_window.json` from litellm
2. Filters models by the prefix rules in `config.json`
3. Applies `keep`/`strip`/`both` actions to produce clean model keys
4. Applies alias mappings and custom model definitions
5. Writes the output JSON + SHA-256 hash, commits only if content changed

## Configuration

All settings live in [`config.json`](config.json):

| Field | Description |
|---|---|
| `upstream_url` | URL to the upstream litellm pricing JSON |
| `output_file` | Output filename (default: `model_prices_and_context_window.json`) |
| `hash_file` | SHA-256 hash filename for change detection |
| `sync_mode` | `"additive"` (only add new) or `"full"` (replace each run) |
| `update_existing` | Whether to update pricing data for models already in the output |
| `prefix_rules` | Dict of prefix → action (`keep`/`strip`/`both`), replaces `prefix_filters` |
| `prefix_filters` | *(Legacy)* List of prefixes — model key must start with one to be included |
| `exclude_patterns` | Substring patterns to exclude (applied before prefix matching) |
| `aliases` | Map alias model keys to existing source models (deep copy pricing) |
| `custom_models` | Manually defined pricing objects, always injected |

### prefix_rules actions

| Action | Behavior | Example |
|--------|----------|---------|
| `keep` | Retain original key as-is | `claude-opus-4-5` → `claude-opus-4-5` |
| `strip` | Remove the matched prefix from the key | `dashscope/qwen-max` → `qwen-max` |
| `both` | Keep both original and stripped key | `minimax/MiniMax-M2.5` → both `minimax/MiniMax-M2.5` and `MiniMax-M2.5` |

### Adding new model prefixes

Edit the `prefix_rules` dict in `config.json`:

```json
{
  "prefix_rules": {
    "claude-": "keep",
    "dashscope/": "strip",
    "your-new-prefix/": "both"
  }
}
```

### Adding aliases

Aliases create copies of an existing model's pricing under a new key:

```json
{
  "aliases": {
    "claude-opus-4-6-thinking": {
      "source": "claude-opus-4-6",
      "description": "Thinking variant, same pricing"
    }
  }
}
```

If the source model doesn't exist in the filtered data, the alias is skipped with a warning.

## Usage with sub2api

**Option A: Use the [sub2api fork](https://github.com/SeasonTemple/sub2api-fk) (recommended)**

The fork has `pricing.remote_url` pre-configured to point here, with an updated fallback JSON. Deploy it directly — no extra configuration needed.

**Option B: Use upstream sub2api with environment variables**

No fork needed. Just set two environment variables when deploying:

```bash
export PRICING_REMOTE_URL=https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.json
export PRICING_HASH_URL=https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.sha256
```

Or in Docker Compose:

```yaml
environment:
  PRICING_REMOTE_URL: https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.json
  PRICING_HASH_URL: https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.sha256
```

> **Note:** Option B relies on remote fetch succeeding. If the fetch fails, the built-in fallback JSON (from upstream sub2api) has no Chinese domestic model pricing, and those models will bill as $0.

## Running locally

```bash
python3 scripts/sync_prices.py --config config.json --repo-root .
```

No pip dependencies — uses Python standard library only.

## CRS integration

Point CRS to the raw output file from this repo:

```
MODEL_PRICES_URL=https://raw.githubusercontent.com/SeasonTemple/model-price-repo-fk/main/model_prices_and_context_window.json
```

The output JSON structure is identical to what litellm produces (model key -> pricing object), so CRS `pricingService.js` works without changes.

## License

[MIT](LICENSE)
