# Architecture

## 경계 요약

| 레이어 | 위치 | 역할 |
|---|---|---|
| Isaac Sim 5.1+ (6.0.0-dev2) | Docker 컨테이너 | 시뮬레이션 런타임, 렌더러, 씬 상태 |
| Newton Physics | Isaac Sim 내부 확장 | 미분 가능 물리 스텝 (GPU) |
| ROS 2 Bridge | Isaac Sim 내부 확장 | USD 상태 ↔ DDS 토픽 매핑 |
| ROS 2 Jazzy | 호스트 | 외부 제어기, 분석, 시각화 |

## 통신 경로

```
World.step()             [Isaac Sim 프로세스]
   │
   ├─ Newton GPU solve   (physics_dt, rendering_dt 는 sim 모드로부터 유도)
   │
   ├─ Newton ArticulationView ────┐
   │  (torch frontend, cuda:0)    │  set_dof_position_targets()  ▲
   │                               │  get_dof_positions()         │
   ├─ OmniGraph tick               │                              │
   │   └─ ROS2PublishClock ──┐     │                              │
   │                         │     │                              │
   └─ simulation loop (Python)     │                              │
        ├─ rclpy.spin_once(0)      │                              │
        ├─ /joint_command → ───────┼──────────────────────────────┘ (write targets)
        └─ /joint_states  ← ───────┼──────────────────────────────── (read positions, sim-time stamp)
                                   │
                                   │  Cyclone DDS (기본) / FastRTPS
                                   │  (network_mode: host)
                                   ▼
                             ros2 topic /clock, /joint_states, /joint_command
                                   [호스트 DDS]
```

`network_mode: host` 덕분에 컨테이너의 DDS 참여자는 호스트의 네트워크 스택을 그대로 공유합니다. 즉 컨테이너 내부와 호스트가 **동일 DDS 도메인**에 속하므로 별도의 브리지 프록시가 필요 없습니다.

## Joint bridge 경로 — OmniGraph 가 아닌 rclpy sidechannel

`/clock` 은 OmniGraph `ROS2PublishClock` 노드로 퍼블리시합니다. 반면 `/joint_states` · `/joint_command` 는 **OmniGraph 를 쓰지 않고** `isaacsim_bridge/main_loop.py` 의 시뮬 루프 안에 심은 rclpy 노드로 처리합니다. 이유는 Isaac Sim 6.0.0-dev2 의 PhysX-tensor 기반 OmniGraph 노드 (`ROS2PublishJointState`, `IsaacArticulationController`) 가 Newton 이 만든 articulation 의 `URDFImporter` 출력을 삼키지 못하고 SEGV 하기 때문입니다. 자세한 내용은 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 의 "PhysX-tensor joint 노드 SEGV" 항목.

사이드채널 구현은 Newton 의 tensor **ArticulationView** 를 사용합니다 (`isaacsim_bridge/newton_view.py` 에서 생성, `torch` frontend + `cuda:0`):

- 읽기: `articulation.get_dof_positions(copy=True)` → `(count, max_dofs)` shape 의 torch tensor. cpu() / numpy() 로 옮겨 `sensor_msgs/JointState.position` 에 채움. **단위는 radian** — Newton 내부가 radian 이므로 ROS 와 변환 불필요.
- 쓰기: 수신한 `JointState` 를 DOF 인덱스로 매핑해 `articulation.set_dof_position_targets(buffer, indices0)` 로 기록. 내부적으로 Newton `control.joint_target_pos` 에 라우팅되며, `apply_drive_gains_to_joints()` 가 pre-reset 에 주입한 stiffness/damping 으로 POSITION-mode JOINT_TARGET actuator 가 PD servo 로 구동.

ArticulationView pattern 은 **`PhysicsArticulationRootAPI` (또는 `NewtonArticulationRootAPI`) 가 붙은 prim 경로** 를 지정해야 합니다. URDFImporter 출력에서는 `/World/Robot/Geometry/world/base_link` 같은 링크 prim 이 해당 — 레퍼런스 앵커 (`/World/Robot`) 로 지정하면 `count=0` 이 반환됩니다. 로직은 `isaacsim_bridge/robot.py::find_articulation_root_path()` 가 스키마로 스캔해 첫 매칭을 돌려주므로 로봇별 base-link 이름에 독립적입니다.

