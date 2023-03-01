import torch as th
import torch.nn as nn
import torch.nn.functional as F
from modules.layers import EntityAttentionLayer, EntityPoolingLayer
import numpy as np

class EntityAttentionRNNAgent(nn.Module):
    def __init__(self, input_shape, args):
        super(EntityAttentionRNNAgent, self).__init__()
        self.args = args

        self.fc1 = nn.Linear(input_shape, args.attn_embed_dim)
        if args.pooling_type is None:
            self.attn = EntityAttentionLayer(args.attn_embed_dim,
                                             args.attn_embed_dim,
                                             args.attn_embed_dim, args)
        else:
            self.attn = EntityPoolingLayer(args.attn_embed_dim,
                                           args.attn_embed_dim,
                                           args.attn_embed_dim,
                                           args.pooling_type,
                                           args)
        self.fc2 = nn.Linear(args.attn_embed_dim, args.rnn_hidden_dim)
        self.rnn = nn.GRUCell(args.rnn_hidden_dim, args.rnn_hidden_dim)
        self.fc3 = nn.Linear(args.rnn_hidden_dim, args.n_actions)

    def init_hidden(self):
        # make hidden states on same device as model
        return self.fc1.weight.new(1, self.args.rnn_hidden_dim).zero_()

    def forward(self, inputs, hidden_state, ret_attn_logits=None):
        entities, obs_mask, entity_mask = inputs
        bs, ts, ne, ed = entities.shape
        entities = entities.reshape(bs * ts, ne, ed)
        obs_mask = obs_mask.reshape(bs * ts, ne, ne)
        entity_mask = entity_mask.reshape(bs * ts, ne)
        agent_mask = entity_mask[:, :self.args.n_agents]
        x1 = F.relu(self.fc1(entities))
        attn_outs = self.attn(x1, pre_mask=obs_mask,
                              post_mask=agent_mask,
                              ret_attn_logits=ret_attn_logits)
        if ret_attn_logits is not None:
            x2, attn_logits = attn_outs
        else:
            x2 = attn_outs
        x3 = F.relu(self.fc2(x2))
        x3 = x3.reshape(bs, ts, self.args.n_agents, -1)

        h = hidden_state.reshape(-1, self.args.rnn_hidden_dim)
        hs = []
        for t in range(ts):
            curr_x3 = x3[:, t].reshape(-1, self.args.rnn_hidden_dim)
            h = self.rnn(curr_x3, h)
            hs.append(h.reshape(bs, self.args.n_agents, self.args.rnn_hidden_dim))
        hs = th.stack(hs, dim=1)  # Concat over time

        q = self.fc3(hs)
        # zero out output for inactive agents
        q = q.reshape(bs, ts, self.args.n_agents, -1)
        q = q.masked_fill(agent_mask.reshape(bs, ts, self.args.n_agents, 1), 0)
        # q = q.reshape(bs * self.args.n_agents, -1)
        if ret_attn_logits is not None:
            return q, h, attn_logits.reshape(bs, ts, self.args.n_agents, ne)
        return q, hs

class ImagineEntityAttentionRNNAgent(EntityAttentionRNNAgent):
    def __init__(self, *args, **kwargs):
        super(ImagineEntityAttentionRNNAgent, self).__init__(*args, **kwargs)

    def logical_not(self, inp):
        return 1 - inp

    def logical_or(self, inp1, inp2):
        out = inp1 + inp2
        out[out > 1] = 1
        return out

    def entitymask2attnmask(self, entity_mask):
        bs, ts, ne = entity_mask.shape
        # agent_mask = entity_mask[:, :, :self.args.n_agents]
        in1 = (1 - entity_mask.to(th.float)).reshape(bs * ts, ne, 1)
        in2 = (1 - entity_mask.to(th.float)).reshape(bs * ts, 1, ne)
        attn_mask = 1 - th.bmm(in1, in2)
        return attn_mask.reshape(bs, ts, ne, ne).to(th.uint8)

    def forward(self, inputs, hidden_state, imagine=False, **kwargs):
        if not imagine:
            return super(ImagineEntityAttentionRNNAgent, self).forward(inputs, hidden_state)
        entities, obs_mask, entity_mask = inputs
        bs, ts, ne, ed = entities.shape

        # create random split of entities (once per episode)
        groupA_probs = th.rand(bs, 1, 1, device=entities.device).repeat(1, 1, ne)

        groupA = th.bernoulli(groupA_probs).to(th.uint8)
        groupB = self.logical_not(groupA)
        # mask out entities not present in env
        groupA = self.logical_or(groupA, entity_mask[:, [0]])
        groupB = self.logical_or(groupB, entity_mask[:, [0]])

        # convert entity mask to attention mask
        groupAattnmask = self.entitymask2attnmask(groupA)
        groupBattnmask = self.entitymask2attnmask(groupB)
        # create attention mask for interactions between groups
        interactattnmask = self.logical_or(self.logical_not(groupAattnmask),
                                           self.logical_not(groupBattnmask))
        # get within group attention mask
        withinattnmask = self.logical_not(interactattnmask)

        activeattnmask = self.entitymask2attnmask(entity_mask[:, [0]])
        # get masks to use for mixer (no obs_mask but mask out unused entities)
        Wattnmask_noobs = self.logical_or(withinattnmask, activeattnmask)
        Iattnmask_noobs = self.logical_or(interactattnmask, activeattnmask)
        # mask out agents that aren't observable (also expands time dim due to shape of obs_mask)
        withinattnmask = self.logical_or(withinattnmask, obs_mask)
        interactattnmask = self.logical_or(interactattnmask, obs_mask)

        entities = entities.repeat(3, 1, 1, 1)
        obs_mask = th.cat([obs_mask, withinattnmask, interactattnmask], dim=0)
        entity_mask = entity_mask.repeat(3, 1, 1)

        inputs = (entities, obs_mask, entity_mask)
        hidden_state = hidden_state.repeat(3, 1, 1)
        q, h = super(ImagineEntityAttentionRNNAgent, self).forward(inputs, hidden_state)
        return q, h, (Wattnmask_noobs.repeat(1, ts, 1, 1), Iattnmask_noobs.repeat(1, ts, 1, 1))


