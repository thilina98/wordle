# Shared by pre-commit and pre-push. Add a branch name to protect it.
PROTECTED_BRANCHES="master"

is_protected() {
  for branch in $PROTECTED_BRANCHES; do
    [ "$1" = "$branch" ] && return 0
  done
  return 1
}

# Orange text on a terminal, plain text elsewhere (GUIs, logs).
warn() {
  if [ -t 2 ]; then
    printf '\033[38;5;208m%s\033[0m\n' "$@" >&2
  else
    printf '%s\n' "$@" >&2
  fi
}
