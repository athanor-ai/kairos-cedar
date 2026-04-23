# cedar-diff-fleet palamedes image — Lean 4.24.0 + Mathlib for generator synthesis.
#
# Purpose: build + run palamedes-lean (Aesop-based generator-search tactic).
# Pinned to the toolchain palamedes-lean's lake-manifest declares (4.24.0).
#
# Note: palamedes-lean pulls Mathlib + Aesop + Plausible on first `lake build`.
# That's a ~15min one-time build. We run it in the image build so customers
# don't hit it at run time. Result: image is large (~3-4GB) but self-contained.
#
# Build:   docker build -f containers/palamedes.Containerfile -t cedar-palamedes:dev .
# Use:     docker run --rm -v $PWD:/work -w /work/palamedes-lean cedar-palamedes:dev lake build
#
# NOTE on toolchain mismatch with spec: cedar-spec is on 4.29.1, this is on
# 4.24.0. They cannot coexist in one Lake project. Current plan is to
# fork palamedes-lean and bump to 4.29.1 + Mathlib-4.29.x inside a separate
# image (bridge.Containerfile, future). This image serves the "run palamedes
# as-is on their STLC bench" smoke path for now.

FROM docker.io/library/amazonlinux:2023

RUN dnf update -y && dnf install -y \
  git curl-minimal tar gzip gcc gcc-c++ make findutils which \
  python3.12 \
  && dnf clean all && rm -rf /tmp/* /var/tmp/*

ENV ELAN_HOME=/root/.elan
ENV PATH="${ELAN_HOME}/bin:${PATH}"
RUN curl -fsSL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
  | sh -s -- --default-toolchain leanprover/lean4:v4.24.0 -y --no-modify-path

RUN lean --version && lake --version

# Prewarm: copy palamedes-lean in and lake-build it at image-build time
# so the Mathlib pull + compile is amortized into the image.
# (Guarded so the image still builds without the clone available; user can
# skip prewarm by building with --build-arg PREWARM=0.)
ARG PREWARM=1
COPY palamedes-lean /opt/palamedes-lean
WORKDIR /opt/palamedes-lean
RUN if [ "$PREWARM" = "1" ]; then \
      lake update && lake build ; \
    else \
      echo "Skipping palamedes prewarm (PREWARM=$PREWARM)"; \
    fi

WORKDIR /work
CMD ["/bin/bash"]