class ImagineEntityAttentionRNNAgentDrop(EntityAttentionRNNAgent):
    def __init__(self, *args, **kwargs):
        super(ImagineEntityAttentionRNNAgentDrop, self).__init__(*args, **kwargs)

    def logical_not(self, inp):
        return 1 - inp

    def logical_or(self, inp1, inp2):
        out = inp1 + inp2
        out[out > 1] = 1
        return out

    def entitymask2attnmask(self, entity_mask):
        bs, ts, ne = entity_mask.shape
        # agent_mask = entity_mask[:, :, :self.args.n_agents]
        in1 = (1 - entity_mask.to(th.float)).reshape(bs * ts, ne, 1)
        in2 = (1 - entity_mask.to(th.float)).reshape(bs * ts, 1, ne)
        attn_mask = 1 - th.bmm(in1, in2)
        return attn_mask.reshape(bs, ts, ne, ne).to(th.uint8)

    def forward(self, inputs, hidden_state, imagine=False, **kwargs):
        if not imagine:
            return super(ImagineEntityAttentionRNNAgentDrop, self).forward(inputs, hidden_state)
        entities, obs_mask, entity_mask = inputs
        bs, ts, ne, ed = entities.shape

        # create random split of entities (once per episode)
        groupA_probs = th.rand(bs, 1, 1, device=entities.device).repeat(1, 1, ne)

        groupA = th.bernoulli(groupA_probs).to(th.uint8)
        groupB = self.logical_not(groupA)
        # mask out entities not present in env
        groupA = self.logical_or(groupA, entity_mask[:, [0]])
        groupB = self.logical_or(groupB, entity_mask[:, [0]])

        # convert entity mask to attention mask
        groupAattnmask = self.entitymask2attnmask(groupA)
        groupBattnmask = self.entitymask2attnmask(groupB)
        # create attention mask for interactions between groups
        interactattnmask = self.logical_or(self.logical_not(groupAattnmask),
                                           self.logical_not(groupBattnmask))
        # get within group attention mask
        withinattnmask = self.logical_not(interactattnmask)

        activeattnmask = self.entitymask2attnmask(entity_mask[:, [0]])
        # get masks to use for mixer (no obs_mask but mask out unused entities)
        Wattnmask_noobs = self.logical_or(withinattnmask, activeattnmask)
        Iattnmask_noobs = self.logical_or(interactattnmask, activeattnmask)
        # mask out agents that aren't observable (also expands time dim due to shape of obs_mask)
        withinattnmask = self.logical_or(withinattnmask, obs_mask)
        interactattnmask = self.logical_or(interactattnmask, obs_mask)

        # drop_loss --
        if self.args.drop_fix:
            drop_probs = self.args.drop_rate * th.ones(bs, ts, 1, 1, device=entities.device).repeat(1, 1, ne, ne)
            ndrop_obs = th.bernoulli(drop_probs).to(th.uint8)
            drop_attnmask = self.logical_or(ndrop_obs, obs_mask)
            drop_attnmask_noobs = self.logical_or(ndrop_obs, activeattnmask)
        else:
            drop_probs = th.rand(bs, 1, 1, device=entities.device).repeat(1, 1, ne)
            drop_groupA = th.bernoulli(drop_probs).to(th.uint8)
            drop_groupB = self.logical_not(drop_groupA)
            # mask out entities not present in env
            drop_groupA = self.logical_or(drop_groupA, entity_mask[:, [0]])
            drop_groupB = self.logical_or(drop_groupB, entity_mask[:, [0]])

            # convert entity mask to attention mask
            drop_groupAattnmask = self.entitymask2attnmask(drop_groupA)
            drop_groupBattnmask = self.entitymask2attnmask(drop_groupB)
            # create attention mask for interactions between groups
            drop_interactattnmask = self.logical_or(self.logical_not(drop_groupAattnmask),
                                               self.logical_not(drop_groupBattnmask))
            # get within group attention mask
            drop_withinattnmask = self.logical_not(drop_interactattnmask)
            drop_attnmask_noobs = self.logical_or(drop_withinattnmask, activeattnmask).repeat(1, ts, 1, 1)
            drop_attnmask = self.logical_or(drop_withinattnmask, obs_mask)




        entities = entities.repeat(4, 1, 1, 1)
        obs_mask = th.cat([obs_mask, withinattnmask, interactattnmask, drop_attnmask], dim=0)
        entity_mask = entity_mask.repeat(4, 1, 1)

        inputs = (entities, obs_mask, entity_mask)
        hidden_state = hidden_state.repeat(4, 1, 1)
        q, h = super(ImagineEntityAttentionRNNAgentDrop, self).forward(inputs, hidden_state)
        return q, h, (Wattnmask_noobs.repeat(1, ts, 1, 1), Iattnmask_noobs.repeat(1, ts, 1, 1), drop_attnmask_noobs)