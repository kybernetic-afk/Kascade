import ipaddress


def is_local_host(host: str) -> bool:
    """True for loopback / private / link-local addresses (and 'localhost').

    Used to permit plain http only for AMP instances on the same machine/LAN.
    """
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local
