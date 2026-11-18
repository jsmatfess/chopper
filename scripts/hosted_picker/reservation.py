import os
from pathlib import Path

class Reservation:
    """The original acquire-to-close CRT descriptor; no lock-free probe or stamp authority."""
    def __init__(self, windows):
        import msvcrt
        self.windows, self.crt = windows, msvcrt
        self.path = Path.home()/'.chopper'/'local-ci.lock'
        if str(self.path) != EXPECTED_LOCK['path']: raise OSError('Unexpected original lock path')
        self.owner = windows.process_identity(os.getpid())
        # Same durable file/range/CRT acquisition as maintained local-ci.py.
        # Never truncate, replace, unlink, unlock/relock, or acquire a second reservation.
        # This finite adapter requires the original R4 file: no creation or replacement.
        stamp = self.path.stat()
        if [stamp.st_dev,stamp.st_ino] != EXPECTED_LOCK['identity']:
            raise OSError('Original R4 lock absent/changed')
        fd = os.open(self.path, os.O_RDWR)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            original = os.fstat(fd)
            if not os.path.samestat(original, self.path.stat()): raise OSError('Original lock replaced')
            if [original.st_dev, original.st_ino] != EXPECTED_LOCK['identity']:
                raise OSError('R4 original lock file identity changed')
        except BaseException:
            try: os.close(fd)
            except BaseException: retain_unknown()
            raise
        self.fd, self.original, self.handle = fd, original, msvcrt.get_osfhandle(fd)
    def check(self):
        # The descriptor is private to this finite adapter; no code receives it to close/unlock.
        # Successful original LK_NBLCK + unbroken descriptor lifetime is ownership provenance.
        if self.windows.process_identity(os.getpid()) != self.owner:
            raise OSError('Original PID/creation identity lost')
        if self.crt.get_osfhandle(self.fd) != self.handle or os.get_inheritable(self.fd):
            raise OSError('Original CRT descriptor/native handle lost')
        if not os.path.samestat(self.original, os.fstat(self.fd)) or not os.path.samestat(self.original, self.path.stat()):
            raise OSError('Original lock file identity lost')
        if os.lseek(self.fd, 0, os.SEEK_CUR) != 0: raise OSError('Original locked range offset changed')
    def receipt(self):
        self.check()
        return dict(descriptor=self.fd, native_handle=self.handle, owner=self.owner,
                    identity=[self.original.st_dev,self.original.st_ino], range=[0,1],
                    acquisition='msvcrt.LK_NBLCK on this original retained descriptor')

def retain_unknown():
    # No product exists during constructor failure; leave OS cleanup to process exit.
    raise OSError('ambiguous original descriptor close before product launch')
