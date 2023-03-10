import numpy as np
import os
import collections
from os.path import dirname, abspath
from sacred import Experiment, SETTINGS
from sacred.observers import FileStorageObserver
from sacred.utils import apply_backspaces_and_linefeeds
import sys
import torch as th
from utils.logging import get_logger
import yaml
import time

from run import run

SETTINGS['CAPTURE_MODE'] = "fd"  # set to "no" if you want to see stdout/stderr in console
logger = get_logger()

ex = Experiment("pymarl")
ex.logger = logger
ex.captured_out_filter = apply_backspaces_and_linefeeds

results_path = os.path.join(dirname(dirname(abspath(__file__))), "results")
# os.environ['CUDA_VISIBLE_DEVICES'] = '2'

@ex.main
def my_main(_run, _config, _log, env_args):
    # Setting the random seed throughout the modules
    np.random.seed(_config["seed"])
    th.manual_seed(_config["seed"])
    env_args['seed'] = _config["seed"]

    # run the framework
    run(_run, _config, _log)

    # force exit
    os._exit(0)


def _get_config(params, arg_name, subfolder):
    config_name = None
    for _i, _v in enumerate(params):
        if _v.split("=")[0] == arg_name:
            config_name = _v.split("=")[1]
            del params[_i]
            break

    if config_name is not None:
        with open(os.path.join(os.path.dirname(__file__), "config", subfolder, "{}.yaml".format(config_name)), "r") as f:
            try:
                config_dict = yaml.load(f)
            except yaml.YAMLError as exc:
                assert False, "{}.yaml error: {}".format(config_name, exc)
        return config_dict

def _get_map_name(params, arg_name):
    for _i, _v in enumerate(params):
        if _v.split("=")[0] == arg_name:
            map_name = _v.split("=")[1]
            # del params[_i]
            break
    return map_name

def recursive_dict_update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            d[k] = recursive_dict_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


if __name__ == '__main__':
    import os

    from copy import deepcopy
    params = deepcopy(sys.argv)

    # Get the defaults from default.yaml
    with open(os.path.join(os.path.dirname(__file__), "config", "default.yaml"), "r") as f:
        try:
            config_dict = yaml.load(f)
        except yaml.YAMLError as exc:
            assert False, "default.yaml error: {}".format(exc)

    # Load algorithm and env base configs
    env_config = _get_config(params, "--env-config", "envs")
    alg_config = _get_config(params, "--config", "algs")
    # config_dict = {**config_dict, **env_config, **alg_config}
    config_dict = recursive_dict_update(config_dict, env_config)
    config_dict = recursive_dict_update(config_dict, alg_config)

    # now add all the config to sacred
    ex.add_config(config_dict)

    if not config_dict['evaluate']:  # only log if training
        # Save to disk by default for sacred
        logger.info("Saving to FileStorageObserver in results/sacred.")
        map_name = _get_map_name(params,'scenario')
        file_obs_path = os.path.join(config_dict['local_results_path'],map_name, "sacred")
        while True:
            try:
                ex.observers.append(FileStorageObserver.create(file_obs_path))
                break
            except FileExistsError:
                # sometimes we see race condition
                logger.info("Creating FileStorageObserver failed. Trying again...")
                time.sleep(1)

    ex.run_commandline(params)

