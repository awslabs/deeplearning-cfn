import sys, getopt, os, argparse

#parse arguments
def parse_args():
    parser = argparse.ArgumentParser(description='Run Benchmark on various imagenet networks using train_imagenent.py')
    parser.add_argument('--trainer_script_dir', type=str, help='location where distributed trainer scripts should be stored, use a shared file system like efs',required=True)
    parser.add_argument('--log_dir', type=str, default="/tmp/", help='location where the logs should be stored',required=False)
    parser.add_argument('--workers_file_path', type=str, help='worker file path', required=True)
    parser.add_argument('--worker_count', type=int, help='number of workers', required=True)
    parser.add_argument('--worker_gpu_count', type=int, help='number of gpus on each worker to use', required=True)
    parser.add_argument('--training_script', nargs='+', help = 'training script and its arguments, e.g: --script cifar10_train.py --batch_size 8 --data_dir /myEFSVolume/data')
    args, unknown = parser.parse_known_args()
    args.training_script += unknown
    args.training_script = ' '.join(args.training_script)
    return args

# generates a list of workers where the training will be run. 
# one worker per GPU
def get_worker_list(nodes, gpu_per_node):
    lst = []
    for node in nodes:
        for index in range(gpu_per_node):
            port = str(2230 + (index%gpu_per_node))
            lst.append( node + ":" + port )
    return ','.join(lst)

# generates a list of parameter servers
# one parameter server per node
def get_ps_list(nodes):
    return ','.join( [n + ":2222" for n in nodes] )

#creates list of commands that has to be run on each node
def get_script(training_script, workers_list, ps_list, index, gpu_per_node, log_dir):
   
    script = 'source /etc/profile'
    script += "\n\n"

    script += "CUDA_VISIBLE_DEVICES='' python " + training_script + " " \
                + "--ps_hosts=" + ps_list + " " \
                + "--worker_hosts=" + workers_list + " " \
                + "--job_name=ps " \
                + "--task_index=" + str(index) \
                + " > " + log_dir + "/ps" + str(index) \
                + " 2>&1" \
                + " &" 
                
    script += "\n\n"

    for i in range(gpu_per_node):    
        script += "CUDA_VISIBLE_DEVICES='" + str(i) + "' " \
                    + "python " + training_script + " " \
                    + "--ps_hosts=" + ps_list + " " \
                    + "--worker_hosts=" + workers_list + " " \
                    + "--job_name=worker " \
                    + "--task_index=" + str(index*gpu_per_node + i) \
                    + " > "+ log_dir + "/worker" + str(index*gpu_per_node + i) \
                    + " 2>&1" \
                    + " &"
                
        script += "\n\n"
    
    return script    

def gen_scripts(training_script, nodes_file, trainer_script_dir, num_nodes, gpu_per_node, log_dir):

    with open(nodes_file, 'r') as f:
        nodes = f.read().splitlines()
    
    workers_list = get_worker_list(nodes, gpu_per_node)
    ps_list = get_ps_list(nodes)

    for index, host in enumerate(nodes):
        script = get_script(training_script, workers_list, ps_list, index, gpu_per_node, log_dir)
        file_name = trainer_script_dir + "/" + host + ".sh"
        with open(file_name, "w") as sh_file:
            sh_file.write(script)

def main():
    args = parse_args()
    if not os.path.exists(args.log_dir):
        os.makedirs(args.log_dir)  
    gen_scripts(args.training_script, args.workers_file_path, args.trainer_script_dir, 
        args.worker_count, args.worker_gpu_count, args.log_dir)

if __name__ == "__main__":
    main()
