from numpy.random import RandomState
from os.path import dirname, join
from functools import partial
from itertools import combinations_with_replacement, product


def get_all_unique_teams(all_types, min_len, max_len):
    all_uniq = []
    for i in range(min_len, max_len + 1):
        all_uniq += list(combinations_with_replacement(all_types, i))
    all_uniq_counts = []
    for scen in all_uniq:
        curr_uniq = list(set(scen))
        uniq_counts = list(zip([scen.count(u) for u in curr_uniq], curr_uniq))
        all_uniq_counts.append(uniq_counts)
    return all_uniq_counts


def fixed_armies(ally_army, enemy_army, ally_centered=False, rotate=False,
                 separation=10, jitter=0, episode_limit=100,
                 map_name="empty_passive", rs=None):
    scenario_dict = {'scenarios': [(ally_army, enemy_army)],
                     'max_types_and_units_scenario': (ally_army, enemy_army),
                     'ally_centered': ally_centered,
                     'rotate': rotate,
                     'separation': separation,
                     'jitter': jitter,
                     'episode_limit': episode_limit,
                     'map_name': map_name}
    return scenario_dict


def symmetric_armies(army_spec, ally_centered=False,
                     rotate=False, separation=10,
                     jitter=0, episode_limit=100, map_name="empty_passive",
                     n_extra_tags=0,
                     rs=None):
    if rs is None:
        rs = RandomState()

    unique_sub_teams = []
    for unit_types, n_unit_range in army_spec:
        unique_sub_teams.append(get_all_unique_teams(unit_types, n_unit_range[0],
                                                     n_unit_range[1]))
    unique_teams = [sum(prod, []) for prod in product(*unique_sub_teams)]

    scenarios = list(zip(unique_teams, unique_teams))
    # sort by number of types and total number of units
    max_types_and_units_team = sorted(unique_teams, key=lambda x: (len(x), sum(num for num, unit in x)), reverse=True)[0]
    # a = sum(num for num, unit in unique_teams[0])
    max_types_and_units_scenario = (max_types_and_units_team,
                                    max_types_and_units_team)

    scenario_dict = {'scenarios': scenarios,
                     'max_types_and_units_scenario': max_types_and_units_scenario,
                     'ally_centered': ally_centered,
                     'rotate': rotate,
                     'separation': separation,
                     'jitter': jitter,
                     'episode_limit': episode_limit,
                     'n_extra_tags': n_extra_tags,
                     'map_name': map_name}
    return scenario_dict


def asymm_armies(army_spec, spec_delta, ally_centered=False,
                 rotate=False, separation=10,
                 jitter=0, episode_limit=100, map_name="empty_passive",
                 n_extra_tags=0,
                 rs=None):
    if rs is None:
        rs = RandomState()

    unique_sub_teams = []
    for unit_types, n_unit_range in army_spec:
        unique_sub_teams.append(get_all_unique_teams(unit_types, n_unit_range[0],
                                                     n_unit_range[1]))
    enemy_teams = [sum(prod, []) for prod in product(*unique_sub_teams)]
    agent_teams = [[(max(num + spec_delta.get(typ, 0), 0), typ) for num, typ in team] for team in enemy_teams]

    scenarios = list(zip(agent_teams, enemy_teams))
    # sort by number of types and total number of units
    max_types_and_units_ag_team = sorted(agent_teams, key=lambda x: (len(x), sum(num for num, unit in x)), reverse=True)[0]
    max_types_and_units_en_team = sorted(enemy_teams, key=lambda x: (len(x), sum(num for num, unit in x)), reverse=True)[0]
    max_types_and_units_scenario = (max_types_and_units_ag_team,
                                    max_types_and_units_en_team)

    scenario_dict = {'scenarios': scenarios,
                     'max_types_and_units_scenario': max_types_and_units_scenario,
                     'ally_centered': ally_centered,
                     'rotate': rotate,
                     'separation': separation,
                     'jitter': jitter,
                     'episode_limit': episode_limit,
                     'n_extra_tags': n_extra_tags,
                     'map_name': map_name}
    return scenario_dict


def sym_asym_armies(army_spec, spec_delta, ally_centered=False,
                 rotate=False, separation=10,
                 jitter=0, episode_limit=100, map_name="empty_passive",
                 n_extra_tags=0,
                 rs=None):
    if rs is None:
        rs = RandomState()

    unique_sub_teams = []
    for unit_types, n_unit_range in army_spec:
        unique_sub_teams.append(get_all_unique_teams(unit_types, n_unit_range[0],
                                                     n_unit_range[1]))
    enemy_teams = [sum(prod, []) for prod in product(*unique_sub_teams)]
    agent_teams = [[(max(num + spec_delta.get(typ, 0), 0), typ) for num, typ in team] for team in enemy_teams]
    unique_teams = [sum(prod, []) for prod in product(*unique_sub_teams)]

    enemy = enemy_teams + unique_teams
    agent = agent_teams + unique_teams

    scenarios = list(zip(agent, enemy))
    # sort by number of types and total number of units
    max_types_and_units_ag_team = sorted(agent, key=lambda x: (len(x), sum(num for num, unit in x)), reverse=True)[0]
    max_types_and_units_en_team = sorted(enemy, key=lambda x: (len(x), sum(num for num, unit in x)), reverse=True)[0]
    max_types_and_units_scenario = (max_types_and_units_ag_team,
                                    max_types_and_units_en_team)

    scenario_dict = {'scenarios': scenarios,
                     'max_types_and_units_scenario': max_types_and_units_scenario,
                     'ally_centered': ally_centered,
                     'rotate': rotate,
                     'separation': separation,
                     'jitter': jitter,
                     'episode_limit': episode_limit,
                     'n_extra_tags': n_extra_tags,
                     'map_name': map_name}
    return scenario_dict


