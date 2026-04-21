# Isaac Sim 네이티브 기능 이관 계획

목적: 현재 워크스페이스의 우회 코드 (USD runtime patch + rclpy sidechannel) 를 Isaac Sim 네이티브 API 로 교체하고, Sensor API · USD Composer workflow · GUI 버튼 인터랙션을 추가한다.

범위는 3 개 Phase:

- **Phase 1 — 축 A 네이티브 API 이관 (우선)**
- **Phase 2 — 축 B 부분 (Sensor API · USD Composer)**
- **Phase 3 — GUI 버튼 인터랙션**

각 단계마다 이 문서의 체크박스와 "상태" 를 실시간 업데이트한다.

---

## Resume Point (2026-04-21 세션 종료 시점)

**새 대화에서 시작하려면**: 아래 스냅샷을 읽고, "다음 작업" 섹션에서 한 항목을 선택해서 착수하면 됩니다.

### 완료 요약

| Phase | 상태 | 핵심 산출물 |
|---|---|---|
| 1.1 이미지 태그 재평가 | ✅ | `6.0.0-dev2` 유지 결정. 네이티브 전환 타겟 4개 확인 (`isaacsim.core.experimental.prims.Articulation`, `isaacsim.ros2.nodes`, `ROS2PublishJointState` sensor-input 경로, `IsaacReadJointState`) |
| 1.2 USD 패치 per-patch 검증 | ✅ | USD 패치 4 → 2 감소 (`strip_zero_mass_api` · `populate_robot_schema_links` 삭제). 테스트 인프라 초안 + docker smoke harness 신설 |
| 6 robot-agnostic 레이어 검증 (side-quest) | ✅ | 정적 감사 · pack-declared `host_deps.txt` · `validate_robot_config` · runtime DOF 어써션 · `pytest -m phase6` dual-pack regression gate · `run.sh list` · 스키마 청소 (`joints_subpath` 제거) |

### 다음 대화 진입 체크리스트

1. `git log --oneline -5` 로 마지막 커밋 확인.
2. 호스트 유닛 테스트 상태 확인:
   ```bash
   cd isaac_scripts && pytest isaacsim_bridge/tests/ -v --ignore=isaacsim_bridge/tests/integration
   # 32/32 통과해야 정상 (config validator 9 tests + dof_map 10 tests + config base 13 tests)
   ```
3. 본 문서 "전체 진행 순서" (최하단) 를 읽고 착수할 Phase 선택.

### 다음 작업 (independent · 병렬 가능)

**옵션 A — Phase 3 (GUI 버튼 패널)** — 리스크 낮음, 독립적
- 선행 조건: 없음
- 착수: [isaac_scripts/isaacsim_bridge/](../isaac_scripts/isaacsim_bridge/) 에 `ui_panel.py` 신설 → `omni.ui.Window` + `robot.yaml::gui.buttons` 기반 동적 버튼. 상세는 본 문서 "Phase 3" 섹션 (체크리스트 포함).
- 테스트: 액션 dispatch 를 `set_targets(targets, latest_cmd)` 같은 순수 함수로 분리 → 호스트 유닛 테스트 가능. GUI 자체는 컨테이너 smoke test.

