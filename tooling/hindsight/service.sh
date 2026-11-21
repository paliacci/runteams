#!/bin/bash
# Optional local memory service for the macOS desktop host.
set -eu
umask 077
tooling_dir=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
runtime_dir="${RUNTEAMS_HINDSIGHT_DIR:-$HOME/Library/Application Support/RunTeams/Hindsight}"
model_dir="$runtime_dir/model"
key_file="${RUNTEAMS_HINDSIGHT_KEY_FILE:-$runtime_dir/service.key}"
case "${1:-}" in
  install)
    mkdir -p "$model_dir/onnx"
    python3.12 -m venv "$runtime_dir/venv"
    python="$runtime_dir/venv/bin/python"
    # The PyPI source distribution contains the SDK without its private CLI.
    # Only replace an existing wheel when upgrading an older installation.
    site_dir=$("$python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
    if [[ -f "$site_dir/claude_agent_sdk/_bundled/claude" ]]; then
      sdk_version=$("$python" -c 'from importlib.metadata import version; print(version("claude-agent-sdk"))')
      "$python" -m pip install --no-compile --no-cache-dir --force-reinstall --no-deps \
        --no-binary=claude-agent-sdk "claude-agent-sdk==$sdk_version"
    fi
    "$python" -m pip install --no-compile --no-cache-dir --no-binary=claude-agent-sdk \
      'hindsight-api-slim[embedded-db,local-onnx]==1.2.3'
    revision=761b726dd34fb83930e26aab4e9ac3899aa1fa78
    while read -r checksum file; do
      if [[ -f "$model_dir/$file" ]] && (cd "$model_dir" && echo "$checksum  $file" | shasum -a 256 -c - >/dev/null 2>&1); then
        continue
      fi
      curl -fSL --retry 3 "https://huggingface.co/Xenova/multilingual-e5-small/resolve/$revision/$file" -o "$model_dir/$file.part"
      (cd "$model_dir" && echo "$checksum  $file.part" | shasum -a 256 -c - >/dev/null)
      mv "$model_dir/$file.part" "$model_dir/$file"
    done <<'MODEL_FILES'
cb99455288675345e1a4f411438d5d0adbba5fbd3a67ea4fb03c015433b996c1 config.json
a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b tokenizer_config.json
d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7 special_tokens_map.json
0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39 tokenizer.json
f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193 onnx/model_quantized.onnx
MODEL_FILES
    "$python" "$tooling_dir/compact.py" "$site_dir" "$model_dir"
    ;;
  serve)
    cd "$runtime_dir"
    echo "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193  model/onnx/model_quantized.onnx" | shasum -a 256 -c - >/dev/null
    if [[ ! -e "$key_file" ]]; then
      (set -C; "$runtime_dir/venv/bin/python" -c 'import secrets; print(secrets.token_hex(32))' > "$key_file")
    fi
    export HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension
    HINDSIGHT_API_TENANT_API_KEY=$(cat "$key_file")
    export HINDSIGHT_API_TENANT_API_KEY
    export HINDSIGHT_API_LLM_PROVIDER=none HINDSIGHT_API_RERANKER_PROVIDER=rrf HINDSIGHT_API_EMBEDDINGS_PROVIDER=onnx
    export HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_PATH="$model_dir/onnx/model_quantized.onnx"
    export HINDSIGHT_API_EMBEDDINGS_ONNX_TOKENIZER_NAME_OR_PATH="$model_dir"
    export HINDSIGHT_API_EMBEDDINGS_ONNX_DIMENSIONS=384 HF_HUB_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=True
    export HINDSIGHT_API_DATABASE_URL=pg0://runteams-asset-memory PG0_HOME="$runtime_dir/pg0"
    export HINDSIGHT_API_MCP_ENABLED=false HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=false
    exec "$runtime_dir/venv/bin/python" -B -m hindsight_api.main --host 127.0.0.1 --port "${RUNTEAMS_HINDSIGHT_PORT:-18918}"
    ;;
  *) echo "Usage: $0 install|serve" >&2; exit 2 ;;
esac
