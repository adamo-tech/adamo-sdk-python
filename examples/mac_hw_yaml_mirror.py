"""Python equivalent of configs/mac-hw-test.yaml.

Mirrors:
    robot_name: macbook
    api_key:    ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6
    zenoh:      mode=client, protocol=quic
    track:      v4l2 1280x720@30, vtenc_h264, 2 Mbps
"""
import adamo

robot = adamo.Robot(
    api_key="ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6",
    name="macbook",
    protocol="quic",
)

robot.attach_video(
    "webcam",
    device=0,
    width=1280,
    height=720,
    fps=30,
    bitrate_kbps=2000,
    encoder="vtenc_h264",
)

robot.run()
