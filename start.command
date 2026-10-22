#!/bin/zsh
set -eu
cd "${0:A:h}"
python_candidates=("${PET_STUDIO_PYTHON:-}" "$PWD/.venv/bin/python" "$(command -v python3 || true)" "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3")
for candidate in "${python_candidates[@]}"; do
  if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import sys, tomllib, PIL; assert sys.version_info >= (3, 11)' 2>/dev/null; then
    exec "$candidate" studio/server.py --open "$@"
  fi
done
echo 'Python 3.11+와 Pillow가 필요합니다. 준비된 Python 경로를 PET_STUDIO_PYTHON으로 지정해 주세요.'
exit 1
