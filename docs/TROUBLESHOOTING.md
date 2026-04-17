# Troubleshooting

## Docker / 런타임

### `missing command: docker`
`install.sh` 가 docker.com 저장소에서 Docker Engine 을 자동 설치합니다. 이미 한 번 돌렸다면 `newgrp docker` 또는 재로그인 후 재실행.

### `permission denied while trying to connect to the Docker daemon socket`
사용자가 `docker` 그룹에 들어갔지만 현재 쉘이 반영되지 않은 상태. 해결:
```bash
newgrp docker
# 또는 로그아웃 후 재로그인
```

### `could not select device driver "nvidia"`
NVIDIA Container Toolkit 미설치/미설정. `install.sh` 재실행, 또는 수동으로:
```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### `curl: (22) The requested URL returned error: 404` (nvidia-container-toolkit 설치 중)
NVIDIA 가 per-distro 저장소 경로(`https://nvidia.github.io/libnvidia-container/ubuntu24.04/libnvidia-container.list` 등) 를 폐기하고 통합 경로 `https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list` 만 유지. 구버전 `install.sh` 를 가진 체크아웃에서 발생. 최신 `install.sh` 를 pull 한 뒤, 중도 실패로 남은 리스트 파일을 제거하고 재실행:
```bash
sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list
./install.sh
```

### `nvidia-ctk` 가 "It is recommended that docker daemon be restarted" 출력
`install.sh` 가 바로 다음 줄에서 `systemctl restart docker` 를 호출하므로 무시해도 됨. 수동 실행 시에만 재시작 필요.

## NGC 이미지 Pull

### `docker login nvcr.io` 에서 `unauthorized` (이메일·NGC 웹 비밀번호로 시도)
NGC는 일반 계정 자격증명을 받지 않습니다. Username 은 **리터럴 문자열 `$oauthtoken`** (쉘 변수 확장 아님, 정확히 이 8자), password 는 NGC 웹에서 발급한 **API Key** (`nvapi-...`). 이메일/NGC 로그인 비번으로는 항상 실패합니다.
```bash
docker login nvcr.io
# Username: $oauthtoken
# Password: <nvapi-...>
```
stdin 파이프로 넣을 때는 `$oauthtoken` 이 쉘 변수로 확장되지 않도록 반드시 작은따옴표:
```bash
echo '<API_KEY>' | docker login nvcr.io -u '$oauthtoken' --password-stdin
```

### `pull access denied for nvcr.io/nvidia/isaac-sim`
NGC 미로그인. `docker login nvcr.io` — username 은 문자 그대로 `$oauthtoken`, password 는 NGC API Key.

### Pull 속도가 매우 느림
이미지 ~20GB. 재시도 시 이전 레이어는 캐시되므로 끊긴 지점부터 이어받음. `build.sh` 다시 돌리면 됨.

## GUI / X11

### GUI 창이 뜨지 않음 / `cannot open display`
```bash
xhost +local:docker
echo $DISPLAY   # :0 또는 :1 이어야 함
```
Wayland 세션이면 X11 호환 세션(Xorg) 으로 로그인.

### "app ready" 이후 멈추고 GUI 없음 (6.0.0-dev2 특유)
증상: 로그에 `Isaac Sim Full Streaming Version …` / `Streaming App is loaded` 가 뜨고 `[launch_sim] … bootstrap complete` 가 **끝내 안 나옴**.

근본 원인: 이미지의 ENTRYPOINT가 `/isaac-sim/runheadless.sh` (스트리밍 kiosk 런처) 로 박혀 있어, compose 의 `command:` 는 이 스크립트의 인자로만 전달되고 무시됨 — `launch_sim.py` 가 아예 실행되지 않음. 확인:
```bash
docker image inspect nvcr.io/nvidia/isaac-sim:6.0.0-dev2 \
  --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}} {{json .Config.User}}'
# ["/isaac-sim/runheadless.sh"] null "isaac-sim"
```

해결: `docker-compose.yml` 에서 entrypoint 를 `python.sh` 로 오버라이드, user 를 root 로 전환 (이미지의 kiosk user 는 HOME 이 달라 `/root/.Xauthority` 마운트·`/root/.cache/*` 볼륨과 불일치):
```yaml
user: "0:0"
entrypoint: ["/isaac-sim/python.sh"]
command: ["/workspace/scripts/launch_sim.py"]
```

SimulationApp 에서 Newton 데스크톱 experience 를 명시 (streaming.kit 자동 선택 방지):
```python
simulation_app = SimulationApp(
    CONFIG,
    experience="/isaac-sim/apps/isaacsim.exp.full.newton.kit",
)
```

