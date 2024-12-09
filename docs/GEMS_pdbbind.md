Download the PDBbind database from http://www.pdbbind.org.cn/. Then follow the steps below to construct a dataset of affinity-labelled interactions graphs and run trainining/inference. 

* **Prepare your data:** Save all PDB and the SDF files (including CASF complexes) in the same directory. Each protein-ligand pair should share the same unique identifier (_ID_) as filenames to indicate they form a complex. For example, use filenames like _ID_.pdb and _ID_.sdf to represent the same complex.
* **Prepare the labels:** Use the provided PDBbind data dictionary (`PDBbind_data/PDBbind_data_dict.json`) or parse the index file of PDBbind into a json dictionary (you can use `PDBbind_data/read_index_into_dict.py`, but you might have to adjust some paths)
* **Compute Language Model Embeddings:** This will compute ChemBERTa, ANKH and ESM2 embeddings (as desired) and save them in your data directory. We recommend running these scripts on a GPU.

    ChemBERTa:     ```python -m dataprep.chemberta_features --data_dir <path/to/data/dir> --model ChemBERTa-77M-MLM``` <br />
    ANKH:          ```python -m dataprep.ankh_features --data_dir <path/to/data/dir> --ankh_base True``` <br />
    ESM2:          ```python -m dataprep.esm_features --data_dir <path/to/data/dir> --esm_checkpoint t6``` <br />
  
* **Run the graph construction:** This will construct graphs objects for all protein-ligand complexes in your data directory, incorporating language model embeddings.

    ```
    python -m dataprep.graph_construction
    --data_dir <data/dir>
    --protein_embeddings ankh_base esm2_t6
    --ligand_embeddings ChemBERTa_77M
    ```
  
* **Run the dataset construction:** You need to provide the path to the directory containing your data (--data_dir) and the path to save the dataset (--save_path). In addition, provide the split dictionary and the dataset (corresponding to a key in the dictionary) for which the PyTorch dataset should be contstructed. To include the labels, provide also the path to the JSON file containing the log_kd_ki values. Finally, add the protein embeddings and the ligand embeddings that should be used to featurize the graphs (any combination of the embeddings included in the graph construction process is possible). This will generate a pytorch dataset of affinity-labelled interactions graphs featurized with the desired language model embeddings.

    **PDBbind training dataset:** Replace "train" with "casf2013" or "casf2016" to build datasets for CASF
    ```
    python -m dataprep.construct_dataset
    --data_dir <data/dir> 
    --save_path <save/output/path/.pt>
    --data_split PDBbind_data/data_splits/PDBbind_data_split.json
    --dataset train
    --data_dict PDBbind_data/PDBbind_data_dict.json 
    --protein_embeddings ankh_base esm2_t6
    --ligand_embeddings ChemBERTa_77M
    ```
    
    **PDBbind CleanSplit training dataset:** Replace "train" with "casf2013" or "casf2016" to build datasets for CASF
    ```
    python -m dataprep.construct_dataset
    --data_dir <data/dir> 
    --save_path <save/output/path/.pt>
    --data_split PDBbind_data/data_splits/PDBbind_CleanSplit_data_split.json
    --dataset train
    --data_dict PDBbind_data/PDBbind_data_dict.json 
    --protein_embeddings ankh_base esm2_t6
    --ligand_embeddings ChemBERTa_77M
    ```

  
* **Inference/Training:** You can now run inference or training on the generated PyTorch datasets:
    ```
    python inference.py --dataset_path <path/to/dataset>
    ```
    ```
    python train.py --dataset_path <path/to/dataset_file> --run_name <select a run name>
    ```