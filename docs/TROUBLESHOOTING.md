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

해결: joint bridge 를 OmniGraph 가 아니라 **rclpy sidechannel** 로 구현. Newton 의 tensor **ArticulationView** (`sim_bridge/newton_view.py` 에서 `create_simulation_view("torch", ...)` → `create_articulation_view(<ArticulationRootAPI prim path>)` 로 생성) 의 `get_dof_positions(copy=True)` 로 상태를 읽고 `set_dof_position_targets(buffer, indices0)` 로 명령을 기록. 단위는 radian — Newton 내부가 radian 이므로 ROS 와 변환 불필요. 향후 PhysX-tensor 가 Newton articulation 을 안전히 감싸게 되면 OmniGraph 경로로 되돌릴 수 있음.

### `AttributeError: module 'pxr.UsdPhysics' has no attribute 'JointStateAPI'`
증상: joint 상태를 USD attribute 사이드채널로 읽으려 `UsdPhysics.JointStateAPI.Get(prim, "angular")` 호출 시 터짐.

근본 원인: Isaac Sim 6.0.0-dev2 가 번들하는 OpenUSD 빌드의 `pxr.UsdPhysics` 에는 `JointStateAPI` 가 없습니다. 이 스키마는 `PhysxSchema.JointStateAPI` 로 옮겨감 (USD string schema 이름은 여전히 `PhysicsJointStateAPI`). `launch_sim.py` 는 이 경로 자체를 포기하고 Newton ArticulationView tensor API 로 우회합니다 — USD attribute 사이드채널이 필요해지면 `PhysxSchema.JointStateAPI.Get(prim, "angular")` 를 써야 합니다.

### `The Numpy frontend cannot be used with GPU pipelines`
증상: `newton_tensors.create_simulation_view("numpy", newton_stage)` 호출 시 Exception.

근본 원인: `World(device="cuda:0")` 로 GPU 파이프라인을 쓰면 Newton tensor frontend 도 GPU-호환이어야 합니다. `numpy` 프런트엔드는 CPU 전용. 해결: `create_simulation_view("torch", newton_stage)` (`sim_bridge/newton_view.py` 에서 채택) 또는 `"warp"`.

### `Newton ArticulationView matched no articulations for pattern '/World/Robot'`
증상: `sim_view.create_articulation_view("/World/Robot")` 이 `count=0` 반환 → 이후 `set_dof_position_targets` 가 무동작.

근본 원인: Newton 의 `articulation_label` 은 `PhysicsArticulationRootAPI` / `NewtonArticulationRootAPI` 가 **붙은 prim 의 전체 경로** 로 매칭합니다. URDFImporter 출력은 ArticulationRootAPI 를 레퍼런스 앵커 (`/World/Robot`) 가 아니라 kinematic base link (`/World/Robot/Geometry/world/base_link`) 에 붙입니다. pattern 으로 앵커를 주면 매칭 실패.

해결: `sim_bridge/robot.py::find_articulation_root_path()` 가 robot prim 하위를 순회해 스키마가 적용된 prim 경로를 자동 반환. 그걸 `create_articulation_view()` 에 넘기면 정상 매칭됨. robot pack 에 따라 base link 이름이 달라져도 스키마 기준이라 그대로 작동.

### `Newton model articulations: [...]` 에 여러 엔트리 / `max_dofs=0`
증상: `newton_stage.model.articulation_label` 출력이 링크별로 쪼개져 나열되고 ArticulationView 의 `max_dofs=0`. 로봇이 가만히 있음.

근본 원인: URDFImporter 6.0.0-dev2 가 **모든 조인트의 `physics:body0` 를 robot root (`</robot_name>`) 로** 설정 — star topology. robot root 는 `RigidBodyAPI` 가 없어 Newton 이 유효한 부모로 인식 못 하고, 각 링크를 독립 articulation 으로 파싱. 결과적으로 각 "articulation" 에 DOF 가 하나도 없음.

