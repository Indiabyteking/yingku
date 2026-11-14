from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable

import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YingKuMediaManager/1.0",
    "Accept": "application/json, text/plain, */*",
}


class ExternalServiceError(RuntimeError):
    """统一的外部服务调用异常。"""

    def __init__(self, service: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.message = message
        self.status_code = status_code


class RateLimitedHttpClient:
    """带最小请求间隔限速与 429/5xx 指数退避重试的 HTTP 客户端封装。"""

    def __init__(
        self,
        service_name: str,
        min_interval: float = 0.2,
        max_retries: int = 3,
        base_backoff: float = 0.8,
        timeout: float = 15.0,
        session: requests.Session | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.service_name = service_name
        self.min_interval = max(0.0, float(min_interval))
        self.max_retries = max(0, int(max_retries))
        self.base_backoff = max(0.05, float(base_backoff))
        self.timeout = timeout
        self.session = session or requests.Session()
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._lock = threading.Lock()
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = self._clock()
            elapsed = now - self._last_request_ts
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                self._sleep(wait_time)
                now = self._clock()
            self._last_request_ts = now

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        timeout: float | None = None,
        stream: bool = False,
    ) -> requests.Response:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        req_timeout = timeout if timeout is not None else self.timeout

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=merged_headers,
                    params=params,
                    json=json_body,
                    timeout=req_timeout,
                    stream=stream,
                )
            except requests.Timeout as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    self._sleep(self._compute_backoff(attempt))
                    continue
                raise ExternalServiceError(self.service_name, f"{self.service_name} 请求超时，请检查网络连接") from exc
            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    self._sleep(self._compute_backoff(attempt))
                    continue
                raise ExternalServiceError(self.service_name, f"无法连接到 {self.service_name} 服务，请确认地址正确且服务已启动") from exc
            except requests.RequestException as exc:
                raise ExternalServiceError(self.service_name, f"{self.service_name} 网络请求异常: {exc}") from exc

            if resp.status_code == 429 or resp.status_code in (502, 503, 504):
                if attempt < self.max_retries:
                    retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                    delay = retry_after if retry_after is not None else self._compute_backoff(attempt)
                    self._sleep(delay)
                    continue
                if resp.status_code == 429:
                    raise ExternalServiceError(
                        self.service_name,
                        f"{self.service_name} 触发接口限流 (HTTP 429)，已重试仍受限，请稍后再试",
                        status_code=429,
                    )
                raise ExternalServiceError(
                    self.service_name,
                    f"{self.service_name} 服务暂时不可用 (HTTP {resp.status_code})",
                    status_code=resp.status_code,
                )

            return resp

        raise ExternalServiceError(self.service_name, f"{self.service_name} 请求失败: {last_exc}")

    def _compute_backoff(self, attempt: int) -> float:
        jitter = random.uniform(0.0, 0.15 * self.base_backoff)
        return self.base_backoff * (2**attempt) + jitter

    @staticmethod
    def _parse_retry_after(header_val: str | None) -> float | None:
        if not header_val:
            return None
        try:
            seconds = float(header_val.strip())
            return max(0.1, min(seconds, 15.0))
        except ValueError:
            return None
