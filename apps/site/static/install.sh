#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  curl -fsSL https://elephant.agentic-in.ai/install.sh | bash
  bash install.sh [install|upgrade|health] [options]

Options:
  --install-root PATH   Durable install root. Default: $HOME/.elephant
  --bin-dir PATH        Directory that will receive the elephant launcher. Default: $HOME/.local/bin
  --python PATH         Python interpreter to use. Default: python3
  --channel CHANNEL     Package channel to install. One of: dev, stable. Default: dev
  --pip-spec SPEC       Explicit pip-installable package spec. Overrides --channel
  --skip-run            Skip the automatic elephant launch after install or upgrade
  --skip-health         Deprecated alias for --skip-run
  --help                Show this help text

Environment overrides:
  ELEPHANT_INSTALL_CHANNEL
  ELEPHANT_PIP_SPEC
  ELEPHANT_PYTHON
EOF
}

command_name="install"
install_root="${HOME}/.elephant"
bin_dir="${HOME}/.local/bin"
python_bin="${ELEPHANT_PYTHON:-python3}"
channel="${ELEPHANT_INSTALL_CHANNEL:-dev}"
pip_spec="${ELEPHANT_PIP_SPEC:-}"
package_name="elephant-agent"
skip_run="0"

while [ "$#" -gt 0 ]; do
  case "$1" in
    install|upgrade|health)
      command_name="$1"
      shift
      ;;
    --install-root)
      install_root="$2"
      shift 2
      ;;
    --bin-dir)
      bin_dir="$2"
      shift 2
      ;;
    --python)
      python_bin="$2"
      shift 2
      ;;
    --channel)
      channel="$2"
      shift 2
      ;;
    --pip-spec|--package-source)
      pip_spec="$2"
      shift 2
      ;;
    --skip-run|--skip-health)
      skip_run="1"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

venv_dir="${install_root}/venv"
venv_python="${venv_dir}/bin/python"
state_dir="${install_root}/herd"
launcher_path="${bin_dir}/elephant"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

has_uv() {
  command -v uv >/dev/null 2>&1
}

require_python_version() {
  if ! "$python_bin" - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY
  then
    echo "Elephant Agent currently requires Python 3.12 or newer." >&2
    exit 1
  fi
}

ensure_config_yaml() {
  mkdir -p "${state_dir}"
  local config_path="${install_root}/config.yaml"
  if [ ! -f "${config_path}" ]; then
    cat > "${config_path}" <<EOF
runtime:
  state_dir: ${state_dir}
  default_profile_id: default
models:
  default_provider_source: config
  provider: null
sessions:
  persist_system_prompts: true
  persist_assistant_responses: true
  max_history_rows: 200
skills:
  enable_profile_overrides: true
  external_dirs: ["~/.agents/skills"]
tools:
  require_approval_for_risky: true
gateway:
  enabled: false
  state_dir: ${state_dir}
dashboard:
  host: "127.0.0.1"
  port: 4174
extensions: {}
EOF
  fi
}

normalize_channel() {
  case "$channel" in
    dev|stable)
      ;;
    *)
      echo "Unsupported channel: $channel" >&2
      exit 2
      ;;
  esac
}

describe_package_selection() {
  if [ -n "${pip_spec}" ]; then
    printf '%s\n' "${pip_spec}"
    return
  fi

  case "${channel}" in
    dev)
      printf '%s\n' "${package_name} (--pre, latest development release)"
      ;;
    stable)
      printf '%s\n' "${package_name} (latest stable release)"
      ;;
  esac
}

