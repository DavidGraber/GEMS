import argparse
import sys
import os
import torch
import matplotlib.pyplot as plt
import numpy as np
import wandb

from torch_geometric.loader import DataLoader
from sklearn.model_selection import StratifiedKFold
from torch.utils.data import Subset
from Models import *


from Dataset import IG_Dataset

def parse_args():
    parser = argparse.ArgumentParser(description="Training Parameters and Input Dataset Control")
    parser.add_argument("--model", required=True, help="The name of the model architecture")
    parser.add_argument("--loss_func", default='MSE', help="The loss function that will be used ['MSE', 'wMSE', 'L1', 'Huber']")
    parser.add_argument("--wandb", default=True, type=lambda x: x.lower() in ['true', '1', 'yes'], help="Wheter or not the run should be streamed to Weights and Biases")
    parser.add_argument("--project_name", help="Project Name for the saving of run data to Weights and Biases")
    parser.add_argument("--run_name", required=True, help="Name of the Run to display in saved data and in Weights and Biases (string)")
    parser.add_argument("--n_folds", default=5, type=int, help="The number of stratified folds that should be generated (n-fold-CV)")
    parser.add_argument("--fold_to_train", default=0, type=int, help="Of the n_folds generated, on which fold should the model be trained")
    parser.add_argument("--num_epochs", default=1000, type=int, help="Number of Epochs the model should be trained (int)")
    parser.add_argument("--batch_size", default=256, type=int, help="The Batch Size that should be used for training (int)")
    parser.add_argument("--learning_rate", default=0.01, type=float, help="The learning rate with which the model should train (float)")
    parser.add_argument("--weight_decay", default=0.001, type=float, help="The weight decay parameter with which the model should train (float)")
    parser.add_argument("--dropout", default=0, type=float, help="The dropout probability that should be applied in the dropout layer")
    parser.add_argument("--device", default=1, type=int, help="The device index of the device on which the code should run")

    # If the learning rate should be adaptive LINEAR
    parser.add_argument("--alr_lin", default=False, help="Linear learning rate reduction scheme will be used")
    parser.add_argument("--start_factor", default=1, help="Factor by which the learning rate will be reduced. new_lr = lr * factor.")
    parser.add_argument("--end_factor", default=0.01, help="Factor by which the learning rate will be reduced in the last epoch. new_lr = lr * factor.")
    parser.add_argument("--total_iters", default=10000, help="The number of iterations after which the linear reduction of the LR should be finished")

    # If the learning rate should be adaptive MULTIPLICATIVE
    parser.add_argument("--alr_mult", default=False, help="Multiplicative learning rate reduction scheme will be used")
    parser.add_argument("--factor", default=0.9995, help="Factor by which the learning rate will be reduced. new_lr = lr * factor.")

    # If the learning rate should be adaptive REDUCEONPLATEAU
    parser.add_argument("--alr_plateau", default=False, help="Adaptive learning rate reduction REDUCELRONPLATEAU scheme will be used")
    parser.add_argument("--reduction", default=0.1, type=float, help="Factor by which the LR should be reduced on plateau")
    parser.add_argument("--patience", default=10, type=int, help="Number of epochs with no improvement after which learning rate will be reduced.")
    parser.add_argument("--min_lr", default=0.5e-4, type=float, help="A lower bound on the learning rate")

    # If a state_dict should be loaded before the training
    parser.add_argument("--pretrained", default=False, help="Provide the path of a state dict that should be imported")
    parser.add_argument("--start_epoch", default=0, type=int, help="Provide the starting epoch (in case of importing pretrained model)")

    return parser.parse_args()

args = parse_args()

torch.manual_seed(0)


# Training Parameters and Config
#----------------------------------------------------------------------------------------------------

# Location and feature dimensionality of the dataset to be used
data_dir = '/data/grbv/PDBbind/input_graphs/training_data'

# Architecture and run settings
model_arch = args.model
project_name = args.project_name
run_name = args.run_name
wandb_tracking = args.wandb
device_idx = args.device
if wandb_tracking: print(f'Saving into Project Folder {project_name}')

random_seed = 42

