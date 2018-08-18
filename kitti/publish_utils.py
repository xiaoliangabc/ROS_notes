#!/usr/bin/env python
import time
import cv2

import rospy
from visualization_msgs.msg import Marker, MarkerArray
from sensor_msgs.msg import Image, PointCloud2, PointField, Imu, NavSatFix
from geometry_msgs.msg import Point
import sensor_msgs.point_cloud2 as pcl2
import std_msgs.msg
from cv_bridge import CvBridge, CvBridgeError
import tf as ros_tf # ROS transformation library

LINES = [[0, 1], [1, 2], [2, 3], [3, 0]] # lower face
LINES+= [[4, 5], [5, 6], [6, 7], [7, 4]] # upper face
LINES+= [[4, 0], [5, 1], [6, 2], [7, 3]] # connect lower face and upper face
LINES+= [[4, 1], [5, 0]] # front face

FRAME_ID = "map" # the base coordinate name in rviz
LIFETIME = 0.1 # 1/rate

DETECTION_COLOR_MAP = {'Car': (255,255,0), 'Pedestrian': (0, 226, 255), 'Cyclist': (141, 40, 255)} # color for detection, in format bgr

def publish_camera(cam_pub, bridge, image, borders_2d_cam2s=None, object_types=None, log=False):
    """
    Publish image in bgr8 format
    If borders_2d_cam2s is not None, publish also 2d boxes with color specified by object_types
    If object_types is None, set all color to cyan
    """
    try:
        if borders_2d_cam2s is not None:
            for i, box in enumerate(borders_2d_cam2s):
                top_left = int(box[0]), int(box[1])
                bottom_right = int(box[2]), int(box[3])
                if object_types is None:
                    cv2.rectangle(image, top_left, bottom_right, (255,255,0), 2)
                else:
                    cv2.rectangle(image, top_left, bottom_right, DETECTION_COLOR_MAP[object_types[i]], 2)
        cam_pub.publish(bridge.cv2_to_imgmsg(image, "bgr8"))

    except CvBridgeError as e:
        rospy.loginfo(e)
    if log:
        rospy.loginfo("camera image published")

def publish_3dbox(markers_pub, corners_3d_velos, track_ids, object_types=None, publish_id=True, log=False):
    """
    Publish 3d boxes in velodyne coordinate, with color specified by object_types
    If object_types is None, set all color to cyan
    corners_3d_velos : list of (8, 4) 3d corners
    """
    marker_array = MarkerArray()
    for i, corners_3d_velo in enumerate(corners_3d_velos):
        track_id = track_ids[i]
        marker = Marker()
        marker.header.frame_id = FRAME_ID
        marker.header.stamp = rospy.Time.now()

        marker.id = track_id
        marker.action = Marker.ADD
        marker.lifetime = rospy.Duration(LIFETIME)
        marker.type = Marker.LINE_LIST

        if object_types is None:
            marker.color.r = 0.0
            marker.color.g = 1.0
            marker.color.b = 1.0
        else:
            b, g, r = DETECTION_COLOR_MAP[object_types[i]]
            marker.color.r = r/255.0
            marker.color.g = g/255.0
            marker.color.b = b/255.0

        marker.color.a = 1.0

        marker.scale.x = 0.1

        marker.points = []
        for l in LINES:
            p1 = corners_3d_velo[l[0]]
            marker.points.append(Point(p1[0], p1[1], p1[2]))
            p2 = corners_3d_velo[l[1]]
            marker.points.append(Point(p2[0], p2[1], p2[2]))
        marker_array.markers.append(marker)
        
        if publish_id:
            text_marker = Marker()
            text_marker.header.frame_id = FRAME_ID
            text_marker.header.stamp = rospy.Time.now()

            text_marker.id = track_id + 1000
            text_marker.action = Marker.ADD
            text_marker.lifetime = rospy.Duration(LIFETIME)
            text_marker.type = Marker.TEXT_VIEW_FACING

            p4 = corners_3d_velo[4] # upper front left corner

            text_marker.pose.position.x = p4[0]
            text_marker.pose.position.y = p4[1]
            text_marker.pose.position.z = p4[2] + 0.5

            text_marker.text = str(track_id)

            text_marker.scale.x = 1
            text_marker.scale.y = 1
            text_marker.scale.z = 1

            if object_types is None:
                text_marker.color.r = 0.0
                text_marker.color.g = 1.0
                text_marker.color.b = 1.0
            else:
                b, g, r = DETECTION_COLOR_MAP[object_types[i]]
                text_marker.color.r = r/255.0
                text_marker.color.g = g/255.0
                text_marker.color.b = b/255.0
            text_marker.color.a = 1.0
            marker_array.markers.append(text_marker)

    markers_pub.publish(marker_array)
    if log:
        rospy.loginfo("%d 3d boxes published"%len(corners_3d_velos))

