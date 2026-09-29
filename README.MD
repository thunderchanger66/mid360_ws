# mid360_ws 使用说明

本工作空间提供 Gazebo Harmonic 中的 Livox MID-360 仿真，以及与 PX4
SITL 的联动启动。当前机器使用 ROS 2 Jazzy、Gazebo Sim 8 和 PX4
`gz_x500_gimbal_mid360` 模型。

## 1. 环境要求

- Ubuntu 图形桌面或可用的 X11/Xwayland 会话
- ROS 2 Jazzy
- Gazebo Harmonic（`gz sim --version` 应显示 8.x）
- 已编译的 PX4 SITL：`~/PX4-Autopilot/build/px4_sitl_default`
- `libassimp-dev`、`libtbb-dev`、`python3-colcon-common-extensions`

先加载 ROS 2：

```bash
source /opt/ros/jazzy/setup.bash
```

如果安装了 `livox_ros_driver2`，在加载工作空间前加载它的 overlay；没有
该包时仍可以发布 `sensor_msgs/msg/PointCloud2`。

## 2. 编译工作空间

```bash
cd /home/thunder/study/mid360_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
```

修改 C++、launch、模型或 world 后，重新编译受影响的包；使用
`--symlink-install` 时，Python launch 和 SDF 修改通常会直接生效。

## 3. 独立启动 MID-360 测试世界

```bash
cd /home/thunder/study/mid360_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch mid360_simulation_plugin_ros2 mid360_test.launch.py
```

检查输出话题：

```bash
ros2 topic type /livox/lidar
ros2 topic type /livox/imu
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
```

默认输出为：

- `/livox/lidar`: `sensor_msgs/msg/PointCloud2`
- `/livox/imu`: `sensor_msgs/msg/Imu`

参数位于：

```text
src/mid360_gazebo_harmonic/packages/mid360_simulation_plugin_ros2/models/mid360/model.sdf
```

`<publish_pointcloud_type>2</publish_pointcloud_type>` 发布
`PointCloud2`；设置为 `3` 时，如果已安装 `livox_ros_driver2`，可发布
`livox_ros_driver2/msg/CustomMsg`。

## 4. PX4 SITL 联动

### 4.1 检查 PX4

默认启动文件假设 PX4 位于：

```text
/home/thunder/PX4-Autopilot
```

如果路径不同，编辑：

```text
src/mid360_gazebo_harmonic/launch/mid360_posix_sitl.launch.py
```

修改顶部的 `PX4_DIR`。

确认 PX4 已编译：

```bash
test -x /home/thunder/PX4-Autopilot/build/px4_sitl_default/bin/px4 && echo OK
test -d /home/thunder/PX4-Autopilot/build/px4_sitl_default/rootfs && echo OK
```

### 4.2 同步启动文件

PX4 使用的是它自己的 `launch` 目录中的副本。工作区内修改后，需要重新
同步：

```bash
cp /home/thunder/study/mid360_ws/src/mid360_gazebo_harmonic/launch/mid360_posix_sitl.launch.py \
  /home/thunder/PX4-Autopilot/launch/mid360_posix_sitl.launch.py
```

确认实际运行的文件配置：

```bash
grep -n 'DEFAULT_GUI\|USE_NVIDIA_GPU' \
  /home/thunder/PX4-Autopilot/launch/mid360_posix_sitl.launch.py
```

当前机器应为：

```text
DEFAULT_GUI = True
USE_NVIDIA_GPU = False
```

### 4.3 启动 PX4 + Gazebo + MID-360

```bash
source /opt/ros/jazzy/setup.bash
source /home/thunder/study/mid360_ws/install/setup.bash
cd /home/thunder/PX4-Autopilot/launch
ros2 launch ./mid360_posix_sitl.launch.py
```

常用参数：