USD attribute 사이드채널 (`UsdPhysics.JointStateAPI` / `DriveAPI.targetPosition` 에 직접 read/write 하는 방식) 은 **포기**했습니다. 이 번들의 `pxr.UsdPhysics` 에는 `JointStateAPI` 가 아예 없고 (PhysxSchema 로 이동), DriveAPI 경로는 URDFImporter 의 누락된 게인과 결합해 조용히 무동작으로 떨어집니다.

## Mimic 조인트 경로

URDF `<mimic>` 는 **bridge 코드가 전혀 관여하지 않는 경로**로 처리됩니다 — URDFImporter → USD schema → Newton solver constraint 까지 네이티브:

```
robot.urdf  <mimic joint="L" multiplier="k" offset="c"/>
     │
     ▼   URDFImporter (convert_urdf.py)
follower joint prim
   apiSchemas = ["NewtonMimicAPI"]        (plain physics variant)
     OR
   apiSchemas = ["PhysxMimicJointAPI:rotY"]  (physx variant; default)
   newton:mimicCoef0 = c, newton:mimicCoef1 = k, newton:mimicJoint = </L>
     │
     ▼   Newton USD importer (launch_sim.py → world.reset())
builder.add_constraint_mimic(follower, leader, coef0=c, coef1=k)
     │
     ▼   Newton solver
hard constraint: q[follower] = c + k * q[leader]
```

외부 제어기는 leader 만 `/joint_command` 로 publish 하면 follower 가 자동으로 따라갑니다. `/joint_states` 는 `robot.yaml::joint_names` 에 나열된 모든 조인트의 현재 위치를 싣습니다 (driver + follower 전부).

**중요 — drive 는 leader 에만**: `apply_drive_gains_to_joints()` 가 `NewtonMimicAPI` 또는 `PhysxMimicJointAPI:*` 를 가진 조인트를 skip 합니다. Follower 에 PD drive 가 걸리면 controller 가 건드리지 않은 stale target (0 초기값 등) 을 유지하려 해서 mimic 제약과 충돌 → 접촉 부하 하에서 drift. Robotiq 2F-85 (4-bar 폐쇄 링크) 로 검증: drift < 1e-5 rad = solver 수치 오차 수준.

URDFImporter 는 follower 에 대해 **variant set 을 authoring**하므로 composed stage 에는 기본 `physx` variant 가 선택되어 PhysxMimicJointAPI 가 보입니다. Newton 의 USD importer 는 양쪽 variant 를 fallback 순서로 읽으므로 어느 쪽이 선택되어도 동일한 mimic constraint 가 설치됩니다.

## 왜 Newton 인가

- GPU 기반 병렬 물리 (multi-env 학습 친화적)
- **미분 가능** — gradient 를 뽑아 정책 학습 / 파라미터 최적화에 사용
- **단, gradient 는 ROS 2 토픽으로 전파되지 않습니다.** 메시지 직렬화가 그래프를 끊기 때문. Gradient 가 필요한 제어기는 Isaac Sim 프로세스 *안에* 두어야 함.

이 제약이 향후 설계 분기점입니다:

- **외부 제어기 (ROS 2 over DDS)**: 기존 ROS 2 생태계 호환. Gradient 사용 불가.
- **내부 제어기 (Python in-process)**: Newton API 직접 호출, gradient 사용 가능. ROS 2 는 관찰/로깅 채널로만 사용.

현재는 외부 제어기 전제로 bridge 를 세팅하되, 확장 API 를 막지 않는 방향으로 둡니다.

## 시간 모델

| 클럭 | 주기 | 출처 |
|---|---|---|
| `physics_dt` | `rendering_dt / sim.substeps` | `isaacsim_bridge/robot.py::build_world()` |
| `rendering_dt` | freerun: `1/render_rate_hz` · sync: `1/step_rate_hz` | `build_world()` |
| `/clock` | physics tick 마다 (sync: cmd 도착 · heartbeat 시점에만 전진) | `ROS2PublishClock` OmniGraph |
| `/joint_states` | freerun: `publish_rate_hz` timer · sync: 매 `world.step()` 직후 | rclpy sidechannel |
| `/joint_command` | 호스트 publish rate 에 따름 | rclpy sidechannel |
| `JointState.header.stamp` | sim-time (`omni.timeline`) — `/clock` 과 동일 타임베이스 | `isaacsim_bridge/main_loop.py` |
| 호스트 `use_sim_time` | `/clock` 구독 | 호스트 ROS 2 노드 설정 |

호스트 노드가 `use_sim_time: true` 를 사용하면 `header.stamp` 와 `/clock` 이 정확히 일치합니다 (양쪽 모두 `omni.timeline` 기반).

