"""Retry logic with exponential backoff and network-aware waiting.

This module provides:
- retry_with_backoff: Simple exponential backoff retry
- wait_for_network: Wait for network connectivity to be restored
- retry_with_network_wait: Combines retry with network awareness
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syncagent.client.api import HTTPClient

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_BACKOFF = 1.0  # seconds
DEFAULT_MAX_BACKOFF = 60.0  # seconds
DEFAULT_BACKOFF_MULTIPLIER = 2.0

# Network-aware retry configuration
NETWORK_CHECK_INTERVAL = 5.0  # seconds between network checks

# Network-related exceptions that indicate connectivity issues
NETWORK_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def wait_for_network(
    client: HTTPClient,
    check_interval: float = NETWORK_CHECK_INTERVAL,
    on_waiting: Callable[[], None] | None = None,
    on_restored: Callable[[], None] | None = None,
) -> None:
    """Wait indefinitely for network connectivity to be restored.

    Polls the server health endpoint every check_interval seconds until
    the server becomes reachable. This is used when network errors occur
    during sync to wait for the connection to be restored rather than
    failing immediately.

    Args:
        client: SyncClient to use for health checks.
        check_interval: Seconds between health check attempts (default: 5s).
        on_waiting: Optional callback when starting to wait (e.g., update tray icon).
        on_restored: Optional callback when network is restored.
    """
    logger.info(
        f"Network appears down. Waiting for connectivity "
        f"(checking every {check_interval}s)..."
    )

    if on_waiting:
        on_waiting()

    attempts = 0
    while True:
        time.sleep(check_interval)
        attempts += 1

        if client.health_check():
            logger.info(f"Network restored after {attempts * check_interval:.0f}s")
            if on_restored:
                on_restored()
            return

        if attempts % 12 == 0:  # Log every minute (12 * 5s)
            logger.info(
                f"Still waiting for network... ({attempts * check_interval:.0f}s elapsed)"
            )


def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Execute a function with exponential backoff retry.

    Args:
        func: Function to execute.
        max_retries: Maximum number of retry attempts.
        initial_backoff: Initial backoff time in seconds.
        max_backoff: Maximum backoff time in seconds.
        backoff_multiplier: Multiplier for each retry.
        retryable_exceptions: Tuple of exception types to retry on.

    Returns:
        Result of the function.

    Raises:
        The last exception if all retries fail.
    """
    backoff = initial_backoff
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.error(f"All {max_retries} retries failed: {e}")
                raise

            logger.warning(
                f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                f"Retrying in {backoff:.1f}s..."
            )
            time.sleep(backoff)
            backoff = min(backoff * backoff_multiplier, max_backoff)

    # Should not reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")


def retry_with_network_wait(
    func: Callable[[], Any],
    client: HTTPClient,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    network_check_interval: float = NETWORK_CHECK_INTERVAL,
    on_network_waiting: Callable[[], None] | None = None,
    on_network_restored: Callable[[], None] | None = None,
) -> Any:
    """Execute a function with retry and network-aware waiting.

    This function combines exponential backoff retry with network-aware waiting.
    When a network-related error occurs (ConnectionError, TimeoutError, OSError),
    it waits for the network to be restored by polling the server health endpoint
    every 5 seconds. For other retryable errors, it uses exponential backoff.

    Args:
        func: Function to execute.
        client: SyncClient for health checks during network wait.
        max_retries: Maximum retry attempts for non-network errors.
        initial_backoff: Initial backoff time in seconds.
        max_backoff: Maximum backoff time in seconds.
        backoff_multiplier: Multiplier for each retry.
        retryable_exceptions: Tuple of exception types to retry on.
        network_check_interval: Seconds between network health checks.
        on_network_waiting: Callback when network wait starts.
        on_network_restored: Callback when network is restored.

    Returns:
        Result of the function.

    Raises:
        The last exception if all retries fail (for non-network errors).
    """
    backoff = initial_backoff
    retry_count = 0

    while True:
        try:
            return func()
        except NETWORK_EXCEPTIONS as e:
            # Network error - wait for network to come back, then retry
            logger.warning(f"Network error: {e}")
            wait_for_network(
                client,
                check_interval=network_check_interval,
                on_waiting=on_network_waiting,
                on_restored=on_network_restored,
            )
            # Reset backoff after network wait (fresh start)
            backoff = initial_backoff
            retry_count = 0
            continue
        except retryable_exceptions as e:
            # Other retryable error - use exponential backoff
            retry_count += 1

            if retry_count > max_retries:
                logger.error(f"All {max_retries} retries failed: {e}")
                raise

            logger.warning(
                f"Attempt {retry_count}/{max_retries + 1} failed: {e}. "
                f"Retrying in {backoff:.1f}s..."
            )
            time.sleep(backoff)
            backoff = min(backoff * backoff_multiplier, max_backoff)
