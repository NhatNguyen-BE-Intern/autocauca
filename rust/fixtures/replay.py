"""Runs the real binary entrypoint with deterministic CDP replay, without Chrome."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/"target"/"release"/"nomstead-rust.exe"
cases = [
    (["--check","--fixture","fixtures/check.json"], 0, "energy"),
    (["--check","--fixture","fixtures/wrong-origin.json"], 1, "Wrong game origin"),
    (["--check","--fixture","fixtures/cdp-error.json"], 1, "fixture disconnect"),
    (["--run","--casts","0"], 1, "1..1000"),
    (["--run","--lake","41"], 1, "1..40"),
]
if not BINARY.is_file():
    raise SystemExit(f"Build the binary first: {BINARY}")
for args, expected, text in cases:
    result=subprocess.run([str(BINARY),*args],cwd=ROOT,capture_output=True,text=True,timeout=15)
    output=result.stdout+result.stderr
    assert result.returncode==expected,(args,result.returncode,output)
    assert text in output,(args,output)
    print("PASS",*args)
