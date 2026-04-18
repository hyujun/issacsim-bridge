# Robots

`launch_sim.py` + `sim_bridge/` 는 로봇에 대해 모릅니다. 실행 시 `ROBOT_PACK` 환경변수 하나만 보고, 해당 디렉토리의 **robot pack** 규약대로 에셋과 설정을 읽어 스테이지에 로드합니다. 새 로봇을 추가하는 일은 곧 새 pack 을 만드는 일입니다.

## 레이어 경계

| 레이어 | 성격 | 위치 |
|---|---|---|
| Isaac Sim bootstrap (Newton, ROS 2 bridge, `/clock`, joint bridge 루프) | **robot-agnostic** | `isaac_scripts/launch_sim.py` + `isaac_scripts/sim_bridge/` |
| Sim/infra 설정 (Docker, ROS 도메인, FastDDS 전송) | **robot-agnostic** | `docker/`, `install.sh`, `build.sh`, `run.sh` |
| URDF, USD, joint 이름, home pose, drive 게인 | **robot-specific** | `robots/<name>/` |

`launch_sim.py` / `sim_bridge/` 안에는 로봇 이름·조인트 수·드라이브 튜닝이 하드코딩돼 있지 않습니다. 반대로 `robots/<name>/` 안에는 Isaac Sim 부트스트랩 코드가 들어가지 않습니다.

## Pack 디렉토리 레이아웃

```
robots/<name>/
├── robot.yaml          (필수) 스키마 아래 참고
├── urdf/
│   ├── <name>.urdf
│   └── meshes/…
├── usd/                (생성물) convert_urdf.py 실행 후 채워짐
└── convert_urdf.py     URDF → USD 변환 스크립트
```

## `robot.yaml` 스키마

```yaml
robot:
  urdf_rel: urdf/<name>.urdf          # pack 기준 상대경로
  usd_rel: usd/<name>/<name>.usda     # URDFImporter 출력 내부 경로
  prim_path: /World/Robot             # 스테이지 위치. 관례상 agnostic 이름
  joints_subpath: Physics             # 참고용 — Newton ArticulationView 가 DOF 이름을 자동 매핑하므로 실제 조회에는 사용되지 않음
  root_link: base_link                # (필수) URDF root link 이름. `repair_joint_chain` 이 world-anchor 고정 조인트 (body1 == root_link) 를 식별하는 데 사용 — 해당 조인트의 body0 은 robot root Xform 에 남겨둬야 Newton 이 world anchor 로 취급.

joint_names:                          # /joint_states 에 publish 되는 조인트. driver 우선, mimic follower 는 뒤. mimic 이 있으면 controller 는 driver 만 /joint_command 로 보내도 follower 가 solver constraint 로 따라옴.
  - joint_a
  - joint_b

home_pose:                            # 현재는 참고용 (호스트에서 /joint_command 로 적용)
  joint_a: 0.0
  joint_b: 0.0

drive:                                # `apply_drive_gains_to_joints()` 가 authoring. mimic follower 에는 자동 생략 (NewtonMimicAPI / PhysxMimicJointAPI 검출 기반).
  mode: position                      # 현재 position 만 구현
  stiffness: 10000.0                  # 로봇 스케일에 맞춰 조정 (UR5e=10000, Robotiq 2F-85=100)
  damping: 100.0

# (선택) 루프 동작 방식. 생략하면 전부 기본값 — freerun 모드로 동작.
# 각 필드의 의미는 docs/ARCHITECTURE.md#시뮬레이션-모드 참조.
sim:
  mode: freerun                       # "freerun" | "sync"
  substeps: 4                         # physics_dt = rendering_dt / substeps
  render_rate_hz: 60                  # sync 의 maybe_render() wall-clock cadence
  step_rate_hz: 500                   # sync: rendering_dt = 1/step_rate_hz
  sync_timeout_s: 0.5                 # sync: cmd 없을 때 heartbeat step 주기

ros:
  joint_states_topic: /joint_states
  joint_command_topic: /joint_command
  publish_rate_hz: 100                # freerun 전용 publisher timer rate
```

