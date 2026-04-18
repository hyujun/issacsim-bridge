# PLAN — remaining cleanup after Phase 3

> **이 문서의 목적**: 다음 Claude 대화가 이어서 실행할 수 있도록 정리한 handoff. 2026-04-18 세션에서 Phase 1 (sim_bridge/ 패키지 분리), Phase 2 (수정 가능한 USD warning 정리), Phase 3 (Python `warnings` 필터), Phase 5 (docs 업데이트) 는 끝났으므로, 이 문서는 Phase 4 만 남김. Phase 4 까지 마치면 이 파일은 삭제.

## 배경 — 현재 상태

Phase 3 기준:

- Isaac Sim 6.0.0-dev2 Newton 백엔드 + UR5e 로봇 + ROS 2 Jazzy bridge end-to-end 동작.
- `launch_sim.py` 는 SimulationApp 부팅 + 오케스트레이션만. 런타임 로직은 `isaac_scripts/sim_bridge/{config,usd_patches,robot,newton_view,ros_bridge,main_loop}.py`.
- `usd_patches.py` 에 runtime 패치 4 종: `repair_joint_chain`, `strip_zero_mass_api`, `populate_robot_schema_links`, `apply_drive_gains_to_joints` — 모두 `world.reset()` 이전에 pre-parse 된 stage 에 돌아감.
- `launch_sim.py` 최상단 (SimulationApp 이전) 에 `warnings.filterwarnings` 4종: Newton 의 per-prim zero-mass UserWarning 스팸과 MuJoCo 의 per-actuator unresolved warning 을 Python 레벨에서 침묵. pxr.Semantics (omni.log.warn 직행) 와 warp (자체 `catch_warnings` 로 필터 리셋) 는 Python warnings 우회 — 1회성 startup 로그로 남음 (의도된 상태).
- 5 개 docs (README / ARCHITECTURE / ROBOTS / TROUBLESHOOTING / SETUP) 는 Newton ArticulationView 아키텍처 + sim_bridge/ 레이아웃에 맞춰 업데이트 완료.

## 원칙 / 제약

- **SimulationApp 생성 이전에 `pxr` / kit 모듈을 import 하지 말 것.** `launch_sim.py` 가 `SimulationApp(CONFIG, experience=...)` 를 먼저 띄우고 나서 `sim_bridge` 서브모듈을 import 하는 구조 유지.
- `docker-compose.yml` 의 `command: ["/workspace/scripts/launch_sim.py"]` 는 바꾸지 않는다. `../isaac_scripts:/workspace/scripts` 마운트 그대로.
- 동작이 검증된 현재 로직을 **의미적으로 동일하게 유지**.
- Hard constraint: Newton backend 유지, `ROBOT_PACK` 한 줄로 로봇 교체 가능, 번들 rclpy (`LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib`).

## 작업 범위

### Phase 4 — publish rate 54 Hz → 100 Hz (별도 이슈, 선택)

`sim_bridge/main_loop.py` 의 `world.step(render=True)` 가 60 Hz 렌더 페이스에 갇혀 yaml `publish_rate_hz: 100` 을 못 따라감. 몇 개 옵션:

1. **옵션 A — 매 스텝 render 끄기**: `world.step(render=False)` 기본, N 스텝마다 한 번만 `render=True`. 간단. GUI 프레임 레이트 저하 가능.
2. **옵션 B — publish 스레드 분리**: rclpy executor 를 별도 스레드로. 복잡. rclpy 스레드 안전성 확인 필요.
3. **옵션 C — publish rate 를 실제 달성 가능한 rate 로 조정** (현실적): 60 Hz 로 낮춤.

사용자 선호 확인 후 단일 커밋.

## 권장 커밋 단위

1. (선택) publish rate 수정.
2. `docs/PLAN.md` 삭제.

각 단계 후 `./run.sh` 로 회귀 확인.

## 참고 위치

- Entry script: [isaac_scripts/launch_sim.py](../isaac_scripts/launch_sim.py)
- USD patches: [isaac_scripts/sim_bridge/usd_patches.py](../isaac_scripts/sim_bridge/usd_patches.py) (`repair_joint_chain`, `strip_zero_mass_api`, `populate_robot_schema_links`, `apply_drive_gains_to_joints`)
- Main loop: [isaac_scripts/sim_bridge/main_loop.py](../isaac_scripts/sim_bridge/main_loop.py)
- Newton ArticulationView: [isaac_scripts/sim_bridge/newton_view.py](../isaac_scripts/sim_bridge/newton_view.py)
- Robot pack 규약: [docs/ROBOTS.md](ROBOTS.md), 현재 pack: [robots/ur5e/robot.yaml](../robots/ur5e/robot.yaml)
- Newton 내부 레퍼런스 (컨테이너 안):
  - `/isaac-sim/exts/isaacsim.physics.newton/isaacsim/physics/newton/tensors/articulation_view.py` — ArticulationView 전체 surface
  - `/isaac-sim/exts/isaacsim.pip.newton/pip_prebundle/newton/_src/solvers/mujoco/solver_mujoco.py` — `_init_actuators`, `JointTargetMode.from_gains`
  - `/isaac-sim/exts/isaacsim.pip.newton/pip_prebundle/newton/_src/sim/builder.py` — `joint_target_mode` 결정 로직