해결: `sim_bridge/usd_patches.py::repair_joint_chain()` 가 pre-reset 에 각 joint 의 `body0` 를 `parent(body1)` 로 재작성. 예외는 `base_link` 를 world 에 고정하는 fixed joint 하나 — 얘는 body0=robot root 를 유지해야 함 (Newton 이 robot root 를 world 로 취급). 재작성 후 `articulation_label` 이 단일 엔트리 + `max_dofs=6` 이 나옵니다.

### ~~`Body .../base_link has zero mass and zero inertia despite having the MassAPI USD schema applied.`~~ (obsolete)
**Phase 1.2 검증 (2026-04-20)으로 URDFImporter 3.2.1 에서 더 이상 발생하지 않음 확인**. `strip_zero_mass_api` 패치는 `sim_bridge/usd_patches.py` 에서 제거됨. 과거에는 URDFImporter 가 `<inertial>` 블록 없는 frame 링크에도 `PhysicsMassAPI` 를 붙여 Newton 이 mass=0 경고를 5 회 반복했으나, 현재 이미지 (6.0.0-dev2 / URDFImporter 3.2.1) 는 근본 원인을 해결함. 옛 버전으로 되돌린다면 해당 패치를 다시 복원해야 함 — `git log` 에서 `strip_zero_mass_api` 로 찾으면 구현 참고 가능.

### `Robot at /World/Robot has links missing from schema relationship: [...]` (cosmetic, 현재 억제 불가)
증상: 로그에 위 warning 1 회. 기능 영향 없음. URDFImporter 가 `IsaacRobotAPI::isaac:physics:robotLinks` 관계를 자동 populate 하지만 BFS 결과가 런타임 체인과 불일치하는 경우 발생.

**Phase 1.2 검증 결과**: 과거에 있던 `populate_robot_schema_links` 패치는 **무효했음** — 패치 on/off 양쪽 모두 동일한 경고 1 회 발생. 현재 코드에서는 제거됨. 이 schema 는 Newton 물리 경로에서 소비되지 않으므로 warning 은 무시해도 안전함. 향후 Isaac Sim 업데이트로 URDFImporter 가 이를 정상 populate 하면 자연 해소될 예정.

### Drive gain 누락 → OmniGraph 코어 segfault (6.0.0-dev2 에서 격상된 증상)
증상: `apply_drive_gains_to_joints` 없이 기동하면 `ROS2ClockGraph` 노드 생성 단계에서 Fatal 크래시 → `Segmentation fault (core dumped)`. Phase 1.2 smoke test (2026-04-20) 로 재현 확정.

근본 원인: DriveAPI 에 stiffness/damping 이 없으면 Newton 은 `JointTargetMode.EFFORT` 로 떨어짐. 과거에는 `solver_mujoco.py::_init_actuators` 가 `MuJoCo actuator has unresolved target` warning 만 찍고 skip 했으나, 6.0.0-dev2 에서는 OmniGraph hash 테이블 rehash 중 libomni.graph.core.plugin.so 가 세그폴트. stack trace 는 대체로 `_Hashtable::_M_rehash` + ROS2ClockGraph 노드 생성 커맨드.

해결: `sim_bridge/usd_patches.py::apply_drive_gains_to_joints()` 가 pre-reset 에 `robot.yaml.drive.{stiffness,damping}` 을 모든 `PhysicsRevoluteJoint` 에 기록. Mimic follower (`NewtonMimicAPI` / `PhysxMimicJointAPI:*`) 는 skip — solver constraint 와 충돌. 이 패치는 **필수** — cosmetic 이었던 warning 이 현재는 하드 크래시 유발. Phase 1.2 검증으로 SIM_SKIP_PATCHES=apply_drive_gains 설정 시 즉시 재현됨.

### `[Error] [py stderr]` 스팸 (Newton per-prim / MuJoCo per-actuator)
증상: 부팅 중 `[Error] [omni.kit.app._impl] [py stderr]: /isaac-sim/.../newton/.../*.py:...: UserWarning: ...` 류가 반복 출력. carb 는 stderr 를 Error 레벨로 태그함.

해결: `launch_sim.py` 최상단 (SimulationApp 생성 **전**) 에 Python warnings 필터 4종을 설치. `warnings.filterwarnings("ignore", category=UserWarning, module=r"newton\._src\..*")` 등. Newton 의 zero-mass UserWarning 스팸과 MuJoCo 의 `unresolved target` 은 여기서 침묵.

