"""Contains utility functions"""
import inspect
import sys
from typing import Callable
import torch
import torch.nn.functional as F
from skimage.color import hsv2rgb as sk_hsv2rgb
import numpy as np
import cppn_torch.activation_functions as af
import cppn_torch.fitness_functions as ff
import logging

def is_valid_connection(nodes, connections, key:tuple, config, warn:bool=False):
    """
    Checks if a connection is valid.
    params:
        from_node: The node from which the connection originates.
        to_node: The node to which the connection connects.
        config: The settings to check against
    returns:
        True if the connection is valid, False otherwise.
    """
    from_node, to_node = key
    from_node, to_node = nodes[from_node], nodes[to_node]
    
    connections = list(connections.keys())
    
    # if from_node.layer == to_node.layer:
    #     if warn:
    #         logging.warning(f"Connection from node {from_node.id} (layer:{from_node.layer}) to node {to_node.id} (layer:{to_node.layer}) is invalid because they are on the same layer.")
    #     return False  # don't allow two nodes on the same layer to connect

    if not config.allow_recurrent and creates_cycle(connections, key):
        if warn:
            logging.warning(f"Connection from node {from_node.id} (layer:{from_node.layer}) to node {to_node.id} (layer:{to_node.layer}) is invalid because it creates a cycle.")
        return False
    # if not config.allow_recurrent and from_node.layer > to_node.layer:
    #     if warn:
    #         logging.warning(f"Connection from node {from_node.id} (layer:{from_node.layer}) to node {to_node.id} (layer:{to_node.layer}) is invalid because it is recurrent.")
    #     return False  # invalid

    return True


def name_to_fn(name):
    """
    Converts a string to a function.
    params:
        name: The name of the function.
    returns:
        The function.
    """
    if isinstance(name, (Callable,)) or name is None:
        return name
    assert isinstance(name, str), f"name must be a string but is {type(name)}"
    if name == "":
        return None
    fns = inspect.getmembers(sys.modules[af.__name__])
    fns.extend(inspect.getmembers(sys.modules[ff.__name__]))
    
    fns.extend([("round", lambda x: torch.round(x))])
    
    if name == "Conv2d":
        return torch.nn.Conv2d
    
    try:
        return fns[[f[0] for f in fns].index(name)][1]
    except ValueError:
        raise ValueError(f"Function {name} not found.")


def choose_random_function(generator, config) -> Callable:
    """Chooses a random activation function from the activation function module."""
    if generator:
        random_fn = config.activations[torch.randint(0,
                                                    len(config.activations),
                                                    (1,), 
                                                    generator=generator,
                                                    device=generator.device)[0]]
    else:
        random_fn = config.activations[torch.randint(0,
                                                    len(config.activations),
                                                    (1,))[0]]
    return random_fn


def get_disjoint_connections(this_cxs, other_innovation):
    """returns connections in this_cxs that do not share an innovation number with a
        connection in other_innovation"""
    if(len(this_cxs) == 0 or len(other_innovation) == 0):
        return []
    return [t_cx for t_cx in this_cxs if\
        (t_cx.key not in other_innovation and t_cx.key < other_innovation[-1])]


def get_excess_connections(this_cxs, other_innovation):
    """returns connections in this_cxs that share an innovation number with a
        connection in other_innovation"""
    if(len(this_cxs) == 0 or len(other_innovation) == 0):
        return []
    return [t_cx for t_cx in this_cxs if\
            (t_cx.key not in other_innovation and t_cx.key > other_innovation[-1])]


def get_matching_connections(cxs_1, cxs_2):
    """returns connections in cxs_1 that share an innovation number with a connection in cxs_2
       and     connections in cxs_2 that share an innovation number with a connection in cxs_1"""

    return sorted([c1 for c1 in cxs_1 if c1.key in [c2.key for c2 in cxs_2]],
                    key=lambda x: x.key),\
                    sorted([c2 for c2 in cxs_2 if c2.key in [c1.key for c1 in cxs_1]],
                    key=lambda x: x.key)