loss_function = args.loss_func
num_epochs = args.num_epochs
learning_rate = args.learning_rate
weight_decay = args.weight_decay
batch_size = args.batch_size
dropout_prob = args.dropout

n_folds = args.n_folds
fold_to_train = args.fold_to_train

save_dir = f'data_runs/{project_name}/{run_name}/Fold{fold_to_train}'
wandb_dir = '/data/grabeda2'

run_name = f'{run_name}_f{fold_to_train}' 


# The learning rate reduction scheme
alr_lin = args.alr_lin
alr_mult = args.alr_mult
alr_plateau = args.alr_plateau

alr = ''
if alr_lin:
    start_factor = args.start_factor
    end_factor = args.end_factor
    total_iters = args.total_iters
    alr += f'Linear: Start Factor {start_factor}, End Factor {end_factor}, Total Iters {total_iters}\n'

if alr_mult:
    factor = args.factor
    alr += f'Multiplicative: Factor {factor}\n'

if alr_plateau:
    patience = args.patience
    reduction = args.reduction
    min_lr = args.min_lr
    alr += f'Plateau: Patience {patience}, Reduction Factor {reduction}, Min LR {min_lr}'

if wandb_tracking: 
        config = {
                "Learning Rate": learning_rate,
                "Weight Decay": weight_decay,
                "Architecture": model_arch,
                "Epochs": num_epochs,
                "Batch Size": batch_size,
                "Splitting Random Seed":random_seed,
                "Dropout Probability": dropout_prob,
                "Device Idx": device_idx,
                "Adaptive LR Scheme": alr
                }

pretrained = args.pretrained
start_epoch = args.start_epoch

if not os.path.exists(save_dir): 
        os.makedirs(save_dir)
        print(f'Saving Directory generated')
#----------------------------------------------------------------------------------------------------





# Load Dataset - Split into training and validation set in a stratified way
#----------------------------------------------------------------------------------------------------
dataset = IG_Dataset(data_dir)
print(dataset)

node_feat_dim = dataset[0].x.shape[1]
edge_feat_dim = dataset[0].edge_attr.shape[1]

labels = [graph.affinity.item() for graph in dataset]
print(max(labels), len(labels))


# Initialize StratifiedKFold
skf = StratifiedKFold(n_splits=n_folds, random_state=random_seed, shuffle=True)

group_assignment = np.array( [round(lab) for lab in labels] )

train_indices = []
val_indices = []
for i, (train_index, val_index) in enumerate(skf.split(np.zeros(len(dataset)), group_assignment)):
    val_indices.append(val_index.tolist())
    train_indices.append(train_index.tolist())


# Select the fold that should be used for the training
train_idx = train_indices[fold_to_train]
val_idx = val_indices[fold_to_train]

train_dataset = Subset(dataset, train_idx)
val_dataset = Subset(dataset, val_idx)

print(f'Length Training Dataset: {len(train_dataset)}')
print(f'Length Validation Dataset: {len(val_dataset)}')

train_loader = DataLoader(dataset = train_dataset, batch_size=batch_size, shuffle=True, num_workers=4, persistent_workers=True)
eval_loader_train = DataLoader(dataset = train_dataset, batch_size=1024, shuffle=True, num_workers=4, persistent_workers=True)
eval_loader_val = DataLoader(dataset = val_dataset, batch_size=1024, shuffle=True, num_workers=4, persistent_workers=True)
#----------------------------------------------------------------------------------------------------




# Plot the distributions of the datasets
#----------------------------------------------------------------------------------------------------
training_labels = [graph.affinity.item() for graph in train_dataset]
validation_labels = [graph.affinity.item() for graph in val_dataset]
highest_label = max([max(training_labels), max(validation_labels)])

def create_histogram(data, title, xlim, num_bins=50):

    plt.style.use('ggplot')
    fig = plt.figure(figsize=(12, 6))  # Set the figure size as needed

    # Create the histogram
    frequencies, bins, _ = plt.hist(data, bins=num_bins)
    plt.xlabel('Labels')
    plt.ylabel('Count (Log Scale)')
    plt.title(title)

    # # Set a gap in the y-axis
    # max_freq = max(plt.gca().get_ylim()[1], max(frequencies))
    # plt.ylim(0, max_freq * 1.1)  # Adjust the multiplier as needed

    # Add labels to the columns
    for freq, bin_val in zip(frequencies, bins):
        plt.text(bin_val, freq, str(int(freq)), ha='center', va='bottom')

    plt.yscale('log')
    plt.xlim(0, np.ceil(xlim))

    return fig