## 시뮬레이션 모드

`robot.yaml` 의 `sim.mode` 로 루프 동작 방식을 선택합니다. 기본값 `freerun`, 외부 RT 제어기 연동 시 `sync`.

### freerun

```
loop:
    world.step(render=True)        # sim-time += 1/render_rate_hz
    apply_cmd (있으면)
    spin_once(0)
    if timer due: publish /joint_states
```

- GUI 관찰 / 테스트 주도 개발 / 외부 제어기 미연동 시.
- publish rate 는 `ros.publish_rate_hz` timer. render 가 60 Hz 에 묶여 있으므로 그 이상은 aliasing (같은 state 반복 pub).

### sync (lock-step on `/joint_command`)

```
loop:
    got_cmd = wait_cmd_or_timeout(sync_timeout_s)      # rclpy.spin_once + maybe_render
    if got_cmd: apply_cmd
    world.step(render=False)                           # sim-time += 1/step_rate_hz
    publish /joint_states (sim-time stamp)
    maybe_render()                                     # simulation_app.update() at render_rate_hz wall-clock
```

- 외부 제어기 1 tick = `/joint_command` 1 publish. sim 은 그 tick 에 **정확히 한 번** step + publish.
- `sync_timeout_s` 동안 cmd 없으면 **heartbeat step** — 마지막 target 을 유지한 채 1 step + publish. 첫 cmd 이전에도 동일 → bootstrap 데드락 없음.
- `rendering_dt = 1/step_rate_hz` 라 한 tick 이 `step_rate_hz` 에 상응하는 sim-time 을 전진 (예: 500 → 2 ms). substeps=4 이면 physics 내부적으로 4 번 적분.
- **render 와 physics 분리**: `world.step()` 은 항상 `render=False`. GUI 는 `simulation_app.update()` 를 `render_rate_hz` wall-clock cadence 로 호출하는 `maybe_render()` 가 담당. cmd 없이 대기 중에도 GUI 살아있음.
- wall-clock 페이싱 없음 — 제어기 publish 속도가 sim 속도를 결정. 제어기가 느리면 sim 도 느리고, 빠르면 GPU 포화 수준에서 사무중.

### 세 가지 호출의 책임 분담 (sync 모드에서 중요)

| 호출 | physics 전진 | Kit 프레임 (render + UI + extensions) |
|---|---|---|
| `world.step(render=True)` | ✅ | ✅ (freerun 에서 사용) |
| `world.step(render=False)` | ✅ | ❌ (sync 모드 active step) |
| `simulation_app.update()` | ❌ | ✅ (sync 의 `maybe_render`, 대기 중 GUI 유지) |

이 분리가 없으면 sync 모드에서 cmd 대기 중에 GUI 가 freeze 됩니다 (Kit extension tick 도 정지).

## 레이어 분리 — agnostic vs robot-specific

Isaac Sim 부트스트랩은 로봇에 대해 모르도록 설계돼 있습니다. 실행 시 `ROBOT_PACK` 환경변수 하나로 `robots/<name>/` 디렉토리를 가리키고, `isaacsim_bridge.config` 가 그 pack 의 `robot.yaml` 만 참고해 USD 레퍼런스·조인트 이름·드라이브 게인·토픽 이름을 가져옵니다. 규약과 pack 추가 방법은 [ROBOTS.md](ROBOTS.md).

- **agnostic**: `isaac_scripts/launch_sim.py` + `isaac_scripts/isaacsim_bridge/` 패키지, `docker/`, `install.sh` / `build.sh` / `run.sh`.
- **robot-specific**: `robots/<name>/` — URDF, USD, `robot.yaml`, `convert_urdf.py`.

이 경계를 넘지 않는 한 로봇을 바꿔 끼울 수 있습니다.

## 확장성 고려

- **호스트 ROS 2 제어기 추가**: `ros2_ws/` 를 별도 추가하고 `JointState` / `JointCommand` 토픽 바인딩. Bridge 는 이미 활성화 상태.
- **다중 환경 (parallel envs)**: Newton 의 GPU 병렬성을 쓰려면 씬을 복제하고 토픽을 namespace 분기. 단, `/clock` 은 글로벌.
- **새 로봇 투입**: `robots/<name>/` 추가 → `ROBOT=<name> ./run.sh convert` → `ROBOT=<name> ./run.sh`. 규약은 [ROBOTS.md](ROBOTS.md).
