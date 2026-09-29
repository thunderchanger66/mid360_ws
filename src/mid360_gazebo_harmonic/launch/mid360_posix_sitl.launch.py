import os
import glob
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration


# ======================== 用户配置区 ========================
# PX4-Autopilot 根目录。PX4 不在主目录时，在这里修改。
PX4_DIR = Path.home() / "PX4-Autopilot"

# MID-360 模型目录。默认自动定位安装后的 models，也可改为绝对路径。
MID360_MODELS_PATH = (
    Path(get_package_share_directory("mid360_simulation_plugin_ros2")) / "models"
)

# 默认仿真世界。可改为自己 world 文件的绝对路径。
DEFAULT_WORLD = PX4_DIR / "Tools" / "simulation" / "gz" / "worlds" / "default.sdf"

# PX4 模型名称和自启动配置。4019 是 PX4 自带的 X500 云台配置。
PX4_MODEL = "gz_x500_gimbal_mid360"
PX4_AUTOSTART_ID = "4019"

# 飞机默认出生坐标，单位为米。
DEFAULT_X = "0"
DEFAULT_Y = "0"
DEFAULT_Z = "0.3"

# True：显示 Gazebo 界面；False：仅运行无界面仿真。
# 当前机器的 Intel/Mesa OpenGL 可用，默认显示 Gazebo 界面。
DEFAULT_GUI = True

# 只有 NVIDIA 驱动可用时才设为 True。当前机器使用 Intel/Mesa 渲染。
USE_NVIDIA_GPU = False
# ============================================================


def _prepend_unique(current, entries):
    paths = []
    for entry in [*entries, *current.split(":")]:
        if entry and entry not in paths:
            paths.append(entry)
    return ":".join(paths)


def _find_iomp5():
    """Find Intel's OpenMP runtime without changing PX4's library path."""
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


def _prepare_server_config(px4_dir, world):
    world_text = world.read_text(encoding="utf-8", errors="ignore")
    if "RmagineEmbreeMapSystem" in world_text:
        return None

    source = px4_dir / "Tools" / "simulation" / "gz" / "server.config"
    if not source.exists():
        raise RuntimeError(f"找不到 PX4 Gazebo 配置: {source}")

    plugin = """
    <plugin entity_name="*" entity_type="world"
            filename="librmagine_embree_map_system.so"
            name="rmagine_gazebo_plugins::RmagineEmbreeMapSystem">
      <update>
        <rate_limit>30</rate_limit>
        <delta_trans>0.001</delta_trans>
        <delta_rot>0.001</delta_rot>
      </update>
    </plugin>"""
    # Ubuntu 22.04 的 GStreamer 1.20 与新款 NVIDIA GPU 的 NVENC preset
    # 不兼容，会导致编码管线失败并持续占用内存。保留视频流，改用稳定的
    # x264 软件编码；云台、相机传感器和其余 PX4 系统保持不变。
    source_text = source.read_text(encoding="utf-8").replace(
        '    <plugin entity_name="*" entity_type="world" filename="libGstCameraSystem.so" name="custom::GstCameraSystem"/>\n',
        '    <plugin entity_name="*" entity_type="world" filename="libGstCameraSystem.so" name="custom::GstCameraSystem">\n'
        '      <useCuda>false</useCuda>\n'
        '    </plugin>\n',
    )
    config = source_text.replace(
        "  </plugins>", f"{plugin}\n  </plugins>"
    )
    target = Path("/tmp") / f"mid360_gz_server_{os.getuid()}.config"
    target.write_text(config, encoding="utf-8")
    return target


