"""
自動偵測可用硬體，回傳最佳推理裝置。

回傳範例：
{
  "platform": "windows",
  "cpu": "Intel64 Family 6 Model 158 Stepping 10",
  "gpu": "NVIDIA GeForce RTX 3080",
  "mlx_available": False,
  "cuda_available": True,
  "recommended_device": "cuda",
  "display_name": "NVIDIA GPU (NVIDIA GeForce RTX 3080)",
  "badge_color": "green"
}
"""
import platform
import subprocess
from typing import TypedDict

class HardwareInfo(TypedDict):
    platform: str
    cpu: str
    gpu: str | None
    mlx_available: bool
    cuda_available: bool
    recommended_device: str  # "mlx" | "cuda" | "cpu"
    display_name: str
    badge_color: str          # "green" | "blue" | "gray"

def detect_hardware() -> HardwareInfo:
    """
    偵測當前環境可用硬體並回傳適當的推論裝置。
    """
    sys_platform = platform.system().lower()
    cpu_name = _get_cpu_name()

    # 優先順序：MLX > CUDA > CPU
    if sys_platform == "darwin" and _check_mlx():
        return HardwareInfo(
            platform=sys_platform, cpu=cpu_name, gpu=None,
            mlx_available=True, cuda_available=False,
            recommended_device="mlx",
            display_name=f"Apple MLX ({cpu_name})",
            badge_color="green"
        )

    cuda_gpu = _check_cuda()
    if cuda_gpu:
        return HardwareInfo(
            platform=sys_platform, cpu=cpu_name, gpu=cuda_gpu,
            mlx_available=False, cuda_available=True,
            recommended_device="cuda",
            display_name=f"NVIDIA GPU ({cuda_gpu})",
            badge_color="green"
        )

    return HardwareInfo(
        platform=sys_platform, cpu=cpu_name, gpu=None,
        mlx_available=False, cuda_available=False,
        recommended_device="cpu",
        display_name=f"CPU ({cpu_name})",
        badge_color="blue"
    )

def _check_mlx() -> bool:
    """
    檢查 Apple MLX 模組是否可用。
    """
    try:
        import mlx.core as mx
        mx.array([1])  # 確認 Metal 可用
        return True
    except Exception:
        return False

def _check_cuda() -> str | None:
    """
    檢查 NVIDIA CUDA 是否可用。
    """
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return None

def _get_cpu_name() -> str:
    """
    取得系統 CPU 的區辨名稱。
    """
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True
            )
            return result.stdout.strip()
        # Linux/Windows：讀取 /proc/cpuinfo 或 wmic
        return platform.processor() or "Unknown CPU"
    except Exception:
        return "Unknown CPU"
