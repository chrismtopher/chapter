# Security Policy

## Supported Versions

Security fixes are made for the latest tagged release. Update to the release shown at the top of the [README](README.md) before reporting a problem.

## Trusted Network Design

Chapter Player is a local appliance. Its administration page intentionally has no account or password and is designed only for a trusted private home network.

Anyone who can reach the administration page can control playback, change player settings, replace the Audiobookshelf login, change or forget Wi-Fi, reboot the player, or restore it to default settings. The setup service also performs privileged system operations so it can manage networking and reboot the appliance.

- Do not expose ports `80` or `47831` to the internet.
- Do not configure router port forwarding for the player.
- Keep the player off public, guest, or otherwise untrusted networks.
- Complete first-time setup in a controlled location. The temporary `Chapter-Setup` network is intentionally open.
- Use a dedicated Audiobookshelf account limited to the libraries and content intended for the player.

The administration page uses CSRF tokens to stop unrelated websites from submitting commands through a parent's browser. CSRF protection is not authentication and does not prevent another person already on the same network from opening the page directly.

## Reporting A Vulnerability

Please do not disclose a suspected vulnerability in a public issue. Use GitHub's private vulnerability reporting option on the repository's Security tab when available. Include the affected release, reproduction steps, expected behavior, and observed behavior.
