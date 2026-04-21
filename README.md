# isaacsim-bridge

Isaac Sim (Newton physics backend) ↔ ROS 2 Jazzy 브리지 환경. 컨테이너에서 Isaac Sim GUI를 띄우고 `network_mode: host` 를 통해 호스트 ROS 2 와 토픽을 주고받습니다.

## 아키텍처 한눈에

```
┌─ Host: Ubuntu 24.04 + ROS 2 Jazzy ──────────────────────┐
│                                                         │
│   ros2 topic echo /clock ◄──┐                           │
│                             │ DDS (network_mode: host)  │
│   ┌─────────────────────────┴─────────────────────────┐ │
│   │ Docker: nvcr.io/nvidia/isaac-sim:6.0.0-dev2       │ │
│   │                                                   │ │
│   │   isaacsim.physics.newton (differentiable physics)│ │
│   │   isaacsim.ros2.bridge   → /clock publisher       │ │
│   │   World (freerun | sync lock-step, GUI)           │ │
│   └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Quick start

```bash
./install.sh     # 호스트 prereq (1회만)
./build.sh       # Isaac Sim 이미지 pull (~20GB, 10분+)
./run.sh         # 컨테이너 기동, GUI 실행
```

별도 터미널에서 bridge 검증:

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic hz /clock
```

## 프로젝트 구조

```
isaacsim-bridge/
├── README.md               ← 여기
├── install.sh              호스트 prereq + pack host_deps 합집합 설치     ┐
├── build.sh                docker compose pull                            │ robot-agnostic
├── run.sh                  up / down / shell / logs / convert / list      │
├── docker/                                                                 │
│   └── docker-compose.yml  Isaac Sim 컨테이너 정의                         │
├── isaac_scripts/                                                          │
│   ├── launch_sim.py       entry: SimulationApp + 오케스트레이션            │
│   └── isaacsim_bridge/    런타임 로직 패키지                               │
│       ├── config.py         robot.yaml loader + validate_robot_config    │
│       ├── usd_patches.py    URDFImporter 출력 교정 (2 patches)            │
│       ├── robot.py          World, USD ref, articulation root             │
│       ├── newton_view.py    Newton ArticulationView + DOF map + DoF assert│
│       ├── ros_bridge.py     /clock OmniGraph + rclpy sidechannel          │
│       ├── main_loop.py      step · command · publish loop                 │
│       ├── dof_map.py        yaml joint_names ↔ Newton DOF index (순수)    │
│       └── tests/            호스트 유닛 + phase6/phase12 integration       ┘
├── robots/                 robot-specific 영역 (pack 하나당 1 디렉토리)
│   ├── ur5e/
│   │   ├── robot.yaml      pack 계약 (조인트·게인·토픽·sim 모드)
│   │   ├── convert_urdf.py URDF → USD 변환 (pack 단위)
│   │   ├── urdf/           URDF + mesh
│   │   └── usd/            변환 결과 (convert 실행 후 생성)
│   └── robotiq_2f_85/
│       ├── robot.yaml
│       ├── convert_urdf.py
│       ├── build_urdf.sh   xacro → urdf 전개 (host-side, 1회)
│       ├── host_deps.txt   install.sh 가 읽을 apt 의존성 (xacro 등)
│       ├── urdf/
│       └── usd/
└── docs/
    ├── ARCHITECTURE.md     시스템 설계 상세 + 레이어 분리
    ├── ROBOTS.md           pack 규약, 새 로봇 추가법
    ├── SETUP.md            환경 구축 & 최초 기동
    └── TROUBLESHOOTING.md  알려진 문제 / 해결 (6.0.0-dev2 이슈 포함)
```

## 현재 상태

End-to-end 동작 (Phase 1–6 완료, 상세는 `git log`):