def publish_car_fov(marker_pub):
    """
    Publish left and right 45 degree FOV lines
    """
    marker = Marker()
    marker.header.frame_id = FRAME_ID
    marker.header.stamp = rospy.Time.now()

    #marker.id = i-10
    marker.action = Marker.ADD
    marker.lifetime = rospy.Duration()
    marker.type = Marker.LINE_STRIP

    marker.color.r = 0.0
    marker.color.g = 1.0
    marker.color.b = 0.0
    marker.color.a = 1.0
    marker.scale.x = 0.2

    marker.points = []
    marker.points.append(Point(10, -10, 0))
    marker.points.append(Point(0, 0, 0))
    marker.points.append(Point(10, 10, 0))
    marker_pub.publish(marker)

def publish_point_cloud(pcl_pub, point_cloud, format='xyz', log=False):
    """
    Publish the point cloud in a specific format.
    Valid formats :
        'xyz'       : points with 3 channels, xyz coordinates.
        'xyzi'      : points with 4 channels, xyz coordinates and intensity.
        'xyzrgb'    : points with 4 channels, xyz coordinates and rgb color.
                      rgb should come with FLOAT32 format.
    """
    assert format in ['xyz', 'xyzi', 'xyzrgb'], \
        "please set the format in ['xyz', 'xyzi', 'xyzrgb'] according to the point cloud format!"

    #header
    header = std_msgs.msg.Header()
    header.stamp = rospy.Time.now()
    header.frame_id = FRAME_ID

    if format == 'xyz':
        pcl_msg = pcl2.create_cloud_xyz32(header, point_cloud[:, :3])

    elif format == 'xyzi':
        fields = [PointField('x', 0, PointField.FLOAT32, 1),
                  PointField('y', 4, PointField.FLOAT32, 1),
                  PointField('z', 8, PointField.FLOAT32, 1),
                  PointField('i', 12, PointField.FLOAT32, 1)]
        pcl_msg = pcl2.create_cloud(header, fields, point_cloud)

    elif format == 'xyzrgb':
        fields = [PointField('x', 0, PointField.FLOAT32, 1),
                  PointField('y', 4, PointField.FLOAT32, 1),
                  PointField('z', 8, PointField.FLOAT32, 1),
                  PointField('rgb', 12, PointField.FLOAT32, 1)]
        pcl_msg = pcl2.create_cloud(header, fields, point_cloud)

    pcl_pub.publish(pcl_msg)
    if log:
        rospy.loginfo("point cloud published")

def publish_imu(imu_pub, imu_data, log=False):
    """
    Publish IMU data
    """
    imu = Imu()
    imu.header.frame_id = FRAME_ID
    imu.header.stamp = rospy.Time.now()
    q = ros_tf.transformations.quaternion_from_euler(float(imu_data.roll), float(imu_data.pitch), \
                                                     float(imu_data.yaw)) # prevent the data from being overwritten
    imu.orientation.x = q[0]
    imu.orientation.y = q[1]
    imu.orientation.z = q[2]
    imu.orientation.w = q[3]
    imu.linear_acceleration.x = imu_data.af
    imu.linear_acceleration.y = imu_data.al
    imu.linear_acceleration.z = imu_data.au
    imu.angular_velocity.x = imu_data.wf
    imu.angular_velocity.y = imu_data.wl
    imu.angular_velocity.z = imu_data.wu

    imu_pub.publish(imu)
    if log:
        rospy.loginfo("imu msg published")

def publish_gps(gps_pub, gps_data, log=False):
    """
    Publish GPS data
    """
    gps = NavSatFix()
    gps.header.frame_id = FRAME_ID
    gps.header.stamp = rospy.Time.now()
    gps.latitude = gps_data.lat
    gps.longitude = gps_data.lon
    gps.altitude = gps_data.alt

    gps_pub.publish(gps)
    if log:
        rospy.loginfo("gps msg published")

def publish_location(loc_pub, points, log=False):
    marker = Marker()
    marker.header.frame_id = FRAME_ID
    marker.header.stamp = rospy.Time.now()

    #marker.id = i-10
    marker.action = Marker.ADD
    marker.lifetime = rospy.Duration()
    marker.type = Marker.LINE_STRIP

    marker.color.r = 1.0
    marker.color.g = 0.0
    marker.color.b = 0.0
    marker.color.a = 1.0
    marker.scale.x = 0.2

    marker.points = []
    for p in points:
        marker.points.append(Point(p[0], p[1], 0))

    loc_pub.publish(marker)
    if log:
        rospy.loginfo("locations published")