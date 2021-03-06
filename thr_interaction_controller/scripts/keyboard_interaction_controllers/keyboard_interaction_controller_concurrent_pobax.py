#! /usr/bin/env python

import rospy, json
import actionlib
import sys

from thr_infrastructure_msgs.msg import *
from thr_infrastructure_msgs.srv import *
from thr_interaction_controller.srv import *
from actionlib_msgs.msg import GoalStatus

class InteractionController(object):

    def __init__(self,comm_mode="woz"):
        self.running = True
        self.current_scene = None
        self.previous_decision = Decision(type='wait')
        self.scene_before_decision = None
        self.run_decision_name = '/thr/run_decision'
        self.scene_state_service = '/thr/scene_state'
        self.comm_mode = comm_mode

        self.logs = []

        # Initiating topics ands links to services/actions
        self.run_decision_client = actionlib.SimpleActionClient(self.run_decision_name, RunDecisionAction)
        rospy.loginfo("Waiting action client {}...".format(self.run_decision_name))
        self.run_decision_client.wait_for_server()
        self.services = [self.scene_state_service]
        for service in self.services:
            rospy.loginfo("Waiting service {}...".format(service))
            rospy.wait_for_service(service)

        self.start_or_stop_episode(True)  # Start a new (and unique) episode

        if self.comm_mode == "ros":
            # Init ROS service to send commands
            s = rospy.Service('/pobax_playground/baxter/command', BaxterCommand, self.cb_baxter_command)
            rospy.loginfo('Baxter interaction using ROS service!')   

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


    def cb_baxter_command(self,request): 
        try:
            self.update_scene()
            ret = self.preprocess_entry(request.cmd)
            if ret is not None:
                _, type, params = ret
                self.check_for_previous_decisions()  # user inputs are blocking for this setup so update action state at the last time
                self.logs.append({'timestamp': rospy.get_time(),
                                  'type': type,
                                  'parameters': params})
                decision = Decision(type=type, parameters=params)
                self.run_decision(decision)
        finally:
            logs_name = rospy.get_param('/thr/logs_name')
            if logs_name != "none":
                with open('decisions_'+logs_name+'.json', 'w') as f:
                    json.dump(self.logs, f)
        return BaxterCommandResponse("TODO put_error_message_here")



    def preprocess_entry(self,raw_cmd):
        command = raw_cmd.strip('\r\n').lower()
        parameters = []
        type = "wait"

        if len(command)<1 or len(command)>4:
                rospy.logerr("Invalid command {} (1a)".format(command))
                return False,None,None
        elif command[0] == 'l':
            type = 'start_go_home_left'
        elif command[0] == 'r':
            type = 'start_go_home_right'
        elif command[0] == 'g':
            type = 'start_grasp'
        elif command[0] == 'p':
            type = 'start_place_right'
        else:
            rospy.logerr("Invalid command {} (1b)".format(command))
            return False,None,None

        if type in ['start_grasp']:
            if len(command)<2:
                rospy.logerr("Invalid command {} (2c)".format(command))
                return False,None,None
            elif command[1] == '1':
                parameters.append('/culbuto/1')
            elif command[1] == '2':
                parameters.append('/culbuto/2')
            else:
                rospy.logerr("Invalid command {} (2d)".format(command))
                return False,None,None

        if type in ['start_place_right']:
            if len(command)<2:
                rospy.logerr("Invalid command {} (2e)".format(command))
                return False,None,None
            elif command[1] == '1':
                parameters += ['/culbuto/1', '/table']
            elif command[1] == '2':
                parameters += ['/culbuto/2', '/table']
            else:
                rospy.logerr("Invalid command {} (2f)".format(command))
                return False,None,None
        
        return True, type, parameters

    def wizard_entry(self):
        while not rospy.is_shutdown():
            command = raw_input("> ")
            valid, type, parameters = self.preprocess_entry(command)
            if valid:
                return type, parameters
            else:
                continue

    ###################################################################################################################

    def run(self):
        rospy.loginfo('Manual interaction starting from keyboard!')
        try:
            while self.running and not rospy.is_shutdown():
                self.update_scene()
                ret = self.wizard_entry()
                if ret is not None:
                    type, params = ret
                    self.check_for_previous_decisions()  # user inputs are blocking for this setup so update action state at the last time

                    self.logs.append({'timestamp': rospy.get_time(),
                                      'type': type,
                                      'parameters': params})
                    decision = Decision(type=type, parameters=params)
                    self.run_decision(decision)
        finally:
            logs_name = rospy.get_param('/thr/logs_name')
            if logs_name != "none":
                with open('decisions_'+logs_name+'.json', 'w') as f:
                    json.dump(self.logs, f)

    def run_decision(self, decision):
        if self.previous_decision.type== 'wait':
            self.run_decision_client.cancel_all_goals()
            self.scene_before_decision = self.current_scene
            goal = RunDecisionGoal()
            goal.decision = decision
            self.run_decision_client.send_goal(goal)
            self.previous_decision = decision
            rospy.loginfo("You're asking to run decision {}({})".format(decision.type, ', '.join(decision.parameters)))

    def check_for_previous_decisions(self):
        if self.previous_decision.type != 'wait' and self.run_decision_client.get_state() not in [GoalStatus.PENDING, GoalStatus.ACTIVE]:  # ... and the action server reports it's ended...
            state = self.run_decision_client.get_state()
            if state == GoalStatus.SUCCEEDED:
                rospy.loginfo("Decision {}({}) succeeded!".format(self.previous_decision.type, ', '.join(self.previous_decision.parameters)))
            else:
                rospy.logwarn("Decision {}({}) failed ;-(".format(self.previous_decision.type, ', '.join(self.previous_decision.parameters)))
            self.previous_decision = Decision(type='wait')

if __name__=='__main__':
    rospy.init_node("interaction_controller")

    if sys.argv[1] == "woz": #classical keyboard interaction
        InteractionController(comm_mode=sys.argv[1]).run()
    elif sys.argv[1] == "ros": #ros node providing a command service
        InteractionController(comm_mode=sys.argv[1])
        rospy.spin()