# cedar-diff-fleet spec image — Lean 4.29.1 + batteries for cedar-spec work.
#
# Purpose: build + run cedar-spec's cedar-lean (type system, eval, symcc, proofs,
# DiffTest FFI). Pinned to the toolchain cedar-spec's lake-manifest declares.
#
# Build:   docker build -f containers/spec.Containerfile -t cedar-spec:dev .
# Publish: docker tag cedar-spec:dev ghcr.io/athanor-ai/cedar-spec:2026.04.23 && docker push ...
# Use:     docker run --rm -v $PWD:/work -w /work/cedar-spec/cedar-lean cedar-spec:dev lake build Cedar
#
# Sized to reuse lean-base layer semantics (amazonlinux:2023 + elan + uv),
# but pinned to 4.29.1 instead of 4.14.0 since cedar-spec requires 4.29.1.

FROM docker.io/library/amazonlinux:2023

RUN dnf update -y && dnf install -y \
  git curl-minimal tar gzip gcc gcc-c++ make findutils which \
  python3.12 python3.12-pip \
  && dnf clean all && rm -rf /tmp/* /var/tmp/*

# Lean 4.29.1 via elan
ENV ELAN_HOME=/root/.elan
ENV PATH="${ELAN_HOME}/bin:${PATH}"
RUN curl -fsSL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
  | sh -s -- --default-toolchain leanprover/lean4:v4.29.1 -y --no-modify-path

# Smoke-check the toolchain
RUN lean --version && lake --version

WORKDIR /work

# Default command = interactive shell; callers override with lake build etc.
CMD ["/bin/bash"]