hist_training_labels = create_histogram(training_labels, f'Labels Training Dataset', highest_label)
hist_validation_labels = create_histogram(validation_labels, f'Labels Validation Dataset', highest_label)
#----------------------------------------------------------------------------------------------------





# Initialize Model, Optimizer and Loss Function
#-------------------------------------------------------------------------------------------------------------------------------
 
# Function to count number of trainable parameters
def count_parameters(model, trainable=True):
    return sum(p.numel() for p in model.parameters() if p.requires_grad or not trainable)


# Device Settings
num_threads = torch.get_num_threads() // 2
torch.set_num_threads(num_threads)

torch.cuda.set_device(device_idx)
device = torch.device(f'cuda:{device_idx}' if torch.cuda.is_available() else 'cpu')
print(device, torch.cuda.current_device(), torch.cuda.get_device_name())


# Initialize the model and optimizer
model_class = getattr(sys.modules[__name__], args.model)
Model = model_class(dropout_prob=dropout_prob, in_channels=node_feat_dim, edge_dim=edge_feat_dim).to(device)
Model = Model.double()
torch.save(Model, f'{save_dir}/model_configuration.pt')

parameters = count_parameters(Model)
if wandb_tracking: config['Number of Parameters'] = parameters
print(f'Model architecture {model_arch} with {parameters} parameters')

optimizer = torch.optim.Adam(list(Model.parameters()),lr=learning_rate, weight_decay=weight_decay)


# Apply adaptive learning rate (alr) scheme
if alr_lin: 
    lin_scheduler = torch.optim.lr_scheduler.LinearLR(optimizer, start_factor=start_factor, end_factor=end_factor, total_iters=total_iters)
    learning_rate_reduction_scheme = f'Linear LR Scheduler enabled with start factor {start_factor}, end factor {end_factor} and total iters {total_iters}'
if alr_mult:
    mult_scheduler = torch.optim.lr_scheduler.MultiplicativeLR(optimizer, lr_lambda=lambda epoch: factor)
    learning_rate_reduction_scheme = f'Multiplicative LR Scheduler enabled with factor {factor}'
if alr_plateau: 
    plat_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=reduction, patience=patience, min_lr=min_lr)
    learning_rate_reduction_scheme = f'ReduceLRonPlateau LR Scheduler enabled with patience {patience}, factor {reduction} and min LR {min_lr}'
else: 
    learning_rate_reduction_scheme = 'No learning rate scheduler has been selected'

print(learning_rate_reduction_scheme)



# DEFINE LOSS FUNCTION ['MSE', 'wMSE', 'L1', 'Huber']



if loss_function == 'Huber':
    criterion = torch.nn.HuberLoss(reduction='mean', delta=1.0)

elif loss_function == 'L1':
    criterion = torch.nn.L1Loss(size_average=None, reduce=None, reduction='mean')

elif loss_function == 'wMSE':
    def compute_wMSE_loss(output, targets): # Sum of squared error (label weighted) = w_sse
        error = (output-targets)
        return (torch.sum(error**2 * torch.add(targets, 1)))
    criterion = compute_wMSE_loss()

else: 
    criterion = torch.nn.MSELoss()

#----------------------------------------------------------------------------------------------------




# Training Function for 1 Epoch
#-------------------------------------------------------------------------------------------------------------------------------
def train(Model, loader):
    Model.train()
        
    # Initialize variables to accumulate metrics
    total_loss = 0.0
    y_true = []
    y_pred = []
                
    for graphbatch in loader:
        graphbatch.to(device)
        targets = graphbatch.affinity

        # Forward pass
        optimizer.zero_grad()
        output = Model(graphbatch).view(-1)
        loss = criterion(output, targets)
        loss.backward()
        optimizer.step()

        # Accumulate loss collect the true and predicted values for later use
        total_loss += loss.item()
        y_true.extend(targets.tolist())
        y_pred.extend(output.tolist())

    # Calculate evaluation metrics
    epoch_loss = total_loss / len(loader.dataset)
    r2_score = 1 - np.sum((np.array(y_true) - np.array(y_pred)) ** 2) / np.sum((np.array(y_true) - np.mean(np.array(y_true))) ** 2)

    return epoch_loss, r2_score
