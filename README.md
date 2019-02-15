


# **Distributed Deep Learning on AWS Using MXNet and TensorFlow**

[AWS CloudFormation](https://aws.amazon.com/cloudformation), which creates and configures Amazon Web Services resources with a template, simplifies the process of setting up a distributed deep learning cluster. The AWS CloudFormation Deep Learning template uses the [Amazon Deep Learning AMI](https://aws.amazon.com/marketplace/pp/B01M0AXXQB) (which provides MXNet, TensorFlow, Caffe, Theano, Torch, and CNTK frameworks) to launch a cluster of [EC2](https://aws.amazon.com/ec2) instances and other AWS resources needed to perform distributed deep learning.  
With this template, we continue with our mission to make [distributed deep learning easy](https://aws.amazon.com/blogs/compute/distributed-deep-learning-made-easy/). AWS CloudFormation creates all resources in the customer account.

## What's New?  
We've updated the AWS CloudFormation Deep Learning template to add some exciting new features and capabilities.

### Dec 19 2018
* Updated AWS DLAMI Conda version in CFN template file to v20.0. Check **[release notes](https://aws.amazon.com/releasenotes/?tag=releasenotes%23keywords%23aws-deep-learning-amis)** for details.
* Updated instructions to use tensorflow with horovod for distributed training.

### Nov 7 2018
* Introduce AWS DLAMI Conda v16.0 - For developers who want pre-installed pip packages of deep learning frameworks in separate virtual environments, the Conda-based AMI is available in **[Ubuntu](https://aws.amazon.com/marketplace/pp/B077GCH38C)** and  **[Amazon Linux](https://aws.amazon.com/marketplace/pp/B077GF11NF)**. Check [AWS DLAMI Official webpage](https://aws.amazon.com/machine-learning/amis/) for more details.

* We now support 11 AWS regions- us-east-1, us-west-2, eu-west-1, us-east-2, ap-southeast-2, ap-northeast-1, ap-northeast-2, ap-south-1, eu-central-1,ap-southeast-1, us-west-1.

* We now support g3 and c5 instances, and remove g2 instances.

* Update MXNet submodule to 1.3.0.





### Mar 22 2018

* We now support 10 AWS regions - us-east-1, us-west-2, eu-west-1, us-east-2, ap-southeast-2, ap-northeast-1, ap-northeast-2, ap-south-1, eu-central-1,ap-southeast-1.

* We now support p3 instances.

### Older Release Notes

* We now support 5 AWS regions - us-east-1, us-east-2, us-west-2, eu-west-1 and ap-southeast-2.

*  We've enhanced the AWS CloudFormation Deep Learning template with automation that continues stack creation even if the provisioned number of worker instances falls short of the desired count. In the previous version of the template, if one of the worker instances failed to be provisioned, for example, if it a hit account limit, AWS CloudFormation rolled back the stack and required you to adjust your desired count and restart the stack creation process. The new template includes a function that automatically adjusts the count down and proceeds with setting up the rest of the cluster (stack).  

*  We now support creating a cluster of CPU Amazon EC2 instance types.

*  We've also added [Amazon Elastic File System (Amazon EFS)](https://aws.amazon.com/efs/) support for the cluster created with the template.  
	*  Amazon EFS is automatically mounted on all worker instances during startup.  
	*  Amazon EFS allows sharing of code, data, and results across worker instances.  
	*  Using Amazon EFS doesn't degrade performance for densely packed files (for example, .rec files containing image data).  

* We now support creating a cluster of instances running Ubuntu. See the [Ubuntu Deep Learning AMI](https://aws.amazon.com/marketplace/pp/B076TGJHY1).

## EC2 Cluster Architecture
The following architecture diagram shows the EC2 cluster infrastructure.  
![](images/Slide0.png)  

## Resources Created by the Deep Learning Template
The Amazon Deep Learning template creates a stack that contains the following resources:  

* A VPC in the customer account.
* The requested number or available number of worker instances in an [Auto Scaling](https://aws.amazon.com/autoscaling) group within the VPC. These worker instances are launched in a private subnet.
* A master instance in a separate Auto Scaling group that acts as a proxy to enable connectivity to the cluster with SSH. AWS CloudFormation places this instance within the VPC and connects it to both the public and private subnets. This instance has both public IP addresses and DNS.
* An Amazon EFS file storage system configured in General Purpose performance mode.
* A mount target to mount Amazon EFS on the instances.
* A security group that allows external SSH access to the master instance.
* A security group that allows the master and worker instances to mount and access Amazon EFS through NFS port 2049.  
* Two security groups that open ports on the private subnet for communication between the master and workers.
* An [AWS Identity and Access Management (IAM)](https://aws.amazon.com/iam) role that allows instances to poll [Amazon Simple Queue Service (Amazon SQS)](https://aws.amazon.com/sqs/) and access and query Auto Scaling groups and the private IP addresses of the EC2 instances.
* A NAT gateway used by the instances within the VPC to talk to the outside world.
* Two Amazon SQS queues to configure the metadata at startup on the master and the workers.
* An [AWS Lambda](https://aws.amazon.com/lambda/) function that monitors the Auto Scaling group's launch activities and modifies the desired capacity of the Auto Scaling group based on availability.
* An [Amazon Simple Notification Service (Amazon SNS)](https://aws.amazon.com/sns/) topic to trigger the Lambda function on Auto Scaling events.
* AWS CloudFormation WaitCondition and WaitHandler, with a stack creation timeout of 55 minutes to complete metadata setup.

## How the Deep Learning Template Works
The startup script enables SSH forwarding on all hosts. Enabling SSH agent forwarding is essential because frameworks such as MXNet use SSH for communication between master and worker instances during distributed training.  

The startup script on the master polls the master SQS queue for messages confirming that Auto Scaling setup is complete. The Lambda function sends two messages, one when the master Auto Scaling group is successfully set up, and a second when either the requested capacity is satisfied or when instances fail to launch on the worker Auto Scaling group. When instance launch fails on the worker Auto Scaling group, the Lambda function modifies the desired capacity to the number of instances that have been successfully launched.

Upon receiving messages on the Amazon SQS master queue, the setup script on the master configures all of the necessary worker metadata (IP addresses of the workers, GPU count, etc.,) and broadcasts the metadata on the worker SQS queue. Upon receiving this message, the startup script on the worker instances that are polling the SQS worker queue configure this metadata on the workers.

The following environment variables are set up on all the instances:

* **$DEEPLEARNING_WORKERS_PATH**: The file path that contains the list of workers  

* **$DEEPLEARNING_WORKERS_COUNT**: The total number of workers  

* **$DEEPLEARNING_WORKER_GPU_COUNT**: The number of GPUs on the instance

* **$EFS_MOUNT**: The directory where Amazon EFS is mounted

## Setting Up a Deep Learning Stack
To set up a deep learning AWS CloudFormation stack, follow [Using the AWS CloudFormation Deep Learning Template](cfn-template/StackSetup.md).

## Running Distributed Training
To demonstrate how to run distributed training using [MXNet](http://mxnet.io/) and [Tensorflow](https://www.tensorflow.org/) frameworks, we use the standard [CIFAR-10 model](https://www.cs.toronto.edu/~kriz/cifar.html).  CIFAR-10 is a sufficiently complex network that benefits from a distributed setup and that can be quickly trained on such a setup.  

### Log in to the Master Instance
Follow **[Step 3](cfn-template/StackSetup.md#logintomaster)** in [Using the AWS CloudFormation Deep Learning Template](cfn-template/StackSetup.md).

### Clone the [awslabs/deeplearning-cfn](https://github.com/awslabs/deeplearning-cfn) repo that contains the examples onto the EFS mount

**Note:** This could take a few minutes.  

    git clone https://github.com/awslabs/deeplearning-cfn $EFS_MOUNT/deeplearning-cfn && \
    cd $EFS_MOUNT/deeplearning-cfn && \
    #
    #fetches dmlc/mxnet and tensorflow/models repos as submodules
    git submodule update --init $EFS_MOUNT/deeplearning-cfn/examples/tensorflow/models && \
    git submodule update --init $EFS_MOUNT/deeplearning-cfn/examples/incubator-mxnet && \
    cd $EFS_MOUNT/deeplearning-cfn/examples/incubator-mxnet && \
    git submodule update --init $EFS_MOUNT/deeplearning-cfn/examples/incubator-mxnet/3rdparty/dmlc-core
	# We also need to pull latest dmlc-core code to make it work in conda environment
	cd $EFS_MOUNT/deeplearning-cfn/examples/incubator-mxnet/3rdparty/dmlc-core
	git fetch origin master
	git checkout -b master origin/master



### Running Distributed Training on MXNet

The following example shows how to run CIFAR-10 with data parallelism on MXNet. Note the use of the DEEPLEARNING_* environment variables.

	#terminate all running Python processes across workers
	while read -u 10 host; do ssh -o "StrictHostKeyChecking no" $host "pkill -f python" ; \
	done 10<$DEEPLEARNING_WORKERS_PATH

	#navigate to the MXNet image-classification example directory \
	cd $EFS_MOUNT/deeplearning-cfn/examples/incubator-mxnet/example/gluon/

	#run the CIFAR10 distributed training example in mxnet conda environment(Change mxnet_p36 to mxnet_p27 if you wnat to run in python27 environment)\
	../../tools/launch.py -n $DEEPLEARNING_WORKERS_COUNT -H $DEEPLEARNING_WORKERS_PATH "source activate mxnet_p36 && python image_classification.py --dataset cifar10 --model vgg11 --epochs 1 --kvstore dist_device_sync"

We were able to run the training for 100 epochs in 25 minutes on 2 P2.8x EC2 instances and achieve a training accuracy of 92%.  

These steps summarize how to get started. For more information about running distributed training on MXNet, see [Run MXNet on Multiple Devices](http://mxnet.readthedocs.io/en/latest/how_to/multi_devices.html).

### Running Distributed Training on TensorFlow with Horovod
Horovod is a distributed training framework to make distributed deep learning easy and fast. You can get more information about the advantages of using [Horovod](https://github.com/uber/horovod) to do distributed training with Tensorflow or other framework.
Starting from DLAMI Conda v19.0, it comes with example pre-configured scripts to show how you can train model with Tensorflow and Horovod on multi gpus/machines.

The following example shows how to train a ResNet-50 model with synthetic data.

    cd ~/examples/horovod/tensorflow
    vi hosts

You should be able to see `localhost slots=8` in your hosts file. The number of slots means how many GPUs you want to use in that machine to train your model. Also, you should append your worker nodes to the hosts file, and assign GPU number to it. To know how many GPUs available in your instance, run `nvidia-smi`. After the change, your hosts file should look like
```
localhost slots=<#GPUs>
<worker node private ip> slots=<#GPUs>
......
```
You can easily calculate the number of GPUs you'll use to train the model by summing up the slots available on each machine. Note that: the argument passed to the train_synthetic.sh script below is passed to -np parameter of mpirun. The -np argument represents the total number of processes and the slots argument in hostfile represents the split of those processes per machine.

Then, just  run
`./train_synthetic.sh 24`  or replace 24 with number of GPUs you use. 
