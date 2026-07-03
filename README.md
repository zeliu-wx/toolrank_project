# LAKES

LAKES recommends and optionally runs smart-contract vulnerability analyzers for Solidity contracts.

## Install

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install .
```

Configure your OpenAI-compatible chat endpoint:

```bash
export LAKES_OPENAI_BASE_URL="https://your-llm-endpoint/v1"
export LAKES_OPENAI_MODEL="your-model"
export OPENAI_API_KEY="your-api-key"
```

## Run

```bash
lakes recommend path/to/Contract.sol --emit summary
```

Run selected analyzers too:

```bash
lakes recommend path/to/Contract.sol --execute --emit summary
```

Outputs are written under `LAKES_out/`.

## Docker

Docker includes the analyzer runtime and compiler setup.

```bash
docker build -t lakes .
docker run --rm --privileged \
  -v "$PWD/out:/work/out" \
  -v "$PWD/path/to/Contract.sol:/work/Contract.sol:ro" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e LAKES_OPENAI_BASE_URL="$LAKES_OPENAI_BASE_URL" \
  -e LAKES_OPENAI_MODEL="$LAKES_OPENAI_MODEL" \
  lakes recommend /work/Contract.sol --execute --emit summary --results-root /work/out
```