이미지의 사용 가능한 experience 확인:
```bash
docker run --rm --entrypoint ls nvcr.io/nvidia/isaac-sim:6.0.0-dev2 /isaac-sim/apps/
```
선택지: `isaacsim.exp.full.newton.kit` (Newton 프리셋, 본 프로젝트 권장) · `isaacsim.exp.full.kit` (표준 데스크톱) · `isaacsim.exp.full.streaming.kit` (WebRTC 전용).

### GUI 창은 뜨지만 검은 화면 / 렌더 먹통
GPU 드라이버 버전 확인 (550+). `nvidia-smi` 로 확인 후 필요 시 업데이트.

## Newton / 확장

### 확장 이름 네임스페이스 (6.0.0 rename)
Isaac Sim 6.0.0부터 `omni.isaac.*` / `omni.physx.newton` 등 구 네임스페이스가 `isaacsim.*` 로 이전됨. `6.0.0-dev2` 이미지 기준 실제 번들된 이름:

| 구버전 | 6.0.0-dev2 실제 이름 |
|---|---|
| `omni.physx.newton` | `isaacsim.physics.newton` (+ `.ui`, `isaacsim.pip.newton`) |
| `omni.isaac.ros2_bridge` | `isaacsim.ros2.bridge` |

구 이름을 `enable_extension` 하면 에러 없이 silent로 no-op 되어 `launch_sim.py` 가 "app ready" 직후 멈춘 것처럼 보임. 컨테이너 내부에서 실제 이름 조회:
```bash
docker run --rm -it --entrypoint bash nvcr.io/nvidia/isaac-sim:6.0.0-dev2
ls /isaac-sim/exts | grep -iE "newton|ros2"
```

### `AttributeError: 'numpy.ndarray' object has no attribute 'detach'` (world.reset 중)
증상 패턴:
```
[Warning] Changing backend from 'numpy' to 'torch' since NumPy cannot be used with GPU pipelines
…
File ".../xform_prim.py", line 1194, in _on_post_reset
    self.set_world_poses(self._default_state.positions, ...)
AttributeError: 'numpy.ndarray' object has no attribute 'detach'
```
`World()` 를 backend 명시 없이 생성하면 numpy 기본값으로 prim의 `_default_state` 를 저장함. 이후 Newton/GPU 파이프라인이 backend를 torch 로 auto-switch 하지만 이미 저장된 numpy 기본값은 변환되지 않아, `post_reset` 경로에서 torch API (`.detach()`) 호출 시 터짐. 해결: `World()` 생성 시 torch/cuda 명시:
```python
world = World(
    stage_units_in_meters=1.0,
    physics_dt=1.0 / 400.0,
    rendering_dt=1.0 / 60.0,
    backend="torch",
    device="cuda:0",
)
```

### PhysX-tensor joint 노드 SEGV (URDFImporter 출력 + Newton articulation)
증상: `ROS2PublishJointState`, `ROS2SubscribeJointState`, `IsaacArticulationController` OmniGraph 노드의 `targetPrim` 을 UR5e articulation 루트로 세팅한 직후 `launch_sim.py` 가 Python 스택 없이 segfault. 로그 마지막 줄은 보통:

```
[carb] [Error] … Segmentation fault (Address not mapped)
```

근본 원인: 이 3개 노드는 PhysX-tensor C++ 런타임이 articulation 을 tensor view 로 잡아야 동작합니다. 6.0.0-dev2 의 `URDFImporter` 는 Newton 쪽 schema (`NewtonArticulationRootAPI`) 와 PhysX 쪽 schema 가 섞인 출력을 내놓는데, Newton backend 아래에서는 PhysX-tensor 가 이 articulation 을 인식하지 못하고 null 포인터를 탑니다. **Python `isaacsim.core.api.articulations.Articulation` 래퍼도 동일 경로를 타므로 같은 위험이 있습니다.**

해결: joint bridge 를 OmniGraph 가 아니라 **rclpy sidechannel** 로 구현. 조인트 prim 의 `UsdPhysics.JointStateAPI:angular.position` 을 읽고 `UsdPhysics.DriveAPI:angular.targetPosition` 에 쓰는 방식. 단위는 USD 규약대로 degree 이므로 ROS radian 과 변환 필요. 현재 `launch_sim.py` 에 `setup_joint_drives()` + `setup_rclpy_bridge()` 로 구현돼 있음. 향후 PhysX-tensor 가 Newton articulation 을 안전히 감싸게 되면 OmniGraph 경로로 되돌릴 수 있음.