## 런타임 계약

`sim_bridge/` 가 pack 에 대해 가정하는 것:

1. `prim_path` 밑 어딘가에 `joint_names` 와 매칭되는 `PhysicsRevoluteJoint` prim 들이 존재한다. (정확한 하위 경로는 자유 — Newton ArticulationView 가 DOF 이름으로 매핑.)
2. `prim_path` 계층 어딘가의 prim 이 `PhysicsArticulationRootAPI` 또는 `NewtonArticulationRootAPI` 를 가진다. 이름·위치는 자유 — `sim_bridge/robot.py::find_articulation_root_path()` 가 스키마로 스캔.
3. URDFImporter 출력의 알려진 결함 네 가지는 `sim_bridge/usd_patches.py` 의 runtime patch 로 교정되므로 pack 에서 추가 작업 불필요:
   - 모든 조인트의 `physics:body0` 이 robot root 로 고정된 star topology → `repair_joint_chain()` 이 `parent(body1)` 로 재작성. `robot.root_link` 에 해당하는 world-anchor 조인트만 예외 처리.
   - virtual 링크 (`base_link`, `ft_frame`, `flange`, `tool0`, `base` 류) 에 `PhysicsMassAPI` 가 mass/inertia 없이 붙어 Newton UserWarning 반복 → `strip_zero_mass_api()` 가 empty MassAPI 를 제거.
   - `IsaacRobotAPI::isaac:physics:robotLinks` 가 star topology 기준으로 authoring 되어 후속 BFS 와 불일치 → `populate_robot_schema_links()` 가 repair 이후 `PopulateRobotSchemaFromArticulation` 재호출로 relationship 재작성.
   - `DriveAPI:angular` 가 `maxForce` 만 가짐 → `apply_drive_gains_to_joints()` 가 `robot.yaml` 의 stiffness/damping 주입. **단 mimic follower (NewtonMimicAPI 또는 PhysxMimicJointAPI:* 적용된 조인트) 는 skip** — 아래 mimic 섹션 참조.

단위는 ROS 관례대로 **radian** — Newton 내부가 radian 이므로 `JointState` ↔ 내부 상태 간 변환 없이 바로 주고받음. 구 문서가 언급하던 degree 컨벤션은 USD 시절 이야기로, 현재 ArticulationView 경로에선 무관.

### Mimic 조인트

URDF `<mimic joint="..." multiplier="..." offset="..."/>` 는 **URDFImporter 와 Newton 이 네이티브로 처리**합니다. Bridge 레이어는 mimic 을 알 필요 없음:

1. `convert_urdf.py` 실행 시 URDFImporter 가 follower 조인트에 `NewtonMimicAPI` (또는 physx variant 선택 시 `PhysxMimicJointAPI:rotY`) 를 authoring. `newton:mimicCoef0/1`, `newton:mimicJoint` 관계 포함.
2. `launch_sim.py` 기동 시 Newton 의 USD importer 가 해당 schema 를 읽어 `builder.add_constraint_mimic(follower, leader, coef0, coef1)` 로 solver-level **하드 제약** 등록. 수식: `follower = coef0 + coef1 * leader`.
3. 따라서 외부 제어기는 **driver 조인트만** `/joint_command` 로 publish 하면 되고, follower 들은 solver 가 자동으로 수식에 맞춰 움직임. `/joint_states` 에는 `joint_names` 에 나열된 모든 조인트 (driver + follower) 의 현재 위치가 실림.
4. `apply_drive_gains_to_joints()` 는 mimic follower 를 skip — PD drive 를 인가하면 stale target 과 mimic 제약이 싸워 drift 발생. Drive 는 leader 에만.

