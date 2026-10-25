"""Bounded derived-byte cache; never writes to source datasets.

Content keys belong to callers and must include dataset/rendering revisions.
Disk failure is an optimization failure: compute and return the real result.
"""
import copy, hashlib, json, os, threading, time, uuid
from collections import OrderedDict
from concurrent.futures import Future
from functools import lru_cache
from pathlib import Path

HEADER=b'SOFIA_TILE_CACHE_1\x00'


def file_signature(path):
    # Resolving every directory/symlink on every Windows request is expensive.
    # Stat the supplied path on every call (therefore following its current
    # target), but normalize its absolute name without extra filesystem walks.
    path=Path(os.path.abspath(os.fspath(path)));s=path.stat()
    return (os.path.normcase(str(path)),s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino)


@lru_cache(maxsize=128)
def _json_document(signature):
    return json.loads(Path(signature[0]).read_text(encoding='utf-8'))


def read_json_cached(path):
    # API adapters may add fields; no caller may mutate the shared parsed document.
    return copy.deepcopy(_json_document(file_signature(path)))


class ByteTileCache:
    def __init__(self,directory,max_bytes=256*1024*1024,max_files=4096,memory_bytes=32*1024*1024):
        self.directory=Path(directory);self.max_bytes=max_bytes;self.max_files=max_files
        self.memory_bytes=memory_bytes;self._memory=OrderedDict();self._memory_size=0
        self._lock=threading.RLock();self._inflight={};self._disk={};self._disk_size=0
        self._stats={k:0 for k in ['memory_hits','disk_hits','renders','coalesced','corrupt','write_failures']}
        self.disk_enabled=True
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            for p in self.directory.glob('*.tile'):
                s=p.stat();self._disk[p.stem]=(s.st_size,s.st_mtime);self._disk_size+=s.st_size
            self._prune()
        except OSError:self.disk_enabled=False

    @property
    def stats(self):
        with self._lock:return {**self._stats,'inflight':len(self._inflight),'memory_entries':len(self._memory),'disk_entries':len(self._disk)}

    def _remember(self,key,value):
        if len(value)>self.memory_bytes:return
        with self._lock:
            old=self._memory.pop(key,None)
            if old is not None:self._memory_size-=len(old)
            self._memory[key]=value;self._memory_size+=len(value)
            while self._memory_size>self.memory_bytes or len(self._memory)>1024:
                _,old=self._memory.popitem(last=False);self._memory_size-=len(old)

    def _prune(self):
        # Incremental accounting makes ordinary writes O(1). Sorting/deleting is
        # needed only when a cap is crossed, then leaves10%room for later writes.
        if len(self._disk)<=self.max_files and self._disk_size<=self.max_bytes:return
        target_size=int(self.max_bytes*.9);target_count=int(self.max_files*.9)
        for key,(size,used) in sorted(self._disk.items(),key=lambda item:item[1][1]):
            try:(self.directory/(key+'.tile')).unlink(missing_ok=True)
            except OSError:self.disk_enabled=False;return
            self._disk.pop(key,None);self._disk_size-=size
            if len(self._disk)<=target_count and self._disk_size<=target_size:break

    def _read(self,key):
        if not self.disk_enabled:return None
        path=self.directory/(key+'.tile')
        try:data=path.read_bytes()
        except OSError:return None
        start=len(HEADER)+32
        if data[:len(HEADER)]!=HEADER or len(data)<start or hashlib.sha256(data[start:]).digest()!=data[len(HEADER):start]:
            with self._lock:self._stats['corrupt']+=1
            try:path.unlink(missing_ok=True)
            except OSError:pass
            return None
        with self._lock:
            old=self._disk.get(key)
            if old is None:self._disk_size+=len(data)
            self._disk[key]=(len(data),time.time());self._stats['disk_hits']+=1
        return data[start:]

    def _write(self,key,value):
        if not self.disk_enabled or len(value)+len(HEADER)+32>self.max_bytes:return
        temporary=self.directory/(key+'.'+uuid.uuid4().hex+'.tmp')
        data=HEADER+hashlib.sha256(value).digest()+value
        try:
            temporary.write_bytes(data);os.replace(temporary,self.directory/(key+'.tile'))
            with self._lock:
                old=self._disk.get(key)
                if old is not None:self._disk_size-=old[0]
                self._disk[key]=(len(data),time.time());self._disk_size+=len(data);self._prune()
        except OSError:
            with self._lock:self._stats['write_failures']+=1
        finally:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass

    def get_or_render(self,key,producer):
        key=hashlib.sha256(json.dumps(key,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        with self._lock:
            if key in self._memory:
                self._stats['memory_hits']+=1;self._memory.move_to_end(key);return self._memory[key]
            future=self._inflight.get(key)
            if future is None:future=Future();self._inflight[key]=future;owner=True
            else:self._stats['coalesced']+=1;owner=False
        if not owner:return future.result()
        try:
            value=self._read(key)
            if value is None:
                with self._lock:self._stats['renders']+=1
                value=producer()
                if not isinstance(value,bytes):raise TypeError('Tile producer must return bytes')
                self._write(key,value)
            self._remember(key,value);future.set_result(value);return value
        except BaseException as error:future.set_exception(error);raise
        finally:
            with self._lock:self._inflight.pop(key,None)


@lru_cache(maxsize=8)
def get_tile_cache(directory):
    """Share the same PNG/MVT byte budget when callers use the same directory."""
    return ByteTileCache(Path(directory))
