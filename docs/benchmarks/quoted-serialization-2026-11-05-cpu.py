"""Windows completed-process CPU control; not a function-level profiler.

GetProcessTimes returns summed kernel/user time for all process threads:
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
"""
import ctypes
from ctypes import wintypes
import subprocess,time,json,pathlib,sys,os
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
get_times=kernel.GetProcessTimes
get_times.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
get_times.restype=wintypes.BOOL

def completed_run(argv,env):
    started=time.perf_counter()
    process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    stdout,stderr=process.communicate()
    wall=time.perf_counter()-started
    creation,exit_time,kernel_time,user_time=[wintypes.FILETIME() for _ in range(4)]
    ok=get_times(wintypes.HANDLE(int(process._handle)),*(ctypes.byref(t) for t in [creation,exit_time,kernel_time,user_time]))
    seconds=lambda t:((t.dwHighDateTime<<32)|t.dwLowDateTime)/10_000_000
    cpu={'ok':bool(ok),'source':'Win32 GetProcessTimes after completed wait; all child threads; query outside wall clock'}
    if ok:
        cpu.update(user_seconds=seconds(user_time),kernel_seconds=seconds(kernel_time),total_seconds=seconds(user_time)+seconds(kernel_time))
    else:
        cpu['winerror']=ctypes.get_last_error()
    return subprocess.CompletedProcess(argv,process.returncode,stdout,stderr),wall,cpu

if __name__=='__main__':
    result,wall,cpu=completed_run([sys.executable,'-c','print(sum(i*i for i in range(1000000)))'],os.environ.copy())
    record={'type':'cpu_measurement_self_control','returncode':result.returncode,'stdout':result.stdout.decode(),'stderr':result.stderr.decode(),'wall_seconds':wall,'cpu':cpu,'scope':'Tiny Python child only, not a Chopper job or performance sample'}
    (pathlib.Path(sys.argv[1])/'cpu-control.json').write_text(json.dumps(record,indent=2)+'\n')
    assert result.returncode==0 and cpu['ok'] and cpu['total_seconds']>0,record
    print('Completed-child CPU measurement control passed')
