import pickle
import os
import torch
from transformers import AutoTokenizer, AutoModel
from rdkit import Chem
import argparse
import numpy as np
from tqdm import tqdm
import time


def arg_parser():
    parser = argparse.ArgumentParser(description='Preprocess PDBbind data for DTI5')
    parser.add_argument('--data_dir', type=str, required=True, help='Path to the data directory containing all proteins(PDB) and ligands (SDF)')
    parser.add_argument('--model', default='ChemBERTa-77M-MLM', type=str, help="Which ChemBERTa model should be used [ChemBERTa-77M-MLM, ChemBERTa-10M-MLM]")
    return parser.parse_args()

args = arg_parser()
data_dir = args.data_dir
model_descriptor = args.model

def sdf_to_smiles(sdf_path):
    suppl = Chem.SDMolSupplier(sdf_path)
    smiles_list = [Chem.MolToSmiles(mol) for mol in suppl if mol is not None]
    return smiles_list[0]

def smiles_to_embedding(smiles, tokenizer, model):
    inputs = tokenizer(smiles, return_tensors="pt", padding=False, truncation=False)
    with torch.no_grad():
        outputs = model(**inputs)
    embeddings = outputs.last_hidden_state

    return embeddings.mean(dim=1)



model_name = f'DeepChem/{model_descriptor}'

tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir='./huggingface')
model = AutoModel.from_pretrained(model_name, cache_dir='./huggingface')

# Initialize Log File
log_file_path = os.path.join(data_dir, '.logs', f'{model_descriptor}.txt')
log = open(log_file_path, 'a')
log.write("Generating ChemBERTa Embeddings for PDBbind - Log File:\n")
log.write("\n")


# Generate a lists of all ligands
ligands = sorted([ligand for ligand in os.scandir(data_dir) if ligand.name.endswith('ligand.sdf')], key=lambda x: x.name)
num_ligands = len(ligands)

print(f'Number of ligands to be processed: {num_ligands}')
print(f'Model Name: {model_name}')


# Start generating embeddings for all ligands iteratively
tic = time.time()
for ligand in tqdm(ligands):

    id = ligand.name.split('_')[0]
    log_string = f'{id}: '

    save_filepath = os.path.join(data_dir, f'{id}_{model_descriptor}.pt')
    if os.path.exists(save_filepath):
        log_string += 'Embedding already exists'
        log.write(log_string + "\n")
        continue
        
    smiles = sdf_to_smiles(ligand.path)
    embedding = smiles_to_embedding(smiles, tokenizer, model)

    print(id, embedding.shape)
    torch.save(embedding, save_filepath)
    log_string += 'Successful'


    log.write(log_string + "\n")

print(f'Time taken for {num_ligands} ligands: {time.time() - tic} seconds')
log.close()
