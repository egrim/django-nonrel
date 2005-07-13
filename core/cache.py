"""
Caching framework.

This module defines set of cache backends that all conform to a simple API.
In a nutshell, a cache is a set of values -- which can be any object that 
may be pickled -- identified by string keys.  For the complete API, see 
the abstract Cache object, below.

Client code should not access a cache backend directly; instead
it should use the get_cache() function.  This function will look at
settings.CACHE_BACKEND and use that to create and load a cache object.

The CACHE_BACKEND setting is a quasi-URI; examples are:

    memcached://127.0.0.1:11211/    A memcached backend; the server is running 
                                    on localhost port 11211.
                                    
    pgsql://tablename/              A pgsql backend (the pgsql backend uses 
                                    the same database/username as the rest of
                                    the CMS, so only a table name is needed.)
                                    
    file:///var/tmp/django.cache/      A file-based cache at /var/tmp/django.cache
    
    simple:///                      A simple single-process memory cache; you
                                    probably don't want to use this except for
                                    testing. Note that this cache backend is 
                                    NOT threadsafe!

All caches may take arguments; these are given in query-string style.  Valid
arguments are:

    timeout         
        Default timeout, in seconds, to use for the cache.  Defaults
        to 5 minutes (300 seconds).
                
    max_entries     
        For the simple, file, and database backends, the maximum number of
        entries allowed in the cache before it is cleaned.  Defaults to
        300.
                
    cull_percentage 
        The percentage of entries that are culled when max_entries is reached. 
        The actual percentage is 1/cull_percentage, so set cull_percentage=3 to
        cull 1/3 of the entries when max_entries is reached.
        
        A value of 0 for cull_percentage means that the entire cache will be
        dumped when max_entries is reached.  This makes culling *much* faster
        at the expense of more cache misses.
                
For example:

    memcached://127.0.0.1:11211/?timeout=60
    pgsql://tablename/?timeout=120&max_entries=500&cull_percentage=4
    
Invalid arguments are silently ignored, as are invalid values of known 
arguments.
    
So far, only the memcached and simple backend have been implemented; backends
using postgres, and file-system storage are planned.
"""

##############
# Exceptions #
##############

class InvalidCacheBackendError(Exception):
    pass

################################
# Abstract base implementation #
################################

class _Cache:

    def __init__(self, params):
        timeout = params.get('timeout', 300)
        try:
            timeout = int(timeout)
        except (ValueError, TypeError):
            timeout = 300
        self.default_timeout = timeout
        
    def get(self, key, default=None):
        '''
        Fetch a given key from the cache.  If the key does not exist, return
        default, which itself defaults to None.
        '''
        raise NotImplementedError
 
    def set(self, key, value, timeout=None):
        '''
        Set a value in the cache.  If timeout is given, that timeout will be
        used for the key; otherwise the default cache timeout will be used.
        '''
        raise NotImplementedError

    def delete(self, key):
        '''
        Delete a key from the cache, failing silently.
        '''
        raise NotImplementedError

    def get_many(self, keys):
        '''
        Fetch a bunch of keys from the cache.  For certain backends (memcached,
        pgsql) this can be *much* faster when fetching multiple values.
        
        Returns a dict mapping each key in keys to its value.  If the given
        key is missing, it will be missing from the response dict.
        '''
        d = {}
        for k in keys:
            val = self.get(k)
            if val is not None:
                d[k] = val
        return d
 
    def has_key(self, key):
        '''
        Returns True if the key is in the cache and has not expired.
        '''
        return self.get(key) is not None

###########################
# memcached cache backend #
###########################

try:
    import memcache
except ImportError:
    _MemcachedCache = None
else:
    class _MemcachedCache(_Cache):
        """Memcached cache backend."""
        
        def __init__(self, server, params):
            _Cache.__init__(self, params)
            self._cache = memcache.Client([server])
            
        def get(self, key, default=None):
            val = self._cache.get(key)
            if val is None:
                return default
            else:
                return val
                    
        def set(self, key, value, timeout=0):
            self._cache.set(key, value, timeout)
            
        def delete(self, key):
            self._cache.delete(key)
                
        def get_many(self, keys):
            return self._cache.get_multi(keys)

##################################
# Single-process in-memory cache #
##################################

import time
    
class _SimpleCache(_Cache):
    """Simple single-process in-memory cache"""
    
    def __init__(self, host, params):
        _Cache.__init__(self, params)
        self._cache = {}
        self._expire_info = {}
        
        max_entries = params.get('max_entries', 300)
        try:
            self._max_entries = int(max_entries)
        except (ValueError, TypeError):
            self._max_entries = 300
            
        cull_frequency = params.get('cull_frequency', 3)
        try:
            self._cull_frequency = int(cull_frequency)
        except (ValueError, TypeError):
            self._cull_frequency = 3
        
    def get(self, key, default=None):
        now = time.time()
        exp = self._expire_info.get(key, now)
        if exp is not None and exp < now:
            del self._cache[key]
            del self._expire_info[key]
            return default
        else:
            return self._cache.get(key, default)
        
    def set(self, key, value, timeout=None):
        if len(self._cache) >= self._max_entries:
            self._cull()
        if timeout is None:
            timeout = self.default_timeout
        self._cache[key] = value
        self._expire_info[key] = time.time() + timeout
        
    def delete(self, key):
        try:
            del self._cache[key]
        except KeyError:
            pass
        try:
            del self._expire_info[key]
        except KeyError:
            pass
            
    def has_key(self, key):
        return self._cache.has_key(key)

    def _cull(self):
        if self._cull_frequency == 0:
            self._cache.clear()
            self._expire_info.clear()
        else:
            doomed = [k for (i, k) in enumerate(self._cache) if i % self._cull_frequency == 0]
            for k in doomed:
                self.delete(k)

##########################################        
# Read settings and load a cache backend #
##########################################

from cgi import parse_qsl

_BACKENDS = {
    'memcached' : _MemcachedCache,
    'simple'    : _SimpleCache,
}

def get_cache(backend_uri):
    if backend_uri.find(':') == -1:
        raise InvalidCacheBackendError("Backend URI must start with scheme://")
    scheme, rest = backend_uri.split(':', 1)
    if not rest.startswith('//'):
        raise InvalidCacheBackendError("Backend URI must start with scheme://")
    if scheme not in _BACKENDS.keys():
        raise InvalidCacheBackendError("%r is not a valid cache backend" % scheme)
        
    host = rest[2:]
    qpos = rest.find('?')
    if qpos != -1:
        params = dict(parse_qsl(rest[qpos+1:]))
        host = rest[:qpos]
    else:
        params = {}
    if host.endswith('/'):
        host = host[:-1]

    return _BACKENDS[scheme](host, params)

from django.conf.settings import CACHE_BACKEND
cache = get_cache(CACHE_BACKEND)
