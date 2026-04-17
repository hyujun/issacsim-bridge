# Robots

`launch_sim.py` 는 로봇에 대해 모릅니다. 실행 시 `ROBOT_PACK` 환경변수 하나만 보고, 해당 디렉토리의 **robot pack** 규약대로 에셋과 설정을 읽어 스테이지에 로드합니다. 새 로봇을 추가하는 일은 곧 새 pack 을 만드는 일입니다.

## 레이어 경계

| 레이어 | 성격 | 위치 |
|---|---|---|
| Isaac Sim bootstrap (Newton, ROS 2 bridge, `/clock`, joint bridge 루프) | **robot-agnostic** | `isaac_scripts/launch_sim.py` |
| Sim/infra 설정 (Docker, ROS 도메인, FastDDS 전송) | **robot-agnostic** | `docker/`, `install.sh`, `build.sh`, `run.sh` |
| URDF, USD, joint 이름, home pose, drive 게인 | **robot-specific** | `robots/<name>/` |

`launch_sim.py` 안에는 로봇 이름·조인트 수·드라이브 튜닝이 하드코딩돼 있지 않습니다. 반대로 `robots/<name>/` 안에는 Isaac Sim 부트스트랩 코드가 들어가지 않습니다.

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
  joints_subpath: Physics             # prim_path 밑에서 joint 를 찾을 하위 스코프

joint_names:                          # /joint_states, /joint_command 순서가 이 순서로 고정
  - joint_a
  - joint_b

home_pose:                            # 현재는 참고용 (호스트에서 /joint_command 로 적용)
  joint_a: 0.0
  joint_b: 0.0

drive:
  mode: position                      # 현재 position 만 구현
  stiffness: 10000.0
  damping: 100.0

ros:
  joint_states_topic: /joint_states
  joint_command_topic: /joint_command
  publish_rate_hz: 100
```

## 런타임 계약

`launch_sim.py` 가 pack 에 대해 가정하는 것:

1. `{prim_path}/{joints_subpath}/<joint_name>` 경로에 `PhysicsRevoluteJoint` prim 이 존재한다.
2. 그 prim 에 `UsdPhysics.DriveAPI:angular` 와 `UsdPhysics.JointStateAPI:angular` schema 가 붙어 있다.
3. 각도 단위는 USD 규약 대로 **degree** (내부에서 ROS 의 radian 과 변환).

위 조건은 Isaac Sim 6.0.0-dev2 의 `URDFImporter` 기본 출력에서 자동으로 충족됩니다. 다른 importer 를 쓰면 pack 에서 변환해 맞추거나 `joints_subpath` 만 조정하면 됩니다.

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
