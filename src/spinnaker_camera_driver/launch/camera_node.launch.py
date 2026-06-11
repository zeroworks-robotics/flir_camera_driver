# -----------------------------------------------------------------------------
# camera_node.launch.py
#
# ROS2 port of the ROS1 (noetic) camera_node.launch:
#   - plain camera driver node (no composition) under namespace <camera_name>
#   - image_proc debayer pipeline alongside it
#   - parameter defaults reproduce the ROS1 cfg/Spinnaker.cfg tuning
#     (see docs/driver_source_changes.md in the migration workspace)
#
# Serial: the default ('0') auto-selects the first camera found (patched
# driver behavior, see src/camera.cpp openDevice()). With multiple cameras
# pass an explicit serial; find it via SpinView, /opt/spinnaker/bin/Enumeration,
# or the driver log (" instead found camera: <serial>").
# -----------------------------------------------------------------------------

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument as LaunchArg
from launch.actions import OpaqueFunction
from launch.substitutions import EnvironmentVariable
from launch.substitutions import LaunchConfiguration as LaunchConfig
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

# Reproduction of the ROS1 Spinnaker.cfg tuning (ROS1 name -> ROS2 name):
#   image_format_color_coding      -> pixel_format
#   isp_enable                     -> isp_enable
#   auto_white_balance             -> balance_white_auto
#   exposure_auto                  -> exposure_auto
#   auto_exposure_time_upper_limit -> auto_exposure_time_upper_limit
#   auto_gain                      -> gain_auto
#   auto_exposure_gain_upper_limit -> auto_exposure_gain_upper_limit
#   brightness                     -> black_level
#   gamma_enable / gamma           -> gamma_enable / gamma
#   acquisition_frame_rate(_enable)-> frame_rate(_enable)  [launch args below]
tuned_parameters = {
    'debug': False,
    'compute_brightness': False,
    'adjust_timestamp': True,
    'dump_node_map': False,
    'buffer_queue_size': 10,
    'trigger_mode': 'Off',
    # ---- image format ----
    'isp_enable': False,  # only valid with a Bayer pixel format!
    # ---- exposure ----
    'exposure_auto': 'Continuous',
    'auto_exposure_time_upper_limit': 12000.0,  # us
    # ---- gain ----
    'gain_auto': 'Continuous',
    'auto_exposure_gain_upper_limit': 45.0,  # dB
    # ---- black level (ROS1 "brightness") ----
    'black_level_selector': 'All',
    'black_level': 0.0,
    # ---- gamma ----
    'gamma_enable': False,
    # 'gamma': 0.7,  # not applied while gamma_enable is False (kept for reference)
    # ---- chunk data (image meta data) ----
    'chunk_mode_active': True,
    'chunk_selector_frame_id': 'FrameID',
    'chunk_enable_frame_id': True,
    'chunk_selector_exposure_time': 'ExposureTime',
    'chunk_enable_exposure_time': True,
    'chunk_selector_gain': 'Gain',
    'chunk_enable_gain': True,
    'chunk_selector_timestamp': 'Timestamp',
    'chunk_enable_timestamp': True,
}


def launch_setup(context, *args, **kwargs):
    """Create camera driver node and debayer node."""
    parameter_file = LaunchConfig('parameter_file').perform(context)
    if not parameter_file:
        parameter_file = PathJoinSubstitution(
            [FindPackageShare('spinnaker_camera_driver'), 'config', 'topRGB.yaml']
        )

    camera_name = LaunchConfig('camera_name')

    camera_node = Node(
        package='spinnaker_camera_driver',
        executable='camera_driver_node',
        output='screen',
        name=[camera_name],
        parameters=[
            tuned_parameters,
            {
                'parameter_file': parameter_file,
                'serial_number': [LaunchConfig('serial')],
                'frame_id': [camera_name],
                'pixel_format': LaunchConfig('encoding'),
                'balance_white_auto': LaunchConfig('color_balance'),
                'frame_rate_enable': ParameterValue(
                    LaunchConfig('control_frame_rate'), value_type=bool
                ),
                'frame_rate': ParameterValue(LaunchConfig('frame_rate'), value_type=float),
                'camerainfo_url': [LaunchConfig('camerainfo_url')],
            },
        ],
    )

    # debayer + rectify pipeline. The humble `image_proc` executable cannot be
    # used here: it spawns debayer + 2 rectify components WITHOUT the topic
    # remappings its comments claim, so the rectify nodes wait forever on
    # <camera_name>/image and warn "Topics ... do not appear to be synchronized".
    # Compose the components with explicit remappings instead (same wiring as
    # upstream image_proc.launch.py).
    image_proc_container = ComposableNodeContainer(
        name='image_proc_container',
        namespace=[camera_name],
        package='rclcpp_components',
        executable='component_container',
        output='screen',
        composable_node_descriptions=[
            # image_raw -> image_mono, image_color
            ComposableNode(
                package='image_proc',
                plugin='image_proc::DebayerNode',
                name='debayer_node',
                namespace=[camera_name],
            ),
            # image_mono + camera_info -> image_rect
            ComposableNode(
                package='image_proc',
                plugin='image_proc::RectifyNode',
                name='rectify_mono_node',
                namespace=[camera_name],
                remappings=[('image', 'image_mono')],
            ),
            # image_color + camera_info -> image_rect_color
            ComposableNode(
                package='image_proc',
                plugin='image_proc::RectifyNode',
                name='rectify_color_node',
                namespace=[camera_name],
                remappings=[
                    ('image', 'image_color'),
                    ('image_rect', 'image_rect_color'),
                ],
            ),
        ],
    )

    return [camera_node, image_proc_container]


def generate_launch_description():
    """Launch camera driver node + image_proc debayer node."""
    return LaunchDescription(
        [
            LaunchArg(
                'camera_name',
                default_value=['topRGB'],
                description='camera name (ros node name and topic namespace)',
            ),
            LaunchArg(
                'serial',
                default_value="'0'",
                description="FLIR serial number (in quotes!!); '0' auto-selects the first camera",
            ),
            LaunchArg(
                'parameter_file',
                default_value='',
                description='path to ros parameter definition file (default: config/topRGB.yaml)',
            ),
            LaunchArg(
                'control_frame_rate',
                default_value='True',
                description='enable manual frame rate control',
            ),
            LaunchArg(
                'frame_rate',
                default_value='30.0',
                description='frame rate in Hz (used when control_frame_rate is True)',
            ),
            LaunchArg(
                'encoding',
                default_value='BayerRG8',
                description='camera pixel format (isp_enable=False requires a Bayer format)',
            ),
            LaunchArg(
                'color_balance',
                default_value='Continuous',
                description='white balance mode: Off, Once or Continuous',
            ),
            LaunchArg(
                'camerainfo_url',
                default_value=['file://', EnvironmentVariable('HOME'), '/camera.yaml'],
                description='URL of the camera calibration file',
            ),
            OpaqueFunction(function=launch_setup),
        ]
    )
