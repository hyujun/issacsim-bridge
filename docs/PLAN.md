# PLAN — remaining cleanup after Phase 1 split

> **이 문서의 목적**: 다음 Claude 대화가 이어서 실행할 수 있도록 정리한 handoff. 2026-04-18 세션에서 Phase 1 (sim_bridge/ 패키지 분리) 와 Phase 5 (docs 업데이트) 는 끝났으므로, 이 문서는 Phase 2–4 만 남김. Phase 4 까지 마치면 이 파일은 삭제.

## 배경 — 현재 상태

`master@33f5be1` 기준:

- Isaac Sim 6.0.0-dev2 Newton 백엔드 + UR5e 로봇 + ROS 2 Jazzy bridge end-to-end 동작 (b1ff44a 에서 달성).
- `launch_sim.py` 는 SimulationApp 부팅 + 오케스트레이션만. 런타임 로직은 `isaac_scripts/sim_bridge/{config,usd_patches,robot,newton_view,ros_bridge,main_loop}.py` (33f5be1).
- 5 개 docs (README / ARCHITECTURE / ROBOTS / TROUBLESHOOTING / SETUP) 는 Newton ArticulationView 아키텍처 + sim_bridge/ 레이아웃에 맞춰 업데이트 완료.

## 원칙 / 제약

- **SimulationApp 생성 이전에 `pxr` / kit 모듈을 import 하지 말 것.** `launch_sim.py` 가 `SimulationApp(CONFIG, experience=...)` 를 먼저 띄우고 나서 `sim_bridge` 서브모듈을 import 하는 구조 유지.
- `docker-compose.yml` 의 `command: ["/workspace/scripts/launch_sim.py"]` 는 바꾸지 않는다. `../isaac_scripts:/workspace/scripts` 마운트 그대로.
- 동작이 검증된 현재 로직을 **의미적으로 동일하게 유지**.
- Hard constraint: Newton backend 유지, `ROBOT_PACK` 한 줄로 로봇 교체 가능, 번들 rclpy (`LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib`).

## 작업 범위

### Phase 2 — 수정 가능한 USD warning 정리

현재 로그에서 나는 경고 중 우리가 고칠 수 있는 것들:

- **`Body .../base_link zero mass and zero inertia despite MassAPI applied` × 5**
  URDFImporter 가 virtual 링크(`base_link`, `ft_frame`, `flange`, `tool0`, `base`) 에도 `PhysicsMassAPI` schema 를 붙임. `mass=0` + `diagonalInertia=(0,0,0)` 인 prim 에서 MassAPI 를 제거하는 `strip_zero_mass_api()` 를 `sim_bridge/usd_patches.py` 에 추가. `repair_joint_chain` 과 같은 타이밍(pre-reset)에 돈다.

- **`Robot at /World/Robot has links missing from schema relationship`**
  `isaacsim.robot.schema` 가 ArticulationRoot prim 에 `isaac:robot:links` rel targets 가 채워져 있길 기대. 현재 URDFImporter 출력은 비어 있음. `populate_robot_schema_links()` 를 `sim_bridge/usd_patches.py` 에 추가 (optional — schema hint 성격, 동작에 영향 없음). 기능보다 로그 노이즈 감축 목적이면 우선순위 낮춤.

완료 기준: 해당 5 + 1 경고가 로그에서 사라짐. 단일 커밋.

### Phase 3 — py-stderr UserWarning 소음 억제

현재 로그의 `[Error] [omni.kit.app._impl] [py stderr]: /isaac-sim/.../newton/.../solver_mujoco.py:...: UserWarning: ...` 류는 Newton 내부 warning 이 stderr 로 나가 carb 가 Error 레벨로 찍는 것. 우리가 억제할 수 있는 것만:

- `warnings.filterwarnings("ignore", category=UserWarning, module=r"newton\._src\..*")`
- `warnings.filterwarnings("ignore", category=UserWarning, module=r"warp\..*")`
- `warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"warp\..*")`
- `warnings.filterwarnings("ignore", category=DeprecationWarning, message=r".*pxr\.Semantics is deprecated.*")`

`launch_sim.py` 최상단 (SimulationApp 생성 전) 에 둔다. 너무 광범위한 suppress 는 금지 — 우리 코드 warning 은 통과해야 함.

완료 기준: 로그가 "Body .. zero mass" / "pxr.Semantics deprecated" / "warp.context.Kernel will soon be removed" / "MuJoCo actuator N unresolved" 계열 모두 침묵. Phase 2 에서 실제로 사라지는 경고와 구분해 개별 커밋.

### Phase 4 — publish rate 54 Hz → 100 Hz (별도 이슈, 선택)

`sim_bridge/main_loop.py` 의 `world.step(render=True)` 가 60 Hz 렌더 페이스에 갇혀 yaml `publish_rate_hz: 100` 을 못 따라감. 몇 개 옵션:

1. **옵션 A — 매 스텝 render 끄기**: `world.step(render=False)` 기본, N 스텝마다 한 번만 `render=True`. 간단. GUI 프레임 레이트 저하 가능.
2. **옵션 B — publish 스레드 분리**: rclpy executor 를 별도 스레드로. 복잡. rclpy 스레드 안전성 확인 필요.
3. **옵션 C — publish rate 를 실제 달성 가능한 rate 로 조정** (현실적): 60 Hz 로 낮춤.

사용자 선호 확인 후 단일 커밋.

## 권장 커밋 단위

1. `usd_patches.strip_zero_mass_api` + (옵션) `populate_robot_schema_links` 추가 + orchestration 연결.
2. `warnings.filterwarnings` 노이즈 억제.
3. (선택) publish rate 수정.
4. `docs/PLAN.md` 삭제.

각 단계 후 `./run.sh` 로 회귀 확인.

## 참고 위치

- Entry script: [isaac_scripts/launch_sim.py](../isaac_scripts/launch_sim.py) (커밋 33f5be1)
- USD patches: [isaac_scripts/sim_bridge/usd_patches.py](../isaac_scripts/sim_bridge/usd_patches.py) (`repair_joint_chain`, `apply_drive_gains_to_joints`)
- Main loop: [isaac_scripts/sim_bridge/main_loop.py](../isaac_scripts/sim_bridge/main_loop.py)
- Newton ArticulationView: [isaac_scripts/sim_bridge/newton_view.py](../isaac_scripts/sim_bridge/newton_view.py)
- Robot pack 규약: [docs/ROBOTS.md](ROBOTS.md), 현재 pack: [robots/ur5e/robot.yaml](../robots/ur5e/robot.yaml)
- Newton 내부 레퍼런스 (컨테이너 안):
  - `/isaac-sim/exts/isaacsim.physics.newton/isaacsim/physics/newton/tensors/articulation_view.py` — ArticulationView 전체 surface
  - `/isaac-sim/exts/isaacsim.pip.newton/pip_prebundle/newton/_src/solvers/mujoco/solver_mujoco.py` — `_init_actuators`, `JointTargetMode.from_gains`
  - `/isaac-sim/exts/isaacsim.pip.newton/pip_prebundle/newton/_src/sim/builder.py` — `joint_target_mode` 결정 로직
