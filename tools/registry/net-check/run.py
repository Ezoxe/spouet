"""Tool net-check : diagnostic réseau RÉEL et restreint (stdlib uniquement).

Convention Spouet : 1 invocation = 1 conteneur jetable. Lit un JSON sur stdin,
écrit un JSON sur stdout.

Conçu pour tourner sous `--cap-drop=ALL --read-only` (cf. tools/runner.py) :
tout passe par des sockets NON privilégiés. L'ICMP brut (ping classique) et
traceroute nécessitent CAP_NET_RAW, volontairement retiré → « ping » mesure ici
une connexion TCP (la méthode est indiquée dans la sortie). Aucune commande shell
n'est exécutée : pas de surface d'injection. Les cibles sont validées par regex.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

ALLOWED_ACTIONS = ("ping", "dns", "http", "port")
# Hostname plausible (RFC 1123, tolérant) — pas d'espaces, pas de méta-shell.
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
_CONNECT_TIMEOUT = 2.5
_HTTP_TIMEOUT = 8.0


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("status") == "ok" else 1


def _err(action: str, target: str, msg: str, **extra) -> int:
    return _emit({"status": "error", "action": action, "target": target, "error": msg, **extra})


def _clean_host(target: str) -> str | None:
    """Extrait un hostname/IP sûr depuis `target` (accepte une URL)."""
    t = (target or "").strip()
    if "://" in t:
        t = urlparse(t).hostname or ""
    # IPv6 entre crochets
    if t.startswith("[") and "]" in t:
        t = t[1 : t.index("]")]
    # retire un éventuel :port (IPv4/host uniquement)
    elif t.count(":") == 1:
        t = t.split(":", 1)[0]
    t = t.strip()
    if not t:
        return None
    try:
        ipaddress.ip_address(t)
        return t
    except ValueError:
        pass
    return t if _HOST_RE.match(t) else None


def _tcp_connect(host: str, port: int, timeout: float) -> tuple[float | None, str | None]:
    """Retourne (rtt_ms, None) en cas de succès, (None, message) sinon."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return None, f"DNS: {e}"
    last_err = "aucune adresse"
    for family, stype, proto, _canon, sockaddr in infos:
        s = socket.socket(family, stype, proto)
        s.settimeout(timeout)
        t0 = time.perf_counter()
        try:
            s.connect(sockaddr)
            rtt = (time.perf_counter() - t0) * 1000.0
            return rtt, None
        except OSError as e:
            last_err = str(e)
        finally:
            try:
                s.close()
            except OSError:
                pass
    return None, last_err


def do_dns(target: str) -> int:
    host = _clean_host(target)
    if not host:
        return _err("dns", target, "cible invalide")
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return _err("dns", host, f"résolution échouée: {e}")
    dt = (time.perf_counter() - t0) * 1000.0
    addrs = sorted({i[4][0] for i in infos})
    return _emit(
        {
            "status": "ok",
            "action": "dns",
            "target": host,
            "command": f"getaddrinfo({host})",
            "output": "\n".join(addrs) or "(aucune adresse)",
            "summary": f"{len(addrs)} adresse(s) résolue(s) en {dt:.0f} ms",
        }
    )


def do_ping(target: str, count: int) -> int:
    host = _clean_host(target)
    if not host:
        return _err("ping", target, "cible invalide")
    # On éprouve d'abord 443 puis 80 pour trouver un port qui répond.
    used_port = None
    first_rtt = None
    for port in (443, 80):
        rtt, _e = _tcp_connect(host, port, _CONNECT_TIMEOUT)
        if rtt is not None:
            used_port, first_rtt = port, rtt
            break

    if used_port is None:
        # Diagnostic réussi : l'hôte ne répond pas (down ou ports filtrés).
        return _emit(
            {
                "status": "ok",
                "action": "ping",
                "target": host,
                "command": f"tcp-ping {host}:443/80",
                "output": f"{host} injoignable en TCP (443 et 80 sans réponse)",
                "summary": "100% perte — hôte injoignable (down ou ports filtrés)",
            }
        )

    rtts = [first_rtt]
    fails = 0
    for _ in range(max(0, count - 1)):
        rtt, _e = _tcp_connect(host, used_port, _CONNECT_TIMEOUT)
        if rtt is None:
            fails += 1
        else:
            rtts.append(rtt)

    recv = len(rtts)
    loss = round((count - recv) / count * 100)
    avg = sum(rtts) / recv
    lines = [f"PING {host} via TCP:{used_port} — {count} tentative(s)"]
    lines += [f"  réponse {i + 1}: {r:.1f} ms" for i, r in enumerate(rtts)]
    if fails:
        lines.append(f"  {fails} échec(s)")
    return _emit(
        {
            "status": "ok",
            "action": "ping",
            "target": host,
            "command": f"tcp-ping {host}:{used_port} x{count}",
            "output": "\n".join(lines),
            "summary": (
                f"{loss}% perte, avg {avg:.0f} ms "
                f"(min {min(rtts):.0f} / max {max(rtts):.0f}) — méthode TCP"
            ),
        }
    )


