# Setup

## 호스트 요구사항

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS |
| GPU | NVIDIA (RTX 3070 Ti 기준 검증, 550+ driver) |
| RAM | 16GB 이상 권장 |
| Disk | 이미지 + 캐시 여유 **최소 40GB** |
| Network | NGC 에서 이미지 pull 가능 (IPv4 아웃바운드) |

## NGC 계정 & API 키

Isaac Sim 이미지는 `nvcr.io` 인증이 필요합니다.

1. <https://ngc.nvidia.com> 가입
2. 우측 상단 프로필 → **Setup → API Key → Generate**
3. 호스트에서 로그인:
   ```bash
   docker login nvcr.io
   # Username: $oauthtoken
   # Password: <API KEY>
   ```

## 스크립트별 역할

### `install.sh`
- NVIDIA 드라이버 가시성 확인 (`nvidia-smi`)
- Docker Engine 미설치 시 docker.com apt 저장소에서 설치
- 현재 사용자 `docker` 그룹 추가
- NVIDIA Container Toolkit 설치 & `docker` 재시작
- GPU 가시성 테스트 컨테이너 1회 실행
- `xhost +local:docker` 로 X11 권한 부여
- NGC 로그인 상태 확인
- `ros-jazzy-rmw-cyclonedds-cpp` (agnostic 기본 DDS) + `robots/*/host_deps.txt` 합집합 apt 설치 (예: `ros-jazzy-xacro`, `ros-jazzy-robotiq-description`). 각 pack 이 자신이 필요한 호스트 패키지를 manifest 로 선언.

**idempotent**: 이미 설치된 항목은 skip.

### `build.sh`
- `docker/docker-compose.yml` 기준 이미지 pull
- 최초 ~20GB, 10분 이상 소요

### `run.sh [subcommand]`
| 서브커맨드 | 동작 |
|---|---|
| (없음) / `up` | 포그라운드 기동 (로그 직접 확인) |
| `upd` | 디태치 기동 |
| `down` | 컨테이너 정지/삭제 |
| `logs` | 디태치 상태 로그 follow |
| `shell` | 실행 중 컨테이너에 bash 진입 |
| `restart` | down → up |
| `convert` | `$ROBOT_PACK/convert_urdf.py` 를 ephemeral 컨테이너로 실행해 USD 생성 |
| `list` | `robots/*/robot.yaml` 을 파싱해 사용 가능한 pack 목록 (이름 · DoF · sim.mode · root_link) 출력 |

pack 전환: `ROBOT=<name> ./run.sh ...` 또는 `ROBOT_PACK=/workspace/robots/<name> ./run.sh ...`. 기본값은 `ROBOT=ur5e`.

## 최초 기동 절차

```bash
cd isaacsim-bridge     # 클론한 디렉토리로 이동

./install.sh
# docker 그룹이 새로 추가되었다면:
newgrp docker      # 또는 재로그인

docker login nvcr.io    # NGC 인증 (한 번만)

./build.sh
./run.sh
```

Isaac Sim GUI 창이 뜨고, 터미널에는 다음 로그가 보여야 함 (UR5e pack 기준 — 숫자는 로봇마다 달라짐):

```
[launch_sim] Loading robot pack: /workspace/robots/ur5e
[launch_sim] Robot referenced: /workspace/robots/ur5e/usd/ur5e/ur5e.usda -> /World/Robot
[launch_sim] World dt: mode=freerun rendering_dt=0.01667s physics_dt=0.00417s substeps=4
[launch_sim] Repaired joint chain: rewrote body0 on 11 joints, kept 1 world-anchor joint(s)
[launch_sim] Patched 6 revolute joints with stiffness=10000.0, damping=100.0
[launch_sim] Newton articulation ready: count=1 max_dofs=6 yaml_joints=6 dof_names=['shoulder_pan_joint', ..., 'wrist_3_joint']
[launch_sim] rclpy bridge ready: publish /joint_states, subscribe /joint_command
[PhysicsBackendCheck] physxScene:solverType=TGS
[launch_sim] Newton + ROS2 bridge + robot bootstrap complete. Running simulation loop.
```

`yaml_joints` 는 `robot.yaml::joint_names` 길이, `max_dofs` 는 Newton articulation 의 실제 DoF. 불일치 시 `isaacsim_bridge.newton_view` 가 actionable RuntimeError 로 부팅 차단 — yaml 나 URDF 가 어긋났다는 신호.

`sim.mode: sync` 로 전환 시 대신 다음 로그가 추가로 보임:

```
[launch_sim] World dt: mode=sync rendering_dt=0.002s physics_dt=0.0005s substeps=4
...
[sync] waiting for /joint_command (timeout=0.5s, step_rate=500Hz, render=60Hz)
[sync] first command received, entering lock-step loop   # 첫 cmd 수신 시 1회
```

