#! /usr/bin/env python

import rospy, json
import actionlib

from thr_infrastructure_msgs.msg import *
from thr_infrastructure_msgs.srv import *
from actionlib_msgs.msg import GoalStatus

class InteractionController(object):

    def __init__(self):
        self.running = True
        self.current_scene = None
        self.previous_action = MDPAction(type='wait')
        self.scene_before_action = None
        self.run_action_name = '/thr/run_mdp_action'
        self.scene_state_service = '/thr/scene_state'

        self.logs = []

        # Initiating topics ands links to services/actions
        self.run_action_client = actionlib.SimpleActionClient(self.run_action_name, RunMDPActionAction)
        rospy.loginfo("Waiting action client {}...".format(self.run_action_name))
        self.run_action_client.wait_for_server()
        self.services = [self.scene_state_service]
        for service in self.services:
            rospy.loginfo("Waiting service {}...".format(service))
            rospy.wait_for_service(service)

        self.start_or_stop_episode(True)  # Start a new (and unique) episode

    def start_or_stop_episode(self, start=True):
        for node in ['scene_state_manager', 'action_server']:
            url = '/thr/{}/start_stop'.format(node)
            rospy.wait_for_service(url)
            rospy.ServiceProxy(url, StartStopEpisode).call(StartStopEpisodeRequest(
                command=StartStopEpisodeRequest.START if start else
                StartStopEpisodeRequest.STOP))

    ################################################# SERVICE CALLERS #################################################
    def update_scene(self):
        request = GetSceneStateRequest()
        try:
            getscene = rospy.ServiceProxy(self.scene_state_service, GetSceneState)
            self.current_scene = getscene(request).state
        except rospy.ServiceException, e:
            rospy.logerr("Cannot update scene {}:".format(e.message))

    def wizard_entry(self):
        while not rospy.is_shutdown():
            command = raw_input("> ").strip('\r\n').lower()
            parameters = []
            type = "wait"

            if len(command)<1 or len(command)>3:
                rospy.logerr("Invalid command {}".format(command))
                continue
            elif command[0] == 'w':
                type = 'wait'
            elif command[0] == 'p':
                type = 'start_pick'
            elif command[0] == 'h':
                type = 'start_hold'
            elif command[0] == 'g':
                type = 'start_give'
            elif command[0] == 'l':
                type = 'start_go_home_left'
            elif command[0] == 'r':
                type = 'start_go_home_right'
            elif command[0] == 'e':
                type = 'end'
            elif command[0] == 'f':
                type = 'fail'
            else:
                rospy.logerr("Invalid command {}".format(command))
                continue

            if type in ['start_pick', 'start_hold', 'start_give']:
                if len(command)<2:
                    rospy.logerr("Invalid command {}".format(command))
                    continue
                elif command[1] == 'h':
                    parameters.append('/toolbox/handle')
                elif command[1] == 'f':
                    parameters.append('/toolbox/side_front')
                elif command[1] == 'b':
                    parameters.append('/toolbox/side_back')
                elif command[1] == 'l':
                    parameters.append('/toolbox/side_left')
                elif command[1] == 'r':
                    parameters.append('/toolbox/side_right')
                else:
                    rospy.logerr("Invalid command {}".format(command))
                    continue

                if type in ['start_hold']:
                    if len(command)<3:
                        rospy.logerr("Invalid command {}".format(command))
                        continue
                    elif command[2] == '0':
                        parameters.append('0')
                    elif command[2] == '1':
                        parameters.append('1')
                    else:
                        rospy.logerr("Invalid command {}".format(command))
                        continue
            return type, parameters

    ###################################################################################################################

    def run(self):
        rospy.loginfo('Manual interaction starting from keyboard!')
        rospy.set_param('/thr/num_action', 1)
        try:
            while self.running and not rospy.is_shutdown():
                self.update_scene()
                ret = self.wizard_entry()
                if ret is not None:
                    type, params = ret
                    self.check_for_previous_actions()  # user inputs are blocking for this setup so update action state at the last time

                    self.logs.append({'timestamp': rospy.get_time(),
                                      'type': type,
                                      'parameters': params})
                    action = MDPAction(type=type, parameters=params)
                    self.run_action(action)
        finally:
            logs_name = rospy.get_param('/thr/logs_name')
            if logs_name != "none":
                with open('action_decisions_'+logs_name+'.json', 'w') as f:
                    json.dump(self.logs, f)


    def run_action(self, action):
        if self.previous_action.type=='wait':
            self.run_action_client.cancel_all_goals()
            self.scene_before_action = self.current_scene
            goal = RunMDPActionGoal()
            goal.action = action
            self.run_action_client.send_goal(goal)
            self.previous_action = action
            rospy.loginfo("You're asking to run action {}({})".format(action.type, ', '.join(action.parameters)))

    def check_for_previous_actions(self):
        if self.previous_action.type != 'wait' and self.run_action_client.get_state() not in [GoalStatus.PENDING, GoalStatus.ACTIVE]:  # ... and the action server reports it's ended...
            state = self.run_action_client.get_state()
            if state == GoalStatus.SUCCEEDED:
                rospy.loginfo("Action {}({}) succeeded!".format(self.previous_action.type, ', '.join(self.previous_action.parameters)))
            else:
                rospy.logwarn("Action {}({}) failed ;-(".format(self.previous_action.type, ', '.join(self.previous_action.parameters)))
            self.previous_action = MDPAction(type='wait')

if __name__=='__main__':
    rospy.init_node("interaction_controller")
    InteractionController().run()
