"""Small terminal progress helper."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ProgressLogger:
    verbose: bool = True
    started_at: float = field(default_factory=time.monotonic)

    def log(self, message: str) -> None:
        if not self.verbose:
            return
        elapsed = time.monotonic() - self.started_at
        print(f"[{elapsed:6.1f}s] {message}", flush=True)


QUIET_PROGRESS = ProgressLogger(verbose=False)

