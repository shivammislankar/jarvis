# Security

Jarvis controls a laptop and runs on a server, so security reports are very welcome.

**Please report problems privately:** on GitHub, open the **Security** tab → **Report a vulnerability**.
Don't open a public issue for security problems.

Helpful to include: which file and step, what an attacker would need (e.g. "a compromised server",
"access to the unlocked phone"), and how to reproduce it. Please never include real keys, IPs or
personal data.

The security model is described in the README. In short: only WireGuard (UDP 51820) is reachable
from the internet; the laptop's SSH listens on 127.0.0.1 only; the server's key on the laptop can
run only a fixed list of actions; AI-proposed actions need your confirmation; downloads are
SHA-256 pinned.