def find_node_with_id(nodes, node_id):
    """Returns the node with the given id from the list of nodes"""
    return nodes[node_id]
    # for node in nodes:
    #     if node.id == node_id:
    #         return node
    # return None

def find_cx_with_innovation(cxs, innovation):
    """Returns the node with the given id from the list of nodes"""
    for cx in cxs:
        if cx.key == innovation:
            return cx
    return None


def get_ids_from_individual(individual):
    """Gets the ids from a given individual

    Args:
        individual (CPPN): The individual to get the ids from.

    Returns:
        tuple: (inputs, outputs, connections) the ids of the CPPN's nodes
    """
    inputs = list(individual.input_nodes().keys())
    outputs = list(individual.output_nodes().keys())
    connections = [c.key
                   for c in individual.enabled_connections()]
                #    for c in individual.connection_genome.values()]
    return inputs, outputs, connections


def get_candidate_nodes(s, connections):
    """Find candidate nodes c for the next layer.  These nodes should connect
    a node in s to a node not in s."""
    return set(b for (a, b) in connections if a in s and b not in s)


def get_incoming_connections(individual, node):
    """Given an individual and a node, returns the connections in individual that end at the node"""
    return list(filter(lambda x, n=node: x.key[1] == n.id,
               individual.enabled_connections()))  # cxs that end here

def cx_ids_to_inputs(required_cxs, node_genome):
    inputs = torch.stack([node_genome[c.key[0]].outputs for c in required_cxs], dim=-1)#.to(individual.device)
    weights = torch.stack([cx.weight for cx in required_cxs])#.to(individual.device)
    return inputs, weights

def collect_connections(individual, node_id):
    required_cxs = set()
    
    for cx in individual.connection_genome.values():
        if cx.enabled and cx.key[1] == node_id: #and cx.key[0] in required_nodes:
            required_cxs.add(cx)
    
    return required_cxs

def get_incoming_connections_weights(individual, node_id):
    """Given an individual and a node, returns the connections in individual that end at the node"""
    required_cxs = collect_connections(individual, node_id)
    
    if len(required_cxs) == 0:
        return None, None
    
    weights, inputs = cx_ids_to_inputs(required_cxs, individual.node_genome)
    # weights shape is (num_incoming)
    # inputs shape is (num_incoming, h, w)

    return inputs, weights

def group_incoming_by_fn(inputs, weights, nodes, max_num_incoming) -> dict:
    # from x shapes: (batch, num_incoming, ...)
    # from w shapes: (num_incoming)
    # to x shapes: (batch, nodes_with_fn, num_incoming, ...)
    # to w shapes: (nodes_with_fn, num_incoming)
    X_W_by_fn = {}
    for (id,node), x, w in zip(nodes.items(), inputs, weights):
        fn = node.activation.__name__
        # add nodes_with_fn dimension:
        x, w = x.unsqueeze(1), w.unsqueeze(0) 
        
        # pad inputs and weights with zeros to match the max number of incoming connections
        x = F.pad(x, (0, 0, 0, 0, 0, max_num_incoming - x.shape[2], 0, 0))
        w = F.pad(w, (0, max_num_incoming - w.shape[1]))

        if fn not in X_W_by_fn:
            X_W_by_fn[fn] = [[id], x, w]
        else:
            # concatenate inputs and weights along nodes_with_fn dimension
            X_W_by_fn[fn][0].append(id)
            X_W_by_fn[fn][1] = torch.cat((X_W_by_fn[fn][1], x), dim=1).to(torch.float32)
            X_W_by_fn[fn][2] = torch.cat((X_W_by_fn[fn][2], w), dim=0).to(torch.float32)
       
    return X_W_by_fn

