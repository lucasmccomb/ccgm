#!/usr/bin/env bash
# brand-check-gather.sh - Parallel DNS/whois/curl checks for /brand-check
# Usage: brand-check-gather.sh <name> [tld1,tld2,...]
# Runs all bash-based checks concurrently. WebSearch calls remain in the agent.

NAME="$1"
if [ -z "$NAME" ]; then
  echo "ERROR: No name provided. Usage: brand-check-gather.sh <name> [tld1,tld2,...]"
  exit 1
fi

# Normalize to lowercase
NAME=$(echo "$NAME" | tr '[:upper:]' '[:lower:]')

# TLDs from arg or defaults
if [ -n "$2" ]; then
  IFS=',' read -ra TLDS <<< "$2"
else
  TLDS=(ai io com life work app co dev org net)
fi

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT
mkdir -p "$TMPDIR/dns" "$TMPDIR/whois" "$TMPDIR/social"

# --- Phase 1: Domain checks (parallel per TLD) ---

for tld in "${TLDS[@]}"; do
  (
    DOMAIN="${NAME}.${tld}"
    # DNS pre-check
    A=$(dig +short "$DOMAIN" A 2>/dev/null)
    NS=$(dig +short "$DOMAIN" NS 2>/dev/null)
    if [ -z "$A" ] && [ -z "$NS" ]; then
      DNS_STATUS="MAYBE_AVAIL"
    else
      DNS_STATUS="TAKEN"
    fi

    # Whois verification for MAYBE_AVAIL
    if [ "$DNS_STATUS" = "MAYBE_AVAIL" ]; then
      case "$tld" in
        com|net)
          whois -h whois.verisign-grs.com "$DOMAIN" 2>/dev/null | grep -q "No match" && WHOIS="AVAIL" || WHOIS="TAKEN" ;;
        io)
          whois -h whois.nic.io "$DOMAIN" 2>/dev/null | grep -qi "NOT FOUND" && WHOIS="AVAIL" || WHOIS="TAKEN" ;;
        ai)
          whois -h whois.nic.ai "$DOMAIN" 2>/dev/null | grep -qi "not registered" && WHOIS="AVAIL" || WHOIS="TAKEN" ;;
        work)
          whois -h whois.nic.work "$DOMAIN" 2>/dev/null | grep -qi "DOMAIN NOT FOUND" && WHOIS="AVAIL" || WHOIS="TAKEN" ;;
        app|dev)
          whois "$DOMAIN" 2>/dev/null | grep -qi "No match\|NOT FOUND\|No Data Found" && WHOIS="AVAIL" || WHOIS="TAKEN" ;;
        *)
          whois "$DOMAIN" 2>/dev/null | grep -qi "No match\|NOT FOUND\|No Data Found\|not registered\|DOMAIN NOT FOUND" && WHOIS="AVAIL" || WHOIS="TAKEN" ;;
      esac
    else
      WHOIS="TAKEN"
    fi

    echo "${tld}:${WHOIS}"
  ) > "$TMPDIR/dns/${tld}" 2>/dev/null &
done

# --- Phase 2: Social media curl probes (parallel) ---

# GitHub
(
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://github.com/${NAME}" 2>/dev/null)
  echo "github:${CODE}"
) > "$TMPDIR/social/github" &

# Reddit subreddit
(
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://www.reddit.com/r/${NAME}" 2>/dev/null)
  echo "reddit_sub:${CODE}"
) > "$TMPDIR/social/reddit_sub" &

# Reddit user
(
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://www.reddit.com/user/${NAME}" 2>/dev/null)
  echo "reddit_user:${CODE}"
) > "$TMPDIR/social/reddit_user" &

# YouTube
(
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://www.youtube.com/@${NAME}" 2>/dev/null)
  echo "youtube:${CODE}"
) > "$TMPDIR/social/youtube" &

# TikTok
(
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://www.tiktok.com/@${NAME}" 2>/dev/null)
  echo "tiktok:${CODE}"
) > "$TMPDIR/social/tiktok" &

# Product Hunt
(
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://www.producthunt.com/products/${NAME}" 2>/dev/null)
  echo "producthunt:${CODE}"
) > "$TMPDIR/social/producthunt" &

# --- Phase 3: App Store API (parallel) ---

(
  curl -s "https://itunes.apple.com/search?term=${NAME}&entity=software&limit=10" 2>/dev/null | \
    python3 -c "import sys,json; data=json.load(sys.stdin); [print(f'{r[\"trackName\"]} by {r[\"artistName\"]}') for r in data.get('results',[])]" 2>/dev/null || echo "unavailable"
) > "$TMPDIR/appstore" &

# --- Phase 4: GitHub repo search ---

(
  gh search repos "$NAME" --limit 5 2>/dev/null || echo "unavailable"
) > "$TMPDIR/gh_repos" &

# --- Phase 5: Reddit search ---

(
  curl -s "https://www.reddit.com/search.json?q=${NAME}&limit=5" -H "User-Agent: research-agent/1.0" 2>/dev/null | \
    python3 -c "import sys,json; data=json.load(sys.stdin); [print(f'{c[\"data\"][\"title\"]} (r/{c[\"data\"][\"subreddit\"]}, score:{c[\"data\"][\"score\"]})') for c in data.get('data',{}).get('children',[])]" 2>/dev/null || echo "unavailable"
) > "$TMPDIR/reddit_search" &

wait

# --- Output ---
echo "=== IDENTITY ==="
echo "name:${NAME}"
echo "tlds:${TLDS[*]}"
echo "date:$(date +%Y-%m-%d)"

echo ""
echo "=== DOMAINS ==="
for tld in "${TLDS[@]}"; do
  cat "$TMPDIR/dns/${tld}" 2>/dev/null || echo "${tld}:ERROR"
done

echo ""
echo "=== SOCIAL ==="
for f in "$TMPDIR/social"/*; do
  cat "$f" 2>/dev/null
done

echo ""
echo "=== APPSTORE ==="
cat "$TMPDIR/appstore"

echo ""
echo "=== GH_REPOS ==="
cat "$TMPDIR/gh_repos"

echo ""
echo "=== REDDIT ==="
cat "$TMPDIR/reddit_search"