def _start(context):
    px4_dir = PX4_DIR
    world = Path(LaunchConfiguration("world").perform(context)).expanduser()
    x = LaunchConfiguration("x").perform(context)
    y = LaunchConfiguration("y").perform(context)
    z = LaunchConfiguration("z").perform(context)
    gui = LaunchConfiguration("gui").perform(context).lower() in {
        "1", "true", "yes", "on"
    }

    model_root = MID360_MODELS_PATH
    px4_build = px4_dir / "build" / "px4_sitl_default"
    px4_binary = px4_build / "bin" / "px4"
    px4_rootfs = px4_build / "rootfs"
    px4_plugins = px4_build / "src" / "modules" / "simulation" / "gz_plugins"

    required = {
        "world 文件": world,
        "PX4 SITL": px4_binary,
        "PX4 rootfs": px4_rootfs,
        "X500 MID-360 模型": model_root / "x500_gimbal_mid360" / "model.sdf",
    }
    for description, path in required.items():
        if not path.exists():
            raise RuntimeError(f"找不到{description}: {path}")

    sim_env = os.environ.copy()
    sim_env["GZ_SIM_RESOURCE_PATH"] = _prepend_unique(
        sim_env.get("GZ_SIM_RESOURCE_PATH", ""),
        [
            str(model_root),
            str(px4_dir / "custom_gazebo" / "models"),
            str(px4_dir / "Tools" / "simulation" / "gz" / "models"),
        ],
    )
    sim_env["GZ_SIM_SYSTEM_PLUGIN_PATH"] = _prepend_unique(
        sim_env.get("GZ_SIM_SYSTEM_PLUGIN_PATH", ""),
        [str(px4_plugins)],
    )
    server_config = _prepare_server_config(px4_dir, world)
    if server_config is not None:
        sim_env["GZ_SIM_SERVER_CONFIG_PATH"] = str(server_config)

    gz_env = sim_env.copy()
    iomp5 = _find_iomp5()
    launch_messages = []
    if iomp5:
        # oneTBB used by rmagine/Embree may load libiomp5 at runtime.  Keep
        # this preload scoped to Gazebo so PX4 does not see MATLAB's libraries.
        gz_env["LD_PRELOAD"] = ":".join(
            value for value in (iomp5, gz_env.get("LD_PRELOAD", "")) if value)
        launch_messages.append(
            LogInfo(msg=f"[mid360] Using OpenMP runtime for Gazebo: {iomp5}"))
    else:
        launch_messages.append(LogInfo(
            msg=(
                "[mid360] libiomp5.so was not found. Embree may fail to load; "
                "set MID360_IOMP5_PATH to its absolute path or install Intel "
                "OpenMP runtime."
            )))
    # A headless Gazebo server does not create a GLX context.  Forcing the
    # NVIDIA GLX vendor in that mode can make gz-sim abort with GLXBadFBConfig.
    if USE_NVIDIA_GPU and gui:
        gz_env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        gz_env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
    else:
        # Gazebo's Qt5 GUI is more reliable through Xwayland than Qt's default
        # Wayland selection on this system.
        if gui:
            gz_env["QT_QPA_PLATFORM"] = "xcb"
        gz_env.pop("__NV_PRIME_RENDER_OFFLOAD", None)
        gz_env.pop("__GLX_VENDOR_LIBRARY_NAME", None)
    gz_cmd = ["gz", "sim", "-r"]
    if not gui:
        gz_cmd.append("-s")
    gz_cmd.append(str(world))

    px4_env = sim_env.copy()
    px4_env.update({
        "PX4_GZ_STANDALONE": "1",
        "PX4_SYS_AUTOSTART": PX4_AUTOSTART_ID,
        "PX4_SIM_MODEL": PX4_MODEL,
        "PX4_GZ_MODELS": str(model_root),
        "PX4_GZ_WORLDS": str(world.parent),
        "PX4_GZ_MODEL_POSE": f"{x},{y},{z}",
        "GZ_IP": "127.0.0.1",
    })

    return launch_messages + [
        ExecuteProcess(cmd=gz_cmd, env=gz_env, output="screen"),
        ExecuteProcess(
            cmd=[str(px4_binary)],
            cwd=str(px4_rootfs),
            env=px4_env,
            output="screen",
            emulate_tty=True,
        ),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("world", default_value=str(DEFAULT_WORLD)),
        DeclareLaunchArgument("x", default_value=DEFAULT_X),
        DeclareLaunchArgument("y", default_value=DEFAULT_Y),
        DeclareLaunchArgument("z", default_value=DEFAULT_Z),
        DeclareLaunchArgument("gui", default_value=str(DEFAULT_GUI).lower()),
        OpaqueFunction(function=_start),
    ])
