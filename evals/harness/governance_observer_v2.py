"""Compatibility import path for the separately versioned V3 observer.

The original V2 bytes are preserved as governance_observer_v2_reference.py and in
Git history. New events explicitly identify V3. No policy, boundary or validator
is replaced; callers retain the same public observation interface.
"""

from evals.harness.governance_observer_v3 import (
    MAX_EVENTS as MAX_EVENTS,
)
from evals.harness.governance_observer_v3 import (
    MAX_IDENTIFIER_LENGTH as MAX_IDENTIFIER_LENGTH,
)
from evals.harness.governance_observer_v3 import (
    OBSERVER_VERSION as OBSERVER_VERSION,
)
from evals.harness.governance_observer_v3 import (
    ReadOnlyGovernanceObserver as ReadOnlyGovernanceObserver,
)