def activate_layer(Xs, Ws, nodes, agg, name_to_fn = af.__dict__):
    assert len(Xs) == len(Ws) == len(nodes), "Xs, Ws, Fns, and nodes must be the same length"
    X_W_by_fn = group_incoming_by_fn(Xs, Ws, nodes, max([x.shape[1] for x in Xs])) # dict of (X, W) by node
    
    for fn, (ids, X, W) in X_W_by_fn.items():
        # X shape = (batch, nodes_with_fn, num_incoming, ...)
        # W shape = (nodes_with_fn, num_incoming)

        fn = name_to_fn[fn]
        
        if agg == 'sum':
            outputs = torch.einsum('bni...,ni->bn...', X, W)
        
        # TODO: I think these are wrong:
        elif agg == 'mean':
            outputs = torch.einsum('bni...,ni->bn...', X, W) / torch.sum(W, dim=1, keepdim=True)
        # elif agg == 'max':
            # outputs = torch.einsum('bni...,ni->bn...', X, W)
            # outputs = torch.max(outputs, dim=2)[0]
        # elif agg == 'min':
            # outputs = torch.einsum('bni...,ni->bn...', X, W)
            # outputs = torch.min(outputs, dim=2)[0]
        
        else:
            raise ValueError(f"Unknown aggregation function {agg}. Try `config.activation_mode='node'` for more options.")
        
        # add bias
        #outputs += torch.tensor([node.bias for node in nodes.values() ids], device=outputs.device)
        
        # outputs shape should be (batch, nodes_with_fn, ...)
        
        outputs = fn(outputs)  # apply activation
        for idx, id in enumerate(ids):
            output = outputs[:, idx, ...]
            nodes.get(id).outputs = output


def activate_population(genomes, config, inputs = None,  name_to_fn = af.__dict__):
    if inputs is None:
        inputs = type(genomes[0]).constant_inputs
    batch_size = 1 # TODO
        
    if isinstance(genomes[0], tuple):
        genomes = [g for _,_,g in genomes]
    
    result = []
    nodes_by_id = {}
    genomes_by_id = {}
    for g in genomes:
        g.reset_activations()
        genomes_by_id[g.id] = g
        for node in g.node_genome.values():
            nodes_by_id[(g.id, node.id)] = node
    pop_layers = [feed_forward_layers(genome) for genome in genomes]
    for layers, genome in zip(pop_layers, genomes):
        layers.insert(0, set(genome.input_nodes().keys())) # add input nodes as first layer
        for i in range(len(layers)):
            layers[i] = list(layers[i])

    for i, (layers, genome) in enumerate(zip(pop_layers, genomes)):
        for j in range(len(layers)):
            pop_layers[i][j] = [(genome.id, genome.node_genome[id]) for id in layers[j]]
            
    # pop_layers = (population_size, num_layers, num_nodes_in_layer)
    max_num_layers = max([len(l) for l in pop_layers])
    for layer_index in range(max_num_layers):
        # get this layer from all genomes
        layer = [layer[layer_index] for i, layer in enumerate(pop_layers) if layer_index < len(layer)]

        # find all the nodes in this layer that have incoming connections
        # x shapes: (pop, nodes_with_fn, num_incoming, ...)
        # w shapes: (nodes_with_fn, num_incoming)
        Xs, Ws, nodes = [],[],[]
        max_num_incoming = 0
        layer_flat = [n for sublayer in layer for n in sublayer]
        layer_flat = sorted(layer_flat, key=lambda x: x[1].id, reverse=True)
        for genome_id, node in layer_flat:
            if int(node.type) == 0:
                # initialize the node's sum
                # NOTE: -node.id-1 is really hacky, assumes that input node ids are -1...-num_inputs (they are by default)
                node_index = -node.id-1
                X = inputs[:,:,node_index].repeat(batch_size, 1, 1, 1) # (batch_size, cx, res_h, res_w)
            
                W = torch.ones((1), dtype=config.dtype, device=config.device)
            else:   
                # print("getting incoming connections for ", genome_id, node.id)
                X, W = get_incoming_connections_weights(genomes_by_id[genome_id], node)
                # print("should be", get_incoming_connections(genomes_by_id[genome_id], node))
            if X is not None and X.shape[1] > max_num_incoming:
                max_num_incoming = X.shape[1]
            if X is None:
                X = torch.zeros((1, 1, config.res_h, config.res_w), dtype=config.dtype, device=config.device)
            if W is None:
                W = torch.ones((1), dtype=config.dtype, device=config.device)
            Xs.append(X)
            Ws.append(W)
            nodes.append((genome_id, node))
        layer_nodes_by_id = {(genome_id, node.id): node for genome_id, node in nodes}
        # activate the nodes in this layer
        # group the nodes by their activation function
        assert len(Xs) == len(Ws) == len(nodes), "Xs, Ws, Fns, and nodes must be the same length"
        X_W_by_fn = group_incoming_by_fn(Xs, Ws, layer_nodes_by_id, max_num_incoming) # dict of (X, W) by node
        # print(X_W_by_fn)
        for fn, (ids, layer_X, layer_W) in X_W_by_fn.items():
            # X shape = (batch, nodes_with_fn, num_incoming, ...)
            # W shape = (nodes_with_fn, num_incoming)

            fn = name_to_fn[fn]
            
            if config.node_agg == 'sum':
                outputs = torch.einsum('bni...,ni->bn...', layer_X, layer_W)
            else:
                raise ValueError(f"Unknown config.node_agg function {config.node_agg}. Try `config.activation_mode='node'` for more options.")
            
            # outputs shape should be (batch, nodes_with_fn, ...)
            
            outputs = fn(outputs)  # apply activation
            
            assert len(ids) == outputs.shape[1], "ids and outputs must be the same length"
            for idx, id in enumerate(ids):
                output = outputs[:, idx, ...]
                nodes_by_id.get(id).outputs = output
    
    for g in genomes:
        # collect outputs from the last layer
        sorted_o = sorted(g.output_nodes().values(), key=lambda x: x.key, reverse=True)
        g.outputs = torch.stack([node.outputs for node in sorted_o], dim=1)
        
        if batch_size == 1:
            g.outputs  = g.outputs.squeeze(0) # remove batch dimension if batch size is 1
            # reshape the outputs to image shape
            if not len(g.config.color_mode)>2:
                g.outputs  = torch.reshape(g.outputs, (g.config.res_h, g.config.res_w))
                
        if hasattr(g, 'get_image'):
            if len(g.config.color_mode)>2:
                # g.outputs  =  g.outputs.permute(1, 2, 3, 0) # move color axis to end
                ...
            else:
                g.outputs  = torch.reshape(g.outputs , (1, g.config.res_h, g.config.res_w))

            g.outputs  = g.outputs.squeeze(0) # remove batch dimension if batch size is 1
            # reshape the outputs to image shape
            if not len(g.config.color_mode)>2:
                g.outputs  = torch.reshape(g.outputs, (g.config.res_h, g.config.res_w))
            
            if g.config.normalize_outputs:
                g.normalize_image()

            g.clamp_image()
            
            result.append(g.outputs)
        
        
    return torch.stack(result)




