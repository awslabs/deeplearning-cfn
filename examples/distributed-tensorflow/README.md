# Distributed TensorFlow training using  Deep-learning AMI Cluster

## Pre-requisites
1. [Create and activate an AWS Account](https://aws.amazon.com/premiumsupport/knowledge-center/create-and-activate-aws-account/)

2. [Manage your service limits](https://aws.amazon.com/premiumsupport/knowledge-center/manage-service-limits/) so your EC2 service limit allows you to launch required number of GPU enabled EC2 instances, such as p3.16xlarge or p3dn.24xlarge. You would need a minimum limit of 2 GPU enabled instances. For the purpose of this setup, an EC2 service limit of 8 p3.16xlarge or p3dn.24xlarge instance types is recommended.

3. [Install and configure AWS Command Line Interface](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-welcome.html)

4. The Quick Start Steps described below require adequate [AWS IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/access.html) permissions.

## Create Amazon Deep-Learning AMI Cluster

[Amazon Deep Learning AMIs](https://aws.amazon.com/machine-learning/amis/) are an easy way for developers to launch AWS EC2 instances for machine-learning with many of the commonly used frameworks. Our goal in this project is to create a multi-machine cluster of EC2 instances using Amazon Deep Learning AMI. This [blog](https://aws.amazon.com/blogs/compute/distributed-deep-learning-made-easy/) is a general background reference for what we are trying to accomplish. In our setup, we are focused on distributed training using [TensorFlow](https://github.com/tensorflow/tensorflow), [TensorPack](https://github.com/tensorpack/tensorpack) and [Horovod](https://eng.uber.com/horovod/), so we will be using our own [CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html) template, mask-rcnn-cfn.yaml, included in this project.

The overall solution discussed here can be used to execute any distributed TensorFlow algorithm. However, we will try to be concrete and focus on [TensorPack Mask/Faster-RCNN](https://github.com/tensorpack/tensorpack/tree/master/examples/FasterRCNN) example. 

## TensorPack Mask/Faster-RCNN Example

Specifically, our goal is to do distributed training for TensorPack Mask/Faster-RCNN example using TensorFlow, TensorPack and Horovod in AWS EC2. Below we describe the quick start steps followed by a more detailed explanation.

### Quick Start Steps

1. Customize variables in ```prepare-s3-bucket.sh``` script and execute it as described below:

   S3_BUCKET variable must be set to an existing bucket. To optimize performance and cost, it is recommended that S3_BUCKET be in the region where you plan to do distributed training. 

   STAGE_DIR variable in the script must point to a directory on an EBS volume with at least 100 GB of available space. By  default it points to the home directory.

   This script downloads [Coco 2017](http://cocodataset.org/#download) dataset and [ImageNet-R50-AlignPadding.npz](http://models.tensorpack.com/FasterRCNN/ImageNet-R50-AlignPadding.npz) pre-trained model. 

   It bundles the COCO 2017 dataset and R50 ImageNet pre-trained model into a single TAR file and uploads it to the S3_BUCKET/S3_PREFIX. In addition, it uploads the shell scripts from this project to the S3_BUCKET/S3_PREFIX.
   
   **You can use the [screen](https://linuxize.com/post/how-to-use-linux-screen/) command as an alternative to using ```nohup``` and ```screen``` appears to work more reliably than ```nohup``` command.**
   
   Execute the script: ```nohup ./prepare-s3-bucket.sh & ```
  
2. Customize variables in ```mask-rcnn-stack.sh```. 
   
   You will need to specify S3_BUCKET and S3_PREFIX variables and make sure they are the same as in Step 1 above. 
   
   Customize SSH_LOCATION and KEY_NAME Variables and see section below for details.
   
   Set EFS_DATA to ```true``` if you could like to serve data from EFS file-system, instead of the default EBS file system.
   
   **This script uses  [Deep Learning AMI](https://aws.amazon.com/marketplace/pp/B077GCH38C?qid=1547157538888&sr=0-2&ref_=srh_res_product_title). You would need to subscribe to this AMI in AWS Marketplace before you can execute the script.** 

   Execute: ```./mask-rcnn-stack.sh```. 

   The output of executing the script is a [CloudFormation Stack](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacks.html) ID.

3.  Check status of CloudFormation Stack you created in AWS management console. When stack status is CREATE_COMPLETE, proceed to next step.

4. On your desktop  execute:
```ssh-add <private key file>```

5. Use SSH with forwarding agent to connect to Master Node:  ```ssh -A ubuntu@<master node>``` and do not restart the Master node despite the restart suggestion when you login.

6. Once you are logged on the Master node, **only** if you set ```EFS_DATA=true``` in ```mask-rcnn-stack.sh``` when you created CloudFormation Stack, you would need to extract the data in the EFS file system. To do so, execute following in home direcotry: 
```nohup tar -xvf /efs/coco-2017.tar --directory /efs &```
		
   Extraction of ```coco-2017.tar``` on EFS shared file system will take a while. 
When extraction is complete, you should see COCO dataset and pre-trained model under ```/efs/data```. 
        
7. From home directory on Master node, execute following command to start distributed training: ```nohup ./run.sh 1>run.out 2>&1 &```. Alternaitvely, you can run the command in a ```screen```, instead of using ```nohup```.
                
8. Model checkpoint output location and log directory location are both defined in ```run.sh``` and  are located under ```/efs``` directory, if ```EFS_DATA=true``` in ```mask-rcnn-stack.sh```, else they are located under user home directory. By default, the location is under user home directory.
        
9. If you set ```EFS_DATA=true```, the log files and model checkpoints are saved on EFS file-system, which is not automatically deleted. However, the default setting is ```EFS_DATA=false```, so you must copy the output directory from user home directory to an S3 bucket, before you delete the CloudFormation stack.

### Detailed Explanation

The easiest way to do distributed training using TensorFlow, TensorPack and Horovod in AWS EC2 is to create an AWS CloudFormation stack that instantiates an Amazon Deep Learning AMI based cluster of GPU enabled EC2 instances.

The multi-instance cluster in EC2 has a Master node and 1 or more Worker nodes. The Master node and Worker nodes are running within two separate AWS Auto-scaling groups. The Master node is within a public subnet that can be accessed remotely and the Worker nodes are in a private subnet accessible only from the Master node. All nodes are used for distributd training. 

This distirbuted training setup relies on implicit SSH communication among the nodes. To setup such implcit SSH communication, the Master node relies on [SSH forwarding agent](https://developer.github.com/v3/guides/using-ssh-agent-forwarding/) and this configuration is done as part of creating the AWS CloudFormation stack.

Also, as part of creating the stack, an EFS file-system is automatically created and mounted on all nodes. You may reuse an existing EFS file system free of any existing mount-points, instead of having the CloudFormation stack create a new EFS file-system. See variables defined in mask-rcnn-stack.sh shell script on how to re-use an existing EFS file-system.

#### Private VPC ####

You may need to use an existing private VPC. In this case, customize S3_BUCKET, VPC_ID, SUBNET_ID, SSH_LOCATION and KEY_NAME variables in ```private-mask-rcnn-stack.sh``` script. Make sure the route table associated with your selected subnet inside your private VPC uses a NAT Gateway to route to the Internet and uses a VPC Endpoint Gateway to route to S3. Execute: ```./private-mask-rcnn-stack.sh```.

The output of executing the script is a [CloudFormation Stack](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacks.html) ID.

#### OS and Framework Versions

The Deep Learning AMI version used in Cloud Formation templates is version 21. TensorPack is not included in the AMI. Instead, it is packaged in a Tar file and staged in an S3 bucket as part of Step 1 noted under Quick Start Steps above.

You may experiment with different versions of Amazon Deep Learning AMIs. 

#### Cluster Health and Node Failure Resilience

Distributed machine-learning in general and this specific setup are not automatically resilient to any node failure. If any node fails, the easiest thing to do is to delete the stack and create a new stack reusing existing EFS file-system. Modify run.sh to restart training from a saved model checkpoint.

You can use the provided ```cluster-health-check.sh``` shell script to determine cluster health.

#### SSH_LOCATION, KEY_NAME Variables
SSH_LOCATION variable used in mask-rcnn-stack.sh defines the allowed source CIDR for connecting to the cluster Master node using SSH. This CIDR is used to define Master node SSH [security group](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-network-security.html) incoming instance level network seucrity rules. You can modify the security group after the creation of the cluster, but at least one CIDR at cluster creation time is required. The default value of this variable allows access from any location, which is not recommended practice, so you are advised to change it to your specific CIDR.

KEY_NAME variable in mask-rcnn-stack.sh defines the [EC2 Key Pair](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html) name used to launch EC2 instances.
