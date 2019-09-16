#!/bin/bash

# AWS Region; customize as needed 
AWS_REGION=
[[ -z "${AWS_REGION}" ]] && echo "AWS_REGION is required" && exit 1 

# AWS AZ; customize as needed 
AWS_AZ=
[[ -z "${AWS_AZ}" ]] && echo "AWS_AZ is required" && exit 1 

# VPC ID
VPC_ID=
[[ -z "${VPC_ID}" ]] && echo "VPC_ID is required" && exit 1 

# Subnet ID
SUBNET_ID=
[[ -z "${SUBNET_ID}" ]] && echo "SUBNET_ID is required" && exit 1 

# Cutomize bucket name
S3_BUCKET=
[[ -z "${S3_BUCKET}" ]] && echo "S3_BUCKET is required" && exit 1 

# Cutomize bucket prefix if needed
S3_PREFIX=mask-rcnn/deeplearning-ami/input
[[ -z "${S3_PREFIX}" ]] && echo "S3_PREFIX is required" && exit 1 

# EC2 key pair name
KEY_NAME=saga
[[ -z "${KEY_NAME}" ]] && echo "KEY_NAME is required" && exit 1 

# EC2 instance type
# Recommended p3dn.24xlarge
INSTANCE_TYPE=p3.16xlarge

# Number of workers, minimum 1, maximum n - 1 for cluster of size n
# Master node is also used as a worker node, hence n - 1 for cluster of size n
# Model scales well upto total of 8 nodes, so NUM_WORKERS = 7 is maximum recommended
NUM_WORKERS=1

# Leave blank if you need to create a new EFS file system
# If you use an existing EFS file-system, it must not have any
# existing mount targets
EFS_ID=

# Customize CIDR for SSH 
SSH_LOCATION=0.0.0.0/0

DATE=`date +%s`

#Customize stack name as needed
STACK_NAME=mask-rcnn-$DATE

# cfn template name
CFN_TEMPLATE=private-mask-rcnn-cfn.yaml


# Data Tar file
DATA_TAR=coco-2017.tar

# Source tar file
SOURCE_TAR=tensorpack.tar

# Number of workers, minimum 1, maximum n - 1 for cluster of size n
# Master node is also used as a worker node, hence n - 1 for cluster of size n
NUM_WORKERS=1

# EC2 AMI override; leave blank if using default AMI defined in template
AMI_ID=


# Use EFS to serve data (default is replication of data to EBS volumes on each cluster node)
EFS_SERVES=false

aws cloudformation create-stack --region $AWS_REGION  --stack-name $STACK_NAME \
--template-body file://$CFN_TEMPLATE \
--capabilities CAPABILITY_NAMED_IAM \
--parameters \
ParameterKey=ActivateCondaEnv,ParameterValue=tensorflow_p36 \
ParameterKey=AMIOverride,ParameterValue=$AMI_ID \
ParameterKey=EFSFileSystemId,ParameterValue=$EFS_ID \
ParameterKey=EFSMountPoint,ParameterValue=efs \
ParameterKey=EFSServesData,ParameterValue=$EFS_SERVES \
ParameterKey=EbsVolumeSize,ParameterValue=200 \
ParameterKey=ImageType,ParameterValue=Ubuntu \
ParameterKey=InstanceType,ParameterValue=$INSTANCE_TYPE \
ParameterKey=KeyName,ParameterValue=$KEY_NAME \
ParameterKey=S3Bucket,ParameterValue=$S3_BUCKET \
ParameterKey=RunScript,ParameterValue=$S3_PREFIX/run.sh \
ParameterKey=SetupScript,ParameterValue=$S3_PREFIX/setup.sh \
ParameterKey=SSHLocation,ParameterValue=$SSH_LOCATION \
ParameterKey=TarData,ParameterValue=$S3_PREFIX/$DATA_TAR \
ParameterKey=TarSource,ParameterValue=$S3_PREFIX/$SOURCE_TAR \
ParameterKey=WorkerCount,ParameterValue=$NUM_WORKERS \
ParameterKey=MyVpcId,ParameterValue=$VPC_ID \
ParameterKey=PrivateSubnetId,ParameterValue=$SUBNET_ID


progress=$(aws --region $AWS_REGION cloudformation list-stacks --stack-status-filter 'CREATE_IN_PROGRESS' | grep $STACK_NAME | wc -l)
while [ $progress -ne 0 ]; do
let elapsed="`date +%s` - $DATE"
echo "Stack $STACK_NAME status: Create in progress: [ $elapsed secs elapsed ]"
sleep 30
progress=$(aws --region $AWS_REGION  cloudformation  list-stacks --stack-status-filter 'CREATE_IN_PROGRESS' | grep $STACK_NAME | wc -l)
done
sleep 5
aws --region $AWS_REGION  cloudformation describe-stacks --stack-name $STACK_NAME