```bash
# 无界面后台运行，适合 SSH 或服务器
ros2 launch ./mid360_posix_sitl.launch.py gui:=false

# 修改出生位置
ros2 launch ./mid360_posix_sitl.launch.py x:=2 y:=3 z:=0.3

# 使用指定 world
ros2 launch ./mid360_posix_sitl.launch.py world:=/绝对路径/scene.sdf
```

启动成功的关键日志是：

```text
[init] Gazebo world is ready
[init] Spawning Gazebo model
[px4] Startup script returned successfully
```

## 5. 本次遇到的问题和根因

### 5.1 `libiomp5.so` 找不到

错误：

```text
Error while loading the library ... librmagine_embree_map_system.so:
libiomp5.so: cannot open shared object file
```

原因是 Embree/oneTBB 在运行时需要 Intel OpenMP 运行库。启动文件会自动
查找 Intel oneAPI 或 MATLAB 中的 `libiomp5.so`，并且只预加载给 Gazebo，
不会把 MATLAB 的整个库目录注入 ROS 2。

如果仍找不到，指定单个文件：

```bash
export MID360_IOMP5_PATH=/绝对路径/libiomp5.so
```

不要这样设置：

```bash
export LD_LIBRARY_PATH=/usr/local/MATLAB/R2025a/sys/os/glnxa64:$LD_LIBRARY_PATH
```

这会让 MATLAB 的 `libstdc++.so.6` 覆盖 ROS 2 的版本，进而导致
`rclpy` 或 `ros2` 无法加载。

### 5.2 `Failed to create OpenGL context`

错误：

```text
[GUI] [Err] [Application.cc:912] Failed to create OpenGL context
```

当前机器有 Intel Iris Xe 和 NVIDIA RTX 2050，但 `nvidia-smi` 无法连接
NVIDIA 驱动。Intel/Mesa OpenGL 是正常的，`glxinfo -B` 能显示硬件加速。
因此不能在启动文件中强制：

```text
__NV_PRIME_RENDER_OFFLOAD=1
__GLX_VENDOR_LIBRARY_NAME=nvidia
```

启动文件当前使用 `USE_NVIDIA_GPU = False`，让 Gazebo 使用 Intel/Mesa。
此外当前桌面是 Wayland，Gazebo GUI 会显式使用 Xwayland：

```text
QT_QPA_PLATFORM=xcb
```

这解决了 Qt 默认 Wayland OpenGL 上下文创建失败的问题。

如果 `gui:=true` 仍失败，先检查：

```bash
echo "$DISPLAY $WAYLAND_DISPLAY $XDG_SESSION_TYPE"
glxinfo -B | grep -E 'direct rendering|OpenGL vendor|OpenGL renderer|OpenGL version'
nvidia-smi
```

只有在 `nvidia-smi` 正常工作、且确认要使用独立显卡时，才将
`USE_NVIDIA_GPU` 改为 `True`。

### 5.3 PX4 一直显示 `Waiting for Gazebo world`

这通常不是 PX4 本身的错误，而是 Gazebo 进程已经因为上面的 GUI/OpenGL
错误退出。先查找 Gazebo 的第一个 `[Err]`，不要只看 PX4 最后一行。

如果不需要界面，直接使用：

```bash
ros2 launch ./mid360_posix_sitl.launch.py gui:=false
```

### 5.4 其他常见警告

```text
XML Element[gz_frame_id] ... not defined in SDF
```

这是 PX4 模型的 SDF 兼容性警告，不会阻止仿真启动。

```text
Preflight Fail: system power unavailable
Preflight Fail: No connection to the GCS
```

这是没有接入真实电源/GCS 时的 PX4 起飞前检查提示，不代表 Gazebo 启动失败。

## 6. 进程清理

停止 launch 后如果仍有测试进程占用端口，先确认再清理：

```bash
pgrep -af 'gz sim|px4_sitl_default/bin/px4'
```

正常情况下使用 `Ctrl+C` 退出即可，不要随意删除 PX4 的构建目录或日志。