- Isaac Sim 6.0.0-dev2 Newton 백엔드 + ROS 2 Jazzy bridge GUI 기동.
- `/clock` (OmniGraph) + `/joint_states` · `/joint_command` (rclpy sidechannel + Newton ArticulationView).
- Dual-mode publish loop: `freerun` (GUI 관찰용) / `sync` (외부 RT 제어기 lock-step). 상세: [docs/ARCHITECTURE.md#시뮬레이션-모드](docs/ARCHITECTURE.md#시뮬레이션-모드).
- Robot-agnostic pack 규약: `ROBOT=<name> ./run.sh` 으로 교체. 현재 `robots/` 에 **ur5e** + **robotiq_2f_85** (4-bar mimic gripper). 규약 + 새 로봇 추가법: [docs/ROBOTS.md](docs/ROBOTS.md).
- Pack contract 검증: `validate_robot_config` (bootstrap 시 lazy) + `newton_view` DoF 런타임 어써션 + `pytest -m phase6` dual-pack regression gate (`robots/*/robot.yaml` auto-discover).

### 다음 작업

[docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) 의 "다음 작업" 섹션 참고. 후보: Phase 3 (GUI 버튼 패널, 독립적) · Phase 1.3 (OmniGraph 네이티브 joint bridge, SEGV 재확인 필요).

자세한 설계는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), 셋업은 [docs/SETUP.md](docs/SETUP.md), 트러블슈팅은 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Isaac Sim 6.0.0-dev2 pre-release 주의

6.0.0 은 아직 개발 중이라 공식 5.x 대비 몇 가지 함정이 있습니다. 전부 `docs/TROUBLESHOOTING.md` 에 근거와 함께 정리돼 있음.

- `omni.*` → `isaacsim.*` 네임스페이스 마이그레이션 중 (구 이름은 silent no-op).
- 기본 ENTRYPOINT 가 streaming kiosk 라서 `python.sh` + `isaacsim.exp.full.newton.kit` 로 override 필요.
- 번들 rclpy 는 `/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib` — `LD_LIBRARY_PATH` 에 명시해야 bridge 가 뜸.
- `World()` backend 를 명시 (`torch`, `cuda:0`) 안 하면 `world.reset` 에서 numpy↔torch mismatch 로 `.detach()` 터짐.
- PhysX-tensor OmniGraph joint 노드 (`ROS2PublishJointState`, `IsaacArticulationController`) 는 Newton articulation 위에서 SEGV. 그래서 joint 경로는 rclpy sidechannel + Newton ArticulationView tensor API 사용.
- URDFImporter 출력은 모든 조인트 `physics:body0 = </robot_root>` (star topology). Newton 이 체인을 잃음 → `isaacsim_bridge/usd_patches.py::repair_joint_chain()` 가 body0 = parent(body1) 로 재작성.
- URDFImporter 가 내뱉는 `DriveAPI:angular` 는 `maxForce` 만 가짐. stiffness/damping 이 없으면 Newton 이 EFFORT 모드로 내려가 6.0.0-dev2 에서는 OmniGraph 코어 세그폴트 → `apply_drive_gains_to_joints()` 가 yaml 게인 주입.
- Newton `create_articulation_view(pattern)` 의 pattern 은 **`ArticulationRootAPI` 가 붙은 prim 경로** (URDFImporter 출력 기준 `.../base_link`) — 레퍼런스 앵커 (`/World/Robot`) 가 아님.
- Newton tensor frontend 는 GPU 파이프라인에서 **torch/warp 만** 허용. `create_simulation_view("numpy", ...)` 금지.
- `UsdPhysics.JointStateAPI` 는 이 번들에 없음 — `PhysxSchema.JointStateAPI` 로 옮겨감. Newton ArticulationView 경로를 쓰면 USD attribute 접근 자체를 피할 수 있음.

## Hard constraints

- Newton backend 활성 상태 런타임 assertion (PhysX fallback 금지)
- `ROS_DOMAIN_ID` 호스트·컨테이너 일치
- `network_mode: host` 유지 (DDS discovery)
- Isaac Sim 이미지 태그: `nvcr.io/nvidia/isaac-sim:6.0.0-dev2`
- `launch_sim.py` 에 로봇 식별자 하드코딩 금지 — 모든 로봇 의존성은 `robots/<name>/` 에
