from . action import Action
import rospy
import transformations
from numpy import array
from copy import deepcopy

class Place(Action):
    def __init__(self, commander, tf_listener, action_params, poses, seeds, should_interrupt=None):
        super(Place, self).__init__(commander, tf_listener, action_params, poses, seeds, should_interrupt)
        self.starting_state = self.commander.get_current_state()
        self.gripper = self.commander.name + '_gripper'


    def get_place_pose(self, location_T_object, object, location, viapoint=None):
        # Computes the world_T_gripper transform, taking into account the viapoint if it exists
        location_T_object = deepcopy(location_T_object)
        try:
            object_T_gripper = self.tfl.lookupTransform(object, self.gripper, rospy.Time(0))
            world_T_location = self.tfl.lookupTransform(self.world, location, rospy.Time(0))
        except KeyError:
            rospy.logerr("No declared pose to place {} at {}".format(object, location))
            return None
        if viapoint is not None:
            location_T_object[0] = list(array(location_T_object[0]) + array(self.poses[location]['place']['via']))

        location_T_gripper = transformations.multiply_transform(location_T_object, object_T_gripper)
        world_T_gripper = transformations.multiply_transform(world_T_location, location_T_gripper)
        return world_T_gripper

    def run(self, parameters=None):
        # Parameters could be "/thr/handle", it asks the robot to place the handle using the "place" pose (only 1 per object atm)
        rospy.loginfo("[ActionServer] Executing place{}".format(str(parameters)))
        object = parameters[0]
        location = parameters[1]  # TODO: Can we take coordinates in input as well?
        success = False

        # 1. Passing by the viapoint if it exists
        while not success and not self._should_interrupt():
            if not self.commander.gripping():
                rospy.logerr('Object {} is no longer gripped'.format(object))
                return False

            if 'via' in self.poses[location]['place']:
                rospy.loginfo("Approaching {} according to its viapoint".format(location))
                location_T_object = self.poses[location]['place'][object]
                world_T_gripper = self.get_place_pose(location_T_object, object, location, self.poses[location]['place']['via'])
                if world_T_gripper is None:
                    return False

                try:
                    # Use the rpy attribute hereunder to force PLACE to keep a specific orientation during motion (ex: placing a filled cup of tea)
                    #success = self.commander.move_to_controlled(world_T_gripper, rpy=[1, 1, 0], pause_test=self.pause_test, stop_test=self.stop_test)
                    success = self.commander.move_to_controlled(world_T_gripper, pause_test=self.pause_test, stop_test=self.stop_test)
                except ValueError:
                    rospy.logwarn("Viapoint of location {} found but not reachable, please move it a little bit...".format(location))
                    rospy.sleep(self.action_params['sleep_step'])
            else:
                # No viapoint
                break

        # 2. Placing the object
        rospy.loginfo("Placing {} at location {}".format(object, location))
        success = False
        while not success and not self._should_interrupt():
            if not self.commander.gripping():
                rospy.logerr('Object {} is no longer gripped'.format(object))
                return False

            try:
                distance_object_location = transformations.distance(self.tfl.lookupTransform(location, object, rospy.Time(0)), self.poses[location]['place'][object])
            except:
                rospy.logwarn("{} or {} not found".format(object, location))
                rospy.sleep(self.action_params['sleep_step'])
                continue

            rospy.loginfo("{} at {}m from {}, threshold {}m".format(object, distance_object_location, location, self.action_params['place']['sphere_radius']))
            if distance_object_location > self.action_params['place']['sphere_radius']:
                location_T_object = self.poses[location]['place'][object]
                world_T_gripper = self.get_place_pose(location_T_object, object, location)
                if world_T_gripper is None:
                    return False

                try:
                    # Use the rpy attribute hereunder to force PLACE to keep a specific orientation during motion (ex: placing a filled cup of tea)
                    #success = self.commander.move_to_controlled(world_T_gripper, rpy=[1, 1, 0], pause_test=self.pause_test, stop_test=self.stop_test)
                    success = self.commander.move_to_controlled(world_T_gripper, pause_test=self.pause_test, stop_test=self.stop_test)
                except ValueError:
                    rospy.logwarn("Location {} found but not reachable, please move it a little bit...".format(location))
                    rospy.sleep(self.action_params['sleep_step'])
                    continue
            else:
                success = True # Nothing to do, object already at its location

            if not success:
                rospy.sleep(1)

        if self._should_interrupt():
            return False

        # 3. Release object
        rospy.loginfo("Releasing {}".format(object))
        self.commander.open()

        # 4. Leaving object using the selected method grasp or pick
        method = 'grasp' if self.commander.name == 'right' else 'pick'
        pose = 0  # Grasp pose to be gotten from predicates if several ones exist?

        if 'descent' in self.poses[object][method][pose]:
            if not self.commander.translate_to_cartesian(list(-array(self.poses[object][method][0]['descent'])), object, 1., pause_test=self.pause_test, stop_test=self.stop_test):
                rospy.logerr("Unable to pull the gripper out")
                return False
        elif 'approach' in self.poses[object][method][pose]:
            rospy.loginfo("Leaving {}".format(object))
            approach = array(self.poses[object][method][pose]['approach'])[0]
            grasp = self.tfl.lookupTransform(object, self.gripper, rospy.Time(0))[0]
            pull_out = list(array(approach) - array(grasp))
            if not self.commander.translate_to_cartesian(pull_out, object, 1., pause_test=self.pause_test, stop_test=self.stop_test):
                rospy.logerr("Unable to pull the gripper out")
                return False
        else:
            rospy.logerr("No 'approach' nor 'descent' attribute defined for {}ing object {}".format(method, object))
            return False

        rospy.loginfo("[ActionServer] Executed place{} with {}".format(str(parameters), "failure" if self._should_interrupt() else "success"))
        return True
