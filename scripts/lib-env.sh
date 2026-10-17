# Shared helper: load .env.example as defaults, then .env as overrides.
# Sourced by the dev-*.sh scripts. Never printed — .env may hold the SLNG key.
# shellcheck shell=bash

_vv_load_env() {
  local root="$1" f
  for f in "$root/.env.example" "$root/.env"; do
    [ -f "$f" ] || continue
    # Only KEY=VALUE lines; ignore comments, blanks and anything exotic.
    while IFS= read -r line; do
      case "$line" in
        ''|\#*) continue ;;
      esac
      [[ "$line" == *=* ]] || continue
      local k="${line%%=*}" v="${line#*=}"
      [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      # A blank value is a placeholder, not a setting — never export one.
      #
      # This was a live bug. `.env.example` ships `VOICEAI_API_KEY=` empty, and exporting that
      # empty string SHADOWED the working credential in ~/.config/voiceai/config.json: inside any
      # script that sourced this file, `voiceai whoami` answered "no API key set" while the same
      # command in a plain shell reported region: in. The same held for SLNG_API_KEY, which is what
      # the generated LiveKit worker reads for STT and TTS. Found by scripts/preflight.sh, which
      # checks the credential rather than assuming it.
      [ -n "$v" ] || continue
      # .env.example supplies defaults; .env and the real environment win.
      if [ "$f" = "$root/.env.example" ]; then
        [ -n "${!k:-}" ] || export "$k=$v"
      else
        export "$k=$v"
      fi
    done < "$f"
  done
}

_vv_load_env "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ports derived from the URLs in docs/04 §1, so the scripts follow .env.example.
_vv_port_of() { # $1 = url, $2 = fallback
  local p
  p="$(printf '%s' "$1" | sed -n 's|.*:\([0-9][0-9]*\).*|\1|p')"
  printf '%s' "${p:-$2}"
}
export CONSOLE_PORT="$(_vv_port_of "${CONSOLE_URL:-}" 8808)"
export LIVEKIT_PORT="$(_vv_port_of "${LIVEKIT_URL:-}" 7880)"
export WEB_PORT="${WEB_PORT:-3000}"
