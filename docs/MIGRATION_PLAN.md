# Isaac Sim 네이티브 기능 이관 계획

목적: 현재 워크스페이스의 우회 코드 (USD runtime patch + rclpy sidechannel) 를 Isaac Sim 네이티브 API 로 교체하고, Sensor API · USD Composer workflow · GUI 버튼 인터랙션을 추가한다.

범위는 3 개 Phase:

- **Phase 1 — 축 A 네이티브 API 이관 (우선)**
- **Phase 2 — 축 B 부분 (Sensor API · USD Composer)**
- **Phase 3 — GUI 버튼 인터랙션**

각 단계마다 이 문서의 체크박스와 "상태" 를 실시간 업데이트한다.

---

## Resume Point (2026-04-20 세션 종료 시점)

**새 대화에서 시작하려면**: 아래 스냅샷을 읽고, "다음 작업" 섹션에서 한 항목을 선택해서 착수하면 됩니다.

### 완료 요약

| Phase | 상태 | 핵심 산출물 |
|---|---|---|
| 1.1 이미지 태그 재평가 | ✅ | `6.0.0-dev2` 유지 결정. 네이티브 전환 타겟 4개 확인 (`isaacsim.core.experimental.prims.Articulation`, `isaacsim.ros2.nodes`, `ROS2PublishJointState` sensor-input 경로, `IsaacReadJointState`) |
| 1.2 USD 패치 per-patch 검증 | ✅ | USD 패치 4 → 2 감소 (`strip_zero_mass_api` · `populate_robot_schema_links` 삭제). 테스트 인프라 22 tests + docker smoke harness 신설 |

### 다음 대화 진입 체크리스트

1. `git log --oneline -5` 로 마지막 커밋 (Phase 1.2 마무리) 확인.
2. 호스트 유닛 테스트 상태 확인:
   ```bash
   cd isaac_scripts && pytest isaacsim_bridge/tests/ -v --ignore=isaacsim_bridge/tests/integration
   # 22/22 통과해야 정상
   ```
3. 본 문서 "전체 진행 순서" (최하단) 를 읽고 착수할 Phase 선택.

### 다음 작업 (independent · 병렬 가능)

**옵션 A — Phase 3 (GUI 버튼 패널)** — 리스크 낮음, 독립적
- 선행 조건: 없음
- 착수: [isaac_scripts/isaacsim_bridge/](../isaac_scripts/isaacsim_bridge/) 에 `ui_panel.py` 신설 → `omni.ui.Window` + `robot.yaml::gui.buttons` 기반 동적 버튼. 상세는 본 문서 "Phase 3" 섹션 (체크리스트 포함).
- 테스트: 액션 dispatch 를 `set_targets(targets, latest_cmd)` 같은 순수 함수로 분리 → 호스트 유닛 테스트 가능. GUI 자체는 컨테이너 smoke test.