def layer_to_str(cppn, layer, i):
    if isinstance(layer, Conv2d):
        return f'CONV {i}\n{layer.kernel_size}x{layer.in_channels}'
    elif isinstance(layer, torch.nn.MaxPool2d):
        return f'POOL {i}\n{layer.kernel_size}x{layer.in_channels}'
    elif isinstance(layer, torch.nn.MultiheadAttention):
        return f'ATTN {i}\n{layer.num_heads} heads'
    elif isinstance(layer, torch.nn.Sequential) and isinstance(layer[0], torch.nn.Upsample):
        return f'UPSAMPLE {i}\nX{layer[0].scale_factor}'
    elif isinstance(layer, torch.nn.Upsample):
        return f'UPSAMPLE {i}\nX{layer.scale_factor}'
    elif isinstance(layer, torch.nn.Flatten):
        return f'FLATTEN {i}'
    elif isinstance(layer, torch.nn.Unflatten):
        return f'UNFLATTEN {i}'
    elif isinstance(layer, torch.nn.Linear):
        return f'LINEAR {i}'
    elif isinstance(layer, Block):
        return f'RESNET BLOCK {i}'

def to_nx(cppn, only_enabled=True):
    import networkx as nx
    G = nx.DiGraph()
    cppn.update_node_layers()
    for i, layer in enumerate(cppn.pre_layers):
        G.add_node(cppn.layer_to_str(layer, i))
        
    for i, layer in enumerate(cppn.post_layers):
        G.add_node(cppn.layer_to_str(layer, i))
        
    for i, layer in enumerate(cppn.pre_layers[:-1]):
        G.add_edge(cppn.layer_to_str(layer, i), cppn.layer_to_str(cppn.pre_layers[i+1], i+1))
        
    for i, layer in enumerate(cppn.post_layers[:-1]):
        G.add_edge(cppn.layer_to_str(layer, i), cppn.layer_to_str(cppn.post_layers[i+1], i+1))
    
    if only_enabled:
        used_nodes = set()
        for key, cx in cppn.connection_genome.items():
            if cx.enabled:
                G.add_edge(key[0], key[1], weight=cx.weight.item())
                used_nodes.add(key[0])
                used_nodes.add(key[1])
                
        for key, node in cppn.node_genome.items():
            if key in used_nodes:
                G.add_node(key, activation=node.activation.__name__)
    else:
        for n in cppn.node_genome.values():
            G.add_node(n.key, type=n.type.name, fn=n.activation)
        for c in cppn.connection_genome.values():
            if c.enabled:
                G.add_edge(c.key[0], c.key[1], weight=c.weight.item())
            
    if len(cppn.pre_layers) > 0:
        last_layer = cppn.pre_layers[-1]
        last_layer_i = len(cppn.pre_layers)-1
        for n in cppn.input_nodes().values():
            G.add_edge(cppn.layer_to_str(last_layer, last_layer_i), n.key)
            
    if len(cppn.post_layers) > 0:
        first_layer = cppn.post_layers[0]
        first_layer_i = 0
        for n in cppn.output_nodes().values():
            G.add_edge(n.key, cppn.layer_to_str(first_layer, first_layer_i))
    return G


