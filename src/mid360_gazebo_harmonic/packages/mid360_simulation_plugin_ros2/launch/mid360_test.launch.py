import glob
import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch.actions import LogInfo


def _find_iomp5():
    """Find Intel's OpenMP runtime without changing ROS's library search path."""
    requested = os.environ.get("MID360_IOMP5_PATH")
    candidates = [requested] if requested else []
    candidates += [
        "/opt/intel/oneapi/compiler/latest/linux/lib/libiomp5.so",
        "/opt/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin/libiomp5.so",
    ]
    candidates += glob.glob(
        "/opt/intel/oneapi/compiler/*/linux/lib/libiomp5.so")
    candidates += glob.glob(
        "/opt/intel/oneapi/compiler/*/linux/compiler/lib/intel64_lin/libiomp5.so")
    candidates += glob.glob(
        "/usr/local/MATLAB/*/sys/os/glnxa64/libiomp5.so")

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def generate_launch_description():
    share = Path(get_package_share_directory("mid360_simulation_plugin_ros2"))
    world = share / "worlds" / "mid360_test.sdf"
    iomp5 = _find_iomp5()
    env = {}
    actions = []

    if iomp5:
        # rmagine/Embree's oneTBB may load libiomp5 at runtime.  Preloading it
        # for Gazebo avoids adding MATLAB's incompatible libstdc++ to ros2.
        old_preload = os.environ.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = os.pathsep.join(
            value for value in (iomp5, old_preload) if value)
        actions.append(LogInfo(msg=f"[mid360] Using OpenMP runtime: {iomp5}"))
    else:
        actions.append(LogInfo(
            msg=(
                "[mid360] libiomp5.so was not found. Embree may fail to load; "
                "set MID360_IOMP5_PATH to its absolute path or install Intel "
                "OpenMP runtime."
            )))

    actions.append(ExecuteProcess(
        cmd=["gz", "sim", "-r", str(world)],
        additional_env=env,
        output="screen"))
    return LaunchDescription(actions)
