"""Small in-process guard for repeated password guesses in local deployments."""

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class LoginThrottle:
    def __init__(self, *, window_seconds: int = 60, account_limit: int = 5,
                 address_limit: int = 20, clock=monotonic):
        self.window_seconds = window_seconds
        self.account_limit = account_limit
        self.address_limit = address_limit
        self.clock = clock
        self._accounts = defaultdict(deque)
        self._addresses = defaultdict(deque)
        self._lock = Lock()
        self._last_sweep = self.clock()

    def _recent(self, buckets, key, now):
        attempts = buckets.get(key)
        if attempts is None:
            return ()
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        if not attempts:
            buckets.pop(key, None)
        return attempts

    def _sweep_if_due(self, now):
        if now - self._last_sweep < self.window_seconds:
            return
        for buckets in (self._accounts, self._addresses):
            for key in tuple(buckets):
                self._recent(buckets, key, now)
        self._last_sweep = now

    def allowed(self, username: str, address: str) -> bool:
        now = self.clock()
        with self._lock:
            self._sweep_if_due(now)
            account = self._recent(self._accounts, username.casefold(), now)
            source = self._recent(self._addresses, address, now)
            return len(account) < self.account_limit and len(source) < self.address_limit

    def failed(self, username: str, address: str) -> None:
        now = self.clock()
        with self._lock:
            self._recent(self._accounts, username.casefold(), now)
            self._recent(self._addresses, address, now)
            self._accounts[username.casefold()].append(now)
            self._addresses[address].append(now)

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._accounts.pop(username.casefold(), None)


login_throttle = LoginThrottle()