#-------------------------------------------------------------------------------------------------------------------------------


# Evaluation Function
#-------------------------------------------------------------------------------------------------------------------------------
def evaluate(Model, loader):
    Model.eval()

    # Initialize variables to accumulate the evaluation results
    total_loss = 0.0
    y_true = []
    y_pred = []

    # Disable gradient calculation during evaluation
    with torch.no_grad():
        for graphbatch in loader:

            graphbatch.to(device)
            targets = graphbatch.affinity

            # Forward pass
            output = Model(graphbatch).view(-1)
            loss = criterion(output, targets)

            # Accumulate loss and collect the true and predicted values for later use
            total_loss += loss.item()
            y_true.extend(targets.tolist())
            y_pred.extend(output.tolist())


    # Calculate evaluation metrics
    eval_loss = total_loss / len(loader.dataset)
    r2_score = 1 - np.sum((np.array(y_true) - np.array(y_pred)) ** 2) / np.sum((np.array(y_true) - np.mean(np.array(y_true))) ** 2)

    return eval_loss, r2_score, y_true, y_pred
#-------------------------------------------------------------------------------------------------------------------------------








# Initialize WandB tracking with config dictionary, log file and data collection
#-----------------------------------------------------------------------------------
if wandb_tracking:
    wandb.init(project=project_name, name = run_name, config=config, dir=wandb_dir)
    
    wandb.log({"Training Labels": wandb.Image(hist_training_labels),
               "Validation Labels": wandb.Image(hist_validation_labels)})


if pretrained:
    Model.load_state_dict(torch.load(pretrained))
    print(f'State Dict Loaded: {pretrained}')
    print(f'Start Epoch: {start_epoch}')
    epoch = start_epoch

else: 
    epoch = 0


# Generate txt log file
with open(f'{save_dir}/{run_name}_saving_log.txt', 'w') as f:
    f.write(f'Model Architecture {model_arch} - Fold {fold_to_train} ({run_name}):\n')
    f.write(f'Model Training Output ({run_name}):\n')
    f.write(f'Number of Parameters: {parameters}\n')
    f.write(f'Learning Rate: {learning_rate}\n')
    f.write(f'Weight Decay: {weight_decay}\n')
    f.write(f'Batch Size: {batch_size}\n\n')
    f.write(f'Number of Epochs: {num_epochs}\n')
    f.write(f'{learning_rate_reduction_scheme}\n')
    f.close() 



# Plotting Functions
#-------------------------------------------------------------------------------------------------------------------------
def plot_predictions(train_y_true, train_y_pred, val_y_true, val_y_pred, title, axislim):
    
    fig = plt.figure(figsize=(8, 8))  # Set the figure size as needed

    plt.scatter(train_y_true, train_y_pred, alpha=0.5, c='blue', label='Training Data')
    plt.scatter(val_y_true, val_y_pred, alpha=0.5, c='red', label='Validation Data')

    plt.plot([min(train_y_true + val_y_true), axislim], [min(train_y_true + val_y_true), axislim], color='red', linestyle='--')
    plt.xlabel('True Values')
    plt.ylabel('Predicted Values')
    plt.ylim(-0.25, axislim)
    plt.xlim(0, axislim)
    plt.axhline(0, color='grey', linestyle='--')
    plt.title(title)
    
    # Adding manual legend items for colors
    legend_elements = []
    legend_elements.append(plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='blue', markersize=8, label='Training Dataset'))
    legend_elements.append(plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='red', markersize=8, label='Validation Dataset'))

    plt.legend(handles=legend_elements, loc='upper left')
    return fig


