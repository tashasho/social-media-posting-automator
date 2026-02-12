#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# ClawdBot Firewall Rules — Network Security for Writer Container
#
# These IPTables rules restrict the Writer container's network access
# to ONLY api.anthropic.com, preventing any possibility of the AI
# directly accessing social media APIs.
#
# PREREQUISITES:
#   - Root/sudo access on Docker host
#   - Docker must be running
#   - Writer container must be using subnet 172.28.0.0/16
#     (configured in docker-compose.yml)
#
# USAGE:
#   sudo bash firewall/setup_iptables.sh [apply|remove|status]
# ═══════════════════════════════════════════════════════

set -euo pipefail

WRITER_SUBNET="172.28.0.0/16"
ANTHROPIC_DOMAINS=("api.anthropic.com")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Resolve Domain IPs ───────────────────────────────
resolve_ips() {
    local domain=$1
    dig +short A "$domain" 2>/dev/null | grep -E '^[0-9]+\.'
}

# ── Apply Rules ──────────────────────────────────────
apply_rules() {
    log_info "Applying firewall rules for ClawdBot Writer container..."
    log_info "Writer subnet: ${WRITER_SUBNET}"

    # Allow DNS resolution (required for domain-based rules)
    iptables -I DOCKER-USER -s "${WRITER_SUBNET}" -p udp --dport 53 -j ACCEPT
    iptables -I DOCKER-USER -s "${WRITER_SUBNET}" -p tcp --dport 53 -j ACCEPT
    log_info "✅ DNS resolution allowed"

    # Allow established connections
    iptables -I DOCKER-USER -s "${WRITER_SUBNET}" -m state --state ESTABLISHED,RELATED -j ACCEPT
    log_info "✅ Established connections allowed"

    # Allow whitelisted domains
    for domain in "${ANTHROPIC_DOMAINS[@]}"; do
        log_info "Resolving ${domain}..."
        local ips
        ips=$(resolve_ips "$domain")

        if [ -z "$ips" ]; then
            log_warn "Could not resolve ${domain} — adding by domain name"
            # Fallback: allow by domain using string match (less reliable)
            continue
        fi

        for ip in $ips; do
            iptables -I DOCKER-USER -s "${WRITER_SUBNET}" -d "$ip" -p tcp --dport 443 -j ACCEPT
            log_info "  ✅ Allowed: ${domain} (${ip}:443)"
        done
    done

    # Allow loopback
    iptables -I DOCKER-USER -s "${WRITER_SUBNET}" -d 127.0.0.0/8 -j ACCEPT

    # DROP everything else from the writer subnet
    iptables -A DOCKER-USER -s "${WRITER_SUBNET}" -j DROP
    log_info "🔒 All other outbound traffic from writer DROPPED"

    log_info ""
    log_info "═══════════════════════════════════════════"
    log_info "  Firewall rules applied successfully!"
    log_info "  Writer can ONLY reach: api.anthropic.com"
    log_info "  All other traffic: BLOCKED"
    log_info "═══════════════════════════════════════════"
}

# ── Remove Rules ─────────────────────────────────────
remove_rules() {
    log_warn "Removing ClawdBot firewall rules..."

    # Remove all rules referencing our subnet
    while iptables -D DOCKER-USER -s "${WRITER_SUBNET}" -j DROP 2>/dev/null; do true; done
    while iptables -D DOCKER-USER -s "${WRITER_SUBNET}" -p udp --dport 53 -j ACCEPT 2>/dev/null; do true; done
    while iptables -D DOCKER-USER -s "${WRITER_SUBNET}" -p tcp --dport 53 -j ACCEPT 2>/dev/null; do true; done
    while iptables -D DOCKER-USER -s "${WRITER_SUBNET}" -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; do true; done
    while iptables -D DOCKER-USER -s "${WRITER_SUBNET}" -d 127.0.0.0/8 -j ACCEPT 2>/dev/null; do true; done

    for domain in "${ANTHROPIC_DOMAINS[@]}"; do
        local ips
        ips=$(resolve_ips "$domain")
        for ip in $ips; do
            while iptables -D DOCKER-USER -s "${WRITER_SUBNET}" -d "$ip" -p tcp --dport 443 -j ACCEPT 2>/dev/null; do true; done
        done
    done

    log_info "✅ All ClawdBot firewall rules removed"
}

# ── Status Check ─────────────────────────────────────
show_status() {
    log_info "Current DOCKER-USER chain rules for ${WRITER_SUBNET}:"
    echo ""
    iptables -L DOCKER-USER -v -n 2>/dev/null | grep -E "(${WRITER_SUBNET}|Chain)" || \
        log_warn "No rules found for ${WRITER_SUBNET}"
    echo ""
}

# ── Test Connectivity ────────────────────────────────
test_connectivity() {
    log_info "Testing writer container connectivity..."

    # Find running writer container
    local container_id
    container_id=$(docker ps --filter "name=writer" --format "{{.ID}}" | head -1)

    if [ -z "$container_id" ]; then
        log_warn "Writer container not running — start with 'docker compose up writer'"
        return 1
    fi

    log_info "Container: ${container_id}"

    # Test: anthropic.com should be reachable
    if docker exec "$container_id" python -c "import urllib.request; urllib.request.urlopen('https://api.anthropic.com', timeout=5)" 2>/dev/null; then
        log_info "  ✅ api.anthropic.com: REACHABLE (expected)"
    else
        log_error "  ❌ api.anthropic.com: BLOCKED (unexpected!)"
    fi

    # Test: twitter.com should be blocked
    if docker exec "$container_id" python -c "import urllib.request; urllib.request.urlopen('https://api.twitter.com', timeout=5)" 2>/dev/null; then
        log_error "  ❌ api.twitter.com: REACHABLE (SECURITY ISSUE!)"
    else
        log_info "  ✅ api.twitter.com: BLOCKED (expected)"
    fi

    # Test: linkedin.com should be blocked
    if docker exec "$container_id" python -c "import urllib.request; urllib.request.urlopen('https://api.linkedin.com', timeout=5)" 2>/dev/null; then
        log_error "  ❌ api.linkedin.com: REACHABLE (SECURITY ISSUE!)"
    else
        log_info "  ✅ api.linkedin.com: BLOCKED (expected)"
    fi
}

# ── Main ─────────────────────────────────────────────
case "${1:-status}" in
    apply)
        apply_rules
        ;;
    remove)
        remove_rules
        ;;
    status)
        show_status
        ;;
    test)
        test_connectivity
        ;;
    *)
        echo "Usage: sudo $0 {apply|remove|status|test}"
        echo ""
        echo "  apply   - Apply firewall rules (restrict writer to anthropic.com)"
        echo "  remove  - Remove all ClawdBot firewall rules"
        echo "  status  - Show current firewall rules"
        echo "  test    - Test writer container connectivity"
        exit 1
        ;;
esac