검증 기준: grip 상태에서 `/joint_states` 가 mimic 수식을 **drift < 1e-5 rad** 로 만족해야 함 (Newton solver constraint 는 하드이므로 수치 오차 수준). 위 기준을 넘으면 drive 가 follower 에 누락 skip 된 것 — 로그에 `Patched N revolute joints ... (skipped M mimic follower(s))` 에서 M 이 follower 수와 일치하는지 확인.

### (선택) Xacro 소스 URDF

`ros-jazzy-*-description` 같은 upstream 패키지가 xacro 형식으로 URDF 를 제공하면, pack 에 `build_urdf.sh` 를 두어 host-side 에서 한 번 expansion 하고 결과 `.urdf` + mesh 를 pack 에 커밋하는 패턴을 권장합니다 (현재 `robotiq_2f_85` 가 이 방식). 컨테이너는 완성된 `.urdf` 만 읽으므로 ROS 2 런타임 의존성이 컨테이너로 새지 않습니다. 예:

```bash
# robots/robotiq_2f_85/build_urdf.sh 가 하는 일:
# 1. /opt/ros/jazzy 의 xacro 로 xacro.urdf → urdf 전개
# 2. mesh 를 pack 내부로 복사
# 3. `file://...` 절대경로를 pack-relative 로 재작성
# 4. 불필요한 <ros2_control> 블록 제거
```

`install.sh` 에 관련 `ros-jazzy-*-description` 패키지 설치를 추가하세요.

### sync 모드의 pack 측 고려사항

`sim.mode: sync` 는 외부 제어기가 `/joint_command` 로 sim 을 drive 한다고 가정합니다. Pack 이 이 모드를 기본으로 쓰려면:

- `step_rate_hz` 를 제어기 제어 주기와 일치시키세요. 예: 500 Hz 제어기 → `step_rate_hz: 500` → `rendering_dt = 2 ms`.
- `sync_timeout_s` 는 제어기가 일시 중단돼도 sim 이 heartbeat step 으로 살아 있도록 하는 안전망. 제어기 주기의 수십 배 정도면 충분.
- 제어기가 최초 state 를 기대한다면 **첫 cmd 전에도 heartbeat 로 `/joint_states` 가 timeout 주기로 publish** 되므로 별도 bootstrap 프로토콜 불필요.

## 스위치 방법

```bash
# 기본 (ur5e)
./run.sh

# 다른 로봇 추가 후
ROBOT=my_arm ./run.sh
ROBOT=my_arm ./run.sh convert     # URDF → USD 변환도 pack 단위
```

`ROBOT_PACK` 를 직접 지정해서 호스트상 임의 디렉토리를 쓰고 싶다면:

```bash
ROBOT_PACK=/workspace/robots/ur5e ./run.sh
```

(컨테이너 안 경로 기준. 새 디렉토리를 쓰려면 `docker-compose.yml` 의 volumes 에 마운트를 추가.)

## 새 로봇 추가 체크리스트

1. `robots/<name>/urdf/` 에 URDF + meshes 배치.
2. `robots/<name>/robot.yaml` 작성 (위 스키마 참고). `joint_names` 순서는 호스트 제어기와 공유하는 계약이므로 신중히.
3. `robots/<name>/convert_urdf.py` — `ur5e/convert_urdf.py` 를 복사해 `URDF_PATH` / `USD_OUT` 만 pack 이름에 맞게 수정.
4. `ROBOT=<name> ./run.sh convert` 로 USD 생성.
5. `ROBOT=<name> ./run.sh` 로 기동 후 `ros2 topic hz /joint_states` 확인.

## 현재 pack 목록

- [`robots/ur5e/`](../robots/ur5e/robot.yaml) — Universal Robots UR5e, 6-DoF, `ur_description` (Jazzy) 원본.
- [`robots/robotiq_2f_85/`](../robots/robotiq_2f_85/robot.yaml) — Robotiq 2F-85 gripper, 1 driver + 5 mimic follower (4-bar linkage), `robotiq_description` (Jazzy) xacro 원본. `build_urdf.sh` 로 host-side 전개.
