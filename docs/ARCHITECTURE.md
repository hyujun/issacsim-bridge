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
   ├─ Newton GPU solve   (400Hz 목표, physics_dt = 1/400)
   │
   ├─ USD 상태 갱신 ──────────────┐
   │                               │
   ├─ OmniGraph tick               │  UsdPhysics.JointStateAPI:angular
   │   └─ ROS2PublishClock ──┐     │  UsdPhysics.DriveAPI:angular
   │                         │     │       ▲
   └─ simulation loop (Python)     │       │
        ├─ rclpy.spin_once(0)      │       │
        ├─ /joint_command →  ──────┼───────┘  (write drive target)
        └─ /joint_states  ← ───────┼──────── (read state position)
                                   │
                                   │  FastRTPS / CycloneDDS
                                   │  (network_mode: host)
                                   ▼
                             ros2 topic /clock, /joint_states, /joint_command
                                   [호스트 DDS]
```

`network_mode: host` 덕분에 컨테이너의 DDS 참여자는 호스트의 네트워크 스택을 그대로 공유합니다. 즉 컨테이너 내부와 호스트가 **동일 DDS 도메인**에 속하므로 별도의 브리지 프록시가 필요 없습니다.

## Joint bridge 경로 — OmniGraph 가 아닌 rclpy sidechannel

`/clock` 은 OmniGraph `ROS2PublishClock` 노드로 퍼블리시합니다. 반면 `/joint_states` · `/joint_command` 는 **OmniGraph 를 쓰지 않고** `launch_sim.py` 의 시뮬 루프 안에 심은 rclpy 노드로 처리합니다. 이유는 Isaac Sim 6.0.0-dev2 의 PhysX-tensor 기반 OmniGraph 노드 (`ROS2PublishJointState`, `IsaacArticulationController`) 가 Newton 이 만든 articulation 의 `URDFImporter` 출력을 삼키지 못하고 SEGV 하기 때문입니다. 자세한 내용은 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 의 "PhysX-tensor joint 노드 SEGV" 항목.

대안 경로:
- 읽기: 각 joint prim 의 `UsdPhysics.JointStateAPI:angular` → `state:angular:physics:position` attribute (degree) 를 스텝마다 읽어 radian 변환 후 `JointState` 로 퍼블리시.
- 쓰기: 수신한 `JointState` 의 포지션을 radian→degree 로 바꿔 `UsdPhysics.DriveAPI:angular` 의 `targetPosition` 에 기록. Stiffness/damping 은 pack 의 `robot.yaml` 에서 부트스트랩 단계에 주입.

이 경로는 backend (PhysX vs Newton) 와 articulation root 구현에 의존하지 않으므로 6.x dev 이미지 업그레이드에도 비교적 안전합니다.

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
| `physics_dt` | 1/400 s | `launch_sim.py` |
| `rendering_dt` | 1/60 s | `launch_sim.py` |
| `/clock` | physics tick 마다 | `ROS2PublishClock` OmniGraph |
| `/joint_states` | `publish_rate_hz` (기본 100Hz) | rclpy sidechannel (sim 루프) |
| `/joint_command` | 호스트 publish rate 에 따름 | rclpy sidechannel (sim 루프) |
| 호스트 `use_sim_time` | `/clock` 구독 | 호스트 ROS 2 노드 설정 |

호스트 노드가 `use_sim_time: true` 를 사용하면 시뮬 시간 기준으로 동작하므로 wall-clock drift 영향을 받지 않습니다.

## 레이어 분리 — agnostic vs robot-specific

Isaac Sim 부트스트랩은 로봇에 대해 모르도록 설계돼 있습니다. 실행 시 `ROBOT_PACK` 환경변수 하나로 `robots/<name>/` 디렉토리를 가리키고, `launch_sim.py` 는 그 pack 의 `robot.yaml` 만 참고해 USD 레퍼런스·조인트 경로·드라이브 게인·토픽 이름을 가져옵니다. 규약과 pack 추가 방법은 [ROBOTS.md](ROBOTS.md).

- **agnostic**: `isaac_scripts/launch_sim.py`, `docker/`, `install.sh` / `build.sh` / `run.sh`.
- **robot-specific**: `robots/<name>/` — URDF, USD, `robot.yaml`, `convert_urdf.py`.

이 경계를 넘지 않는 한 로봇을 바꿔 끼울 수 있습니다.

## 확장성 고려

- **호스트 ROS 2 제어기 추가**: `ros2_ws/` 를 별도 추가하고 `JointState` / `JointCommand` 토픽 바인딩. Bridge 는 이미 활성화 상태.
- **다중 환경 (parallel envs)**: Newton 의 GPU 병렬성을 쓰려면 씬을 복제하고 토픽을 namespace 분기. 단, `/clock` 은 글로벌.
- **새 로봇 투입**: `robots/<name>/` 추가 → `ROBOT=<name> ./run.sh convert` → `ROBOT=<name> ./run.sh`. 규약은 [ROBOTS.md](ROBOTS.md).