**옵션 B — Phase 1.3 (OmniGraph 네이티브 joint bridge)** — 리스크 중간, 파급 큼
- 선행 조건: 없음 (1.2 완료 상태에서 바로 가능)
- 착수: `isaacsim.ros2.nodes` + `isaacsim.sensors.physics.nodes` 를 [launch_sim.py:53-55](../isaac_scripts/launch_sim.py#L53-L55) 의 `enable_extension` 목록에 추가 → `/World/ROS2JointStateGraph` OmniGraph 에 `IsaacReadJointState` + `ROS2PublishJointState` (sensor-input 경로) 구성 → smoke test 로 SEGV 재현 여부 확인.
- smoke test: 기존 [run_smoke.sh](../isaac_scripts/isaacsim_bridge/tests/integration/run_smoke.sh) 에 새 env flag (`SIM_BRIDGE_MODE=omnigraph|rclpy`) 추가해서 양쪽 경로 비교.
- 실패 시 (SEGV 재현): 현재 rclpy sidechannel 유지하고 주석에 "PhysX-tensor SEGV still blocks on image vX.Y.Z" 기록 + 다음 릴리스 대기.

### 현재 코드 상태 요약

- **USD 패치 2 종** 만 활성: `repair_joint_chain` (body0 star topology 수정), `apply_drive_gains_to_joints` (stiffness/damping 주입 + mimic follower skip). 둘 다 skip 시 각각 `max_dofs=0` / OmniGraph 코어 세그폴트 재현 확정.
- **ROS bridge 는 여전히 rclpy sidechannel** — [isaacsim_bridge/ros_bridge.py](../isaac_scripts/isaacsim_bridge/ros_bridge.py) 의 `setup_rclpy_bridge()`. OmniGraph 네이티브 전환은 Phase 1.3 에서 수행.
- **Articulation 경로** 는 여전히 Newton tensor ArticulationView — [isaacsim_bridge/newton_view.py](../isaac_scripts/isaacsim_bridge/newton_view.py). `isaacsim.core.experimental.prims.Articulation` 전환은 Phase 1.4 에서 수행 (1.3 결과에 따라 필요 여부 결정).
- **테스트 인프라**: 22 host unit tests (`isaacsim_bridge/tests/test_config.py`, `test_dof_map.py`) + docker smoke harness (`isaacsim_bridge/tests/integration/`). `pytest -m phase12` 로 per-patch 회귀 검증 재실행 가능.
- **환경 변수**: [launch_sim.py:34-36](../isaac_scripts/launch_sim.py#L34-L36) 의 `SIM_HEADLESS`, `SIM_SKIP_PATCHES`, `SIM_MAX_RUN_SECONDS`.

---

## Phase 1 — 네이티브 API 이관

### 1.1 Isaac Sim 이미지 태그 재평가

**상태: ✅ 완료 (2026-04-20)**

#### 조사 결과

현재 Docker 이미지: `nvcr.io/nvidia/isaac-sim:6.0.0-dev2` ([docker/docker-compose.yml:3](../docker/docker-compose.yml#L3)).

NVIDIA Isaac Sim 릴리스 이력 (`gh api repos/isaac-sim/IsaacSim/releases`):

| 태그 | 릴리스일 | 유형 |
|---|---|---|
| v5.0.0 | 2025-08-08 | GA |
| v5.1.0 | 2025-10-21 | GA (최신 stable) |
| v6.0.0-dev | 2025-12-19 | pre-release |
| **v6.0.0-dev2** | **2026-03-16** | **pre-release (최신, 현재 사용 중)** |

**결론 — 이미지 업그레이드 불가 · 불필요**: 2026-04-20 기준 `6.0.0-dev2` 가 최신이며 newer dev/stable 릴리스 없음. 현재 이미지를 유지하고 이 이미지 **안에 이미 들어있지만 사용하지 않는** 네이티브 기능을 활용하는 방향이 정답.

#### 현재 이미지 안에서 활용 가능한 네이티브 기능 (현재 미사용)

`docker run --rm --entrypoint ls … /isaac-sim/exts` 로 확인한 사용 가능 확장:

1. **`isaacsim.core.experimental.prims.Articulation`** — Newton 네이티브 대응 Articulation 래퍼.
   - 파일: `/isaac-sim/exts/isaacsim.core.experimental.prims/isaacsim/core/experimental/prims/impl/articulation.py`.
   - 제공 메서드: `set_dof_position_targets(data, indices)`, `get_dof_positions()`, `num_dofs`, `dof_names`, `joint_names` 등.
   - 경로 정규식 매칭 + 자동 ArticulationRootAPI prim 탐색 (`fetch_articulation_root_api_prim_paths`).
   - **우리 측 [find_articulation_root_path()](../isaac_scripts/isaacsim_bridge/robot.py#L51-L69) + Newton ArticulationView 래핑 전체를 대체 가능**.

2. **`isaacsim.ros2.nodes`** — `isaacsim.ros2.bridge` 에서 분리된 OmniGraph 노드 묶음.
   - 현재 [launch_sim.py:40](../isaac_scripts/launch_sim.py#L40) 는 구 `isaacsim.ros2.bridge` 만 enable 하고 있음 → `ROS2PublishJointState` 등의 노드 사용 시 새 확장 추가 enable 필요.

3. **`ROS2PublishJointState` 데이터 모델 변경 (v1.10.0, 2026-03-05)** — `isaacsim.ros2.nodes/docs/CHANGELOG.md` 인용:
   > *ROS2PublishJointState node now publishes from sensor inputs (e.g. IsaacReadJointState) for joint state data.*

   `.ogn` 정의 확인 (`OgnROS2PublishJointState.ogn`):
   - `jointNames`, `jointPositions`, `jointVelocities`, `jointEfforts`, `jointDofTypes`, `stageMetersPerUnit`, `sensorTime` 모두 **inputs** 으로 존재.
   - `targetPrim` 주석: *"connect instead of targetPrim for preferred path"* → **sensor 경유가 권장 경로**.

4. **`isaacsim.sensors.physics.nodes`** — `IsaacReadJointState` OmniGraph 노드 제공.
   - `inputs:prim` (target articulation 경로) → `outputs:jointNames, jointPositions, jointVelocities, jointEfforts, jointDofTypes, stageUnits, sensorTime, execOut`.
   - 이 노드가 articulation state 를 **PhysX tensor 직결이 아닌 sensor abstraction 을 경유**해 읽으므로, `docs/TROUBLESHOOTING.md` 의 "PhysX-tensor joint 노드 SEGV" 를 우회할 가능성이 큼 (smoke test 로 확정 필요).

5. **`IsaacArticulationController` 대안** — `/joint_command` 쪽은 기존 `IsaacArticulationController` 노드가 여전히 PhysX-tensor 직결이라 SEGV 재현 위험. 1.3 단계에서 smoke test 와 함께 대안 후보 (`isaacsim.core.experimental.prims.Articulation` Python bridge) 를 비교 평가.

#### URDFImporter 관련

- URDFImporter 현재 버전: **3.2.1 (2026-03-09)**. 이미지에 번들된 버전 (`/isaac-sim/exts/isaacsim.asset.importer.urdf/docs/CHANGELOG.md`).
- 3.0.0 (2026-02-01) 에서 "USD exchange based backend / Unified UI / Asset structure 3" 로 대전환.
- 3.1.0 (2026-02-26) 에서 Newton schema 대응 변환 속성 추가.
- 2.4.37 (2026-01-05) 에서 mimic 순서 버그 수정.
- **CHANGELOG 에 body0 star topology 수정 · 빈 MassAPI 억제 · DriveAPI gain 기본값 수정 관련 항목은 보이지 않음** → USD 런타임 패치 4종 중 1~3 은 여전히 필요할 가능성이 높음. 단 실제 재변환 후 per-patch 실험 필요 (1.2 에서 처리).

#### 1.1 의사결정

| 결정 | 이유 |
|---|---|
| 이미지 태그 유지 (`6.0.0-dev2`) | 최신 태그이며 다음 릴리스 미정 |
| Phase 1.3 을 "OmniGraph 네이티브 joint bridge" 로 재정의 | 새 sensor-input 데이터 모델이 SEGV 회피 가능성 제공 |
| Phase 1.4 을 "`isaacsim.core.experimental.prims.Articulation` 전환" 으로 재정의 | 네이티브 Newton-aware 래퍼 존재 확인 |
| 1.2 의 USD 패치 검증은 유지 | 재변환 후 각 patch on/off smoke test 필요 |

---

### 1.2 USD 런타임 패치 per-patch 검증

**상태: ✅ 완료 (2026-04-20)**

목표: [isaac_scripts/isaacsim_bridge/usd_patches.py](../isaac_scripts/isaacsim_bridge/usd_patches.py) 의 4 개 함수 각각이 URDFImporter 3.2.1 출력에서 여전히 필요한지 재확인.

#### 진행 절차

1. pytest 테스트 인프라 구축: [isaac_scripts/isaacsim_bridge/tests/](../isaac_scripts/isaacsim_bridge/tests/) 신설.
2. [isaacsim_bridge/config.py](../isaac_scripts/isaacsim_bridge/config.py) 를 순수 함수 기반으로 리팩터 (lazy module-level constants 로 하위 호환 유지).
3. [isaacsim_bridge/dof_map.py](../isaac_scripts/isaacsim_bridge/dof_map.py) 신설 — Newton 의존성 없는 DOF name ↔ index 매핑 순수 함수.
4. [launch_sim.py](../isaac_scripts/launch_sim.py) 에 `SIM_HEADLESS` / `SIM_SKIP_PATCHES` / `SIM_MAX_RUN_SECONDS` 환경 변수 추가.
5. [tests/integration/run_smoke.sh](../isaac_scripts/isaacsim_bridge/tests/integration/run_smoke.sh) — `docker compose run --rm` 래퍼로 헤드리스 smoke test 실행.
6. [tests/integration/test_phase1_2_usd_patches.py](../isaac_scripts/isaacsim_bridge/tests/integration/test_phase1_2_usd_patches.py) — 4 개 per-patch smoke test harness.

#### 유닛 테스트 결과

| 대상 | 테스트 수 | 결과 |
|---|---|---|
| [tests/test_config.py](../isaac_scripts/isaacsim_bridge/tests/test_config.py) | 12 | ✅ 12/12 |
| [tests/test_dof_map.py](../isaac_scripts/isaacsim_bridge/tests/test_dof_map.py) | 10 | ✅ 10/10 |
| **합계** | **22** | **✅ 22/22** |

#### Smoke test 결과 (UR5e, ur5e pack, URDFImporter 3.2.1)

baseline (모든 패치 활성): bootstrap @ 103.9s, max_dofs=6, 세그폴트 없음.

| 패치 | skip 시 증상 | 결정 |
|---|---|---|
| `repair_joint_chain` | `ArticulationView count=1 max_dofs=0` + `Newton model articulations: [12 entries]` (star topology) | **✅ 유지** |
| `strip_zero_mass_api` | baseline 과 동일 — "zero mass" 경고 **0 회** | **❌ 제거** (URDFImporter 3.2.1 이 MassAPI 를 더 이상 virtual 링크에 붙이지 않거나 Newton 이 경고 안 찍음) |
| `populate_robot_schema_links` | baseline 과 동일 — "missing from schema relationship" 경고 **1 회** (패치 적용과 동일) | **❌ 제거** (패치가 무효함. 경고는 cosmetic 이라 무해) |
| `apply_drive_gains` | OmniGraph 코어 **하드 세그폴트** during `/World/ROS2ClockGraph` 노드 생성 — 이전 memory 의 "unresolved target" 경고보다 훨씬 critical | **✅ 유지** |

#### 변경 사항

- [isaacsim_bridge/usd_patches.py](../isaac_scripts/isaacsim_bridge/usd_patches.py) 에서 `strip_zero_mass_api` / `populate_robot_schema_links` 함수 삭제. 모듈 docstring 에 제거 사유 기록.
- [launch_sim.py](../isaac_scripts/launch_sim.py) 의 `_PATCHES` 리스트 · imports 정리.
- 제거 후 재 smoke test: bootstrap @ 94.6s 정상 완료, max_dofs=6, 회귀 0건.

#### 체크리스트

- [x] baseline 기동 + 관측 로그 기록
- [x] `repair_joint_chain` 필요성 재확인 → **유지**
- [x] `strip_zero_mass_api` 필요성 재확인 → **제거**
- [x] `populate_robot_schema_links` 필요성 재확인 → **제거**
- [x] `apply_drive_gains_to_joints` (mimic skip 포함) 필요성 재확인 → **유지 (필수 격상)**
- [x] 불필요한 패치 삭제 + 문서 정리 (이 항목)
- [ ] robotiq_2f_85 에서도 동일 검증 (추후 — ur5e 에서 이미 확정)
- [ ] 메모리 `urdfimporter_600_dev2_quirks.md` 업데이트 (1.5 단계로 이관)

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
