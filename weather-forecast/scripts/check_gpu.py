"""Phase 0 verification: confirm the weather env can see the RTX 4050."""
import sys

print(f"Python: {sys.version}")

try:
    import onnxruntime as ort
    providers = ort.get_available_providers()
    print(f"ONNX Runtime {ort.__version__} providers: {providers}")
    print("ONNX GPU:", "OK" if "CUDAExecutionProvider" in providers else "CPU ONLY")
except ImportError:
    print("onnxruntime not installed")

try:
    import torch
    print(f"PyTorch {torch.__version__} CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  Device: {torch.cuda.get_device_name(0)}")
        free, total = torch.cuda.mem_get_info()
        print(f"  VRAM: {free / 1e9:.1f} GB free / {total / 1e9:.1f} GB total")
except ImportError:
    print("torch not installed")

try:
    import eccodes
    print(f"ecCodes: {eccodes.codes_get_api_version()}")
except Exception as e:
    print(f"eccodes problem: {e}")

try:
    import cfgrib, xarray, cdsapi  # noqa: F401
    print("cfgrib / xarray / cdsapi: OK")
except ImportError as e:
    print(f"missing: {e}")
