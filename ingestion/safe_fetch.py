"""
Safe PDF fetcher for Campus Brain.

Implements strict SSRF protection, host allowlisting, manual redirect tracking,
timeout enforcement, streaming size caps, and PDF header verification.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse

import requests

MAX_BYTES = 25 * 1024 * 1024  # 25 MB
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 20.0
MAX_REDIRECTS = 3


def _validate_host_and_ip(host: str, port: int) -> None:
    """Validate host against optional ALLOWED_PDF_HOSTS and reject private/restricted IPs."""
    allowed_env = os.environ.get("ALLOWED_PDF_HOSTS", "").strip()
    if allowed_env:
        allowed = {h.strip().lower() for h in allowed_env.split(",") if h.strip()}
        if host.lower() not in allowed:
            raise ValueError(f"Host '{host}' is not allowed by ALLOWED_PDF_HOSTS.")

    try:
        addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host '{host}': {exc}") from exc

    if not addr_info:
        raise ValueError(f"No address information resolved for host '{host}'.")

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise ValueError(f"Invalid resolved IP '{ip_str}' for host '{host}': {exc}") from exc

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(
                f"Blocked access to non-public/restricted IP {ip_str} for host '{host}'."
            )


def fetch_pdf_bytes(url: str) -> bytes:
    """Safely fetch PDF bytes from a URL with strict SSRF and size protections.

    Requirements:
    - Allow only http and https schemes.
    - Resolve the host with socket.getaddrinfo and reject private, loopback,
      link-local, reserved, multicast, and unspecified IPs.
    - Follow redirects manually (max 3) and re-check each hop.
    - Timeouts: connect 5s, read 20s.
    - Stream with a 25 MB cap.
    - Require the %PDF- header.
    - Optional env ALLOWED_PDF_HOSTS (comma-separated) restricts hosts.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")

    current_url = url.strip()

    for hop in range(MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlsplit(current_url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(
                f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed."
            )

        host = parsed.hostname
        if not host:
            raise ValueError(f"Invalid URL '{current_url}': missing hostname.")

        port = parsed.port or (443 if scheme == "https" else 80)
        _validate_host_and_ip(host, port)

        try:
            resp = requests.get(
                current_url,
                allow_redirects=False,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
        except requests.exceptions.Timeout as exc:
            raise TimeoutError(
                f"Connection or read timed out while fetching PDF: {exc}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Failed to fetch PDF from '{current_url}': {exc}") from exc

        if resp.status_code in (301, 302, 303, 307, 308):
            resp.close()
            if hop >= MAX_REDIRECTS:
                raise ValueError(
                    f"Too many redirects (exceeded maximum of {MAX_REDIRECTS} redirects)."
                )
            location = resp.headers.get("Location")
            if not location:
                raise ValueError("Redirect response missing Location header.")
            current_url = urllib.parse.urljoin(current_url, location)
            continue

        if resp.status_code != 200:
            status = resp.status_code
            resp.close()
            raise ValueError(f"HTTP request failed with status code {status}.")

        content_length = resp.headers.get("Content-Length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_BYTES:
            resp.close()
            raise ValueError(
                f"PDF size ({content_length} bytes) exceeds the 25 MB limit."
            )

        downloaded = bytearray()
        try:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    downloaded.extend(chunk)
                    if len(downloaded) > MAX_BYTES:
                        raise ValueError(
                            f"PDF stream exceeded the 25 MB size limit ({MAX_BYTES} bytes)."
                        )
        finally:
            resp.close()

        pdf_bytes = bytes(downloaded)
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("Downloaded file is not a valid PDF: missing '%PDF-' header.")

        return pdf_bytes

    raise ValueError(f"Exceeded maximum redirects ({MAX_REDIRECTS}).")