def residuals_plot(train_y_true, train_y_pred, val_y_true, val_y_pred, title):
    
    fig = plt.figure(figsize=(8, 8))  # Set the figure size as needed

    plt.style.use('ggplot')
    train_residuals = np.array(train_y_true) - np.array(train_y_pred)
    val_residuals = np.array(val_y_true) - np.array(val_y_pred)

    # Plot training residuals in blue
    plt.scatter(train_y_pred, train_residuals, c='blue', label='Training Data')

    # Plot validation residuals in red
    plt.scatter(val_y_pred, val_residuals, c='red', label='Validation Data')

    plt.xlabel('Predicted Values')
    plt.ylabel('Residuals')
    plt.axhline(y=0, color='r', linestyle='--')
    plt.title(title)
    plt.legend()  # Add a legend to differentiate training and validation data
    plt.show()
    return fig
#-------------------------------------------------------------------------------------------------------------------------




lowest_val_mse = 1000
lowest_val_w_mse = 1000
plotted_epochs = []


# Training and Validation Set Performance BEFORE Training
#-------------------------------------------------------------------------------------------------------------------------------

train_w_mse, train_mse, train_mae, train_r2, *_ = evaluate(Model, eval_loader_train)
val_w_mse, val_mse, val_mae, val_r2, *_ = evaluate(Model, eval_loader_val)

printout = f'Before Train: Train Data: W_MSE:{train_w_mse:6.3f}|  MSE:{train_mse:6.3f}|  R2:{train_r2:6.3f}|  -- Val Data: W_MSE:{val_w_mse:6.3f}|  MSE:{val_mse:6.3f}|  R2:{val_r2:6.3f}| '
print(printout)

with open(f'{save_dir}/{run_name}_saving_log.txt', 'a') as f:
        f.write(f'{printout} \n')

if wandb_tracking:
    wandb.log({
            "Epoch": epoch,
            "Learning Rate": optimizer.param_groups[0]['lr'],
            
            "Training Mean Squared Error (MSE)":train_mse,
            "Training Label-Weighted Mean Squared Error (MSE)":train_w_mse,
            "Training Mean Absolute Error (MAE)":train_mae,
            "Training R2": train_r2,

            "Validation Mean Squared Error (MSE)":val_mse,
            "Validation Label-Weighted Mean Squared Error (MSE)":val_w_mse,
            "Validation Mean Absolute Error (MAE)":val_mae,
            "Validation R2": val_r2
            })
#-------------------------------------------------------------------------------------------------------------------------------



