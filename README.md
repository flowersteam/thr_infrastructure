# Third Hand Robot Infrastructure

This repository contains the ROS packages implemented to use Baxter for the 3rd Hand Robot project. 

It comes with a set of robot actions (pick, grasp, place, handover, hold, ...), a set of known manipulable objects part of scenes (wooden toolbox or cooking setup), a scene state representation in the form of set of predicates (`ATTACHED(object_1, object_2`, `AT_HOME(left_arm)`...), the way to trigger actions by hand or following a planned or learned policy.

Videos:

- [Video: Online planner (RAP) + offline learning](https://vimeo.com/139342248)
- [Video: Commented offline learning](https://vimeo.com/145653515)
- [Video: Gesture-based interaction](https://vimeo.com/151623144)

## Implementation

The global architecture is illustrated and explained hereunder, while the ROS messages can be  [viewed online](thr_infrastructure_msgs/msg).

Check out the ![architecture diagram](/architecture.svg).

The experimental setup is fully built on ROS, and composed by the following nodes [Type of node in brackets]:

 - **Scene State Manager** [2 Services]: Observes the scene, creates a representation of the scene made of predicates by generating only generic predicates (in human workspace, arms business, activity predicates...). It is also the guard of the predicates, it stores all of them and serves them to other nodes emitting a request through service `/thr/scene_state`. Other nodes may add or remov predicates through service `/thr/update_relational_state`.
 - **Scene State Updater** [Node]: Observes the scene, creates a representation of the scene made of predicates by generating scene-specific predicates (positioning, attaching, ...). There is thus a different SSU for each scene.

 - **Decision Server** [Action Server]: Executes a decision (start_pick, start_go_home, start_hold, ...) through channel `/thr/run_decision` by checking what arms are able to execute it, forwarding the goal to the Action server of the corresponding arm (left/right). All decisions are non-blocking and always successful.
 - **Activity Server** [Action server]: Executes an action (pick, go_home, hold) on its associated arm through channel `/thr/robot_run_action`. There is one running Activity Server per arm.
 - **Learner/Predictor** [2 Services]: This is the policy provider. It provides two services, one for learning `thr/learner` (called each time an action is being run, it can potentially be unused), one for predicting `/thr/predictor` (infinitely called by the interaction controller to get the next action).
 -  **Interaction controller** [Node]: Controller mastering the whole interaction process, requesting the scene state, the actions to perform from the predictor, sending goals to the arms through their action server, and warning the learner than the action succeeded or has been interrupted. We have implemented two kinds of interaction controllers:
  - *Autonomous interaction controller* (automatically looping)
  - *Keyboard interaction controller* (waits for user commands in a Command-Line Interface for Wizard-Of-Oz commanding).

### Learner/Predictor couple (aka the Planner, package `thr_learner_predictor`)
This node Learner/Predictor is in charge of learning good and bad actions and predicting the next one. It is implemented as a single node instead of two separated ones to be able to share easily a representation of the task in memory (Prolog, or database, or ...). This node has two distinct services for these two features though.

At the moment, different Planners exist, and launching the process requires to choose one of them:

- *Either* a hardcoded policy (mainly for debug/demo purposes)
- *Or* via interactive learning
- *Or* using an online planner (1)

(1) Marc Toussaint from Stuttgart uni developed a concurrent action planner. Based on his work we defined how concurrent actions are handled by the system, thanks to non-blocking and always successful decisions (ROS message `Decision`), triggering blocking Robot actions (ROS message `Action`) on a compatible arm, which might fail if the robot cannot execute this action in that context.

### Action servers (Package `thr_action_server`)
When it receives a new goal to reach, the Decision server considers both arms as two different agents capable of several actions that take parameters. Decisions are orders like "start_something", they are not blocking and they are always successful. Decisions are then forwarded to the right Activity Server able to execute this "something" action.

One Activity Server is declared for each arm and accepts a range of activities, that are:

- Left arm (vacuum gripper):

 - `PICK(Object obj)`: The robot locates object `obj`, picks it up and keeps it in hand a until further `GIVE` or `BRING` or `PLACE` action.
 - `GIVE(Object obj)`: The robot locates locates the human wrist and brings it close to his wrist if it's reachable. When the object is detected to be pulled from the gripper, it is released. The arm does **not** go back in home position.
 - `BRING_LEFT(Object obj)`: The robot locates locates the human wrist and brings it close to his wrist if it's reachable. Unlike the `GIVE` action, `BRING` never release the object.
 - `PLACE_LEFT(Object obj, Object location)`: Place the object `obj` to a pose relative to another object `location`, passing via an optional viapoint.
 - `GO_HOME_LEFT()` The arm goes back in home position, leaving the human's workspace.

- Right arm (1-DoF electric gripper):

 - `HOLD(Object obj, HoldPose hp)`: The robot locates object `obj`, approaches its hold pose `#hp`, and grasps the object. When the user wrist leaves far away from `obj`, the action is considered finished, the robot releases the object but does **not** go back in home position.
 - `GRASP(Object obj)`: The robot locates object `obj`, grasps it and keeps it in hand a until further `GIVE` or `BRING` or `PLACE` action. 
 - `BRING_RIGHT(Object obj)`: same as above
 - `PLACE_LEFT(Object obj, Object location)`: same as above
 - `GO_HOME_RIGHT()` same as above

The Robot action server publishes a topic `action_history` with events each time an action starts, succeeds or fails. These informations are then used by any node (including the display manager, scene state manager, interaction controller) for different needs (warn the user about a failure, update the predicates, and so on...)

Notes :

- Additionally to the parameters hereabove given online, activities may also rely on hardcoded parameters defined in `thr_scenes` if they are scene-specific or in [`action_params.json`](thr_action_server/config/action_params.json) if they are action-specific. 
- There is no `WAIT` action or at least, it is not considered as a Decision. The interaction controller may simulate waiting, but th action servers are wait-agnostic.
- `GRASP` and `PICK` are similar actions, but grasp applies to the electric gripper and pick to the vacuum gripper
- `BRING`, `PLACE`, `GIVE`, and `GO_HOME` actions are symmetrically executable on both arms so they are implemented once and only instanciated twice.
- The setup is made to execute concurrent actions, the former branch `sequential` was no longer maintained and was thus deleted.
- Action servers are automatically started in all scenarii (autonomous, manual/WoZ)

### Perception (package `thr_scene_state_manager`)
The perception ability of the robot is ensured by the Scene State Manager. The scene state is described in the form of predicates. Some predicates are generic and handled by the manager itself, some other predicates are scene-specific and thus require a dedicated scen state updater, a second node adding or removing scene-specific predicates from the manager.

Here are the generic predicates generated by the manager itself:

- `IN_HUMAN_WORKSPACE(Object obj)`: True if `obj` is directly reachable by the human
- `BUSY(Arm arm)` True if `arm` is currently performing an operation (recall that there is no `WAIT` operation so sometimes arms perform no action)
- `IN_HOME_POSITION(Arm arm)` True if `arm` is currently in home position
- All Robot and Human actions are also included within the scene state, to make the learner/predictor aware of what it is currently being executed

Here are the toolbox-specific predicates generated by the toolbox scene state updater:

- `POSITIONED(Object master, Object slave)`: True if the transformation `slave`->`master` matches a documented constraint (i.e. `slave` is positioned close to `master` and is ready to be attached)
- `ATTACHED(Object master, Object slave)`: True if `POSITIONED(master, slave)` and the screwdriver has been seen close to these objects enough time to assume they have been attached together.
- `PICKED(Object obj)` True if `obj` is currently in robot hand

Since interesting predicates are different fr each scene, a decicated scene state updater exists for each one of them. Thus the `scene` argument selects the right scene state updater. The state state manager is generic, produces generic predicates whatever the scene is and allow updaters to update its relational state.

### Interaction controller (package `thr_interaction_controller`)
The Interaction controller is the conductor of the worflow, it orchestrates the other nodes above to create a specific mode of interaction. The default interaction controller requests the current scene state, asks the predictor to return the next action, pass the order to the decision server, it can be for instance replaced by other interaction controllers, like the keyboard interaction controllers which do not call the planners but wait for the user to type commands in a Wizard-Of-Oz mode.

The type of interaction controller is changed by choosing the right launchfile:
- `manual.launch` for a WoZ mode
- `autonomous.launch` for an autonomous robot, with an optional argument:
 - `interaction:=phablet` uses the web asker for interaction, learning and prediction (default)*
 - `interaction:=independent` always asks the predictor and executes the most probable action in loop
 - `interaction:=gestures` uses the gesture detection of the Kinect 2**

* Requires valid mongodb credentials in non-versioned file `thr_interaction_controller/config/mongo_adress_list.json`
** Requires [the Kinect 2 server](https://github.com/baxter-flowers/kinect_2_server/)

### Display manager (package `thr_display`)
The display managers are in charge of printing useful information on Baxter's display. Current display managers are:

- Debug: This manager displays the list of predicates (useful to debug and understand wrong robot decisions due to perception errors)
- Action: This manager uses the provided speech in `display.json` to display user-frendly messages (useful for public demos)

The display manager can be selected with the argument `display:=debug` (default) or `display:=action`.

## Scenes (package `thr_scenes`)
A scene contains a set of objects to work with, the documentation of these (see below), the same of the Optitrack rigid bodies to track, and a relevant text to display to the user to give him feedback.

**All the objects are documented** in a `poses.json` file specific to each scen, i.e. for each object we know:

- Its **shape** (although it is not used)
- Its **constraints** (the ways it can be attached to other objects)
- A **grasp pose**, i.e. the pose that the vacuum gripper should reach to pick it up
- 2 **hold poses** (one to the left, and one to the right), i.e. poses that the vacuum gripper can reach to hold the object 
- Maybe other poses needed by other actions compatible with this object

### Toolbox
The scene `toolbox` works with a 5-piece wooden toolbox designed for a great number of assembly/disassembly cycles that are: a handle, a front side, a back side, a left side, and a right side. The toolbox has actually 7 pieces, the 2 other composing the bottom of the box, that we do not use in this setup. Each of the 5 pieces is fixed to others using screws, and although they are named differently and recognized as different objects by the system, some parts are actually identical and can be inverted: front = back and left = right. Thus the assembly can differ depending to the location we assemble each side.

Relevant robot actions for this scene are:

- pick (with the vacuum gripper)
- give (handover close to the human's wrist)
- hold (while the human is screwing)

Relevant human actions for this scene are:

- position (start positioning two objects together)
- screw (screw them until predicate ATTACHED is true)

### Romeo
The romeo scene illustrates a context of assistive robotics with the following objects:

- A box of drugs
- An orange juice box
- A bowl
- Its cover
- A glass
- A tray

Relevants robot actions:
- grasp
- place_right
- bring_right
- pick
- give_right

Relevant human's actions:

- None (yet)

## How to launch the process?

```
roslaunch thr_interaction_controller autonomous.launch policy:=hardcoded display:=debug ip:=<VRPN IP>
```

 *  The policy can be `hardcoded` (default and fastest), `planner` `random` or `policy_player`
 *  The display can be `debug` (default), `action` (displays the actions)
 *  IP is the IP address of the Windows machine running the Optitrack VRPN server (Arena or Motive), the port can also be set (`port:=`).

To start the manual mode (robot receives individual commands from command line) with a nice action display:
```
roslaunch thr_interaction_controller manual.launch display:=action ip:=<VRPN IP>
```
Commands are, for instance: `hh0` (Hold the handle, on its left), `hr1` (Hold the piece 'side_right' on its right), `l`, (Send the left arm in home pose), `r` (Send the right arm in home pose), `pb` (Pick the back piece), `gl` (Handover the side_left to the human).

The scene (i.e. objects to use) can be passed in argument. For example the scene `romeo` has been conceived to handle cooking tools, its manual setup uses different letters (see the code of the Keyboard IC to know them):
```
roslaunch thr_interaction_controller manual.launch scene:=romeo display:=action ip:=<VRPN IP>
```

A hardcoded (aka scripted) setup is started like this:
```
roslaunch thr_interaction_controller autonomous.launch policy:=hardcoded interaction:=independent ip:=<VRPN IP>
```

The interaction via gestures is started by selected the gestures interaction controller as well as the corresponding predictor policy:
```
roslaunch thr_interaction_controller autonomous.launch interaction:=gestures policy:=gestures
```

## How to implement new...
## New actions?
The action server works with 2 types of actions: **Non-blocking** [`Decision`](thr_infrastructure_msgs/msg/Decision.msg)s like `start_xxxxx` causing the Decision server to trigger a **blocking** [`RobotAction`](thr_action_server/msg/RobotAction.msg) executed by the Robot Action server. The actions themselves are implemented within a [`src/thr_actions/`](thr_action_server/src/thr_actions) subfolder. A new action must then be implemented as:
 *  A new file in this [`src/thr_actions/`](thr_action_server/src/thr_actions) subfoler
 *  A new correspondance `MDP to Robot` in [`config/mdp_robot_mapping.json`](thr_action_server/config/mdp_robot_mapping.json)
 *  A new attribution to the left or right arm in [`config/abilities.json`](thr_action_server/config/abilities.json) (To be merged with mdp_robot_mapping.json?)
 *  Its specific command-line command within the Concurrent Keyboard Interaction Controllers
 *  Its specific tweakable parameters  in [`config/action_params.json`](thr_action_server/config/action_params.json)
 *  Some IK seeds showing some typical arm configuration for this task, in [`config/seeds.json`](thr_action_server/config/seeds.json), if needed
 *  Some text to display to the user on Baxter's screen when the action starts or stops/fails (this file is specific to a scene), in [`config/display.json`](thr_scenes/config/toolbox/display.json), if needed

## New objects/scene?
Scenes are selected thanks to the argument `scene:=toolbox`, all accepted scenes are described within the `thr_scenes` package.
Adding or changing objects in a new scene will require to add/change the files hereunder. Fortunately there is [a notebook](https://github.com/3rdHand-project/thr_infrastructure/tree/master/thr_scenes/notebooks) to give you a hand.
 *  The file [`config/scenes.yaml`](thr_scenes/config/scenes.yaml) which describes the available scenes and objects
 *  [`config/<new_scene>/tracked_objects.yaml`](thr_scenes/config/toolbox/tracked_objects.yaml) which describes which objects must be tracked by optitrack. The number of objects here must be higher or equal to the number in `config/scenes.yaml`
 *  The file [`config/<new_scene>/poses.json`](thr_scenes/config/toolbox/poses.json) which describes, for its objects, a bunch of hardcoded poses relative to that object:
    * If the action has 2 objects involved there's a *master* and a *slave* object: the master is the host for the slave
    * In `poses.json`, hierarchy is *master first, then slave*, so if a table is a host for an object, browse the tree be looking the table, then its slave object
    * For `PLACE`, the relative pose is the slave within the master's frame (use `rosrun tf tf_echo <master> <slave>` to update)
    * For `GRASP` or `PICK`, this relative pose is the robot's gripper within the object's frame (use `rosrun tf tf_echo right_gripper <object>` to update)
    * For `GIVE` or `BRING`, the relative pose is the robot's gripper within human wrist's frame
 *  The file [`config/<new_scene>/display.json`](thr_scenes/config/toolbox/display.json) which contains a very short user-friendly message to be displayed on Baxter's screen when `display:=action` is enabled. The integer -1 means 'look straight ahead', any other integer i>-1 means 'look at the object number #i in the parameters list 
