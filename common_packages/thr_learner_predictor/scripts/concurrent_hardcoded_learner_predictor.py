#!/usr/bin/env python

import rospy
from thr_coop_assembly.srv import GetNextAction, GetNextActionRequest, GetNextActionResponse
from thr_coop_assembly.srv import SetNewTrainingExample, SetNewTrainingExampleRequest, SetNewTrainingExampleResponse
from thr_coop_assembly.msg import MDPAction, Predicate

# To test this server, try: "rosservice call [/thr/learner or /thr/predictor] <TAB>" and complete the pre-filled request message before <ENTER>

class Server(object):
    def __init__(self):
        self.learner_name = '/thr/learner'
        self.predictor_name = '/thr/predictor'
        self.policy = rospy.get_param('/thr/policy')

    def check_attached_pred(self, predictate_list, obj1, obj2, id_c=None):
        return len([p for p in predictate_list if
            p.type == 'attached' and obj1 in p.parameters and obj2 in p.parameters and
            (id_c is None or str(id_c) in p.parameters)]) == 1

    def check_positioned_pred(self, predictate_list, obj1, obj2, id_c=None):
        return len([p for p in predictate_list if
            p.type == 'positioned' and obj1 in p.parameters and obj2 in p.parameters and
            (id_c is None or str(id_c) in p.parameters)]) == 1

    def check_in_hws_pred(self, predictate_list, obj):
        return len([p for p in predictate_list if
            p.type == 'in_human_ws' and obj in p.parameters]) == 1

    def check_picked_pred(self, predictate_list, obj):
        return len([p for p in predictate_list if
            p.type == 'picked' and obj in p.parameters]) == 1

    def check_holded_pred(self, predictate_list, obj):
        return len([p for p in predictate_list if
            p.type == 'holded' and obj in p.parameters]) == 1

    def check_at_home_pred(self, predictate_list, arm):
        return len([p for p in predictate_list if
            p.type == 'at_home' and arm in p.parameters]) == 1

    def check_busy_pred(self, predictate_list, arm):
        return len([p for p in predictate_list if
            p.type == 'busy' and arm in p.parameters]) == 1


    def predictor_handler(self, get_next_action_req):
        """
        This handler is called when a request of prediction is received. It is based on a hardcoded policy
        :param get_next_action_req: an object of type GetNextActionRequest (scene state)
        :return: an object of type GetNextActionResponse
        """
        resp = GetNextActionResponse()
        valid_action = True
        obj_list = ['/toolbox/handle', '/toolbox/side_right', '/toolbox/side_left', '/toolbox/side_front', '/toolbox/side_back']
        pred_list = get_next_action_req.scene_state.predicates
        in_hws_list = [o for o in obj_list if self.check_in_hws_pred(pred_list, o)]

        if len(in_hws_list) == 0:
            if not self.check_busy_pred(pred_list, "left"):
                resp.action.parameters = ['/toolbox/handle']
                if not self.check_picked_pred(pred_list, '/toolbox/handle'):
                    resp.action.type = 'start_pick'
                else:
                    resp.action.type = 'start_give'
                return resp

            if not self.check_busy_pred(pred_list, "right"):
                if not self.check_at_home_pred(pred_list, "right"):
                    resp.action.type = 'start_go_home_right'
                    return resp

        elif len(in_hws_list) == 1:
            if not self.check_busy_pred(pred_list, "left"):
                resp.action.parameters = ['/toolbox/side_right']
                if not self.check_picked_pred(pred_list, '/toolbox/side_right'):
                    resp.action.type = 'start_pick'
                else:
                    resp.action.type = 'start_give'
                return resp

            if not self.check_busy_pred(pred_list, "right"):
                if not self.check_at_home_pred(pred_list, "right"):
                    resp.action.type = 'start_go_home_right'
                    return resp

        elif len(in_hws_list) == 2:
            if self.check_attached_pred(pred_list, '/toolbox/handle', '/toolbox/side_right'):
                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

                if not self.check_busy_pred(pred_list, "left"):
                    resp.action.parameters = ['/toolbox/side_left']
                    if not self.check_picked_pred(pred_list, '/toolbox/side_left'):
                        resp.action.type = 'start_pick'
                    else:
                        resp.action.type = 'start_give'
                    return resp

            elif self.check_positioned_pred(pred_list, '/toolbox/handle', '/toolbox/side_right', 0):
                if not self.check_busy_pred(pred_list, "right"):
                    resp.action.type = 'start_hold'
                    resp.action.parameters = ['/toolbox/handle', '0']
                    return resp

                if not self.check_picked_pred(pred_list, '/toolbox/side_left'):
                    if not self.check_busy_pred(pred_list, "left"):
                        resp.action.type = 'start_pick'
                        resp.action.parameters = ['/toolbox/side_left']
                        return resp

            elif self.check_positioned_pred(pred_list, '/toolbox/handle', '/toolbox/side_right', 1):
                if not self.check_busy_pred(pred_list, "right"):
                    resp.action.type = 'start_hold'
                    resp.action.parameters = ['/toolbox/handle', '1']
                    return resp

                if not self.check_picked_pred(pred_list, '/toolbox/side_left'):
                    if not self.check_busy_pred(pred_list, "left"):
                        resp.action.type = 'start_pick'
                        resp.action.parameters = ['/toolbox/side_left']
                        return resp
            else:
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        resp.action.type = 'start_go_home_left'
                        return resp
                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

        elif len(in_hws_list) == 3:
            if self.check_attached_pred(pred_list, '/toolbox/handle', '/toolbox/side_left'):
                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

                if not self.check_busy_pred(pred_list, "left"):
                    resp.action.parameters = ['/toolbox/side_front']
                    if not self.check_picked_pred(pred_list, '/toolbox/side_front'):
                        resp.action.type = 'start_pick'
                    else:
                        resp.action.type = 'start_give'
                    return resp

            elif self.check_positioned_pred(pred_list, '/toolbox/handle', '/toolbox/side_left', 0):
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_picked_pred(pred_list, '/toolbox/side_front'):
                        resp.action.type = 'start_pick'
                        resp.action.parameters = ['/toolbox/side_front']
                        return resp

                if not self.check_busy_pred(pred_list, "right"):
                    resp.action.type = 'start_hold'
                    resp.action.parameters = ['/toolbox/handle', '0']
                    return resp


            elif self.check_positioned_pred(pred_list, '/toolbox/handle', '/toolbox/side_left', 1):
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_picked_pred(pred_list, '/toolbox/side_front'):
                        resp.action.type = 'start_pick'
                        resp.action.parameters = ['/toolbox/side_front']
                        return resp

                if not self.check_busy_pred(pred_list, "right"):
                    resp.action.type = 'start_hold'
                    resp.action.parameters = ['/toolbox/handle', '1']
                    return resp

            else:
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        resp.action.type = 'start_go_home_left'
                        return resp
                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

        elif len(in_hws_list) == 4:
            if (self.check_attached_pred(pred_list, '/toolbox/side_left', '/toolbox/side_front') and
                self.check_attached_pred(pred_list, '/toolbox/side_right', '/toolbox/side_front')):

                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

                if not self.check_busy_pred(pred_list, "left"):
                    resp.action.parameters = ['/toolbox/side_back']
                    if not self.check_picked_pred(pred_list, '/toolbox/side_back'):
                        resp.action.type = 'start_pick'
                    else:
                        resp.action.type = 'start_give'
                    return resp

   
            elif (self.check_positioned_pred(pred_list, '/toolbox/side_left', '/toolbox/side_front', 0) and
                self.check_positioned_pred(pred_list, '/toolbox/side_right', '/toolbox/side_front', 1)):


                if not self.check_attached_pred(pred_list, '/toolbox/side_left', '/toolbox/side_front', 0):
                    if not self.check_busy_pred(pred_list, "left"):
                        if not self.check_at_home_pred(pred_list, "left"):
                            resp.action.type = 'start_go_home_left'
                            return resp

                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_left', '0']
                        return resp
                else:
                    if not self.check_busy_pred(pred_list, "left"):
                        if not self.check_picked_pred(pred_list, '/toolbox/side_front'):
                            resp.action.type = 'start_pick'
                            resp.action.parameters = ['/toolbox/side_back']
                            return resp

                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_right', '1']
                        return resp

            elif (self.check_positioned_pred(pred_list, '/toolbox/side_left', '/toolbox/side_front', 1) and
                self.check_positioned_pred(pred_list, '/toolbox/side_right', '/toolbox/side_front', 0)):

                if not self.check_attached_pred(pred_list, '/toolbox/side_left', '/toolbox/side_front', 1):
                    if not self.check_busy_pred(pred_list, "left"):
                        if not self.check_at_home_pred(pred_list, "left"):
                            resp.action.type = 'start_go_home_left'
                            return resp

                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_left', '1']
                        return resp
                else:
                    if not self.check_busy_pred(pred_list, "left"):
                        if not self.check_picked_pred(pred_list, '/toolbox/side_front'):
                            resp.action.type = 'start_pick'
                            resp.action.parameters = ['/toolbox/side_back']
                            return resp

                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_right', '0']
                        return resp

            else:
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        resp.action.type = 'start_go_home_left'
                        return resp
                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

        elif len(in_hws_list) == 5:
            if (self.check_attached_pred(pred_list, '/toolbox/side_left', '/toolbox/side_back') and
                self.check_attached_pred(pred_list, '/toolbox/side_right', '/toolbox/side_back')):

                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        resp.action.type = 'start_go_home_left'
                        return resp
   
            elif (self.check_positioned_pred(pred_list, '/toolbox/side_left', '/toolbox/side_back', 0) and
                self.check_positioned_pred(pred_list, '/toolbox/side_right', '/toolbox/side_back', 1)):


                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        resp.action.type = 'start_go_home_left'
                        return resp

                if not self.check_attached_pred(pred_list, '/toolbox/side_left', '/toolbox/side_back', 0):
                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_left', '0']
                        return resp
                else:
                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_right', '1']
                        return resp

            elif (self.check_positioned_pred(pred_list, '/toolbox/side_left', '/toolbox/side_back', 1) and
                self.check_positioned_pred(pred_list, '/toolbox/side_right', '/toolbox/side_back', 0)):

                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        resp.action.type = 'start_go_home_left'
                        return resp

                if not self.check_attached_pred(pred_list, '/toolbox/side_left', '/toolbox/side_back', 1):
                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_left', '1']
                        return resp
                else:
                    if not self.check_busy_pred(pred_list, "right"):
                        resp.action.type = 'start_hold'
                        resp.action.parameters = ['/toolbox/side_right', '0']
                        return resp

            else:
                if not self.check_busy_pred(pred_list, "left"):
                    if not self.check_at_home_pred(pred_list, "left"):
                        action = MDPAction()
                        resp.action.type = 'start_go_home_left'
                        return resp
                if not self.check_busy_pred(pred_list, "right"):
                    if not self.check_at_home_pred(pred_list, "right"):
                        resp.action.type = 'start_go_home_right'
                        return resp

        resp.action.type = 'wait'
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
        rospy.Service(self.predictor_name, GetNextAction, self.predictor_handler)
        rospy.Service(self.learner_name, SetNewTrainingExample, self.learner_handler)
        rospy.loginfo('[LearnerPredictor] server ready...')
        rospy.spin()

if __name__ == "__main__":
    rospy.init_node('learner_and_predictor')
    Server().run() # Blocking spinning call until shutdown!