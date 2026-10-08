"""Single local owner. Never deletes another owner's lock or resets a request ledger."""
import fcntl,os
from pathlib import Path
class Lease:
    def __init__(self,path:Path):self.path=path;self.fd=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:os.close(fd);raise RuntimeError('another_owner_is_active')
        self.fd=fd;return self
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None
    def __enter__(self):return self.acquire()
    def __exit__(self,*args):self.close()