#===============================================================================================================================================
# Training
#===============================================================================================================================================
for epoch in range(epoch+1, num_epochs+1):
    
    train_loss, train_r2, *_ = train(Model, train_loader)


    # Validation Set Performance Between Training Epochs
    #-------------------------------------------------------------------------------------------------------------------------------
    
    val_w_mse, val_mse, val_mae, val_r2, *_ = evaluate(Model, eval_loader_val)

    printout = f'Epoch {epoch:05d}:  Train Data: W_MSE:{train_w_mse:6.3f}|  MSE:{train_mse:6.3f}|  R2:{train_r2:6.3f}|  -- Val Data: W_MSE:{val_w_mse:6.3f}|  MSE:{val_mse:6.3f}|  R2:{val_r2:6.3f}| '
    print(printout)

    if wandb_tracking:
        wandb.log({
                "Epoch": epoch,
                "Learning Rate": optimizer.param_groups[0]['lr'],
                
                "Training Mean Squared Error (MSE)":train_mse,
                "Training Label-Weighted Mean Squared Error (MSE)":train_w_mse,
                "Training Mean Absolute Error (MAE)":train_mae,
                "Training R2": train_r2,

                "Validation Mean Squared Error (MSE)":val_mse,
                "Validation Label-Weighted Mean Squared Error (MSE)":val_w_mse,
                "Validation Mean Absolute Error (MAE)":val_mae,
                "Validation R2": val_r2
                })
        
    # Take a step in the activated learning rate reduction schemes
    if alr_plateau: plat_scheduler.step(val_mse) # THIS WILL NOT WORK 
    if alr_lin: lin_scheduler.step()
    if alr_mult: mult_scheduler.step()
    #-------------------------------------------------------------------------------------------------------------------------------


    # Determine if the model should be saved
    log_string = ''

    # if save_w_mse:= val_w_mse <= lowest_val_mse:
    #     lowest_val_w_mse = val_w_mse
    #     log_string += ' Val W_MSE'
    #     last_saved_epoch = epoch

    if save_mse:= val_mse <= lowest_val_mse:
        lowest_val_mse = val_mse
        log_string += ' Val MSE'
        last_saved_epoch = epoch

    if save_mse or epoch % (num_epochs/20) == 0:
        torch.save(Model.state_dict(), f'{save_dir}/{run_name}_stdict_{epoch}.pt')
        
    with open(f'{save_dir}/{run_name}_saving_log.txt', 'a') as f:
        f.write(f'{printout}{log_string} \n')


    # Evaluation
    #-------------------------------------------------------------------------------------------------------------------------------
    

    if epoch % (num_epochs/20) == 0 or epoch==1:


        # Evaluate the model at the current epoch
        #-------------------------------------------------------------------------------------------------------------------------------
        
        # Initialize the models
        eval_model = model_class(dropout_prob=dropout_prob, in_channels=node_feat_dim, edge_dim=edge_feat_dim).to(device)
        eval_model = eval_model.double()

        state_dict_path = f'{save_dir}/{run_name}_stdict_{epoch}.pt'
        eval_model.load_state_dict(torch.load(state_dict_path))
        
        train_w_mse, train_mse, train_mae, train_r2, train_y_true, train_y_pred = evaluate(eval_model, eval_loader_train)
        val_w_mse, val_mse, val_mae, val_r2, val_y_true, val_y_pred = evaluate(eval_model, eval_loader_val)

        # Plot the predictions
        axislim = int(1 + max( train_y_true + train_y_pred + val_y_true + val_y_pred))
        predictions = plot_predictions( train_y_true, train_y_pred,
                                        val_y_true, val_y_pred,
                                        f"{run_name}: Epoch {epoch}\nTrain R2 = {train_r2:.3f}, Validation R2 = {val_r2:.3f}\nTrain MSE = {train_mse:.3f}, Validation MSE = {val_mse:.3f}",
                                        axislim)
        


        # Check if there has been a new best epoch, if yes, plot the predictions
        #-------------------------------------------------------------------------------------------------------------------------------
        
        if last_saved_epoch not in plotted_epochs:
            
            eval_model = model_class(dropout_prob=dropout_prob, in_channels=node_feat_dim, edge_dim=edge_feat_dim).to(device)
            eval_model = eval_model.double()

            state_dict_path = f'{save_dir}/{run_name}_stdict_{last_saved_epoch}.pt'
            eval_model.load_state_dict(torch.load(state_dict_path))

            train_w_mse, train_mse, train_mae, train_r2, train_y_true, train_y_pred = evaluate(eval_model, eval_loader_train)
            val_w_mse, val_mse, val_mae, val_r2, val_y_true, val_y_pred = evaluate(eval_model, eval_loader_val)

            # Plot the predictions
            axislim = int(1 + max( train_y_true + train_y_pred + val_y_true + val_y_pred))
            best_predictions = plot_predictions( train_y_true, train_y_pred,
                                    val_y_true, val_y_pred,
                                    f"{run_name}: Epoch {last_saved_epoch}\nTrain R2 = {train_r2:.3f}, Validation R2 = {val_r2:.3f}\nTrain MSE = {train_mse:.3f}, Validation MSE = {val_mse:.3f}",
                                    axislim)

            residuals = residuals_plot(train_y_true, train_y_pred, val_y_true, val_y_pred, 
                                       f"{run_name}: Epoch {last_saved_epoch}\nTrain R2 = {train_r2:.3f}, Validation R2 = {val_r2:.3f}\nTrain MSE = {train_mse:.3f}, Validation MSE = {val_mse:.3f}")     
            
            plotted_epochs.append(last_saved_epoch)

            
        plt.close('all')

            
        if wandb_tracking: 
            
            wandb.log({ "Predictions Scatterplot": wandb.Image(predictions),
                        "Best Predictions Scatterplot": wandb.Image(best_predictions),
                        "Residuals Plot":wandb.Image(residuals)
                        })

if wandb_tracking: wandb.finish()