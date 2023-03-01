# PTM

Code for PTM

This codebase is built on top of the [PyMARL](https://github.com/oxwhirl/pymarl) framework and [REFIL](https://github.com/shariqiqbal2810/REFIL) for multi-agent reinforcement learning algorithms.

## Dependencies

- Docker
- NVIDIA-Docker (if you want to use GPUs)

## Setup instructions

Build the Dockerfile using 

```shell
cd docker
./build.sh
```

Set up StarCraft II.

```shell
./install_sc2.sh
```

## Run an experiment in SMAC

```shell
cd src
python main.py --env-config=sc2custom --config=mtmarl_exp with scenario=<ENV> 
```

Possible ENVs  are:

+ case_study
+ 6-11m_symmetric
+ sym_asym