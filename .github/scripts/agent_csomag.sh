#!/usr/bin/env bash
# =====================================================================
#  Ugynok-kiadas epitese es alairasa (a deploy-admin.yml hivja).
#
#  Bemenet:  AGENT_SIGNING_KEY  (kornyezeti valtozo: a PRIVAT kulcs PEM-ben)
#            $1 = a repo gyokere (alap: .)
#  Kimenet:  admin/public/kiadasok/agent-<verzio>.zip + .json
#
#  A verzio az agent/common.py AGENT_VERSION-je. A csomagba minden
#  ugynok-fajl bekerul, KIVEVE a frissito.py-t (az sosem frissul tavolrol)
#  es a kiadas_kulcs.txt-t (a gep sajat kulcsa, azt csomag nem irhatja at).
#
#  Ha nincs kulcs: figyelmeztet, es nem keszit kiadast (kilepes 0).
#  Ha a kulcs nem egyezik az agent/kiadas_kulcs.txt modulusaval: HIBA - egy
#  ilyen csomagot a gepek ugyis elutasitananak.
#  A vegen a frissito.py SAJAT ellenorzesevel probaljuk ki a csomagot.
# =====================================================================
set -euo pipefail
ROOT="${1:-.}"
cd "$ROOT"

VER=$(grep -oP '^AGENT_VERSION = "\K[^"]+' agent/common.py || true)
if [ -z "$VER" ]; then
  echo "::error::Nincs AGENT_VERSION az agent/common.py-ban."
  exit 1
fi
if [ -z "${AGENT_SIGNING_KEY:-}" ]; then
  echo "::warning::Nincs AGENT_SIGNING_KEY secret - ugynok-kiadas nem keszul (a tavoli frissites ki van kapcsolva)."
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
printf '%s\n' "$AGENT_SIGNING_KEY" | sed 's/\r$//' > "$TMP/k.pem"
chmod 600 "$TMP/k.pem"
if ! openssl pkey -in "$TMP/k.pem" -noout 2>"$TMP/err"; then
  echo "::error::Az AGENT_SIGNING_KEY nem olvashato privat kulcs: $(cat "$TMP/err")"
  exit 1
fi
N_KEY=$(openssl rsa -in "$TMP/k.pem" -noout -modulus | cut -d= -f2)
N_FILE=$(grep -oP '^\s*n\s*=\s*\K[0-9A-Fa-f]+' agent/kiadas_kulcs.txt || true)
if [ -z "$N_FILE" ] || [ "${N_FILE^^}" != "${N_KEY^^}" ]; then
  echo "::error::Az agent/kiadas_kulcs.txt modulusa nem egyezik az AGENT_SIGNING_KEY kulccsal. Ird bele: openssl rsa -in <privat.pem> -noout -modulus"
  exit 1
fi

# Az ideiglenes mappaban epitjuk; a kiadasok/ ala CSAK sikeres
# onellenorzes utan kerul - felkesz kiadas soha nem megy fel.
OUT=admin/public/kiadasok
ZIP="$TMP/agent-$VER.zip"
(
  cd agent
  FILES=$(ls -1 *.py *.bat *.md *.example cacert.pem 2>/dev/null | grep -v -x -e frissito.py)
  # shellcheck disable=SC2086
  zip -X -q "$ZIP" $FILES
)
openssl dgst -sha256 -sign "$TMP/k.pem" -out "$TMP/sig" "$ZIP"

python3 - "$VER" "$ZIP" "$TMP/sig" <<'PY'
import base64, hashlib, json, os, sys, time
ver, z, sig = sys.argv[1:]
data = open(z, "rb").read()
m = {
    "verzio": ver,
    "sha256": hashlib.sha256(data).hexdigest(),
    "sig": base64.b64encode(open(sig, "rb").read()).decode("ascii"),
    "meret": len(data),
    "ido": time.strftime("%Y-%m-%d %H:%M"),
    "commit": os.environ.get("GITHUB_SHA", "")[:7],
}
with open(z[:-4] + ".json", "w") as f:
    json.dump(m, f)
PY

# Onellenorzes a gep sajat kodjaval: kulcs betoltese + alairas.
python3 - "$ZIP" <<'PY'
import base64, hashlib, json, sys
sys.path.insert(0, "agent")
import frissito
z = sys.argv[1]
data = open(z, "rb").read()
m = json.load(open(z[:-4] + ".json"))
key = frissito.load_key()
assert key, "a kiadas_kulcs.txt nem toltheto be"
assert hashlib.sha256(data).hexdigest() == m["sha256"]
assert frissito.rsa_verify_sha256(data, base64.b64decode(m["sig"]), *key), "alairas ervenytelen"
print("Kiadas kesz es ellenorizve: agent-%s.zip (%d bajt)" % (m["verzio"], m["meret"]))
PY

mkdir -p "$OUT"
rm -f "$OUT"/agent-*.zip "$OUT"/agent-*.json
mv "$ZIP" "${ZIP%.zip}.json" "$OUT/"
ls -l "$OUT"