ensure_runtime() {
  mkdir -p "${install_root}"

  if has_uv; then
    if [ ! -x "${venv_python}" ]; then
      uv venv "${venv_dir}" --python "${python_bin}"
    fi
    if [ -n "${pip_spec}" ]; then
      uv pip install --python "${venv_python}" --upgrade "${pip_spec}"
    else
      case "${channel}" in
        dev)
          uv pip install --python "${venv_python}" --upgrade --prerelease=allow "${package_name}"
          ;;
        stable)
          uv pip install --python "${venv_python}" --upgrade "${package_name}"
          ;;
      esac
    fi
  else
    if [ ! -x "${venv_python}" ]; then
      "${python_bin}" -m venv "${venv_dir}"
    fi
    "${venv_python}" -m pip install --upgrade pip setuptools wheel >/dev/null
    if [ -n "${pip_spec}" ]; then
      "${venv_python}" -m pip install --upgrade "${pip_spec}"
    else
      case "${channel}" in
        dev)
          "${venv_python}" -m pip install --upgrade --pre "${package_name}"
          ;;
        stable)
          "${venv_python}" -m pip install --upgrade "${package_name}"
          ;;
      esac
    fi
  fi

  ensure_browser_runtime
}

ensure_browser_runtime() {
  if [ "${ELEPHANT_SKIP_BROWSER_INSTALL:-0}" = "1" ]; then
    return
  fi
  if "${venv_python}" -m playwright install --only-shell chromium >/dev/null 2>&1; then
    return
  fi
  echo "Warning: browser runtime install failed; browser tools will retry on first use." >&2
  echo "         To repair manually, run: ${venv_python} -m playwright install --only-shell chromium" >&2
}

write_launcher() {
  mkdir -p "${bin_dir}"
  cat > "${launcher_path}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
install_root="\${ELEPHANT_HOME:-${install_root}}"
state_dir="\${ELEPHANT_HERD_DIR:-${state_dir}}"
venv_python="\${ELEPHANT_PYTHON:-${venv_python}}"

if [ ! -x "\${venv_python}" ]; then
  echo "Elephant Agent runtime is missing: \${venv_python}" >&2
  echo "Run the installer again." >&2
  exit 1
fi

export ELEPHANT_HOME="\${install_root}"
export ELEPHANT_HERD_DIR="\${state_dir}"
exec "\${venv_python}" -m apps.launcher "\$@"
EOF
  chmod +x "${launcher_path}"
}

run_health() {
  if [ ! -x "${launcher_path}" ]; then
    echo "Launcher not found: ${launcher_path}" >&2
    echo "Run 'curl -fsSL https://elephant.agentic-in.ai/install.sh | bash' first." >&2
    exit 1
  fi
  "${launcher_path}" status
}

run_launcher() {
  if [ ! -x "${launcher_path}" ]; then
    echo "Launcher not found: ${launcher_path}" >&2
    echo "Run 'curl -fsSL https://elephant.agentic-in.ai/install.sh | bash' first." >&2
    exit 1
  fi
  "${launcher_path}"
}

install_or_upgrade() {
  require_command "${python_bin}"
  require_python_version
  normalize_channel
  mkdir -p "${install_root}" "${state_dir}"
  ensure_config_yaml
  ensure_runtime
  write_launcher

  echo "Installed Elephant Agent CLI launcher"
  echo "  package: $(describe_package_selection)"
  echo "  install_root: ${install_root}"
  echo "  herd_dir: ${state_dir}"
  echo "  runtime_db: ${state_dir}/elephant.sqlite3"
  echo "  config: ${install_root}/config.yaml"
  echo "  runtime: ${venv_python}"
  echo "  launcher: ${launcher_path}"
  if ! printf '%s' ":${PATH}:" | grep -Fq ":${bin_dir}:"; then
    echo "  path_hint: add ${bin_dir} to PATH to call 'elephant' directly"
  fi
  echo "Next commands"
  echo "  - elephant"
  echo "  - elephant init"
  echo "  - elephant status"
  echo "  - elephant wake"
  echo "  - elephant herd new nova"

  if [ "${skip_run}" != "1" ]; then
    echo
    echo "Launching Elephant Agent"
    run_launcher
  fi
}

case "${command_name}" in
  install|upgrade)
    install_or_upgrade
    ;;
  health)
    run_health
    ;;
  *)
    echo "Unsupported command: ${command_name}" >&2
    exit 2
    ;;
esac
