# sim-bridge

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
│   │   World (400Hz physics, 60Hz render, GUI)         │ │
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
sim-bridge/
├── README.md               ← 여기
├── install.sh              호스트 prereq 설치·검증              ┐
├── build.sh                docker compose pull                 │ robot-agnostic
├── run.sh                  up / down / shell / logs / convert  │
├── docker/                                                      │
│   └── docker-compose.yml  Isaac Sim 컨테이너 정의              │
├── isaac_scripts/                                               │
│   └── launch_sim.py       Newton + bridge + rclpy sidechannel ┘
├── robots/                 robot-specific 영역 (pack 하나당 1 디렉토리)
│   └── ur5e/
│       ├── robot.yaml      pack 계약 (조인트·게인·토픽)
│       ├── convert_urdf.py URDF → USD 변환 (pack 단위)
│       ├── urdf/           ur_description 원본 URDF + mesh
│       └── usd/            변환 결과 (convert 실행 후 생성)
└── docs/
    ├── ARCHITECTURE.md     시스템 설계 상세 + 레이어 분리
    ├── ROBOTS.md           pack 규약, 새 로봇 추가법
    ├── SETUP.md            환경 구축 & 최초 기동
    └── TROUBLESHOOTING.md  알려진 문제 / 해결 (6.0.0-dev2 이슈 포함)
```

## 현재 진행 Phase

- [x] Phase 1 — Repo 스캐폴드
- [x] Phase 2 — Docker 환경 정의
- [x] Phase 3 — `launch_sim.py` 최소본 (Newton + `/clock`)
- [x] Phase 0 — 실제 기동 & Newton 활성 런타임 검증 (Newton Physics experience, GUI up)
- [x] Phase 4 — Bridge 통신 검증 (호스트에서 `/clock` ≈ 60Hz 수신, FastDDS UDPv4 전송)
- [~] Phase 5 — UR5e 로드 + joint bridge
    - [x] URDF → USD 변환, GUI 에 UR5e 표시, `/clock` 정상
    - [x] OmniGraph joint bridge 포기 (PhysX-tensor SEGV) → rclpy sidechannel 구현
    - [ ] 컨테이너 기동 + 호스트 `ros2 topic hz /joint_states` 검증
- [ ] Phase 6 — robot-agnostic 레이어 검증 + 두 번째 로봇 (hand) 투입

자세한 설계 논의는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), robot pack 규약은 [docs/ROBOTS.md](docs/ROBOTS.md), 셋업 절차는 [docs/SETUP.md](docs/SETUP.md), 트러블슈팅은 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Isaac Sim 6.0.0-dev2 pre-release 주의

6.0.0 은 아직 개발 중이라 공식 5.x 대비 몇 가지 함정이 있습니다. 전부 `docs/TROUBLESHOOTING.md` 에 근거와 함께 정리돼 있음.

- `omni.*` → `isaacsim.*` 네임스페이스 마이그레이션 중 (구 이름은 silent no-op).
- 기본 ENTRYPOINT 가 streaming kiosk 라서 `python.sh` + `isaacsim.exp.full.newton.kit` 로 override 필요.
- 번들 rclpy 는 `/isaac-sim/exts/isaacsim.ros2.core/jazzy/lib` — `LD_LIBRARY_PATH` 에 명시해야 bridge 가 뜸.
- `World()` backend 를 명시 (`torch`, `cuda:0`) 안 하면 `world.reset` 에서 numpy↔torch mismatch 로 `.detach()` 터짐.
- PhysX-tensor OmniGraph joint 노드 (`ROS2PublishJointState`, `IsaacArticulationController`) 는 Newton articulation 위에서 SEGV. 그래서 joint 경로는 rclpy sidechannel 사용.

## Hard constraints

- Newton backend 활성 상태 런타임 assertion (PhysX fallback 금지)
- `ROS_DOMAIN_ID` 호스트·컨테이너 일치
- `network_mode: host` 유지 (DDS discovery)
- Isaac Sim 이미지 태그: `nvcr.io/nvidia/isaac-sim:6.0.0-dev2`
- `launch_sim.py` 에 로봇 식별자 하드코딩 금지 — 모든 로봇 의존성은 `robots/<name>/` 에