def to_networkx(cppn):
    cppn.update_node_layers()
    G = nx.DiGraph()
    used_nodes = set()
    for key, cx in cppn.connection_genome.items():
        if cx.enabled:
            G.add_edge(key[0], key[1], weight=cx.weight.item())
            used_nodes.add(key[0])
            used_nodes.add(key[1])
            
    for key, node in cppn.node_genome.items():
        if key in used_nodes:
            G.add_node(key, activation=node.activation.__name__)
    
    return G

def draw_nx(cppn, size=(10,20), show=True):
    import matplotlib.pyplot as plt
    import networkx as nx
    from networkx.drawing.nx_agraph import graphviz_layout
    fig = plt.figure(figsize=size)
    G = cppn.to_nx()
    args = "-Grankdir=LR"

    pos = graphviz_layout(G, prog='dot', args=args)
    
    
    
    nx.draw_networkx(
        G,
        with_labels=True,
        pos=pos,
        labels={n:f"{cppn.node_genome[n].layer}.{n}\n{cppn.node_genome[n].activation.__name__[:4]}\n"#{1}xHxW"
                if n in cppn.node_genome else n
                for n in G.nodes(data=False) },
        node_size=800,
        font_size=6,
        node_shape='s',
        node_color=['lightsteelblue' if n in cppn.node_genome else 'lightgreen' for n in G.nodes()  ]
        )
    plt.annotate('# params: ' + str(cppn.num_params), xy=(1.0, 1.0), xycoords='axes fraction', fontsize=12, ha='right', va='top')
    
    plt.tight_layout()
    plt.axis('off')
    if show:
        plt.show()




# Functions below are modified from other packages
# This is necessary because AWS Lambda has strict space limits,
# and we only need a few methods, not the entire packages.

###############################################################################################
# Functions below are from the NEAT-Python package https://github.com/CodeReclaimers/neat-python/

# LICENSE:
# Copyright (c) 2007-2011, cesar.gomes and mirrorballu2
# Copyright (c) 2015-2019, CodeReclaimers, LLC
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of
# conditions and the following
# disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice, this list
# of conditions and the following
# disclaimer in the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors may be
# used to endorse or promote products
# derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS
# OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
###############################################################################################


