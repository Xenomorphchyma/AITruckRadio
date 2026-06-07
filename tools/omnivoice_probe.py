from __future__ import annotations

import sys

print('[probe] python:', sys.version)
try:
    import torch
    print('[probe] torch:', torch.__version__)
    print('[probe] cuda_available:', torch.cuda.is_available())
    if torch.cuda.is_available():
        print('[probe] cuda_device:', torch.cuda.get_device_name(0))
except Exception as e:
    print('[probe] torch import failed:', repr(e))

try:
    import soundfile
    _ = soundfile
    print('[probe] soundfile: OK')
except Exception as e:
    print('[probe] soundfile import failed:', repr(e))

try:
    import omnivoice
    print('[probe] omnivoice module:', getattr(omnivoice, '__file__', '<unknown>'))
except Exception as e:
    print('[probe] omnivoice import failed:', repr(e))
