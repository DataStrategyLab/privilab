#!/bin/sh
set -eu

UV_VERSION="0.12.23"
PYTHON_VERSION="3.13.15"
GITLEAKS_VERSION="8.30.1"
TOOLS_DIR=".tools/bin"
UV_BIN="$TOOLS_DIR/uv"
GITLEAKS_BIN="$TOOLS_DIR/gitleaks"

export UV_CACHE_DIR="${UV_CACHE_DIR:-.local/uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-.local/python}"
export UV_MANAGED_PYTHON=true

usage() {
    echo "usage: $0 [--ci]" >&2
}

case "${1:-}" in
    "") ;;
    --ci)
        export CI=true
        export UV_NO_PROGRESS=true
        ;;
    *)
        usage
        exit 2
        ;;
esac

if [ "$#" -gt 1 ]; then
    usage
    exit 2
fi

if [ ! -f pyproject.toml ] || [ ! -f uv.lock ]; then
    echo "bootstrap must run from the repository root with uv.lock present" >&2
    exit 1
fi

for command_name in git curl tar make; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "required bootstrap command is missing: $command_name" >&2
        exit 1
    fi
done

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        echo "a SHA-256 utility (shasum or sha256sum) is required" >&2
        return 1
    fi
}

verify_archive() {
    archive_path="$1"
    expected="$2"
    actual="$(sha256_file "$archive_path")"
    if [ "$actual" != "$expected" ]; then
        echo "checksum mismatch for $archive_path" >&2
        echo "expected: $expected" >&2
        echo "actual:   $actual" >&2
        exit 1
    fi
}

platform="$(uname -s)"
machine="$(uname -m)"

case "$platform/$machine" in
    Darwin/arm64|Darwin/aarch64)
        uv_asset="uv-aarch64-apple-darwin.tar.gz"
        uv_sha="50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_darwin_arm64.tar.gz"
        gitleaks_sha="b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"
        ;;
    Darwin/x86_64|Darwin/amd64)
        uv_asset="uv-x86_64-apple-darwin.tar.gz"
        uv_sha="960da44cb4b73685206ddd250b19e0a117fa41095710c1038f081f5cb613efb4"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_darwin_x64.tar.gz"
        gitleaks_sha="dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709"
        ;;
    Linux/aarch64|Linux/arm64)
        uv_asset="uv-aarch64-unknown-linux-gnu.tar.gz"
        uv_sha="6524bd338177ed50d035d39354e12545e993bbeba2ecbddf0480c5b3a81d313f"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_linux_arm64.tar.gz"
        gitleaks_sha="e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080"
        ;;
    Linux/x86_64|Linux/amd64)
        uv_asset="uv-x86_64-unknown-linux-gnu.tar.gz"
        uv_sha="9167d72b3319674b6303c4cbe071854bba13ebdf3d76b1a7cbdc175471fb66d6"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
        gitleaks_sha="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
        ;;
    *)
        echo "unsupported bootstrap platform: $platform/$machine" >&2
        exit 1
        ;;
esac

mkdir -p "$TOOLS_DIR"

install_uv() {
    temp_dir="$(mktemp -d)"
    trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
    archive="$temp_dir/$uv_asset"
    curl --proto '=https' --tlsv1.2 -fsSL \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${uv_asset}" \
        -o "$archive"
    verify_archive "$archive" "$uv_sha"
    tar -xzf "$archive" -C "$temp_dir"
    extracted="$(find "$temp_dir" -type f -name uv | head -n 1)"
    test -n "$extracted"
    cp "$extracted" "$UV_BIN"
    chmod 0755 "$UV_BIN"
    rm -rf "$temp_dir"
    trap - EXIT HUP INT TERM
}

install_gitleaks() {
    temp_dir="$(mktemp -d)"
    trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
    archive="$temp_dir/$gitleaks_asset"
    curl --proto '=https' --tlsv1.2 -fsSL \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${gitleaks_asset}" \
        -o "$archive"
    verify_archive "$archive" "$gitleaks_sha"
    tar -xzf "$archive" -C "$temp_dir"
    extracted="$(find "$temp_dir" -type f -name gitleaks | head -n 1)"
    test -n "$extracted"
    cp "$extracted" "$GITLEAKS_BIN"
    chmod 0755 "$GITLEAKS_BIN"
    rm -rf "$temp_dir"
    trap - EXIT HUP INT TERM
}

installed_uv_version=""
if [ -x "$UV_BIN" ]; then
    installed_uv_version="$(
        "$UV_BIN" --version 2>/dev/null | awk 'NR == 1 {print $2}'
    )"
fi

if [ "$installed_uv_version" != "$UV_VERSION" ]; then
    echo "installing verified uv $UV_VERSION"
    install_uv
fi

if [ ! -x "$GITLEAKS_BIN" ] || [ "$($GITLEAKS_BIN version 2>/dev/null || true)" != "$GITLEAKS_VERSION" ]; then
    echo "installing verified Gitleaks $GITLEAKS_VERSION"
    install_gitleaks
fi

if ! "$UV_BIN" python find "$PYTHON_VERSION" >/dev/null 2>&1; then
    echo "installing Python $PYTHON_VERSION"
    "$UV_BIN" python install --no-bin "$PYTHON_VERSION"
fi

echo "syncing locked dependencies"
UV_PROJECT_ENVIRONMENT=.venv "$UV_BIN" sync \
    --python "$PYTHON_VERSION" \
    --frozen \
    --all-groups

echo "bootstrap complete"
echo "next: make ci"
