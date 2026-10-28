"""After the active local batch ends, refresh analyses and the review package.

This queue never starts or retries a model request. It only waits for one known
process and then runs stored-result analysis. It is not a scheduled automation.
"""
from pathlib import Path
import argparse,ctypes,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def run(name):
    print('Post-processing:',name,flush=True)
    subprocess.run([sys.executable,str(ROOT/'scripts'/name)],check=True,cwd=ROOT.parent)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pid',type=int,required=True);a=ap.parse_args()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x00100000,False,a.pid)
    if handle:
        try:
            while kernel.WaitForSingleObject(handle,10000)==258:pass
        finally:kernel.CloseHandle(handle)
    for name in ('score_new_models.py','selection_arrival_analysis.py','analyze_generated_structure.py','summarize_final_generation.py'):
        run(name)
    state=json.loads((ROOT/'results/generation/summary.json').read_text(encoding='utf-8'))
    if state['completed']==state['scheduled']==96:
        for name in ('integrate_final.py','compile_preview.py','write_handoff.py'):run(name)
        print('Complete batch integrated; ready for final page and archive validation.',flush=True)
    else:
        run('write_handoff.py')
        print('Batch stopped before completion; pending attempts retained.',state['completed'],flush=True)
if __name__=='__main__':main()
