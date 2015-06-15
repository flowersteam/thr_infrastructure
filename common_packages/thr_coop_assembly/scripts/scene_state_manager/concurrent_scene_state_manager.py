#!/usr/bin/env python

import rospy, rospkg, tf, transformations
from thr_coop_assembly.srv import GetSceneState, GetSceneStateResponse
from thr_coop_assembly.msg import SceneState, Predicate, ActionHistoryEvent, RobotAction
from itertools import combinations
from threading import Lock
import json, cv2, cv_bridge
from numpy import zeros, uint8
from time import time
from sensor_msgs.msg import Image

class ConcurrentSceneStateManager(object):
    def __init__(self, rate):
        self.state = SceneState()
        self.rate = rospy.Rate(rate)
        self.world = "base"
        self.screwdriver = '/tools/screwdriver'
        self.state_lock = Lock()
        self.history_lock = Lock()
        self.attached = set()
        self.attaching_stamps = {}
        self.action_history_name = '/thr/action_history'

        # Action History
        # Stores some info about previously executed actions, useful to produce the predicates AT_HOME, BUSY, HOLDED, PICKED
        self.at_home = {'left': True, 'right': True}
        self.busy = {'left': False, 'right': False}
        self.holded = []
        self.picked = []

        try:
            self.objects = rospy.get_param('/thr/objects')[rospy.get_param('/thr/scene')]
        except KeyError:
            raise KeyError("Unable to read /thr/objects, have you used roslaunch to start this script?")
        self.scene = rospy.get_param('/thr/scene')

        self.rospack = rospkg.RosPack()
        with open(self.rospack.get_path("thr_coop_assembly")+"/config/poses.json") as f:
            self.poses = json.load(f) # TODO separate with scene name [self.scene]

        with open(self.rospack.get_path("thr_coop_assembly")+"/config/perception.json") as f:
            self.config = json.load(f)

        self.attached = [] # Pairs of attached objects on the form o1_o2 with o1<o2
        self.screwed = [] # Pairs of screwed objects (screwdriver 7 seconds => screwed ; screw + wrist > 0.6 m => attached)
        self.tfl = tf.TransformListener(True, rospy.Duration(5*60)) # TF Interpolation ON and duration of its cache = 5 minutes
        self.image_pub = rospy.Publisher('/robot/xdisplay', Image, latch=True, queue_size=1)
        rospy.Subscriber(self.action_history_name, ActionHistoryEvent, self.cb_action_event_received)

    def affected_to(self, type, side):
        return type in ['go_home_left', 'pick', 'give'] and side=='left' or \
               type in ['go_home_right', 'hold'] and side=='right'

    def cb_action_event_received(self, msg):
        #with self.history_lock:
            # Listening action history for predicate AT_HOME
            if msg.type==ActionHistoryEvent.FINISHED_SUCCESS and msg.action.type=='go_home_left':
                self.at_home['left'] = True
            elif msg.type==ActionHistoryEvent.FINISHED_SUCCESS and msg.action.type=='go_home_right':
                self.at_home['right'] = True
            elif msg.type==ActionHistoryEvent.STARTING and self.affected_to(msg.action.type, 'right') and msg.action.type!='go_home_right':
                self.at_home['right'] = False
            elif msg.type==ActionHistoryEvent.STARTING and self.affected_to(msg.action.type, 'left') and msg.action.type!='go_home_left':
                self.at_home['left'] = False

            # Listening action events for predicate BUSY
            if self.affected_to(msg.action.type, 'left'):
                self.busy['left'] = msg.type==ActionHistoryEvent.STARTING
            elif self.affected_to(msg.action.type, 'right'):
                self.busy['right'] = msg.type==ActionHistoryEvent.STARTING
            else:
                rospy.logerr("[Scene state manager] No arm is capable of {}{}, event ignored".format(msg.action.type, str(msg.action.parameters)))

            # Listening action events for predicates PICKED + HOLDED
            if msg.type==ActionHistoryEvent.STARTING and msg.action.type=='hold':
                self.holded = msg.action.parameters
            elif msg.type==ActionHistoryEvent.FINISHED_SUCCESS and msg.action.type=='pick':
                self.picked = msg.action.parameters
            elif msg.type==ActionHistoryEvent.FINISHED_SUCCESS and msg.action.type=='hold':
                self.holded = []
            elif msg.type==ActionHistoryEvent.FINISHED_SUCCESS and msg.action.type=='give':
                self.picked = []

    def pred_holded(self, obj):
        #with self.history_lock:
            return obj in self.holded

    def pred_picked(self, obj):
        #with self.history_lock:
            return obj in self.picked

    def pred_at_home(self, side):
        #with self.history_lock:
            return self.at_home[side]

    def pred_busy(self, side):
        #with self.history_lock:
            return self.busy[side]

    def pred_positioned(self, master, slave, atp):
        """
        Checks if any constraint between master and slave exists at attach point atp and returns True if the constraint is within the tolerance
        :param master:
        :param slave:
        :param atp: (int)
        :return: True if predicate POSITIONED(master, slave, atp) is True
        """
        if master+slave+str(atp) in self.attached:
            return True
        try:
            # WARNING: Do not ask the relative tf directly, it is outdated!
            tf_slave = self.tfl.lookupTransform(self.world, slave, rospy.Time(0))
            tf_master = self.tfl.lookupTransform(self.world, master, rospy.Time(0))
        except Exception, e:
            pass
        else:
            relative = transformations.multiply_transform(transformations.inverse_transform(tf_master), tf_slave)
            constraint = self.poses[master]['constraints'][atp][slave]
            cart_dist = transformations.distance(constraint, relative)
            quat_dist = transformations.distance_quat(constraint, relative)
            return cart_dist<self.config['position_tolerance'] and quat_dist<self.config['orientation_tolerance']
        return False

    def pred_attached(self, master, slave, atp):
        if master+slave+str(atp) in self.attached:
            return True
        elif master+slave+str(atp) in self.screwed:
            try:
                distance_wrist_gripper = transformations.norm(self.tfl.lookupTransform('right_gripper', "/human/wrist", rospy.Time(0)))
            except:
                rospy.logwarn("Human wrist not found")
                return False
            if distance_wrist_gripper > self.config['hold']['sphere_radius']:
                self.attached.append(master+slave+str(atp))
                return True
        elif self.pred_positioned(master, slave, atp):
            try:
                # WARNING: Do not ask the relative tf directly, it is outdated!
                screwdriver = self.tfl.lookupTransform(self.world, self.screwdriver, rospy.Time(0))
                tf_master = self.tfl.lookupTransform(self.world, master, rospy.Time(0))
            except:
                rospy.logwarn("screwdriver or {} not found, I consider that you're NOT attaching {} and {}".format(master, master, slave))
            else:
                relative = transformations.multiply_transform(transformations.inverse_transform(tf_master), screwdriver)
                cart_dist = transformations.distance(relative, self.poses[master]['constraints'][atp][self.screwdriver])
                if cart_dist<self.config['tool_position_tolerance']:
                    try:
                        if time()-self.attaching_stamps[master][slave]>self.config['screwdriver_attaching_time']:
                            rospy.logwarn("[Scene state manager] User has attached {} and {}".format(master, slave))
                            self.screwed.append(master+slave+str(atp))
                    except KeyError:
                        if not self.attaching_stamps.has_key(master):
                            self.attaching_stamps[master] = {}
                        self.attaching_stamps[master][slave] = time()
        return False

    def pred_in_human_ws(self, obj):
        try:
            return transformations.norm(self.tfl.lookupTransform(obj, "/table", rospy.Time(0)))<self.config['in_human_ws_distance']
        except:
            return False

    def handle_request(self, req):
        resp = GetSceneStateResponse()
        self.state_lock.acquire()
        try:
            resp.state = self.state # TODO deepcopy?
        finally:
            self.state_lock.release()
        return resp

    def display_image(self, width, height):
        img = zeros((height,width, 3), uint8)
        preds = {"attached": [], "in_hws": [], "positioned": [], "busy": [], "picked": [], "holded": [], "at_home": []}
        self.state_lock.acquire()
        try:
            for p in self.state.predicates:
                if p.type=='in_human_ws':
                    preds["in_hws"].append(p)
                elif p.type=='positioned':
                    preds["positioned"].append(p)
                elif p.type=='attached':
                    preds["attached"].append(p)
                elif p.type=='picked':
                    preds["picked"].append(p)
                elif p.type=='holded':
                    preds["holded"].append(p)
                elif p.type=='busy':
                    preds["busy"].append(p)
                elif p.type=='at_home':
                    preds["at_home"].append(p)
        finally:
            self.state_lock.release()

        # Now draw the image with opencv
        line = 1
        for i_pred, pred in preds.iteritems():
            cv2.putText(img, '#'+i_pred.upper()+' ['+str(len(pred))+']', (10, 20*line), cv2.FONT_HERSHEY_SIMPLEX, 0.55, [255]*3)
            line+=1
            for i, p in enumerate(pred):
                cv2.putText(img, str(p.parameters), (50, 20*line), cv2.FONT_HERSHEY_SIMPLEX, 0.5, [180]*3)
                line += 1
        #cv2.imshow("Predicates", img)
        #cv2.waitKey(1)
        msg = cv_bridge.CvBridge().cv2_to_imgmsg(img, encoding="bgr8")
        self.image_pub.publish(msg)

    def run(self):
        while not rospy.is_shutdown():
            with self.state_lock:
                self.state.predicates = []
                self.state.header.stamp = rospy.Time.now()
                for o in self.objects:
                    if self.pred_in_human_ws(o):
                        p = Predicate()
                        p.type = 'in_human_ws'
                        p.parameters = [o]
                        self.state.predicates.append(p)
                    elif self.pred_picked(o):
                        p = Predicate()
                        p.type = 'picked'
                        p.parameters = [o]
                        self.state.predicates.append(p)
                    elif self.pred_picked(o):
                        p = Predicate()
                        p.type = 'holded'
                        p.parameters = [o]
                        self.state.predicates.append(p)
                for o1, o2 in combinations(self.objects, 2):
                    if self.poses[o1].has_key('constraints') and len([c for c in self.poses[o1]['constraints'] if o2 in c])>0:
                        master = o1
                        slave = o2
                    elif self.poses[o2].has_key('constraints') and len([c for c in self.poses[o2]['constraints'] if o1 in c])>0:
                        slave = o1
                        master = o2
                    else:
                        continue
                    for atp in range(len(self.poses[master]['constraints'])):
                        if self.pred_positioned(master, slave, atp):
                            p = Predicate()
                            p.type = 'positioned'
                            p.parameters = [master, slave, str(atp)]
                            self.state.predicates.append(p)
                        if self.pred_attached(master, slave, atp):
                            p = Predicate()
                            p.type = 'attached'
                            p.parameters = [master, slave, str(atp)]
                            self.state.predicates.append(p)
                with self.history_lock:
                    for side in ['left', 'right']:
                        if self.pred_busy(side):
                            p = Predicate()
                            p.type = 'busy'
                            p.parameters.append(side)
                            self.state.predicates.append(p)
                        if self.pred_at_home(side):
                            p = Predicate()
                            p.type = 'at_home'
                            p.parameters.append(side)
                            self.state.predicates.append(p)

            self.display_image(1024, 600)
            self.rate.sleep()

    def start(self):
        rospy.Service('/thr/scene_state', GetSceneState, self.handle_request)
        rospy.loginfo('[SceneStateManager] server ready to track {}...'.format(str(self.objects)))
        self.run()

if __name__ == "__main__":
    rospy.init_node('concurrent_scene_state_manager')
    ConcurrentSceneStateManager(20).start()