`count=1` 과 `max_dofs=<n>` 이 pack 의 `joint_names` 길이와 일치해야 합니다. `count=0` 이면 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 의 "Newton ArticulationView matched no articulations" / "Newton model articulations: [...] split" 참조.

## Bridge 동작 검증

별도 호스트 터미널:

```bash
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp   # 컨테이너 기본값과 일치
ros2 topic list                  # /clock 포함 여부
ros2 topic hz /clock             # 주기 측정
ros2 topic echo /clock --once    # 메시지 1건 확인
```

> 컨테이너·호스트 양쪽 모두 `RMW_IMPLEMENTATION` 이 일치해야 discovery 됨. 기본은 Cyclone DDS — FastDDS 의 root/user SHM 권한 문제가 원천적으로 없어 추가 transport 환경변수가 필요 없음. FastDDS 폴백은 아래 "DDS 구현 전환" 참조.

## 로봇 에셋 준비 (robot pack 규약)

로봇별 URDF · 설정 · 변환 스크립트는 `robots/<name>/` pack 한 곳에 모여 있습니다. 기본 로봇은 UR5e. 규약은 [docs/ROBOTS.md](ROBOTS.md).

컨테이너 기동 전에 USD 생성 (UR5e 의 경우 한 번만):

```bash
./run.sh convert                 # 기본 ROBOT=ur5e
# 또는 명시적으로
ROBOT=ur5e ./run.sh convert
```

성공 시 `robots/ur5e/usd/` 아래에 USD 번들이 생성됩니다. URDF (`robots/ur5e/urdf/ur5e.urdf`) 는 `/opt/ros/jazzy/share/ur_description` 에서 xacro 전개 후 mesh 상대경로로 고정된 결과가 이미 체크인돼 있습니다.

로봇 전환은 `ROBOT` 환경변수로:

```bash
ROBOT=my_arm ./run.sh            # robots/my_arm/ 를 로드
```

## Joint 토픽 검증

`launch_sim.py` 기동 후:

```bash
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 topic hz /joint_states
ros2 topic echo /joint_states --once

# shoulder_pan_joint 를 0.5 rad 로 이동 예시
ros2 topic pub --once /joint_command sensor_msgs/msg/JointState \
"{name: ['shoulder_pan_joint','shoulder_lift_joint','elbow_joint','wrist_1_joint','wrist_2_joint','wrist_3_joint'],
  position: [0.5, -1.5708, 1.5708, -1.5708, -1.5708, 0.0]}"
```

`ROS_DOMAIN_ID` 를 기본값(0) 외로 쓰고 싶다면:

```bash
ROS_DOMAIN_ID=7 ./run.sh        # 컨테이너에 주입
export ROS_DOMAIN_ID=7          # 호스트 쉘에서도 일치시켜야 discovery 됨
```

## 테스트

```bash
cd isaac_scripts
pytest isaacsim_bridge/tests/ -v --ignore=isaacsim_bridge/tests/integration
# 호스트 유닛 테스트 (config validator · DOF map). Isaac Sim 미필요, <1s.

pytest -m phase6 isaacsim_bridge/tests/integration/test_phase6_dual_pack.py -v
# Pack 별 agnostic-layer regression gate. robots/*/robot.yaml auto-discover.
# 컨테이너 부팅 ~60s/pack. 새 pack 추가 시 테스트 코드 수정 불필요.

pytest -m phase12 isaacsim_bridge/tests/integration/test_phase1_2_usd_patches.py -v
# USD 패치 per-patch 회귀 (URDFImporter 3.2.1 기준). 환경 업그레이드 후 재확인용.
```

## DDS 구현 전환

기본은 **Cyclone DDS** (`rmw_cyclonedds_cpp`). 컨테이너·호스트 양쪽 모두 같은 RMW 여야 discovery 됨. host 측 `ros-jazzy-rmw-cyclonedds-cpp` 는 `install.sh` 가 설치함. 컨테이너 측 `librmw_cyclonedds_cpp.so` 는 Isaac Sim 이미지에 이미 번들돼 있음.

FastDDS 로 폴백하려면 컨테이너·호스트 둘 다 override:

```bash
# 컨테이너
RMW_IMPLEMENTATION=rmw_fastrtps_cpp ./run.sh

# 호스트 쉘 (모든 ros2 CLI 세션마다)
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4   # 컨테이너(root)<->호스트(user) SHM 권한 회피, 양쪽 모두 필수
```

`FASTDDS_BUILTIN_TRANSPORTS=UDPv4` 는 `docker-compose.yml` 에 이미 영구 세팅돼 있어 컨테이너 쪽은 추가 작업 없음 — host 쉘만 export 해주면 됨. Cyclone 사용 시에는 이 변수 자체가 no-op.

## 종료

포그라운드 실행 시 GUI 창 닫기 또는 터미널 `Ctrl+C`.
디태치 실행 시:

```bash
./run.sh down
```