def do_port(target: str, port: int | None) -> int:
    host = _clean_host(target)
    if not host:
        return _err("port", target, "cible invalide")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return _err("port", host, "paramètre 'port' (1-65535) requis pour l'action port")
    rtt, e = _tcp_connect(host, port, _CONNECT_TIMEOUT)
    if rtt is None:
        return _emit(
            {
                "status": "ok",
                "action": "port",
                "target": host,
                "command": f"tcp-connect {host}:{port}",
                "output": f"{host}:{port} FERMÉ / filtré ({e})",
                "summary": f"port {port} fermé ou filtré",
            }
        )
    return _emit(
        {
            "status": "ok",
            "action": "port",
            "target": host,
            "command": f"tcp-connect {host}:{port}",
            "output": f"{host}:{port} OUVERT — connexion en {rtt:.1f} ms",
            "summary": f"port {port} ouvert ({rtt:.0f} ms)",
        }
    )


def do_http(target: str) -> int:
    raw = (target or "").strip()
    if "://" not in raw:
        raw = "https://" + raw
    scheme = urlparse(raw).scheme.lower()
    if scheme not in ("http", "https"):
        return _err("http", target, "URL http(s) requise")
    if _clean_host(raw) is None:
        return _err("http", target, "hôte d'URL invalide")
    req = urllib.request.Request(
        raw, method="GET", headers={"User-Agent": "spouet-net-check/0.1"}
    )
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as resp:
            status_code = resp.status
            final = resp.geturl()
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        # 4xx/5xx : le serveur a bien répondu, c'est un résultat valide.
        dt = (time.perf_counter() - t0) * 1000.0
        return _emit(
            {
                "status": "ok",
                "action": "http",
                "target": raw,
                "command": f"GET {raw}",
                "output": f"HTTP {e.code} {e.reason}\ntemps: {dt:.0f} ms",
                "summary": f"HTTP {e.code} en {dt:.0f} ms",
            }
        )
    except (urllib.error.URLError, ssl.SSLError, socket.timeout, OSError) as e:
        return _err("http", raw, f"requête échouée: {e}")
    dt = (time.perf_counter() - t0) * 1000.0
    return _emit(
        {
            "status": "ok",
            "action": "http",
            "target": raw,
            "command": f"GET {raw}",
            "output": f"HTTP {status_code}\nContent-Type: {ctype}\nfinal: {final}\ntemps: {dt:.0f} ms",
            "summary": f"HTTP {status_code} en {dt:.0f} ms",
        }
    )


def main() -> int:
    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        return _err("?", "", f"JSON d'entrée invalide: {e}")
    if not isinstance(args, dict):
        return _err("?", "", "entrée JSON: objet attendu")

    action = str(args.get("action") or "").strip().lower()
    target = str(args.get("target") or "").strip()
    if action not in ALLOWED_ACTIONS:
        return _err(action or "?", target, f"action inconnue (autorisé: {', '.join(ALLOWED_ACTIONS)})")
    if not target:
        return _err(action, target, "cible (target) manquante")

    try:
        count = int(args.get("count", 4))
    except (TypeError, ValueError):
        count = 4
    count = max(1, min(8, count))
    port = args.get("port")
    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None

    if action == "ping":
        return do_ping(target, count)
    if action == "dns":
        return do_dns(target)
    if action == "port":
        return do_port(target, port)
    return do_http(target)


if __name__ == "__main__":
    sys.exit(main())