"""
The function in the registry needs to return a tuple of two lists, one for the
ally army and one for the enemy.
Each is of the form [(number, unit_type, pos), ....], where pos is the starting
positiong (relative to center of map) for the corresponding units.
The function will be called on each episode start.
Currently, we only support the same number of agents and enemies each episode.
"""

REGISTRY = {}
REGISTRY["case_study"] = {
  'scenarios': list([([(5, 'Marine')], [(5, 'Marine')]), ([(6, 'Marine')], [(6, 'Marine')]), ([(5, 'Marine')], [(6, 'Marine')])]),
  'max_types_and_units_scenario': ([(6, 'Marine')],[(6, 'Marine')]),
  'ally_centered': False,
  'rotate': True,
  'separation': 14,
  'jitter': 1,
  'episode_limit': 100,
  'n_extra_tags': 0,
  'map_name': "empty_passive"}




custom_scenario_registry = {
  "3-8m_symmetric": partial(symmetric_armies,
                            [(('Marine',), (3, 8))],
                            rotate=True,
                            ally_centered=False,
                            separation=14,
                            jitter=1, episode_limit=100, map_name="empty_passive"),
  "6-11m_symmetric": partial(symmetric_armies,
                            [(('Marine',), (6, 11))],
                            rotate=True,
                            ally_centered=False,
                            separation=14,
                            jitter=1, episode_limit=100, map_name="empty_passive"),
  "6-11m_mandown": partial(asymm_armies,
                          [(('Marine',), (6, 11))],
                          {'Marine': -1},
                          rotate=True,
                          ally_centered=False,
                          separation=14,
                          jitter=1, episode_limit=100, map_name="empty_passive"),
  "3-8z_symmetric": partial(symmetric_armies,
                              [(('Zealot',), (3, 8))],
                              rotate=True,
                              ally_centered=False,
                              separation=14,
                              jitter=1, episode_limit=100, map_name="empty_passive"),
  "8z_symmetric": partial(symmetric_armies,
                              [(('Zealot',), (8, 8))],
                              rotate=True,
                              ally_centered=False,
                              separation=14,
                              jitter=1, episode_limit=100, map_name="empty_passive"),
  "3-8mara_symmetric": partial(symmetric_armies,
                              [(('Marauder',), (3, 8))],
                              rotate=True,
                              ally_centered=False,
                              separation=14,
                              jitter=1, episode_limit=100, map_name="empty_passive"),

  "3-8sz_symmetric": partial(symmetric_armies,
                             [(('Stalker', 'Zealot'), (3, 8))],
                             rotate=True,
                             ally_centered=False,
                             separation=14,
                             jitter=1, episode_limit=150, map_name="empty_passive"),
  "3-8MMM_symmetric": partial(symmetric_armies,
                              [(('Marine', 'Marauder'), (3, 6)),
                               (('Medivac',), (0, 2))],
                              rotate=True,
                              ally_centered=False,
                              separation=14,
                              jitter=1, episode_limit=150, map_name="empty_passive"),
  "3-8csz_symmetric": partial(symmetric_armies,
                              [(('Stalker', 'Zealot'), (3, 6)),
                               (('Colossus',), (0, 2))],
                              rotate=True,
                              ally_centered=False,
                              separation=14,
                              jitter=1, episode_limit=150, map_name="empty_passive"),
  "case_study": REGISTRY["case_study"],
}


if __name__ == '__main__':
    # ss = symmetric_armies([(('Stalker', 'Zealot'), (3, 6)),
    #                            (('Colossus',), (0, 2))],
    #                           rotate=True,
    #                           ally_centered=False,
    #                           separation=14,
    #                           jitter=1, episode_limit=150, map_name="empty_passive")
    dd = sym_asym_armies([(('Marine',), (6, 11))],
                          {'Marine': -1},
                          rotate=True,
                          ally_centered=False,
                          separation=14,
                          jitter=1, episode_limit=100, map_name="empty_passive")

    dd = asymm_armies([(('Marine',), (6, 11))],
                          {'Marine': -1},
                          rotate=True,
                          ally_centered=False,
                          separation=14,
                          jitter=1, episode_limit=100, map_name="empty_passive")

    dd2 = symmetric_armies([(('Stalker', 'Zealot'), (5, 5))],
                             rotate=True,
                             ally_centered=False,
                             separation=14,
                             jitter=1, episode_limit=150, map_name="empty_passive")
    print(dd['scenarios'])
    print(dd['max_types_and_units_scenario'])

    dd2 = REGISTRY["case_study"]
    print(dd2['scenarios'])
    print(dd2['max_types_and_units_scenario'])



    # [(('Stalker',), (0, 3)),
    #  (('Zealot',), (4, 6)),
    #  (('Colossus',), (0, 2))],
    # {'Zealot': -1},
    # rotate = True,
    # ally_centered = False,
    # separation = 14,
    # jitter = 1, episode_limit = 150, map_name = "empty_passive"

    # test_scenario = partial(symmetric_armies,
    #                          [(('Stalker', 'Zealot'), (3, 8))],
    #                          rotate=True,
    #                          ally_centered=False,
    #                          separation=14,
    #                          jitter=1, episode_limit=150, map_name="empty_passive")
    # a = test_scenario['scenarios']
    print('dd')