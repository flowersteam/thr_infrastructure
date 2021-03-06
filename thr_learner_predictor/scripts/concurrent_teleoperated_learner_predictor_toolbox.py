#!/usr/bin/env python

import rospy
import rospkg
import os
import json
import numpy as np

from threading import Lock

from RBLT.domains import domain_dict
from RBLT.learning import bagger
from RBLT import world
# from RBLT.learning.boosted_policy_learning import BoostedPolicyLearning

from thr_infrastructure_msgs.srv import GetNextDecision, GetNextDecisionResponse,\
    StartStopEpisode, StartStopEpisodeRequest, StartStopEpisodeResponse
from thr_infrastructure_msgs.srv import SetNewTrainingExample, SetNewTrainingExampleResponse
from thr_infrastructure_msgs.msg import Decision, PredictedPlan


class Server(object):
    def __init__(self):
        self.learner_name = '/thr/learner'
        self.predictor_name = '/thr/predictor'
        self.rospack = rospkg.RosPack()
        self.main_loop_rate = rospy.Rate(20)

        self.lock = Lock()

        self.tmp_dir_name = "/tmp/"
        self.i_tree = 0

        self.dataset = []
        self.results = []
        self.i_episode = 0
        self.last_state = None

        self.domain = domain_dict["multi_agent_box_coop"].Domain({"random_start": False}, "/tmp")
        self.reward = self.domain.rewards["reward_random"]

        self.task_q_fun = self.reward.get_task_q_fun_gen()
        self.learned_q_fun = self.task_q_fun

        self.learner = None
        self.threshold_ask = 0.05

        self.bagger_params = {
            "name": "bagger",
            "nb_learner": 25,
            "nb_process": 25,
            "sample_ratio": 0.4,
            "only_one_action": True,
            "learner": {
                "name": "gbpl",
                "nb_trees": 4,
                "beta": 10,
                "maxdepth": 5
            }
        }

        # self.algorithm = BoostedPolicyLearning(self.domain, {}, "/tmp")
        # self.algorithm.load()

        self.start_stop_service_name = '/thr/learner_predictor/start_stop'
        rospy.Service(self.start_stop_service_name, StartStopEpisode, self.cb_start_stop)

        self.predicted_plan_publisher = rospy.Publisher('/thr/predicted_plan', PredictedPlan, queue_size=1)

        self.learn_preferences()

    def cb_start_stop(self, request):
        if request.command == StartStopEpisodeRequest.START:
            pass

        elif request.command == StartStopEpisodeRequest.STOP:
            self.predicted_plan_publisher.publish(PredictedPlan())
            self.learn_preferences()
            self.i_episode += 1

        return StartStopEpisodeResponse()

    def learn_preferences(self):
        rospy.loginfo("Start learning")
        # tree_q_user = self.domain.learnRegressor(input_list, target_list, os.path.join(self.tmp_dir_name,
        #                                          "tree_q{}".format(self.i_tree)), maxdepth=6)
        with self.lock:
            self.learner = bagger.Bagger(self.domain, self.bagger_params, self.task_q_fun,
                                         os.path.join(self.tmp_dir_name, "tree_q{}".format(self.i_tree)))

            self.learner.train(self.dataset, None)
        # shutil.rmtree(os.path.join(tmp_dir_name, "tree_q{}".format(i_tree)))
        # human_q_fun_pfull = lambda s, a: tree_q_user((s, a))
        # self.learned_q_fun = lambda s, a: self.task_q_fun(s, a) + 0.1 * human_q_fun_pfull(s, a)

        self.i_tree += 1
        rospy.loginfo("Learning done")

    def relational_action_to_Decision(self, action):
        if isinstance(action, tuple):
            return Decision(type=action[0].replace("activate", "start"),
                            parameters=[c.replace("toolbox_", "/toolbox/") for c in action[1:]])
        else:
            return Decision(type=action.replace("activate", "start"),
                            parameters=[])

    def Decision_to_relational_action(self, action):
        if len(action.parameters) == 0:
            return action.type.replace("start", "activate")
        else:
            return tuple([action.type.replace("start", "activate")] +
                         [c.replace("/toolbox/", "toolbox_") for c in action.parameters])

    def scene_state_to_state(self, scene_state):
        slot_avaiable = {
            "toolbox_handle": 0,
            "toolbox_side_right": 1,
            "toolbox_side_left": 1,
            "toolbox_side_front": 2,
            "toolbox_side_back": 2,
        }
        slot_cor = ["no_slot", "one_slot", "two_slot"]

        pred_list = scene_state.predicates

        pred_robot_list = [
            tuple([str(pred.type)] +
                  [str(s).replace("/toolbox/", "toolbox_") for s in pred.parameters]) for pred in pred_list]

        pred_domain_list = []
        for pred in pred_robot_list:
            pred_domain_list.append(pred)
            if pred[0] == "positioned":
                pred_domain_list.append(("occupied_slot", pred[1], pred[3]))
                slot_avaiable[pred[2]] -= 1

            if pred[0] == "attached":
                pred_domain_list.append(("attached_slot", pred[1], pred[3]))
            for obj in ['toolbox_handle', 'toolbox_side_right', 'toolbox_side_left',
                        'toolbox_side_front', 'toolbox_side_back']:
                pred_domain_list.append(("object", obj))

            pred_domain_list.append(("object1", "toolbox_handle"))
            pred_domain_list.append(("object2", "toolbox_side_right"))
            pred_domain_list.append(("object2", "toolbox_side_left"))
            pred_domain_list.append(("object3", "toolbox_side_front"))
            pred_domain_list.append(("object3", "toolbox_side_back"))

            for obj in slot_avaiable:
                pred_domain_list.append((slot_cor[slot_avaiable[obj]], obj))

            pred_domain_list.append(("no_slot", "toolbox_handle"))

            for pose in ["0", "1"]:
                pred_domain_list.append(("holding_position", pose))
            if len([p for p in pred_robot_list if p[0] == "picked"]) == 0:
                pred_domain_list.append(("free", "left"))

        state = ("state", frozenset(pred_domain_list))
        return state

    def predict(self, state):
        return "wait", self.threshold_ask * 2

    def predictor_handler(self, get_next_action_req):
        """
        This handler is called when a request of prediction is received. It is based on a hardcoded policy
        :param get_next_action_req: an object of type GetNextDecisionRequest (scene state)
        :return: an object of type GetNextDecisionResponse
        """

        state = self.domain.state_to_int(self.scene_state_to_state(get_next_action_req.scene_state))
        self.domain.print_state(state)
        self.last_state = state

        best_action, error = self.predict(state)
        decision = self.relational_action_to_Decision(best_action)

        resp = GetNextDecisionResponse()
        if error > self.threshold_ask:
            resp.mode = resp.CONFIRM
        else:
            resp.mode = resp.SURE
        resp.confidence = error

        resp.probas = []

        print decision

        action_list = self.domain.get_actions(state)
        for candidate_action in action_list:
            resp.decisions.append(self.relational_action_to_Decision(
                self.domain.int_to_action(candidate_action)))

            if decision.type == resp.decisions[-1].type and decision.parameters == resp.decisions[-1].parameters:
                resp.probas.append(1.)
            else:
                resp.probas.append(0.)

        if np.sum(resp.probas) == 0:
            resp.decisions.append(decision)
            resp.probas.append(1.)
            print "###################################################"
            print decision
            print "###################################################"

        return resp

    def learner_handler(self, new_training_ex):
        """
        This handler is called when a request of learning is received, it must return an empty message
        :param snter: an object of type SetNewTrainingExampleRequest
        :return: an object of type SetNewTrainingExampleResponse (not to be filled, this message is empty)
        """
        rospy.loginfo("I'm learning that decision {}{} was good".format(new_training_ex.decision.type,
                                                                        str(new_training_ex.decision.parameters)))

        state = self.domain.state_to_int(self.scene_state_to_state(new_training_ex.scene_state))
        correct_decision = self.domain.action_to_int(self.Decision_to_relational_action(new_training_ex.decision))
        predicted_decision = self.domain.action_to_int(
            self.Decision_to_relational_action(new_training_ex.predicted_decision))

        if correct_decision not in self.domain.get_actions(state):
            print "###################################################"
            print self.domain.int_to_action(correct_decision)
            print self.domain.int_to_state(state)
            print "###################################################"
            return SetNewTrainingExampleResponse()

        if (state, correct_decision, None) in self.dataset:
            memory = True
        else:
            memory = False
            self.dataset.append((state, correct_decision, None))

        if len(self.domain.filter_robot_actions([predicted_decision])) > 0:
            if predicted_decision == correct_decision:
                feedback = "validation"
            else:
                if new_training_ex.prediction_confidence > self.threshold_ask:
                    feedback = "modification"
                else:
                    feedback = "correction"
        else:
            if predicted_decision == correct_decision:
                feedback = "validation"
            else:
                feedback = "modification"

        is_predicted_robot = bool(len(self.domain.filter_robot_actions([predicted_decision])) > 0)
        is_correct_robot = bool(len(self.domain.filter_robot_actions([correct_decision])) > 0)

        self.results.append((self.i_episode,
                             new_training_ex.prediction_confidence,
                             1,
                             len(self.domain.get_actions(state)),
                             bool(new_training_ex.corrected),
                             feedback,
                             is_predicted_robot,
                             is_correct_robot,
                             is_predicted_robot and (not feedback == "modification" or is_correct_robot),
                             len(self.dataset),
                             0.,
                             bool(new_training_ex.prediction_confidence > self.threshold_ask),
                             bool(feedback != "correction"),
                             0.,
                             memory))

        return SetNewTrainingExampleResponse()

    def run(self):
        rospy.Service(self.predictor_name, GetNextDecision, self.predictor_handler)
        rospy.Service(self.learner_name, SetNewTrainingExample, self.learner_handler)
        rospy.loginfo('[LearnerPredictor] server ready...')

        last_state_plan_computed = None
        predicted_plan_list = []

        resdir = self.rospack.get_path("thr_learner_predictor") + "/config/" + rospy.get_param("/thr/logs_name") + "/"
        if not os.path.exists(resdir):
            os.makedirs(resdir)

        logfile = resdir + "logs.json"

        while not rospy.is_shutdown():
            if self.last_state is not None and last_state_plan_computed != self.last_state:
                with open(logfile, "w") as f:
                    json.dump(self.last_state, f)


                predicted_plan_list.append(([], rospy.Time.now().to_sec()))
                last_state_plan_computed = self.last_state
                w = world.World(last_state_plan_computed, self.domain)

                predicted_plan = PredictedPlan()

                for _ in range(20):
                    best_decision, error = self.predict(w.state)

                    predicted_plan_list[-1][0].append((best_decision, error))

                    predicted_plan.decisions.append(self.relational_action_to_Decision(best_decision))
                    predicted_plan.confidences.append(error)

                    w.apply_action(self.domain.action_to_int(best_decision))
                self.predicted_plan_publisher.publish(predicted_plan)

            self.main_loop_rate.sleep()

        if not os.path.exists(resdir):
            os.makedirs(resdir)

        resfile = resdir + "results.json"
        with open(resfile, "w") as f:
            json.dump(self.results, f)

        planfile = resdir + "/plans.json"
        with open(planfile, "w") as f:
            json.dump(predicted_plan_list, f)

if __name__ == "__main__":
    rospy.init_node('learner_and_predictor')
    Server().run()
