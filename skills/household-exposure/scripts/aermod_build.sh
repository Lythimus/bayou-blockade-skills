#!/bin/bash
# Build EPA's AERMOD from the pinned source release into ~/.cache/bayou/aermod/<version>/.
#
#   bash aermod_build.sh            build if not already built
#   bash aermod_build.sh --force    rebuild
#
# Downloads one 675 KB archive. Needs gfortran (`brew install gcc`); nothing is installed here.
# After building, `hx.py model --check-build` reruns EPA's published test cases.
set -euo pipefail

VERSION="v26135"
URL="https://gaftp.epa.gov/Air/aqmg/SCRAM/models/preferred/aermod/aermod_source.zip"
# EPA's URL carries no version and is replaced in place at each release, so the hash is the
# pin: a mismatch means the server now holds a release this skill was never checked against.
SHA256="5092c1d68b77d9407c9f67d497b440a79d2ee746f9ed6515a63ad4a5b11cd8ed"
TOPDIR="aermod_source_${VERSION}"
# EPA's flags from gfortran-aermod.bat without -static, which macOS cannot link.
FFLAGS="-fbounds-check -Wuninitialized -O2"
# EPA's compile order: modules.f defines the modules every other file uses.
ORDER="modules grsm aermod setup coset soset reset meset ouset inpsum metext iblval siggrid
tempgrid windgrid calc1 calc2 prise arise prime sigmas pitarea uninam output evset evcalc
evoutput rline bline"

DEST="${BAYOU_AERMOD_DIR:-$HOME/.cache/bayou/aermod}/$VERSION"
STAMP="$DEST/BUILD.txt"
FC="${FC:-}"
if [ -z "$FC" ]; then
  if [ -x /opt/homebrew/bin/gfortran ]; then FC=/opt/homebrew/bin/gfortran
  elif command -v gfortran >/dev/null 2>&1; then FC="$(command -v gfortran)"
  else
    echo "gfortran not found. Install it with: brew install gcc" >&2
    exit 2
  fi
fi
COMPILER="$("$FC" --version | head -1)"
WANT="aermod $VERSION
source_sha256 $SHA256
compiler $COMPILER
flags $FFLAGS"

if [ "${1:-}" != "--force" ] && [ -x "$DEST/aermod" ] && [ -f "$STAMP" ] \
   && [ "$(cat "$STAMP")" = "$WANT" ]; then
  echo "AERMOD $VERSION already built: $DEST/aermod"
  exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/bayou-aermod.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "Fetching $URL"
curl -fsSL --retry 3 -o "$WORK/src.zip" "$URL"
GOT="$(shasum -a 256 "$WORK/src.zip" | cut -d' ' -f1)"
if [ "$GOT" != "$SHA256" ]; then
  echo "EPA's source archive is not the pinned $VERSION release." >&2
  echo "  expected sha256 $SHA256" >&2
  echo "  received sha256 $GOT" >&2
  echo "EPA has probably published a newer AERMOD. Nothing was built: this skill's checks" >&2
  echo "were run against $VERSION only." >&2
  exit 4
fi
unzip -q "$WORK/src.zip" -d "$WORK"
# EPA's archive marks its top directory read-only; the compiler writes beside the sources.
chmod -R u+w "$WORK"
if [ ! -d "$WORK/$TOPDIR" ]; then
  echo "archive does not unpack to $TOPDIR/" >&2
  exit 4
fi

cd "$WORK/$TOPDIR"
OBJS=""
for f in $ORDER; do
  if ! "$FC" -c $FFLAGS "$f.f" >"$f.log" 2>&1; then
    echo "compile failed: $f.f" >&2
    tail -20 "$f.log" >&2
    exit 5
  fi
  OBJS="$OBJS $f.o"
done
"$FC" -O2 -o aermod $OBJS

mkdir -p "$DEST"
install -m 755 aermod "$DEST/aermod"
printf '%s\n' "$WANT" >"$STAMP"
echo "Built AERMOD $VERSION with $COMPILER"
echo "  $DEST/aermod"
