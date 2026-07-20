from __future__ import annotations

import sys


def main() -> int:
    failed = False
    print("[probe] python:", sys.version)
    try:
        import torch

        print("[probe] torch:", torch.__version__)
        print("[probe] cuda_available:", torch.cuda.is_available())
        if torch.cuda.is_available():
            print("[probe] cuda_device:", torch.cuda.get_device_name(0))
    except Exception as exc:
        failed = True
        print("[probe] torch import failed:", repr(exc))

    try:
        import soundfile

        _ = soundfile
        print("[probe] soundfile: OK")
    except Exception as exc:
        failed = True
        print("[probe] soundfile import failed:", repr(exc))

    try:
        import omnivoice

        print("[probe] omnivoice module:", getattr(omnivoice, "__file__", "<unknown>"))
    except Exception as exc:
        failed = True
        print("[probe] omnivoice import failed:", repr(exc))

    if failed:
        print("[probe] FAILED: one or more required imports are unavailable")
        return 1
    print("[probe] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
