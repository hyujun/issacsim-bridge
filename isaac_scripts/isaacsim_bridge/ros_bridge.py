"""ROS 2 wiring: /clock OmniGraph publisher + rclpy JointState sidechannel.

The PhysX-tensor OmniGraph joint nodes SEGV on URDFImporter output in
Isaac Sim 6.0.0-dev2, so we publish JointState and apply /joint_command via
an rclpy node instead of OmniGraph (see docs/TROUBLESHOOTING.md).
"""

import carb
import rclpy
from sensor_msgs.msg import JointState

from isaacsim_bridge.config import ROBOT_CFG


def setup_clock_publisher() -> None:
    import omni.graph.core as og

    keys = og.Controller.Keys
    og.Controller.edit(
        {"graph_path": "/World/ROS2ClockGraph", "evaluator_name": "execution"},
        {
            keys.CREATE_NODES: [
                ("OnPlaybackTick", "omni.graph.action.OnPlaybackTick"),
                ("ReadSimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
            ],
            keys.CONNECT: [
                ("OnPlaybackTick.outputs:tick", "PublishClock.inputs:execIn"),
                ("ReadSimTime.outputs:simulationTime", "PublishClock.inputs:timeStamp"),
            ],
            keys.SET_VALUES: [
                ("PublishClock.inputs:topicName", "/clock"),
            ],
        },
    )


def setup_rclpy_bridge() -> tuple:
    """Initialize rclpy, create publisher + subscriber, return (node, pub, latest_cmd)."""
    rclpy.init(args=[])
    node = rclpy.create_node("isaac_isaacsim_bridge")

    js_topic = ROBOT_CFG["ros"]["joint_states_topic"]
    jc_topic = ROBOT_CFG["ros"]["joint_command_topic"]

    js_pub = node.create_publisher(JointState, js_topic, 10)

    # Mutable container: callback mutates; main loop reads and clears.
    latest_cmd: dict = {"names": None, "positions": None}

    def _on_cmd(msg: JointState) -> None:
        latest_cmd["names"] = list(msg.name)
        latest_cmd["positions"] = list(msg.position)

    node.create_subscription(JointState, jc_topic, _on_cmd, 10)

    carb.log_warn(
        f"[launch_sim] rclpy bridge ready: publish {js_topic}, subscribe {jc_topic}"
    )
    return node, js_pub, latest_cmd
