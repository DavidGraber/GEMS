import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import BatchNorm1d
import torch_geometric.nn as geom_nn
from torch_geometric.nn import GATv2Conv, global_add_pool
from torch_geometric.nn import MessagePassing
from torch_geometric.utils import add_self_loops
from torch_scatter import scatter, scatter_mean



class EdgeModel(torch.nn.Module):
    def __init__(self, n_node_f, n_edge_f, hidden_dim, out_dim, residuals):
        super().__init__()
        self.residuals = residuals
        self.edge_mlp = nn.Sequential(
            nn.Linear(2 * n_node_f + n_edge_f, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(self, src, dest, edge_attr, u, batch):
        out = torch.cat([src, dest, edge_attr], 1)
        out = self.edge_mlp(out)
        if self.residuals:
            out = out + edge_attr
        return out


class NodeModel(torch.nn.Module):
    def __init__(self, n_node_f, n_edge_f, hidden_dim, out_dim, residuals):
        super(NodeModel, self).__init__()
        self.residuals = residuals
        self.node_mlp_1 = nn.Sequential(
            nn.Linear(n_node_f + n_edge_f, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.node_mlp_2 = nn.Sequential(
            nn.Linear(hidden_dim + n_node_f, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(self, x, edge_index, edge_attr, u, batch):
        row, col = edge_index
        out = torch.cat([x[col], edge_attr], dim=1) # Concatenate destination node features with edge features
        out = self.node_mlp_1(out) # Apply first MLP to the concatenated edge features
        out = scatter_mean(out, row, dim=0, dim_size=x.size(0)) # Map edge features back to source nodes
        out = torch.cat([x, out], dim=1)
        out = self.node_mlp_2(out)
        if self.residuals:
            out = out + x
        return out
    

class GlobalModel(torch.nn.Module):
    def __init__(self, n_node_f, global_f):
        super().__init__()
        self.global_mlp = nn.Sequential(
            nn.Linear(n_node_f + global_f, int(n_node_f/2)), 
            nn.ReLU(), 
            nn.Linear(int(n_node_f/2), global_f))

    def forward(self, x, edge_index, edge_attr, u, batch):
        # x: [N, F_x], where N is the number of nodes.
        # edge_index: [2, E] with max entry N - 1.
        # edge_attr: [E, F_e]
        # u: [B, F_u]
        # batch: [N] with max entry B - 1.
        out = torch.cat([u, scatter(x, batch, dim=0, reduce='mean')], dim=1)
        return self.global_mlp(out)

#################################################################################################################
#################################################################################################################



# Same as GATE4 (edge features are aggregated instead of the node features), but with more layers
class GATE7(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE7, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, residuals=self.residuals)
        self.layer2 = self.build_layer(node_f=256, edge_f=128, node_f_hidden=256, edge_f_hidden=128, node_f_out=256, edge_f_out=256, residuals=self.residuals)
        #self.layer3 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        
        self.dropout_layer = nn.Dropout(dropout_prob)
        self.fc1 = nn.Linear(256, 64)
        self.fc2 = nn.Linear(64, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            #global_model=GlobalModel(node_f_out, global_f=1)
        )

    def forward(self, graphbatch):
        edge_index = graphbatch.edge_index
        # Initialize global feature of length 1 for each graph in the batch
        #initial_global = torch.zeros((graphbatch.num_graphs, 1)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, edge_index, graphbatch.edge_attr, u=None, batch=graphbatch.batch)
        _, edge_attr, _ = self.layer2(x, edge_index, edge_attr, None, batch=graphbatch.batch)
        #x, edge_attr, _ = self.layer3(x, edge_index, edge_attr, None, batch)

        # Pool the nodes of each interaction graph
        out = scatter(edge_attr, graphbatch.batch[edge_index[0]], dim=0, reduce='mean')
        out = self.dropout_layer(out)
        
        # Fully-Connected Layers
        out = self.fc1(out)
        out = F.relu(out)
        out = self.fc2(out)
        return out










# SAME as GATE5 but regression is performed by the global model with more than a scalar value
class GATE6(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE6, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, global_f=64, residuals=self.residuals)
        self.layer2 = self.build_layer(node_f=256, edge_f=128, node_f_hidden=256, edge_f_hidden=128, node_f_out=512, edge_f_out=256, global_f=64, residuals=self.residuals)
        self.layer3 = self.build_layer(node_f=512, edge_f=256, node_f_hidden=512, edge_f_hidden=256, node_f_out=512, edge_f_out=256, global_f=64, residuals=self.residuals)
        
        self.dropout_layer = nn.Dropout(dropout_prob)
        self.fc1 = nn.Linear(64, 16)
        self.fc2 = nn.Linear(16, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, global_f, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            global_model=GlobalModel(node_f_out, global_f)
        )

    def forward(self, graphbatch):
        edge_index = graphbatch.edge_index
        # Initialize global feature of length 1 for each graph in the batch
        initial_global = torch.zeros((graphbatch.num_graphs, 64)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, edge_index, graphbatch.edge_attr, u=initial_global, batch=graphbatch.batch)
        x, edge_attr, u = self.layer2(x, edge_index, edge_attr, u, batch=graphbatch.batch)
        x, edge_attr, u = self.layer3(x, edge_index, edge_attr, u, batch=graphbatch.batch)
        
        # Fully-Connected Layers
        out = self.fc1(u)
        out = F.relu(out)
        out = self.fc2(out)
        return out







# Regression is performed by the global model based on node features (with three layers)
class GATE5(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE5, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, residuals=self.residuals)
        self.layer2 = self.build_layer(node_f=256, edge_f=128, node_f_hidden=256, edge_f_hidden=128, node_f_out=512, edge_f_out=256, residuals=self.residuals)
        self.layer3 = self.build_layer(node_f=512, edge_f=256, node_f_hidden=512, edge_f_hidden=256, node_f_out=512, edge_f_out=256, residuals=self.residuals)
        
        # self.dropout_layer = nn.Dropout(dropout_prob)
        # self.fc1 = nn.Linear(256, 64)
        # self.fc2 = nn.Linear(64, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            global_model=GlobalModel(node_f_out, global_f=1)
        )

    def forward(self, graphbatch):
        edge_index = graphbatch.edge_index
        # Initialize global feature of length 1 for each graph in the batch
        initial_global = torch.zeros((graphbatch.num_graphs, 1)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, edge_index, graphbatch.edge_attr, u=initial_global, batch=graphbatch.batch)
        x, edge_attr, u = self.layer2(x, edge_index, edge_attr, u, batch=graphbatch.batch)
        x, edge_attr, u = self.layer3(x, edge_index, edge_attr, u, batch=graphbatch.batch)
        
        return u







# Same as initial GATE, but the edge features are aggregated instead of the node features
class GATE4(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE4, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, residuals=self.residuals)
        #self.layer2 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        #self.layer3 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        
        self.dropout_layer = nn.Dropout(dropout_prob)
        self.fc1 = nn.Linear(128, 64)
        self.fc2 = nn.Linear(64, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            #global_model=GlobalModel(node_f_out, global_f=1)
        )

    def forward(self, graphbatch):
        edge_index = graphbatch.edge_index
        # Initialize global feature of length 1 for each graph in the batch
        #initial_global = torch.zeros((graphbatch.num_graphs, 1)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, edge_index, graphbatch.edge_attr, u=None, batch=graphbatch.batch)
        #x, edge_attr, _ = self.layer2(x, edge_index, edge_attr, None, batch)
        #x, edge_attr, _ = self.layer3(x, edge_index, edge_attr, None, batch)

        # Pool the nodes of each interaction graph
        out = scatter(edge_attr, graphbatch.batch[edge_index[0]], dim=0, reduce='mean')
        out = self.dropout_layer(out)
        
        # Fully-Connected Layers
        out = self.fc1(out)
        out = F.relu(out)
        out = self.fc2(out)
        return out




# Regression is performed by the global model based on node features (with two layers)
class GATE3(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE3, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, residuals=self.residuals)
        self.layer2 = self.build_layer(node_f=256, edge_f=128, node_f_hidden=256, edge_f_hidden=128, node_f_out=512, edge_f_out=256, residuals=self.residuals)
        #self.layer3 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        
        # self.dropout_layer = nn.Dropout(dropout_prob)
        # self.fc1 = nn.Linear(256, 64)
        # self.fc2 = nn.Linear(64, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            global_model=GlobalModel(node_f_out, global_f=1)
        )

    def forward(self, graphbatch):
        
        # Initialize global feature of length 1 for each graph in the batch
        initial_global = torch.zeros((graphbatch.num_graphs, 1)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, graphbatch.edge_index, graphbatch.edge_attr, u=initial_global, batch=graphbatch.batch)
        x, edge_attr, u = self.layer2(x, graphbatch.edge_index, edge_attr, u, batch=graphbatch.batch)
        #x, edge_attr, _ = self.layer3(x, edge_index, edge_attr, None, batch)
        return u





# Regression is performed by the global model based on node features (with one layers)
class GATE2(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE2, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, residuals=self.residuals)
        #self.layer2 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        #self.layer3 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        
        self.dropout_layer = nn.Dropout(dropout_prob)
        self.fc1 = nn.Linear(256, 64)
        self.fc2 = nn.Linear(64, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            global_model=GlobalModel(node_f_out, global_f=1)
        )

    def forward(self, graphbatch):
        
        # Initialize global feature of length 1 for each graph in the batch
        initial_global = torch.zeros((graphbatch.num_graphs, 1)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, graphbatch.edge_index, graphbatch.edge_attr, u=initial_global, batch=graphbatch.batch)
        #x, edge_attr, _ = self.layer2(x, edge_index, edge_attr, None, batch)
        #x, edge_attr, _ = self.layer3(x, edge_index, edge_attr, None, batch)
        return u
    


# BASELINE: Regression is edge and node model, regression based on global add pool
class GATE(nn.Module):
    def __init__(self, dropout_prob, in_channels, edge_dim, conv_dropout_prob):
        super(GATE, self).__init__()

        self.residuals = False
        
        # Build each layer separately
        self.layer1 = self.build_layer(node_f=in_channels, edge_f=edge_dim, node_f_hidden=128, edge_f_hidden=64, node_f_out=256, edge_f_out=128, residuals=self.residuals)
        #self.layer2 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        #self.layer3 = self.build_layer(n_node_f, n_edge_f, n_node_f_hidden, n_edge_f_hidden, n_node_f_out, n_edge_f_out, residuals=self.residuals)
        
        self.dropout_layer = nn.Dropout(dropout_prob)
        self.fc1 = nn.Linear(256, 64)
        self.fc2 = nn.Linear(64, 1)

    def build_layer(self, node_f, edge_f, node_f_hidden, edge_f_hidden, node_f_out, edge_f_out, residuals):
        return geom_nn.MetaLayer(
            edge_model=EdgeModel(node_f, edge_f, edge_f_hidden, edge_f_out, residuals=residuals),
            node_model=NodeModel(node_f, edge_f_out, node_f_hidden, node_f_out, residuals=residuals),
            #global_model=GlobalModel(node_f_out, global_f=1)
        )

    def forward(self, graphbatch):
        
        # Initialize global feature of length 1 for each graph in the batch
        #initial_global = torch.zeros((graphbatch.num_graphs, 1)).to(graphbatch.x.device)
        x, edge_attr, u = self.layer1(graphbatch.x, graphbatch.edge_index, graphbatch.edge_attr, u=None, batch=graphbatch.batch)
        #x, edge_attr, _ = self.layer2(x, edge_index, edge_attr, None, batch)
        #x, edge_attr, _ = self.layer3(x, edge_index, edge_attr, None, batch)

        # Pool the nodes of each interaction graph
        x = global_add_pool(x, batch=graphbatch.batch)
        x = self.dropout_layer(x)
        
        # Fully-Connected Layers
        x = self.fc1(x)
        x = F.relu(x)
        x = self.fc2(x)
        return x