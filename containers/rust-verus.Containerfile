# cedar-diff-fleet rust-verus image — Rust 1.82 stable + 1.94 nightly + Verus 0.2026.03.28.
#
# Reuses the install recipe from platform/c-to-rust/Containerfile so any
# Verus version bump there propagates here with one copy. When stable,
# promote this into athanor-builder/base-images/rust-verus/ and publish
# to ghcr.io/athanor-ai/rust-verus-base:YYYY.MM.DD alongside lean-base +
# dafny-base.
#
# Used for:
#  - running cedar-policy-generators (cedar-spec's Rust corpus generator)
#  - running the Rust reference cedar-policy CLI
#  - optional: Verus-annotated subsets of cedar typing / eval for an
#    "independent Rust proof oracle" experiment alongside cedar-spec's Lean proofs
#
# Build: docker build -f containers/rust-verus.Containerfile -t cedar-rust-verus:dev .
# Use:   ./scripts/dc rust-verus cargo build --release

FROM docker.io/library/amazonlinux:2023.8.20250818.0

ENV RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    RUST_VERSION=1.82.0
ENV PATH="/opt/cargo/bin:${PATH}"

RUN dnf update -y && \
    dnf install -y shadow-utils findutils which util-linux \
      gcc gcc-c++ make binutils git curl-minimal tar gzip unzip && \
    dnf clean all && rm -rf /tmp/* /var/tmp/*

# Rust stable (for cedar-policy + cedar-policy-generators, which both build on stable)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain ${RUST_VERSION} --no-modify-path && \
    rustc --version && cargo --version

# Verus binary (same release pin as c-to-rust env)
RUN curl -fsSL "https://github.com/verus-lang/verus/releases/download/release/0.2026.03.28.3390e9a/verus-0.2026.03.28.3390e9a-x86-linux.zip" -o /tmp/verus.zip && \
    unzip /tmp/verus.zip -d /opt && \
    ln -sf /opt/verus-x86-linux/verus /usr/local/bin/verus && \
    chmod -R a+rX /opt/verus-x86-linux && \
    chmod a+rx /usr/local/bin/verus && \
    rm /tmp/verus.zip

# Rust nightly 1.94 (Verus toolchain). Slim: drop docs + src.
RUN rustup install 1.94.0-x86_64-unknown-linux-gnu && \
    verus --version && \
    rustup component remove rust-docs --toolchain ${RUST_VERSION}-x86_64-unknown-linux-gnu 2>/dev/null || true && \
    rustup component remove rust-docs --toolchain 1.94.0-x86_64-unknown-linux-gnu 2>/dev/null || true && \
    rm -rf /opt/rustup/toolchains/*/share/doc /opt/rustup/toolchains/*/share/man

WORKDIR /work
CMD ["/bin/bash"]
