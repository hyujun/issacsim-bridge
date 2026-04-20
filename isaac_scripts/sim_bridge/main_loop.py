"""Main simulation loop: two modes, shared command/publish plumbing.

freerun (default): continuous step(render=True) at rendering_dt cadence, state
publishes on a wall-clock timer (publish_rate_hz).

sync: external controller drives via /joint_command. Each received command ->
one world.step(render=False) -> one /joint_states publish. When no command
arrives within sync_timeout_s wall-clock, a heartbeat step fires with the last
target so sim-time keeps advancing. Render is decoupled via maybe_render(),
which calls simulation_app.update() on a render_rate_hz wall-clock cadence
regardless of the command flow — GUI stays live even with no controller.

Both modes publish header.stamp in sim-time (omni.timeline), consistent with
the /clock topic, so use_sim_time=true subscribers see matching stamps.
"""

import time

import omni.timeline
import rclpy
import torch
from sensor_msgs.msg import JointState

from sim_bridge.config import ROBOT_CFG, SIM_CFG


def _sim_time_stamp(timeline, stamp) -> None:
    t = timeline.get_current_time()
    stamp.sec = int(t)
    stamp.nanosec = int((t - int(t)) * 1e9)


def run(
    simulation_app,
    world,
    articulation,
    dof_index_map: dict,
    ros_node,
    js_pub,
    latest_cmd: dict,
    max_run_seconds: float = 0.0,
) -> None:
    """Orchestrate the sim loop.

    max_run_seconds: if > 0, auto-close after that many wall-clock seconds.
    Used by the Phase 1.2 smoke-test harness (SIM_MAX_RUN_SECONDS env).
    """
    timeline = omni.timeline.get_timeline_interface()
    joint_names = list(ROBOT_CFG["joint_names"])
    _device = torch.device("cuda:0")
    indices0 = torch.tensor([0], dtype=torch.int32, device=_device)
    target_buffer = torch.zeros((1, articulation.max_dofs), dtype=torch.float32, device=_device)
    deadline = (time.monotonic() + max_run_seconds) if max_run_seconds > 0 else float("inf")

    def apply_cmd() -> None:
        cmd_positions = latest_cmd["positions"]
        if cmd_positions is None:
            return
        # Seed from current targets so unlisted DOFs keep their last commanded value.
        target_buffer.copy_(articulation.get_dof_position_targets(copy=True))
        for name, pos_rad in zip(latest_cmd["names"], cmd_positions):
            idx = dof_index_map.get(name)
            if idx is not None:
                target_buffer[0, idx] = float(pos_rad)
        articulation.set_dof_position_targets(target_buffer, indices0)
        latest_cmd["positions"] = None

    def publish_state() -> None:
        positions = articulation.get_dof_positions(copy=True).detach().cpu().numpy()
        msg = JointState()
        _sim_time_stamp(timeline, msg.header.stamp)
        msg.name = joint_names
        msg.position = [float(positions[0, dof_index_map[n]]) for n in joint_names]
        js_pub.publish(msg)

    try:
        if SIM_CFG["mode"] == "sync":
            _run_sync(simulation_app, world, ros_node, latest_cmd, apply_cmd, publish_state, deadline)
        else:
            _run_freerun(simulation_app, world, ros_node, apply_cmd, publish_state, deadline)
    finally:
        ros_node.destroy_node()
        rclpy.shutdown()
        simulation_app.close()


def _run_freerun(simulation_app, world, ros_node, apply_cmd, publish_state, deadline: float) -> None:
    pub_interval = 1.0 / float(ROBOT_CFG["ros"]["publish_rate_hz"])
    next_pub_time = 0.0
    while simulation_app.is_running():
        world.step(render=True)
        apply_cmd()
        rclpy.spin_once(ros_node, timeout_sec=0.0)
        now = time.monotonic()
        if now >= next_pub_time:
            publish_state()
            next_pub_time = now + pub_interval
        if now >= deadline:
            return


def _run_sync(simulation_app, world, ros_node, latest_cmd, apply_cmd, publish_state, deadline: float) -> None:
    import carb

    render_dt = 1.0 / float(SIM_CFG["render_rate_hz"])
    timeout_s = float(SIM_CFG["sync_timeout_s"])
    spin_timeout = 0.001
    last_render = 0.0
    first_cmd_logged = False

    def maybe_render() -> None:
        nonlocal last_render
        now = time.perf_counter()
        if now - last_render >= render_dt:
            simulation_app.update()
            last_render = now

    def wait_cmd_or_timeout() -> bool:
        """Block on /joint_command or sync_timeout_s wall-clock. GUI stays live."""
        deadline = time.perf_counter() + timeout_s
        while simulation_app.is_running():
            if latest_cmd["positions"] is not None:
                return True
            if time.perf_counter() >= deadline:
                return False
            rclpy.spin_once(ros_node, timeout_sec=spin_timeout)
            maybe_render()
        return False

    carb.log_warn(
        f"[sync] waiting for /joint_command (timeout={timeout_s}s, "
        f"step_rate={SIM_CFG['step_rate_hz']}Hz, render={SIM_CFG['render_rate_hz']}Hz)"
    )
    while simulation_app.is_running():
        got_cmd = wait_cmd_or_timeout()
        if not simulation_app.is_running():
            break
        if got_cmd:
            if not first_cmd_logged:
                carb.log_warn("[sync] first command received, entering lock-step loop")
                first_cmd_logged = True
            apply_cmd()
        # Heartbeat path reuses whatever targets PhysX already holds.
        world.step(render=False)
        publish_state()
        maybe_render()
        if time.monotonic() >= deadline:
            return