**한계**: 아래 2건은 Python `warnings` 를 우회하므로 필터가 못 잡음 — 각 1회성 startup 로그로 남음 (의도된 상태):
- `[Warning] [pxr.Semantics] pxr.Semantics is deprecated` — `pxr/Semantics/__init__.py` 가 `omni.log.warn()` 으로 carb 채널에 직접 쏨.
- `Warp DeprecationWarning: warp.context.Kernel will soon be removed` — `warp/_src/utils.py::warn()` 이 내부적으로 `warnings.catch_warnings()` + `simplefilter("default")` 로 사용자 필터를 리셋한 뒤 warn. 설계상 필터 우회.

둘 다 1회성 cosmetic. 실제 동작에 영향 없음. 억지로 잡으려면 carb 채널 비활성화 / warp.warn monkey-patch 가 필요한데 스팸이 아니므로 두는 편.

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

## Sim 모드 (freerun / sync)

### sync 모드에서 로봇이 안 움직이고 `/joint_states` 가 `sync_timeout_s` 간격으로만 pub 됨
정상 동작. sync 모드는 `/joint_command` 도착 때마다 step → publish 하는 lock-step 루프. cmd 가 없으면 `sync_timeout_s` (기본 0.5 s) 주기로 heartbeat step 만 실행. 해결:
```bash
# 호스트에서 cmd 가 실제로 나가는지 확인
ros2 topic echo /joint_command
# 안 나가면 제어기 쪽 문제. 나가는데 반응 없으면 sim 쪽 로그 확인 — "[sync] first command received" 가 찍혔어야 함.
```

### sync 모드에서 GUI 가 얼어붙음
`maybe_render()` 가 호출 안 되는 경우. 현재 코드에선 wait loop 와 active step 양쪽에서 `simulation_app.update()` 를 60 Hz (기본) wall-clock 케이던스로 펌핑함. 직접 수정한 버전에서 freeze 하면 `sim_bridge/main_loop.py::_run_sync` 의 `maybe_render()` 호출 누락 여부 점검. `render_rate_hz` 를 낮추면 GUI 프레임도 낮아지지만 freeze 는 아니어야 함.

### sync 모드에서 제어기가 state 보고 시간 불일치 (`use_sim_time:=true` 기준)
sync 모드는 `header.stamp` 를 `omni.timeline.get_current_time()` (sim-time) 으로 채움. `/clock` 도 sim-time 기준이므로 `use_sim_time:=true` 구독자는 stamp 와 clock 이 일치해야 함. 불일치하면:
1. 호스트 노드에 `use_sim_time:=true` 가 실제로 적용됐는지 (`ros2 param get <node> use_sim_time`).
2. wall-clock 기준으로 돌리는 제어기라면 반대로 `use_sim_time:=false` + 호스트 쪽 시간 보정 필요. sync 모드는 wall-clock 기준으로 sim-time 이 늦을 수 있음 (sim 은 cmd 도착 시점에만 전진).

### freerun 모드에서 publish rate 가 `publish_rate_hz` 보다 낮음
정상. freerun 은 `world.step(render=True)` 가 `rendering_dt = 1/60` 케이던스에 묶임 → publish rate 상한 ≈ 60 Hz. yaml 의 `publish_rate_hz: 100` 은 timer 상한일 뿐 실제 rate 보장 아님. 100 Hz 이상이 필요하면 `sim.mode: sync` 로 전환 후 제어기가 원하는 rate 로 `/joint_command` 쏘기.

## 성능

### 물리 주기 미달
GUI 렌더가 물리를 늦추는 경우:
- freerun: `rendering_dt` 는 `render_rate_hz` 로 결정됨. `render_rate_hz` 를 낮추면 frame 당 physics substep 이 늘어남.
- sync: physics 는 `step_rate_hz` 로 결정되고 render 는 별개 (`maybe_render()`). 렌더 부하가 sim 에 영향 주면 `render_rate_hz` 를 낮추거나 headless 전환 (`launch_sim.py` `CONFIG["headless"] = True`).

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
