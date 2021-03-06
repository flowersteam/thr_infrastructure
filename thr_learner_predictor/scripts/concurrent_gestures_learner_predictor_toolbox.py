#!/usr/bin/env python

from pyFolWorld import FolWorld
import rospy
import rospkg
from thr_infrastructure_msgs.srv import StartStopEpisode, StartStopEpisodeRequest, StartStopEpisodeResponse
from thr_infrastructure_msgs.srv import GetNextDecision, GetNextDecisionRequest, GetNextDecisionResponse
from thr_infrastructure_msgs.srv import SetNewTrainingExample, SetNewTrainingExampleRequest, SetNewTrainingExampleResponse
from thr_infrastructure_msgs.msg import Decision, Predicate

# To test this server, try: "rosservice call [/thr/learner or /thr/predictor] <TAB>"
# and complete the pre-filled request message before <ENTER>


class Server(object):
    def __init__(self):
        self.learner_name = '/thr/learner'
        self.predictor_name = '/thr/predictor'
        self.rospack = rospkg.RosPack()
        self.start_stop_service_name = '/thr/learner_predictor/start_stop'
        rospy.Service(self.start_stop_service_name, StartStopEpisode, self.cb_start_stop)

    def cb_start_stop(self, request):
        if request.command == StartStopEpisodeRequest.START:
            pass
        elif request.command == StartStopEpisodeRequest.STOP:
            pass
        return StartStopEpisodeResponse()

    def check_attached_pred(self, predictate_list, obj1, obj2=None, id_c=None):
        return len([p for p in predictate_list if
                    p.type == 'attached' and obj1 == p.parameters[0] and
                    (obj2 is None or obj2 == p.parameters[1]) and
                    (id_c is None or str(id_c) in p.parameters)]) == 1

    def check_positioned_pred(self, predictate_list, obj1, obj2, id_c=None):
        return len([p for p in predictate_list if
                    p.type == 'positioned' and obj1 in p.parameters and obj2 in p.parameters and
                    (id_c is None or str(id_c) in p.parameters)]) == 1

    def check_in_hws_pred(self, predictate_list, obj):
        return len([p for p in predictate_list if
                    p.type == 'in_human_ws' and obj in p.parameters]) == 1

    def check_picked_pred(self, predictate_list, obj=None):
        return len([p for p in predictate_list if
                    p.type == 'picked' and (obj is None or obj in p.parameters)]) == 1

    def check_holded_pred(self, predictate_list, obj):
        return len([p for p in predictate_list if
                    p.type == 'holded' and obj in p.parameters]) == 1  # !!HELD

    def check_at_home_pred(self, predictate_list, arm):
        return len([p for p in predictate_list if
                    p.type == 'at_home' and arm in p.parameters]) == 1

    def check_busy_pred(self, predictate_list, arm):
        return len([p for p in predictate_list if
                    p.type == 'busy' and arm in p.parameters]) == 1

    def string_to_action(self, string):
        string = string.replace("(", "+").replace(",", "+").replace(")", "")
        if string[-1] == "+":
            string = string[:-1]

        if "+" in string:
            return tuple(string.split("+"))
        else:
            return string

    def predictor_handler(self, get_next_action_req):
        """
        This handler is called when a request of prediction is received. It is based on a hardcoded policy
        :param get_next_action_req: an object of type GetNextActionRequest (scene state)
        :return: an object of type GetNextActionResponse
        """
        resp = GetNextDecisionResponse()
        obj_list = ['/toolbox/handle', '/toolbox/side_right', '/toolbox/side_left',
                    '/toolbox/side_front', '/toolbox/side_back']
        pred_list = get_next_action_req.scene_state.predicates

        module_path = self.rospack.get_path("thr_learner_predictor")
        # with tempfile.TemporaryFile() as temp_file:

        state_as_string = ""
        for pred in pred_list:
            if pred.parameters[-1][:2] == "eq":
                state_as_string += " (" + pred.type + " " + " ".join(pred.parameters[:-1]) + ")="
                state_as_string += str(pred.parameters[-1][2:]) + "\n"
            else:
                state_as_string += " (" + pred.type + " " + " ".join(pred.parameters) + ")\n"
        for pred in ["(occupied_slot " + p.parameters[0] + " " + p.parameters[2] + ")\n" for
                     p in pred_list if p.type == "positioned"]:
            state_as_string += pred
        if not self.check_picked_pred(pred_list):
            state_as_string += " (free left)\n"

        state_as_string += " (object /toolbox/handle)\n (object /toolbox/side_right)\n (object /toolbox/side_left)\n\
        (object /toolbox/side_front)\n (object /toolbox/side_back)\n (holding_position 0)\n (holding_position 1)\n"

        with open("tmp_file_planner", "w") as temp_file:
            temp_file.write("START_STATE {\n")
            temp_file.write(state_as_string)
            temp_file.write("}\n")

            with open(module_path + "/config/reward.g") as reward_file:
                for line in reward_file:
                    temp_file.write(line)

        w = FolWorld(module_path + "/config/toolbox.g", "tmp_file_planner")
        action_list = [self.string_to_action(a) for a in w.get_actions(state_as_string)]
        #rospy.loginfo("PREDICTOR ACTION LIST: {}".format(action_list))

        filtered_action_list = []
        for action in action_list:
            # 1 filter hold
            if action[0] == "activate_hold":
                if not self.check_attached_pred(pred_list, action[1], None, action[2]):
                    filtered_action_list.append(action)
            # 2 keep only the first pick giveb a list
            elif action[0] == "activate_pick":
                # Not optimized but simple to read (could do only once)
                not_in_hws_list = [o for o in obj_list if not self.check_in_hws_pred(pred_list, o)]
                ordered_not_in_hws_list = [o for o in obj_list if o in not_in_hws_list]
                if action[1] == ordered_not_in_hws_list[0]:
                    filtered_action_list.append(action)
            else:
                filtered_action_list.append(action)

        #rospy.loginfo("PREDICTOR FILTERED LIST: {}".format(action_list))

        resp = GetNextDecisionResponse()
        resp.confidence = resp.SURE
        resp.probas = []

        for action in filtered_action_list:
            decision = Decision()

            if action == "activate_wait_for_human" or action == "WAIT":
                decision.type = 'wait'
            elif type(action) == str:
                decision.type = action.replace("activate", "start")
                decision.parameters = []
            else:
                decision.type = action[0].replace("activate", "start")
                decision.parameters = list(action)[1:]

            resp.decisions.append(decision)
            resp.probas.append(1. / len(filtered_action_list))

        return resp

    def learner_handler(self, new_training_ex):
        """
        This handler is called when a request of learning is received, it must return an empty message
        :param snter: an object of type SetNewTrainingExampleRequest
        :return: an object of type SetNewTrainingExampleResponse (not to be filled, this message is empty)
        """
        rospy.loginfo("I'm learning that action {}{} was {}".format(new_training_ex.action.type,
                                                                    str(new_training_ex.action.parameters),
                                                                    "good" if new_training_ex.good else "bad"))
        return SetNewTrainingExampleResponse()

    def run(self):
        rospy.Service(self.predictor_name, GetNextDecision, self.predictor_handler)
        rospy.Service(self.learner_name, SetNewTrainingExample, self.learner_handler)
        rospy.loginfo('[LearnerPredictor] server ready...')
        rospy.spin()

if __name__ == "__main__":
    rospy.init_node('learner_and_predictor')
    Server().run()  # Blocking spinning call until shutdown!
