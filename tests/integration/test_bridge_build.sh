#!/usr/bin/env bash
# Integration test. end-to-end: pull the monolith image (or use a
# locally built cedar-spec:dev / kairos-cedar:dev tag), mount the
# repo, run `lake build` against cedar-spec-bridge. Exits 0 on green.
#
# Usage:
#   ./tests/integration/test_bridge_build.sh                  # monolith
#   IMAGE=ghcr.io/athanor-ai/kairos-cedar:2026.04.23 ./...    # specific tag
#
# Run via CI on a self-hosted runner (free-tier 7 GB RAM chokes on
# cedar-spec's SymCC proofs). Locally: 5-10 min from cold, seconds
# with the lake cache warm.
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/athanor-ai/kairos-cedar:latest}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Sanity: docker is available.
if ! command -v docker >/dev/null; then
  echo "skip: docker not installed" >&2
  exit 77  # automake skip convention
fi

# Sanity: submodules populated.
for sub in cedar-spec palamedes-lean; do
  if [ ! -d "$REPO_ROOT/$sub" ] || [ -z "$(ls -A "$REPO_ROOT/$sub")" ]; then
    echo "skip: submodule $sub not initialized; run git submodule update --init --recursive" >&2
    exit 77
  fi
done

# Pull (or use local) the image. If pull fails, fall back to local tag.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker pull "$IMAGE" || {
    echo "warn: pull failed; trying local kairos-cedar:dev" >&2
    IMAGE="kairos-cedar:dev"
    docker image inspect "$IMAGE" >/dev/null 2>&1 || {
      echo "fail: no image available" >&2
      exit 1
    }
  }
fi

echo "integration: using image $IMAGE"

# Actually build the bridge. This exercises:
# - docker image has lean 4.29.1 on PATH
# - cedar-spec submodule checkout produces a buildable Lake project
# - cedar-spec-bridge's lakefile.toml resolves the `path = ../cedar-spec/cedar-lean` requirement
# - isWellTyped predicate compiles against Cedar.Validation.typeOf
docker run --rm \
  -v "$REPO_ROOT":/work \
  -w /work/cedar-spec-bridge \
  "$IMAGE" \
  bash -c 'lake update && lake build' \
  > /tmp/bridge-build.log 2>&1 || {
    tail -30 /tmp/bridge-build.log
    exit 1
  }

# Assert the expected number of jobs completed. 92 as of 2026-04-23;
# this might drift as cedar-spec batteries update, so we just check
# the "Build completed successfully" line.
if ! grep -q "Build completed successfully" /tmp/bridge-build.log; then
  echo "fail: lake build did not complete successfully" >&2
  tail -30 /tmp/bridge-build.log
  exit 1
fi

echo "integration: bridge build PASS"
