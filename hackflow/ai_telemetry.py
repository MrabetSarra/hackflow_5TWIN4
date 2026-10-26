"""Privacy-safe timing logs for synchronous AI feature calls."""
import functools
import logging
import time

logger = logging.getLogger('hackflow.ai')


def timed_ai(feature):
    """Log elapsed time and outcome without recording inputs, outputs, or secrets."""
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            outcome = 'success'
            error_type = ''
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                outcome = 'failure'
                error_type = type(exc).__name__
                raise
            finally:
                duration_ms = round((time.perf_counter() - started) * 1000)
                logger.info(
                    'ai_call feature=%s duration_ms=%d outcome=%s error_type=%s',
                    feature, duration_ms, outcome, error_type,
                )
        return wrapped
    return decorate