def creates_cycle(connections, test):
    """
    Returns true if the addition of the 'test' connection would create a cycle,
    assuming that no cycle already exists in the graph represented by 'connections'.
    """
    i, o = test
    if i == o:
        return True

    visited = {o}
    while True:
        num_added = 0
        for a, b in connections:
            if a in visited and b not in visited:
                if b == i:
                    return True

                visited.add(b)
                num_added += 1

        if num_added == 0:
            return False



def required_for_output(inputs, outputs, connections):
    """
    Collect the nodes whose state is required to compute the final network output(s).
    :param inputs: list of the input identifiers
    :param outputs: list of the output node identifiers
    :param connections: list of (input, output) connections in the network.
    NOTE: It is assumed that the input identifier set and the node identifier set are disjoint.
    By convention, the output node ids are always the same as the output index.

    Returns a set of identifiers of required nodes.
    From: https://neat-python.readthedocs.io/en/latest/_modules/graphs.html
    """

    required = set(outputs) # outputs always required
    s = set(outputs)
    while 1:
        # Find nodes not in S whose output is consumed by a node in s.
        t = set(a for (a, b) in connections if b in s and a not in s)

        if not t:
            break

        layer_nodes = set(x for x in t if x not in inputs)
        if not layer_nodes:
            break

        required = required.union(layer_nodes)
        s = s.union(t)

    return required


def feed_forward_layers(individual):
    """
    Collect the layers whose members can be evaluated in parallel in a feed-forward network.
    :param inputs: list of the network input nodes
    :param outputs: list of the output node identifiers
    :param connections: list of (input, output) connections in the network.

    Returns a list of layers, with each layer consisting of a set of node identifiers.
    Note that the returned layers do not contain nodes whose output is ultimately
    never used to compute the final network output.

    Modified from: https://neat-python.readthedocs.io/en/latest/_modules/graphs.html
    """

    inputs, outputs, connections = get_ids_from_individual(individual)
    required = required_for_output(inputs, outputs, connections)

    layers = []
    s = set(inputs)
    
    dangling_inputs = set()
    for n in required:
        has_input = False
        for (a, b) in connections:
            if b == n:
                has_input = True
                break
    
    # add dangling inputs to the input set
    s = s.union(dangling_inputs)
    
    while 1:

        c = get_candidate_nodes(s, connections)
        # Keep only the used nodes whose entire input set is contained in s.
        t = set()
        for n in c:
            entire_input_set_in_s = all(a in s for (a, b) in connections if b == n)
            if n in required and entire_input_set_in_s:
                t.add(n)
        # t = set(a for (a, b) in connections if b in s and a not in s)
        if not t:
            break

        layers.append(t)
        s = s.union(t)
    return layers


# FROM: https://github.com/limacv/RGB_HSV_HSL
def hsl2rgb_torch(hsl: torch.Tensor) -> torch.Tensor:
    hsl = hsl.unsqueeze(0)
    # hsl = hsl.permute(2, 0, 1).unsqueeze(0)
    hsl_h, hsl_s, hsl_l = hsl[:, 0:1], hsl[:, 1:2], hsl[:, 2:3]
    _c = (-torch.abs(hsl_l * 2. - 1.) + 1) * hsl_s
    _x = _c * (-torch.abs(hsl_h * 6. % 2. - 1) + 1.)
    _m = hsl_l - _c / 2.
    idx = (hsl_h * 6.).type(torch.uint8)
    idx = (idx % 6).expand(-1, 3, -1, -1)
    rgb = torch.empty_like(hsl)
    _o = torch.zeros_like(_c)
    rgb[idx == 0] = torch.cat([_c, _x, _o], dim=1)[idx == 0]
    rgb[idx == 1] = torch.cat([_x, _c, _o], dim=1)[idx == 1]
    rgb[idx == 2] = torch.cat([_o, _c, _x], dim=1)[idx == 2]
    rgb[idx == 3] = torch.cat([_o, _x, _c], dim=1)[idx == 3]
    rgb[idx == 4] = torch.cat([_x, _o, _c], dim=1)[idx == 4]
    rgb[idx == 5] = torch.cat([_c, _o, _x], dim=1)[idx == 5]
    rgb += _m
    rgb = rgb.squeeze(0)#.permute(1, 2, 0)
    return rgb