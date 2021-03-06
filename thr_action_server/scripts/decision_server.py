#! /usr/bin/env python
import rospy
import json
import rospkg
import actionlib

from actionlib_msgs.msg import GoalStatus
from thr_infrastructure_msgs.srv import StartStopEpisode, StartStopEpisodeRequest, StartStopEpisodeResponse
from thr_infrastructure_msgs.msg import RunRobotActionAction, RunRobotActionGoal, RunDecisionGoal, RunDecisionAction, ActionHistoryEvent, Decision

class DecisionServer:
    """
    This is the action server that transforms a Decision in Robot action for the concurrent system.
    """
    def __init__(self):
        # Action server attributes
        self.sequence = 1
        self.server = actionlib.SimpleActionServer('/thr/run_decision', RunDecisionAction, self.execute, False)
        self.rospack = rospkg.RosPack()
        self.current_actions = {'right': None, 'left': None}
        self.action_history_name = '/thr/action_history'
        self.action_history = rospy.Publisher(self.action_history_name, ActionHistoryEvent, queue_size=10)

        with open(self.rospack.get_path("thr_action_server")+"/config/decision_action_mapping.json") as f:
            self.mapping = json.load(f)
        with open(self.rospack.get_path("thr_action_server")+"/config/action_params.json") as f:
            self.action_params = json.load(f)

        # Connect to inner action servers L/R
        self.clients = {'left': actionlib.SimpleActionClient('/thr/robot_run_action/left', RunRobotActionAction),
                        'right': actionlib.SimpleActionClient('/thr/robot_run_action/right', RunRobotActionAction)}
        for name, client in self.clients.iteritems():
            rospy.loginfo('Decision server for concurrent mode is waiting for action server '+name)
            client.wait_for_server()

        self.server.start()
        self.start_stop_service_name = '/thr/action_server/start_stop'
        rospy.Service(self.start_stop_service_name, StartStopEpisode, self.cb_start_stop)

    def cb_start_stop(self, request):
        if request.command == StartStopEpisodeRequest.START:
            rospy.set_param('/thr/action_server/stopped', False)
        elif request.command == StartStopEpisodeRequest.STOP:
            self.clients['left'].cancel_all_goals()
            self.clients['right'].cancel_all_goals()
            # Execute the go_homes and wait for them before stopping
            self.execute(RunDecisionGoal(decision=Decision(type='start_go_home_left')), force=True)
            self.execute(RunDecisionGoal(decision=Decision(type='start_go_home_right')), force=True)
            self.clients['left'].wait_for_result()
            self.clients['right'].wait_for_result()
            rospy.set_param('/thr/action_server/stopped', True)
        return StartStopEpisodeResponse()

    def execute(self, decision_goal, force=False):
        """
        Execute a goal if the server is started or if force mode is enabled
        :param decision_goal: The Decision to execute
        :param force: True when execution must be forced, e.g. this is an internal goal not coming from a client
        """
        if force or not rospy.get_param('/thr/action_server/stopped'):
            robot_goal = RunRobotActionGoal()
            try:
                robot_goal.action.type = self.mapping[decision_goal.decision.type]['type']
                client = self.mapping[decision_goal.decision.type]['client']
            except KeyError as k:
                rospy.logerr("No client is capable of action {}{}: KeyError={}".format(decision_goal.decision.type, str(decision_goal.decision.parameters), k.message))
                if not force:  # Decision goals sent by clients fail only if they are not mapped to robot actions
                    self.server.set_aborted()
            else:
                robot_goal.action.id = self.sequence
                robot_goal.action.parameters = decision_goal.decision.parameters
                self.clients[client].send_goal(robot_goal)
                self.current_actions[client] = robot_goal.action

                # Publish the event to the action history topic
                event = ActionHistoryEvent()
                event.header.stamp = rospy.Time.now()
                event.type = ActionHistoryEvent.STARTING
                event.action = robot_goal.action
                event.side = client
                self.action_history.publish(event)

                if not force:  # Decision goals sent by clients always succeed otherwise
                    self.server.set_succeeded()
        else:
            rospy.logwarn("Decision server stopped, ignoring goal sent without force mode")

    def should_interrupt(self):
        """
        :return: True if motion should interrupts at that time for whatever reason
        """
        return rospy.is_shutdown() or self.server.is_preempt_requested()

    def update_status(self):
        """
        This method gets the status of the children action clients and update the Decision server according to them.
        :return:
        """
        for side, action in self.current_actions.iteritems():
            if action: # If an action is running for this arm...
                robot_state = self.clients[side].get_state()
                if robot_state not in [GoalStatus.PENDING, GoalStatus.ACTIVE]: # ... and the action server reports it's ended...
                    state = self.clients[side].get_state()
                    # Publish the event to the action history topic
                    event = ActionHistoryEvent()
                    event.header.stamp = rospy.Time.now()
                    event.type = ActionHistoryEvent.FINISHED_SUCCESS if state == GoalStatus.SUCCEEDED else ActionHistoryEvent.FINISHED_FAILURE
                    event.action = action
                    event.side = side
                    self.action_history.publish(event)
                    self.current_actions[side] = None

    def start(self):
        while not rospy.is_shutdown():
            self.update_status()
            rospy.sleep(self.action_params['sleep_step'])

if __name__ == '__main__':
    rospy.init_node('robot_action_server')
    server = DecisionServer()
    server.start()