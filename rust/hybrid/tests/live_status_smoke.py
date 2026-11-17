"""Manual bridge-only read-only smoke; never launches a worker."""

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


async def run() -> int:
    print('BRIDGE-ONLY READ-ONLY; WORKER NOT TESTED', flush=True)
    try:
        tab = await bridge.discover_tab()
    except bridge.CdpError:
        print('PENDING: discovery unavailable or trusted tab selection failed')
        return 1
    try:
        status = await bridge.read_status(tab)
    except bridge.CdpError:
        print('PENDING: read-only transport or status validation failed')
        return 1
    if status.energy is None:
        print('PENDING: energy absent; log in directly in the already-open Chrome')
        return 1
    parsed = urlsplit(status.url)
    print(f'origin=https://{parsed.hostname} viewport={status.width:g}x{status.height:g} dpr={status.dpr:g}')
    print('energy=present sequence_available=false sequence=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run()))
