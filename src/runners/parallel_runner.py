from envs import REGISTRY as env_REGISTRY
from functools import partial
from components.episode_buffer import EpisodeBatch
from multiprocessing import Pipe, Process
import numpy as np
import torch as th
from types import SimpleNamespace as SN
import copy
import pickle


# Based (very) heavily on SubprocVecEnv from OpenAI Baselines
# https://github.com/openai/baselines/blob/master/baselines/common/vec_env/subproc_vec_env.py
class ParallelRunner:

    def __init__(self, args, logger):
        self.args = args
        self.logger = logger
        self.batch_size = self.args.batch_size_run

        # Make subprocesses for the envs
        # TODO: Add a delay when making sc2 envs
        self.parent_conns, self.worker_conns = zip(*[Pipe() for _ in range(self.batch_size)])
        env_fn = env_REGISTRY[self.args.env]
        if ('sc2' in self.args.env) or ('group_matching' in self.args.env):
            base_seed = self.args.env_args.pop('seed')
            self.ps = [Process(target=env_worker, args=(worker_conn, self.args.entity_scheme,
                                                        CloudpickleWrapper(partial(env_fn, seed=base_seed + rank,
                                                                                   **self.args.env_args))))
                       for rank, worker_conn in enumerate(self.worker_conns)]
        else:
            self.ps = [Process(target=env_worker, args=(worker_conn, self.args.entity_scheme,
                                                        CloudpickleWrapper(partial(env_fn, env_args=self.args.env_args,
                                                                                   args=self.args))))
                       for worker_conn in self.worker_conns]

        for p in self.ps:
            p.daemon = True
            p.start()

        # TODO: Close stuff if appropriate

        self.parent_conns[0].send(("get_env_info", args))

        self.env_info = self.parent_conns[0].recv()
        self.episode_limit = self.env_info["episode_limit"]

        # TODO: Will have to add stuff to episode batch for envs that terminate at different times to ensure filled is correct
        self.t = 0

        self.t_env = 0

        self.train_returns = []
        self.test_returns = []
        self.train_stats = {}
        self.test_stats = {}

        self.box_info = []
        self.agents_info = []
        self.done_info = []

        self.log_train_stats_t = -100000

        self.test_returns_log = 0.
        if self.args.pickle_path != "":
            with open(self.args.pickle_path, 'rb') as f:
                self.bwm = pickle.load(f)
        else:
            self.bwm = np.zeros(self.args.scenario_len)

        self.bwm_this_run = np.zeros(self.args.scenario_len)
        self.c_this_run = np.zeros(self.args.scenario_len)

    def setup(self, scheme, groups, preprocess, mac):
        self.new_batch = partial(EpisodeBatch, scheme, groups, self.batch_size, self.episode_limit + 1,
                                 preprocess=preprocess, device=self.args.device)
        self.mac = mac
        # TODO: Remove these if the runner doesn't need them
        self.scheme = scheme
        self.groups = groups
        self.preprocess = preprocess

    def get_env_info(self):
        return self.env_info

    def save_replay(self):
        pass

    def close_env(self):
        for parent_conn in self.parent_conns:
            parent_conn.send(("close", None))

    def reset(self, **kwargs):
        self.batch = self.new_batch()

        # Reset the envs
        for parent_conn in self.parent_conns:
            parent_conn.send(("reset", kwargs))

        pre_transition_data = {}
        # Get the obs, state and avail_actions back
        for parent_conn in self.parent_conns:
            data = parent_conn.recv()
            for k, v in data.items():
                if k in pre_transition_data:
                    pre_transition_data[k].append(data[k])
                else:
                    pre_transition_data[k] = [data[k]]

        self.batch.update(pre_transition_data, ts=0)

        self.t = 0
        self.env_steps_this_run = 0
        self.sce_this_run = np.where(np.array(pre_transition_data['scenario']) == 1)[-1]
        self.status_log = np.zeros(self.args.batch_size_run)

    def run(self, test_mode=False, test_scen=None, index=None, vid_writer=None):
        """
        test_mode: whether to use greedy action selection or sample actions
        test_scen: whether to run on test scenarios. defaults to matching test_mode.
        vid_writer: imageio video writer object (not supported in parallel runner)
        """
        if test_scen is None:
            test_scen = test_mode
        assert vid_writer is None, "Writing videos not supported for ParallelRunner"
        self.reset(test=test_scen, index=index)

        all_terminated = False
        episode_returns = [0 for _ in range(self.batch_size)]
        episode_lengths = [0 for _ in range(self.batch_size)]

        self.mac.init_hidden(batch_size=self.batch_size)
        # make sure things like dropout are disabled
        self.mac.eval()
        terminated = [False for _ in range(self.batch_size)]
        envs_not_terminated = [b_idx for b_idx, termed in enumerate(terminated) if not termed]
        final_env_infos = []  # may store extra stats like battle won. this is filled in ORDER OF TERMINATION

        while True:

            # Pass the entire batch of experiences up till now to the agents
            # Receive the actions for each agent at this timestep in a batch for each un-terminated env
            actions = self.mac.select_actions(self.batch, t_ep=self.t, t_env=self.t_env, bs=envs_not_terminated,
                                              test_mode=test_mode)
            cpu_actions = actions.to("cpu").numpy()

            # Update the actions taken
            actions_chosen = {
                "actions": actions.unsqueeze(1)
            }
            self.batch.update(actions_chosen, bs=envs_not_terminated, ts=self.t, mark_filled=False)

            # Send actions to each env
            action_idx = 0
            for idx, parent_conn in enumerate(self.parent_conns):
                if idx in envs_not_terminated:  # We produced actions for this env
                    if not terminated[idx]:  # Only send the actions to the env if it hasn't terminated
                        parent_conn.send(("step", cpu_actions[action_idx]))
                    action_idx += 1  # actions is not a list over every env

            # Post step data we will insert for the current timestep
            post_transition_data = {
                # "actions": actions.unsqueeze(1),
                "reward": [],
                "terminated": []
            }
            # Data for the next step we will insert in order to select an action
            if self.args.entity_scheme:
                pre_transition_data = {
                    "entities": [],
                    "obs_mask": [],
                    "entity_mask": [],
                    "avail_actions": []
                }
            else:
                pre_transition_data = {
                    "state": [],
                    "avail_actions": [],
                    "obs": []
                }

            # Update terminated envs after adding post_transition_data
            envs_not_terminated = [b_idx for b_idx, termed in enumerate(terminated) if not termed]
            all_terminated = all(terminated)
            if all_terminated:
                break

            # Receive data back for each unterminated env
            for idx, parent_conn in enumerate(self.parent_conns):
                if not terminated[idx]:
                    data = parent_conn.recv()
                    # Remaining data for this current timestep
                    post_transition_data["reward"].append((data["reward"],))

                    episode_returns[idx] += data["reward"]
                    episode_lengths[idx] += 1
                    if not test_mode:
                        self.env_steps_this_run += 1

                    env_terminated = False
                    if data["terminated"]:
                        final_env_infos.append(data["info"])
                        self.status_log[idx] = data["info"].get("battle_won", 0)
                    if data["terminated"] and not data["info"].get("episode_limit", False):
                        env_terminated = True
                    terminated[idx] = data["terminated"]
                    post_transition_data["terminated"].append((env_terminated,))

                    # Data for the next timestep needed to select an action
                    for k in pre_transition_data:
                        pre_transition_data[k].append(data[k])

            # Add post_transiton data into the batch
            self.batch.update(post_transition_data, bs=envs_not_terminated, ts=self.t, mark_filled=False)

            # Move onto the next timestep
            self.t += 1

            # Add the pre-transition data

            self.batch.update(pre_transition_data, bs=envs_not_terminated, ts=self.t, mark_filled=True)

        if not test_mode:
            self.t_env += self.env_steps_this_run

        # Get stats back for each env
        for parent_conn in self.parent_conns:
            parent_conn.send(("get_stats", None))

        env_stats = []
        for parent_conn in self.parent_conns:
            env_stat = parent_conn.recv()
            env_stats.append(env_stat)

        cur_stats = self.test_stats if test_mode else self.train_stats
        cur_returns = self.test_returns if test_mode else self.train_returns
        log_prefix = "test_" if test_mode else ""
        infos = [cur_stats] + final_env_infos
        cur_stats.update({k: sum(d.get(k, 0) for d in infos) for k in set.union(*[set(d) for d in infos])})
        cur_stats["n_episodes"] = self.batch_size + cur_stats.get("n_episodes", 0)
        cur_stats["ep_length"] = sum(episode_lengths) + cur_stats.get("ep_length", 0)

        cur_returns.extend(episode_returns)
        # self.status_log = np.array([d.get('battle_won', 0) for d in infos][-self.args.batch_size_run:], dtype=np.float32)
        for i, j in enumerate(self.sce_this_run):
            self.bwm_this_run[j] = self.bwm_this_run[j] + self.status_log[i]
            self.c_this_run[j] = self.c_this_run[j] + 1

        n_test_runs = max(1, self.args.test_nepisode // self.batch_size) * self.batch_size
        if test_mode and (len(self.test_returns) == n_test_runs):
            self.test_returns_log = np.mean(cur_returns)
            self._log(cur_returns, cur_stats, log_prefix)
            self._update_bwm()

        elif not test_mode and self.t_env - self.log_train_stats_t >= self.args.runner_log_interval:
            self._log(cur_returns, cur_stats, log_prefix)
            if hasattr(self.mac.action_selector, "epsilon"):
                self.logger.log_stat("epsilon", self.mac.action_selector.epsilon, self.t_env)
            if 'sc2' in self.args.env:
                self.logger.log_stat("forced_restarts",
                                     sum(es['restarts'] for es in env_stats),
                                     self.t_env)
            self.log_train_stats_t = self.t_env

        return self.batch

    def _log(self, returns, stats, prefix):
        self.logger.log_stat(prefix + "return_mean", np.mean(returns), self.t_env)
        self.logger.log_stat(prefix + "return_std", np.std(returns), self.t_env)
        returns.clear()

        for k, v in stats.items():
            if k != "n_episodes" and k != 'agents' and k != 'box':
                self.logger.log_stat(prefix + k + "_mean", v / stats["n_episodes"], self.t_env)
        stats.clear()

    def _update_bwm(self):
        idx = [i for i, v in enumerate(self.c_this_run) if v != 0]
        self.c_this_run[self.c_this_run == 0] = 1
        self.bwm_this_run = self.bwm_this_run / self.c_this_run
        if self.args.use_bwm_beta:
            self.bwm[idx] = (1 - self.args.bwm_beta) * self.bwm[idx] + self.args.bwm_beta * self.bwm_this_run[idx]
        else:
            delta = np.zeros(self.args.scenario_len)
            delta[idx] = self.bwm_this_run[idx] - self.bwm[idx]
            alpha = np.min([self.args.test_interval, self.t_env]) / self.t_env
            self.bwm[idx] = self.bwm[idx] + alpha * delta[idx]
        self.bwm_this_run = np.zeros(self.args.scenario_len)
        self.c_this_run = np.zeros(self.args.scenario_len)


def env_worker(remote, entity_scheme, env_fn):
    # Make environment
    env = env_fn.x()
    while True:
        cmd, data = remote.recv()
        if cmd == "step":
            actions = data
            # Take a step in the environment
            reward, terminated, env_info = env.step(actions)
            send_dict = {
                "avail_actions": env.get_avail_actions(),
                # Rest of the data for the current timestep
                "reward": reward,
                "terminated": terminated,
                "info": env_info
            }
            if entity_scheme:
                masks = env.get_masks()
                if len(masks) == 2:
                    obs_mask, entity_mask = masks
                    gt_mask = None
                else:
                    obs_mask, entity_mask, gt_mask = masks
                send_dict["obs_mask"] = obs_mask
                send_dict["entity_mask"] = entity_mask
                if gt_mask is not None:
                    send_dict["gt_mask"] = gt_mask
                send_dict["entities"] = env.get_entities()
            else:
                # Data for the next timestep needed to pick an action
                send_dict["state"] = env.get_state()
                send_dict["obs"] = env.get_obs()
            remote.send(send_dict)
        elif cmd == "reset":
            env.reset(**data)
            if entity_scheme:
                masks = env.get_masks()
                if len(masks) == 2:
                    obs_mask, entity_mask = masks
                    gt_mask = None
                else:
                    obs_mask, entity_mask, gt_mask = masks
                send_dict = {
                    "entities": env.get_entities(),
                    "avail_actions": env.get_avail_actions(),
                    "obs_mask": obs_mask,
                    "entity_mask": entity_mask,
                    "scenario": env.get_scenario(),
                }
                if gt_mask is not None:
                    send_dict["gt_mask"] = gt_mask
                remote.send(send_dict)
            else:
                remote.send({
                    "state": env.get_state(),
                    "avail_actions": env.get_avail_actions(),
                    "obs": env.get_obs()
                })
        elif cmd == "close":
            env.close()
            remote.close()
            break
        elif cmd == "get_env_info":
            remote.send(env.get_env_info(data))
        elif cmd == "get_stats":
            remote.send(env.get_stats())
        # TODO: unused now?
        # elif cmd == "agg_stats":
        #     agg_stats = env.get_agg_stats(data)
        #     remote.send(agg_stats)
        else:
            raise NotImplementedError


class CloudpickleWrapper():
    """
    Uses cloudpickle to serialize contents (otherwise multiprocessing tries to use pickle)
    """

    def __init__(self, x):
        self.x = x

    def __getstate__(self):
        import cloudpickle
        return cloudpickle.dumps(self.x)

    def __setstate__(self, ob):
        import pickle
        self.x = pickle.loads(ob)
