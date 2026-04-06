#!/usr/bin/env bash
# postInstall.sh - Download and install the ccgm-agents binary after module install.
#
# Downloads the correct platform binary from GitHub Releases, verifies the
# SHA-256 checksum, and installs it to ~/.ccgm/bin/ccgm-agents.
set -euo pipefail

INSTALL_DIR="${HOME}/.ccgm/bin"
BINARY_NAME="ccgm-agents"
REPO="lucasmccomb/ccgm"
RELEASES_URL="https://github.com/${REPO}/releases/latest/download"

# ---- Detect platform --------------------------------------------------------

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "${ARCH}" in
  x86_64)          ARCH="amd64" ;;
  aarch64|arm64)   ARCH="arm64" ;;
  *)
    echo "ERROR: Unsupported architecture: ${ARCH}" >&2
    exit 1
    ;;
esac

case "${OS}" in
  darwin|linux) ;;
  *)
    echo "ERROR: Unsupported OS: ${OS}" >&2
    exit 1
    ;;
esac

if [[ "${OS}" == "linux" && "${ARCH}" == "arm64" ]]; then
  echo "ERROR: Linux arm64 is not supported. Supported platforms: darwin-arm64, darwin-amd64, linux-amd64" >&2
  exit 1
fi

# Goreleaser archive naming: ccgm-agents_VERSION_OS_ARCH.tar.gz
# The archive contains the binary at the top level.
ARCHIVE_NAME="${BINARY_NAME}_${OS}_${ARCH}.tar.gz"
CHECKSUMS_NAME="checksums.txt"

# ---- Skip if already installed ----------------------------------------------

if [[ -x "${INSTALL_DIR}/${BINARY_NAME}" ]]; then
  echo "ccgm-agents is already installed at ${INSTALL_DIR}/${BINARY_NAME}"
  echo "To upgrade, remove the existing binary and re-run this script."
  exit 0
fi

# ---- Require download tool --------------------------------------------------

if command -v curl &>/dev/null; then
  DOWNLOAD="curl -fsSL --retry 3 --retry-delay 2"
elif command -v wget &>/dev/null; then
  DOWNLOAD="wget -qO-"
else
  echo "ERROR: Neither curl nor wget found. Install one and re-run." >&2
  exit 1
fi

# ---- Create install directory -----------------------------------------------

mkdir -p "${INSTALL_DIR}"

# ---- Download to temp directory ---------------------------------------------

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

ARCHIVE_PATH="${TMP_DIR}/${ARCHIVE_NAME}"
CHECKSUMS_PATH="${TMP_DIR}/${CHECKSUMS_NAME}"

echo "Downloading ccgm-agents for ${OS}/${ARCH}..."

if ! ${DOWNLOAD} "${RELEASES_URL}/${ARCHIVE_NAME}" -o "${ARCHIVE_PATH}" 2>/dev/null; then
  echo "ERROR: Failed to download ${RELEASES_URL}/${ARCHIVE_NAME}" >&2
  echo "Check your network connection or visit https://github.com/${REPO}/releases to download manually." >&2
  exit 1
fi

if ! ${DOWNLOAD} "${RELEASES_URL}/${CHECKSUMS_NAME}" -o "${CHECKSUMS_PATH}" 2>/dev/null; then
  echo "ERROR: Failed to download checksums from ${RELEASES_URL}/${CHECKSUMS_NAME}" >&2
  exit 1
fi

# ---- Verify SHA-256 checksum ------------------------------------------------

echo "Verifying checksum..."

EXPECTED_CHECKSUM=$(grep "${ARCHIVE_NAME}" "${CHECKSUMS_PATH}" | awk '{print $1}')
if [[ -z "${EXPECTED_CHECKSUM}" ]]; then
  echo "ERROR: Could not find checksum for ${ARCHIVE_NAME} in checksums.txt" >&2
  exit 1
fi

if command -v sha256sum &>/dev/null; then
  ACTUAL_CHECKSUM=$(sha256sum "${ARCHIVE_PATH}" | awk '{print $1}')
elif command -v shasum &>/dev/null; then
  ACTUAL_CHECKSUM=$(shasum -a 256 "${ARCHIVE_PATH}" | awk '{print $1}')
else
  echo "ERROR: Neither sha256sum nor shasum found. Cannot verify checksum." >&2
  exit 1
fi

if [[ "${EXPECTED_CHECKSUM}" != "${ACTUAL_CHECKSUM}" ]]; then
  echo "ERROR: Checksum mismatch!" >&2
  echo "  Expected: ${EXPECTED_CHECKSUM}" >&2
  echo "  Actual:   ${ACTUAL_CHECKSUM}" >&2
  echo "The downloaded file may be corrupted or tampered with." >&2
  exit 1
fi

echo "Checksum verified."

# ---- Extract and install ----------------------------------------------------

tar -xzf "${ARCHIVE_PATH}" -C "${TMP_DIR}" "${BINARY_NAME}"
chmod +x "${TMP_DIR}/${BINARY_NAME}"
mv "${TMP_DIR}/${BINARY_NAME}" "${INSTALL_DIR}/${BINARY_NAME}"

echo "Installed ccgm-agents to ${INSTALL_DIR}/${BINARY_NAME}"

# ---- PATH reminder ----------------------------------------------------------

if ! echo "${PATH}" | grep -q "${INSTALL_DIR}"; then
  echo ""
  echo "NOTE: ${INSTALL_DIR} is not in your PATH."
  echo "Add this to your shell profile (.zshrc, .bashrc, etc.):"
  echo "  export PATH=\"\${HOME}/.ccgm/bin:\${PATH}\""
fi

echo "Run 'ccgm-agents' or use the /agents command to launch the TUI."