**옵션 B — Phase 1.3 (OmniGraph 네이티브 joint bridge)** — 리스크 중간, 파급 큼
- 선행 조건: 없음 (1.2 완료 상태에서 바로 가능). Phase 6 regression gate 가 먼저 깔려 있어 1.3 변경이 agnostic 경계를 부수면 즉시 감지됨.
- 착수: `isaacsim.ros2.nodes` + `isaacsim.sensors.physics.nodes` 를 [launch_sim.py:52-54](../isaac_scripts/launch_sim.py#L52-L54) 의 `enable_extension` 목록에 추가 → `/World/ROS2JointStateGraph` OmniGraph 에 `IsaacReadJointState` + `ROS2PublishJointState` (sensor-input 경로) 구성 → smoke test 로 SEGV 재현 여부 확인.
- smoke test: 기존 [run_smoke.sh](../isaac_scripts/isaacsim_bridge/tests/integration/run_smoke.sh) 에 새 env flag (`SIM_BRIDGE_MODE=omnigraph|rclpy`) 추가해서 양쪽 경로 비교. `pytest -m phase6` 으로 두 pack 모두 regress 없는지 확인.
- 실패 시 (SEGV 재현): 현재 rclpy sidechannel 유지하고 주석에 "PhysX-tensor SEGV still blocks on image vX.Y.Z" 기록 + 다음 릴리스 대기.

### 현재 코드 상태 요약

- **USD 패치 2 종** 만 활성: `repair_joint_chain` (body0 star topology 수정), `apply_drive_gains_to_joints` (stiffness/damping 주입 + mimic follower skip). 둘 다 skip 시 각각 `max_dofs=0` / OmniGraph 코어 세그폴트 재현 확정.
- **ROS bridge 는 여전히 rclpy sidechannel** — [isaacsim_bridge/ros_bridge.py](../isaac_scripts/isaacsim_bridge/ros_bridge.py) 의 `setup_rclpy_bridge()`. OmniGraph 네이티브 전환은 Phase 1.3 에서 수행.
- **Articulation 경로** 는 여전히 Newton tensor ArticulationView — [isaacsim_bridge/newton_view.py](../isaac_scripts/isaacsim_bridge/newton_view.py). `isaacsim.core.experimental.prims.Articulation` 전환은 Phase 1.4 에서 수행 (1.3 결과에 따라 필요 여부 결정).
- **Pack contract**: [isaacsim_bridge/config.py::validate_robot_config](../isaac_scripts/isaacsim_bridge/config.py) 가 bootstrap 시 lazy 로 자동 호출. 누락 필드·빈 joint_names·잘못된 drive.mode·urdf 미발견 한 번에 보고. [newton_view.py::setup_newton_articulation](../isaac_scripts/isaacsim_bridge/newton_view.py) 은 `max_dofs == len(joint_names)` 를 런타임 assert.
- **Pack host apt deps**: 각 pack 의 `robots/<name>/host_deps.txt` 에서 선언. `install.sh` 가 글롭 합집합 설치. agnostic `install.sh` 에는 robot-specific 리터럴 없음.
- **테스트 인프라**: 32 host unit tests (config 13 + config validator 9 + dof_map 10) + docker smoke harness (`isaacsim_bridge/tests/integration/`). `pytest -m phase12` 로 per-patch 회귀 검증, `pytest -m phase6` 로 pack 별 agnostic-layer regression 재실행. Phase 6 harness 는 `robots/*/robot.yaml` auto-discover — 새 pack 자동 등록.
- **환경 변수**: [launch_sim.py:33-35](../isaac_scripts/launch_sim.py#L33-L35) 의 `SIM_HEADLESS`, `SIM_SKIP_PATCHES`, `SIM_MAX_RUN_SECONDS`.

---

## Phase 1 — 네이티브 API 이관

### 1.1 Isaac Sim 이미지 태그 재평가 ✅ (2026-04-20)

**결론**: `6.0.0-dev2` 유지. 업그레이드 필요 없음 (NVIDIA 이력에서 최신 dev 태그). 이미지에 이미 번들돼 있으나 미사용인 네이티브 기능 4 개 확인 → Phase 1.3 / 1.4 재정의의 근거가 됨:

- **`isaacsim.core.experimental.prims.Articulation`** — Newton-aware wrapper, `fetch_articulation_root_api_prim_paths()` 내장. 우리 [find_articulation_root_path()](../isaac_scripts/isaacsim_bridge/robot.py#L51-L69) + Newton ArticulationView 래핑을 대체 가능 → Phase 1.4 전환 타겟.
- **`isaacsim.ros2.nodes`** — `isaacsim.ros2.bridge` 에서 분리된 노드 묶음. 추가 `enable_extension` 필요.
- **`ROS2PublishJointState` v1.10.0** (2026-03-05) — sensor-input 경로로 변경. `targetPrim` 대신 `IsaacReadJointState` 출력을 연결하는 것이 권장. Phase 1.3 SEGV 회피 가능성.
- **`isaacsim.sensors.physics.nodes` → `IsaacReadJointState`** — PhysX-tensor 직결 아닌 sensor abstraction. SEGV 원인을 우회할 후보.

URDFImporter **3.2.1** (2026-03-09) 번들. CHANGELOG 에 body0 star topology / MassAPI / DriveAPI gain 관련 항목 없음 — 패치 필요 여부는 1.2 에서 per-patch 실측.

---

### 1.2 USD 런타임 패치 per-patch 검증 ✅ (2026-04-20)

URDFImporter 3.2.1 출력에 대해 기존 4 개 패치를 하나씩 skip 하며 smoke test. 결과 **2 개 제거** (`strip_zero_mass_api` — MassAPI 가 더 이상 virtual 링크에 붙지 않음; `populate_robot_schema_links` — 패치가 실제로 무효). `repair_joint_chain` 은 여전히 필수 (skip → `max_dofs=0`). `apply_drive_gains` 는 **필수로 격상** — skip 시 OmniGraph 코어 **하드 세그폴트** (이전 이미지에서는 cosmetic warning 에 불과했음).

남은 활성 패치 2 종과 재현 시나리오 상세: [memory/urdfimporter_600_dev2_quirks.md](../../../.claude/projects/-home-junho-ros2-ws-isaacsim-bridge/memory/urdfimporter_600_dev2_quirks.md) · [docs/TROUBLESHOOTING.md#drive-gain-누락](TROUBLESHOOTING.md).

신설된 테스트 인프라 (이후 Phase 에서 재사용 중):

- 호스트 유닛 pytest (`isaacsim_bridge/tests/test_{config,dof_map}.py`).
- [tests/integration/run_smoke.sh](../isaac_scripts/isaacsim_bridge/tests/integration/run_smoke.sh) — `docker compose run --rm` 헤드리스 smoke wrapper.
- [tests/integration/test_phase1_2_usd_patches.py](../isaac_scripts/isaacsim_bridge/tests/integration/test_phase1_2_usd_patches.py) — per-patch 회귀 harness (`pytest -m phase12`).
- [launch_sim.py](../isaac_scripts/launch_sim.py) 의 `SIM_HEADLESS` / `SIM_SKIP_PATCHES` / `SIM_MAX_RUN_SECONDS` 환경 변수.

---

### 1.3 Joint bridge → OmniGraph 네이티브 (sensor-input 경로)

**상태: ⏳ 예정**

목표: [isaac_scripts/isaacsim_bridge/ros_bridge.py](../isaac_scripts/isaacsim_bridge/ros_bridge.py) 의 rclpy sidechannel 을 `IsaacReadJointState` (sensor) → `ROS2PublishJointState` (sensor-input) OmniGraph 그래프로 교체. `/joint_command` 측은 `ROS2SubscribeJointState` + `IsaacArticulationController` 조합 또는 sensor-input 기반 대안으로 구성.

#### 절차

1. 실험 브랜치에서 `isaacsim.ros2.nodes` + `isaacsim.sensors.physics.nodes` enable 추가.
2. `/World/ROS2JointStateGraph` OmniGraph 추가 — 노드 구성:
   - `OnPlaybackTick`
   - `IsaacReadJointState` (inputs:prim = articulation root)
   - `ReadSimTime`
   - `ROS2PublishJointState` (inputs 는 sensor output 경유, targetPrim 비사용)
3. smoke test: UR5e 에서 bootstrap 완료 후 `ros2 topic hz /joint_states` 로 퍼블리시 확인. SEGV 재현 여부 관찰.
4. `/joint_command` 측 smoke test:
   - 1st 시도: `ROS2SubscribeJointState` → `IsaacArticulationController` 전통 경로. SEGV 발생 시 롤백.
   - 2nd 시도 (1st 실패 시): `ROS2SubscribeJointState` → Python callback → `isaacsim.core.experimental.prims.Articulation.set_dof_position_targets()`.
5. 두 경로 모두 통과 시 [main_loop.py](../isaac_scripts/isaacsim_bridge/main_loop.py) 의 `apply_cmd` / `publish_state` / rclpy spin 제거. 루프는 `world.step` + `simulation_app.update` 만.
6. sync 모드 호환: OmniGraph 는 `OnPlaybackTick` 으로만 트리거. sync 에서는 `world.step(render=False)` 뒤 수동 그래프 evaluate 고려 필요. 설계 결정 후 문서화.
7. 실패 시 현재 rclpy sidechannel 로 롤백. 주석 추가: *"PhysX-tensor SEGV still blocks on image vX.Y.Z"*.

#### 체크리스트

- [ ] 확장 enable 추가 + 기동 smoke test
- [ ] IsaacReadJointState → ROS2PublishJointState 그래프 동작 확인 (`ros2 topic hz /joint_states`)
- [ ] PhysX-tensor SEGV 미재현 확인
- [ ] `/joint_command` 경로 선정 + 구현
- [ ] sync 모드 호환 검증
- [ ] [ros_bridge.py](../isaac_scripts/isaacsim_bridge/ros_bridge.py) / [main_loop.py](../isaac_scripts/isaacsim_bridge/main_loop.py) 에서 rclpy sidechannel 제거
- [ ] [docs/ARCHITECTURE.md](ARCHITECTURE.md) · [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) 갱신

---

### 1.4 Newton ArticulationView → `isaacsim.core.experimental.prims.Articulation`

**상태: ⏳ 예정 (1.3 통과 후)**

목표: [newton_view.py](../isaac_scripts/isaacsim_bridge/newton_view.py) 의 Newton tensor ArticulationView 를 `isaacsim.core.experimental.prims.Articulation` 로 교체. `isaacsim.core.experimental.prims.Articulation.fetch_articulation_root_api_prim_paths()` 가 내부적으로 ArticulationRootAPI 를 탐색하므로 [find_articulation_root_path()](../isaac_scripts/isaacsim_bridge/robot.py#L51-L69) 도 제거.

주의: 1.3 이 OmniGraph 만으로 완결되면 Python 쪽 articulation 핸들 자체가 불필요해짐 → 1.4 스킵 가능. 1.3 에서 `/joint_command` 경로가 Python callback 으로 빠졌을 때만 1.4 필요.

#### 체크리스트

- [ ] 1.3 결과에 따라 1.4 필요 여부 결정
- [ ] (필요 시) `Articulation(prim_path)` 생성 + smoke test
- [ ] `set_dof_position_targets` / `get_dof_positions` 동작 검증
- [ ] Newton ArticulationView 관련 코드 제거
- [ ] 메모리 `newton_articulation_view_api.md` 갱신

---

### 1.5 문서 · 메모리 정리

**상태: ⏳ 예정 (1.2~1.4 완료 후)**

- [ ] [docs/ARCHITECTURE.md](ARCHITECTURE.md) 에서 삭제된 우회 경로 설명 제거
- [ ] [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) 에서 "PhysX-tensor joint 노드 SEGV" / "`UsdPhysics.JointStateAPI` 없음" 등 상태 업데이트
- [ ] `~/.claude/projects/.../memory/` stale 엔트리 갱신

---

## Phase 2 — 축 B 부분 (Sensor API · USD Composer)

### 2.1 Sensor API 통합

**상태: ⏳ 예정**

목표: `robot.yaml` 에 `sensors:` 섹션 추가 → [isaacsim_bridge/](../isaac_scripts/isaacsim_bridge/) 에 `sensors.py` 신설 → pack 별로 contact/IMU/camera 센서를 자동 부착 + ROS2 publish.

사용 확장:

- `isaacsim.sensors.physics` — contact sensor, IMU
- `isaacsim.sensors.camera` — RGB, depth
- `isaacsim.sensors.physics.nodes` — OG 바인딩 (contact force publisher 등)
- `isaacsim.sensors.rtx` — RTX Lidar

#### robot.yaml 스키마 확장안

```yaml
sensors:
  - type: contact
    prim_path: /World/Robot/.../tool0
    topic: /tool0/contact
  - type: imu
    prim_path: /World/Robot/.../base_link
    topic: /imu
    rate_hz: 200
  - type: camera
    prim_path: /World/Robot/.../camera_link
    topic_rgb: /camera/image_raw
    topic_depth: /camera/depth
    width: 640
    height: 480
    hfov_deg: 70
```

#### 체크리스트

- [ ] robot.yaml 스키마 설계 확정 (`docs/ROBOTS.md` 갱신)
- [ ] `isaacsim_bridge/sensors.py` 구현 (contact · IMU · camera 최소 3종)
- [ ] ur5e pack 에 FT · IMU 테스트 케이스 추가
- [ ] robotiq_2f_85 pack 에 contact sensor 테스트 케이스 추가
- [ ] ROS2 퍼블리시 토픽 smoke test (`ros2 topic hz`)

---

### 2.2 USD Composer workflows

**상태: ⏳ 예정**

목표: [robot.py::build_world()](../isaac_scripts/isaacsim_bridge/robot.py#L13-L40) 의 `add_default_ground_plane()` 하드코딩을 "베이스 씬 USD 레이어" 패턴으로 분리. 로봇은 sublayer composition 으로 올림.

#### 디렉토리 구조 안

```
scenes/
├── default_ground.usda     # 현재 add_default_ground_plane() 대체
├── warehouse.usda          # 창고 환경 샘플
└── empty.usda              # 빈 씬 (순수 로봇만)
```

`robot.yaml` 에 `scene_usd_rel: ../../scenes/default_ground.usda` 필드 추가 (선택, 생략 시 default_ground).

#### 체크리스트

- [ ] `scenes/default_ground.usda` 작성 (기존 `add_default_ground_plane` 결과를 export)
- [ ] `isaacsim_bridge/robot.py::build_world()` 에 sublayer composition 로직 추가
- [ ] `robot.yaml::scene_usd_rel` 처리 (optional, default fallback)
- [ ] ur5e · robotiq_2f_85 기동 smoke test (씬 교체 x2)
- [ ] [docs/ROBOTS.md](ROBOTS.md) 에 scene 레이어 섹션 추가

---

## Phase 3 — GUI 버튼 인터랙션

**상태: ⏳ 예정**

설계: `omni.ui` 기반 커스텀 윈도우. `robot.yaml` 의 `gui.buttons` 선언을 읽어 pack-specific 버튼을 동적으로 생성. 콜백은 공유 상태 (`latest_cmd` dict + `world` ref) 를 변경하고 기존 메인 루프가 다음 step 에서 반영.

### 구성 요소

**3.1 `isaacsim_bridge/ui_panel.py` 신설**
- `omni.ui.Window("Robot Bridge Control")` 생성
- `robot.yaml::gui.buttons` 순회 → `ui.Button(label, clicked_fn=_make_handler(action, params))` 생성
- sync 모드 호환: 버튼은 `latest_cmd` 업데이트만 수행 → 다음 step 에 반영

**3.2 robot.yaml 스키마 확장**

```yaml
gui:
  buttons:
    - label: "Go Home"
      action: set_targets
      targets:                    # joint_name → rad
        shoulder_pan_joint: 0.0
        shoulder_lift_joint: -1.57
        # ...
    - label: "Open Gripper"
      action: set_targets
      targets: { finger_joint: 0.0 }
    - label: "Reset World"
      action: reset_world
    - label: "Start Recording"
      action: trigger_topic
      topic: /record
      msg_type: std_msgs/Empty
```

**3.3 액션 종류 (최소 구현)**

| action | 효과 | 파라미터 |
|---|---|---|
| `set_targets` | `latest_cmd` 를 채움 → 메인 루프가 다음 step 에서 articulation 에 write | `targets: {joint_name: rad, ...}` |
| `reset_world` | `world.reset()` 호출 → 로봇 초기 자세 복귀 | (none) |
| `trigger_topic` | 미리 생성한 publisher 로 `std_msgs/Empty` 또는 비슷한 메시지 pub | `topic`, `msg_type` |

**3.4 바인딩**
- [launch_sim.py](../isaac_scripts/launch_sim.py) 의 `run(...)` 호출 직전에 `ui_panel.build(robot_cfg, shared_state)` 호출
- `shared_state = {"latest_cmd": latest_cmd, "world": world, "ros_node": ros_node}`

### 체크리스트

- [ ] `isaacsim_bridge/ui_panel.py` 스켈레톤 + Window 등록 확인
- [ ] robot.yaml `gui.buttons` 스키마 처리
- [ ] `set_targets` 액션 구현 + ur5e 에서 "Go Home" 검증
- [ ] `reset_world` 액션 구현 + 동작 검증
- [ ] `trigger_topic` 액션 구현 + `ros2 topic echo` 로 검증
- [ ] sync 모드 호환성 검증 (버튼 누른 뒤 lock-step 루프가 정상 반응)
- [ ] [docs/ROBOTS.md](ROBOTS.md) 에 `gui` 섹션 추가

---

## TODO — 축 B 나머지 (보류)

이번 이관에서 다루지 않는 확장 후보. 필요 시 별도 이슈/계획으로 분리.

- [ ] Isaac Lab / Gym envs — multi-env RL 병렬화
- [ ] Replicator — 도메인 랜덤화, synthetic data 생성

---

## 전체 진행 순서

```
1.1 이미지 태그 재평가 (완료)
   ↓
1.2 USD 패치 per-patch 검증          ──┐
                                        ├── 병렬 가능
Phase 3 GUI 버튼 인터랙션           ──┘  (1.1 결과만 필요, 나머지 phase 와 독립)
   ↓
1.3 OmniGraph 네이티브 joint bridge
   ↓
1.4 experimental.prims.Articulation 전환 (1.3 결과에 따라 선택적)
   ↓
2.1 Sensor API 통합
   ↓
2.2 USD Composer workflows
   ↓
1.5 문서 · 메모리 정리
```

Phase 3 (GUI) 는 Phase 1 과 독립적이므로 1.2/1.3 병행 진행 가능. 2.x 는 1.x 완료 후 시작 권장 (sensor 용 OmniGraph 경로가 1.3 네이티브 bridge 와 자연스럽게 같은 그래프에 합류).
