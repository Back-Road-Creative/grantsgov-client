"""Keyless connectors for public US grant and nonprofit data.

Three pieces, all optional to each other:

* `grants_gov` - sweep the Grants.gov `search2` endpoint, fetch the rich
  per-opportunity record, and normalize both into flat dicts.
* `propublica` - look up an EIN in ProPublica's Nonprofit Explorer and reduce
  the IRS registration record to a profile prefill.
* `matching` - score an organisation profile against an opportunity, 0-100,
  with a human-readable reason behind every point.

No API keys. No runtime dependencies - `urllib` from the standard library is
the whole transport. Both connectors retry transport faults (never a 4xx) with
doubling backoff and pace themselves at roughly one request a second, and both
treat everything they fetch as untrusted data: normalized to plain text, never
executed, never followed.
"""

from . import grants_gov, matching, propublica, vocabulary
from .grants_gov import ConnectorError
from .matching import Reason
from .propublica import LookupFailed
from .text import plain_text

__version__ = "0.1.0"

__all__ = [
    "ConnectorError", "LookupFailed", "Reason", "__version__", "grants_gov",
    "matching", "plain_text", "propublica", "vocabulary",
]
