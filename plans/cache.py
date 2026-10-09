"""
Caching strategy for GET /api/plans/
------------------------------------
We use a *versioned* key: `plans:list:v<version>:<query-string>`.

* Every page / filter combination is cached separately under the current version.
* To invalidate, we just bump the version number (one atomic INCR in Redis).
  All old keys become unreachable and expire on their own after the TTL.
* This avoids scanning/deleting keys by pattern (slow, not atomic) and works
  no matter how many pages are cached.
"""
from django.conf import settings
from django.core.cache import cache

VERSION_KEY = "plans:list:version"


def _version():
    version = cache.get(VERSION_KEY)
    if version is None:
        cache.add(VERSION_KEY, 1, timeout=None)
        version = cache.get(VERSION_KEY) or 1
    return version


def list_cache_key(query_string: str) -> str:
    return f"plans:list:v{_version()}:{query_string or '-'}"


def get_cached_list(query_string):
    return cache.get(list_cache_key(query_string))


def set_cached_list(query_string, data):
    cache.set(list_cache_key(query_string), data, timeout=settings.PLAN_LIST_CACHE_TTL)


def invalidate_plan_list_cache():
    try:
        cache.incr(VERSION_KEY)
    except ValueError:  # key missing -> set it
        cache.set(VERSION_KEY, 2, timeout=None)