### rclpy import 실패 (`ModuleNotFoundError: No module named 'rclpy'`)
컨테이너 안에서 `launch_sim.py` 가 `import rclpy` 에서 죽는 경우. Isaac Sim 6.0.0-dev2 는 `isaacsim.ros2.bridge` 가 활성화될 때 번들 rclpy 를 sys.path 에 등록합니다. 증상이 나오면 다음을 순서대로 확인:

1. `LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib` 가 env 에 있는지 (compose 에 영구 세팅됨).
2. `enable_extension("isaacsim.ros2.bridge")` 가 `import rclpy` **이전** 에 호출되는지.
3. 번들 rclpy 모듈 위치:
   ```bash
   docker compose exec isaac-sim bash -lc 'ls /isaac-sim/exts/isaacsim.ros2.core/jazzy/*/site-packages/rclpy/__init__.py 2>/dev/null || echo missing'
   ```
   비어 있으면 이미지 버전 재확인 (`6.0.0-dev2` 태그 필요).

### Physics backend 가 Newton 이 아님
`launch_sim.py` 의 `assert_newton_backend()` 로그 확인. `physxScene:solverType` 또는 `physics:backend` 가 노출되지 않을 수 있음 — `isaacsim.physics.newton` 은 자체 런타임 API로 백엔드 상태를 노출하므로 번들된 `newton` 파이썬 패키지 (`/isaac-sim/exts/isaacsim.pip.newton/pip_prebundle/newton`) 를 통해 조회:
```python
# launch_sim.py 내부에서 시도:
import newton   # isaacsim.pip.newton 이 site-packages 에 prebundle
```

## ROS 2 Bridge

### `/clock` 은 `topic list` 에 보이지만 `topic hz` 가 값 안 뽑음
Discovery는 되지만 메시지가 발행되지 않는 상태. `OnPlaybackTick` 노드는 **타임라인 Play 상태에서만** 트리거됨. GUI 상단 ▶ 버튼으로 수동 Play 해보고 복구되면 원인 확정. 스크립트에서 자동화하려면 `world.reset()` 직후 `world.play()` 호출.

### 호스트에서 `/clock` 이 안 보임
1. 컨테이너 내부에서 토픽이 발행되고 있는지:
   ```bash
   ./run.sh shell
   source /opt/ros/jazzy/setup.bash   # 이미지 내부 ROS 설치 경로에 맞게
   ros2 topic list
   ```
2. `ROS_DOMAIN_ID` 호스트/컨테이너 일치 확인
3. `RMW_IMPLEMENTATION` 일치 (양쪽 모두 `rmw_fastrtps_cpp` 기본). 다르면 호스트 쉘에서도 동일하게 export.
4. 호스트에서 FastRTPS 사용 시 multicast 차단된 네트워크면 discovery 실패 → 로컬 localhost-only 모드 사용:
   ```bash
   export ROS_LOCALHOST_ONLY=1
   ```

### `ROS2PublishClock` 노드 타입 없음 / `ROS2 Bridge startup failed`
6.0.0-dev2 이미지는 호스트 ROS 2 를 컨테이너 안에서 source 하지 않고 **번들된 내부 ROS 2 Jazzy** 를 `/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib` 에 둠. 이 경로가 `LD_LIBRARY_PATH` 에 없으면 bridge 로드 중:
```
Could not load … librmw_implementation.so. Error: libament_index_cpp.so: cannot open shared object file
[Error] [isaacsim.ros2.core.impl.extension] ROS2 Bridge startup failed
```
로 실패하고 `isaacsim.ros2.bridge` 가 즉시 shutdown → 이후 `og.Controller.edit` 가 `ROS2PublishClock` 타입을 못 찾아 `OmniGraphError` 로 죽음.

해결: `docker-compose.yml` 의 environment 에 추가:
```yaml
- ROS_DISTRO=jazzy
- LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib
```
(python.sh 가 자신의 라이브러리 경로를 앞쪽에 prepend 하므로 기존 경로와 충돌하지 않음.)

## 성능

### 물리 주기 400Hz 미달
GUI 렌더가 물리를 늦춥니다. 진단:
- `rendering_dt` 를 1/30 으로 낮추기
- 또는 headless 모드로 전환 (`launch_sim.py` `CONFIG["headless"] = True`)

### GPU 메모리 부족
Isaac Sim 초기 로딩이 큼. 다른 GPU 프로세스 종료 후 재시도. 필요 시 텍스처 해상도 낮은 씬으로 교체.

## 정리 / 초기화

### 캐시 볼륨 전부 삭제
```bash
cd docker
docker compose down -v          # named volume 까지 제거 — 다음 기동 시 재다운로드 주의
```

### 컨테이너만 재생성
```bash
./run.sh down
./run.sh up
```
