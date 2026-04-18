"""Main simulation loop: step world, apply joint commands, publish joint state."""

import time

import rclpy
import torch
from sensor_msgs.msg import JointState

from sim_bridge.config import ROBOT_CFG


def run(
    simulation_app,
    world,
    articulation,
    dof_index_map: dict,
    ros_node,
    js_pub,
    latest_cmd: dict,
) -> None:
    pub_interval = 1.0 / float(ROBOT_CFG["ros"]["publish_rate_hz"])
    next_pub_time = 0.0
    joint_names = list(ROBOT_CFG["joint_names"])
    _device = torch.device("cuda:0")
    indices0 = torch.tensor([0], dtype=torch.int32, device=_device)
    target_buffer = torch.zeros((1, articulation.max_dofs), dtype=torch.float32, device=_device)

    try:
        while simulation_app.is_running():
            world.step(render=True)

            cmd_positions = latest_cmd["positions"]
            if cmd_positions is not None:
                # Seed from current targets so unlisted DOFs keep their last commanded value.
                target_buffer.copy_(articulation.get_dof_position_targets(copy=True))
                for name, pos_rad in zip(latest_cmd["names"], cmd_positions):
                    idx = dof_index_map.get(name)
                    if idx is not None:
                        target_buffer[0, idx] = float(pos_rad)
                articulation.set_dof_position_targets(target_buffer, indices0)
                latest_cmd["positions"] = None

            rclpy.spin_once(ros_node, timeout_sec=0.0)

            now = time.monotonic()
            if now >= next_pub_time:
                positions = articulation.get_dof_positions(copy=True).detach().cpu().numpy()
                msg = JointState()
                msg.header.stamp = ros_node.get_clock().now().to_msg()
                msg.name = joint_names
                msg.position = [float(positions[0, dof_index_map[n]]) for n in joint_names]
                js_pub.publish(msg)
                next_pub_time = now + pub_interval
    finally:
        ros_node.destroy_node()
        rclpy.shutdown()
        simulation_app.close()
