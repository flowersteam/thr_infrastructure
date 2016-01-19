from . action import Action
import rospy
import transformations

class Place(Action):
    def __init__(self, commander, tf_listener, action_params, poses, seeds, should_interrupt=None):
        super(Place, self).__init__(commander, tf_listener, action_params, poses, seeds, should_interrupt)
        self.starting_state = self.commander.get_current_state()
        self.gripper_name = self.commander.name + '_gripper'

    def run(self, parameters=None):
        # Parameters could be "/thr/handle", it asks the robot to place the handle using the "place" pose (only 1 per object atm)
        rospy.loginfo("[ActionServer] Executing place{}".format(str(parameters)))
        object = parameters[0]
        location = parameters[1]  # TODO: Can we take coordinates in input as well?

        rospy.loginfo("Placing {} at location {}".format(object, location))
        while not self._should_interrupt():
            can_release = False
            try:
                distance_object_location = transformations.distance(self.tfl.lookupTransform(location, object, rospy.Time(0)), self.poses[location]['place'][object])
                object_T_gripper = self.tfl.lookupTransform(object, self.gripper_name, rospy.Time(0))
                world_T_location = self.tfl.lookupTransform(self.world, location, rospy.Time(0))
            except KeyError:
                rospy.logerr("No declared pose to place {} at {}".format(object, location))
                return False
            except:
                rospy.logwarn("{} or {} not found".format(object, location))
                rospy.sleep(self.action_params['sleep_step'])
                continue

            rospy.loginfo("{} at {}m from {}, threshold {}m".format(object, distance_object_location, location, self.action_params['place']['sphere_radius']))
            if distance_object_location > self.action_params['place']['sphere_radius']:

                location_T_gripper = transformations.multiply_transform(self.poses[location]['place'][object], object_T_gripper)
                world_T_gripper = transformations.multiply_transform(world_T_location, location_T_gripper)

                try:
                    success = self.commander.move_to_controlled(world_T_gripper, rpy=[1, 1, 0])
                except ValueError:
                    rospy.logwarn("Location {} found but not reachable, please move it a little bit...".format(location))
                    rospy.sleep(self.action_params['sleep_step'])
                    continue
                else:
                    if not success:
                        return False
            else:
                can_release = True

            if can_release and not rospy.is_shutdown():
                    rospy.loginfo("Releasing {}".format(object))
                    self.commander.open()
                    break
            else:
                rospy.sleep(1)

        rospy.loginfo("[ActionServer] Executed place{} with {}".format(str(parameters), "failure" if self._should_interrupt() else "success"))
        return True